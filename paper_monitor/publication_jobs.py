"""Resumable author import and identifier completion for My Publications.

Only explicitly added publications enter the queue. Workers never depend on an
open browser tab; SQLite checkpoints survive application shutdown.
"""
import hashlib
import json
import random
import threading
import time
from urllib.parse import quote, parse_qs, urlparse

from .storage import Storage
from .time_utils import now_iso
from .workflow_store import publication_work_snapshot, PUBLICATION_REMOVED_BY_USER
from .publication_errors import report_publication_error

MUTATION_LOCK = threading.RLock()
_WORKERS_LOCK = threading.Lock()
_WORKERS = set()


def queue_identifier(storage, publication, *, retry=False):
    from . import ui_server as ui
    paper_id = str(publication.get('paper_id') or '')
    if not paper_id or ui.author_monitor_paper_has_identifier(storage.get_paper(paper_id) or {}):
        return
    storage.conn.execute('''
        INSERT INTO publication_identifier_tasks(publication_id,status,updated_at)
        VALUES (?, 'pending', ?)
        ON CONFLICT(publication_id) DO UPDATE SET status='pending', message='', updated_at=excluded.updated_at
        WHERE ? AND publication_identifier_tasks.status IN ('unresolved','error')
    ''', (publication['id'], now_iso(), int(retry)))
    storage.conn.commit()


def add_candidate(storage, candidate):
    from . import ui_server as ui
    with MUTATION_LOCK:
        normalized = ui.paper_from_publication_candidate(candidate)
        existing = ui.existing_paper_for_author_monitor(storage, normalized)
        if existing:
            reasons = storage.paper_identity_conflict_reasons(existing, normalized)
            if reasons:
                storage.record_paper_identity_conflict(existing, normalized, reasons)
                raise ValueError('Paper identity conflict is pending review')
            paper_id = existing['paper_id']
            if not ui.author_monitor_paper_has_identifier(existing) and ui.author_monitor_paper_has_identifier(normalized):
                storage.refresh_paper_metadata(paper_id, ui.merge_refreshed_metadata(existing, normalized))
            ui.save_google_scholar_publication_observation(storage, paper_id, candidate)
        else:
            if not storage.upsert_paper(normalized):
                raise ValueError('Paper identity conflict is pending review')
            paper_id = normalized['paper_id']
        existed = storage.conn.execute('SELECT id FROM my_publications WHERE paper_id=?', (paper_id,)).fetchone()
        publication = storage.add_my_publication(paper_id=paper_id)
        ui.sync_my_publication_existing_pubmed_marks(storage, paper_id=paper_id)
        ui.move_monitor_pdf_into_context_if_needed(storage, paper_id, ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT)
        ui.sync_my_publication_alias(storage, paper_id)
        queue_identifier(storage, publication)
        return publication, bool(existed)


def create_import(storage, profile):
    from . import ui_server as ui
    user_id = ui.google_scholar_user_id(str(profile.get('url') or profile.get('profile_url') or ''))
    if not user_id:
        raise ValueError('Choose a Google Scholar author profile first')
    url = 'https://scholar.google.com/citations?user=' + quote(user_id) + '&hl=en'
    with MUTATION_LOCK:
        storage.conn.execute('''
            INSERT INTO publication_import_jobs(user_id,profile_url,name,updated_at)
            VALUES (?,?,?,?) ON CONFLICT(user_id) DO NOTHING
        ''', (user_id, url, str(profile.get('name') or ''), now_iso()))
        storage.conn.commit()
    return dict(storage.conn.execute('SELECT * FROM publication_import_jobs WHERE user_id=?', (user_id,)).fetchone())


def control_import(storage, job_id, action):
    if action not in {'pause', 'resume', 'check'}:
        raise ValueError('Unknown import action')
    with MUTATION_LOCK:
        job = storage.conn.execute('SELECT * FROM publication_import_jobs WHERE id=?', (job_id,)).fetchone()
        if not job:
            raise ValueError('Import not found')
        if action == 'pause' and job['status'] in {'queued', 'running'}:
            storage.conn.execute("UPDATE publication_import_jobs SET status='paused',message='Import paused',updated_at=? WHERE id=?", (now_iso(),job_id))
        elif action == 'resume' and job['status'] in {'paused', 'error', 'partial'}:
            if job['status'] == 'partial':
                storage.conn.execute("DELETE FROM publication_import_items WHERE job_id=? AND error!='' AND error!=?",(job_id,PUBLICATION_REMOVED_BY_USER))
                storage.conn.execute("UPDATE publication_import_jobs SET seen=seen-rejected,rejected=0,page_offset=0,page_signature='' WHERE id=?",(job_id,))
            storage.conn.execute("UPDATE publication_import_jobs SET status='queued',message='',updated_at=? WHERE id=?", (now_iso(),job_id))
        elif action == 'check' and job['status'] == 'complete':
            # Explicit recheck starts from page one; existing source items and
            # canonical papers are reused, so repeated Add All is idempotent.
            storage.conn.execute("UPDATE publication_import_jobs SET status='queued',page_offset=0,page_signature='',message='',updated_at=? WHERE id=?", (now_iso(),job_id))
            storage.conn.execute("UPDATE publication_import_items SET error='' WHERE job_id=? AND error=?", (job_id,PUBLICATION_REMOVED_BY_USER))
        storage.conn.commit()


def retry_identifiers(storage, publication_id=0):
    rows = ([storage.get_my_publication(publication_id=publication_id)] if publication_id else storage.list_my_publications())
    with MUTATION_LOCK:
        for row in rows:
            if row:
                queue_identifier(storage, row, retry=True)


def fetch_profile_page(profile_url, offset):
    """Read one source page using the same parser and request spacing as Author Monitor."""
    from . import ui_server as ui
    user_id = ui.google_scholar_user_id(profile_url)
    response = ui.google_scholar_request_with_spacing(
        'GET', 'https://scholar.google.com/citations',
        params={'user': user_id, 'hl': 'en', 'cstart': offset, 'pagesize': 100},
        headers={'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'en-US,en;q=0.9', 'Referer': 'https://scholar.google.com/'},
        timeout=20, max_retries=1,
    )
    if ui.is_google_scholar_block_page(response.text, response.url):
        raise ui.GoogleScholarBlockedError(ui.google_scholar_block_message())
    soup = ui.BeautifulSoup(response.text, 'html.parser')
    rows = soup.select('tr.gsc_a_tr')
    if not rows and soup.select_one('#gsc_a_b') is None:
        raise ValueError('The author publication list could not be read; import is incomplete')
    candidates = []
    for row in rows:
        candidate = ui.google_scholar_row_to_publication(row)
        if not candidate:
            raise ValueError('A publication row could not be read; import is incomplete')
        candidates.append(candidate)
    more = soup.select_one('#gsc_bpf_more')
    finished = not rows or (more is not None and more.has_attr('disabled')) or (more is None and len(rows) < 100)
    return {'candidates': candidates, 'finished': finished, 'next_offset': offset + len(rows)}


def source_key(candidate):
    paper = candidate.get('paper') or candidate
    raw = candidate.get('raw') or {}
    observation = raw.get('google_scholar') or {}
    url = observation.get('publication_url') or ''
    if url:
        citation = parse_qs(urlparse(url).query).get('citation_for_view', [''])[0]
        return 'scholar:' + citation if citation else url
    values = [str(paper.get(k) or '').strip().lower() for k in ('title','journal','publication_date')]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False).encode()).hexdigest()


def run_import_step(storage):
    from . import ui_server as ui
    row = storage.conn.execute("SELECT * FROM publication_import_jobs WHERE status IN ('queued','running') ORDER BY id LIMIT 1").fetchone()
    if not row:
        return False
    job = dict(row); job_id = job['id']
    try:
        cooldown = ui.google_scholar_global_cooldown(storage)
        if cooldown.get('active'):
            raise ValueError(ui.google_scholar_global_cooldown_message(cooldown))
        storage.conn.execute("UPDATE publication_import_jobs SET status='running',message='',updated_at=? WHERE id=? AND status IN ('queued','running')", (now_iso(), job_id))
        storage.conn.commit()
        page = fetch_profile_page(job['profile_url'], job['page_offset'])
        keys = [source_key(c) for c in page['candidates']]
        signature = hashlib.sha256(json.dumps(keys).encode()).hexdigest()
        if keys and signature == job['page_signature']:
            raise ValueError('The source repeated a page; import is incomplete. Resume later.')
        if not page['finished'] and page['next_offset'] <= job['page_offset']:
            raise ValueError('The source did not advance; import is incomplete')
        for key, candidate in zip(keys, page['candidates']):
            with MUTATION_LOCK:
                if storage.conn.execute('SELECT status FROM publication_import_jobs WHERE id=?',(job_id,)).fetchone()[0] != 'running':
                    return True
                item = storage.conn.execute('SELECT paper_id,error FROM publication_import_items WHERE job_id=? AND source_key=?',(job_id,key)).fetchone()
                if item:
                    if item['error'] or storage.conn.execute('SELECT 1 FROM my_publications WHERE paper_id=?',(item['paper_id'],)).fetchone():
                        continue
                    # Recheck also handles a removed placement or fully deleted
                    # paper. Retain the source checkpoint and avoid double counts.
                try:
                    publication, existed = add_candidate(storage, candidate)
                except ValueError as exc:
                    storage.conn.execute("INSERT INTO publication_import_items(job_id,source_key,error) VALUES (?,?,?) ON CONFLICT(job_id,source_key) DO UPDATE SET error=excluded.error",(job_id,key,str(exc)))
                    storage.conn.execute("UPDATE publication_import_jobs SET seen=seen+?,rejected=rejected+1,message=?,updated_at=? WHERE id=?",(int(not item),str(exc),now_iso(),job_id))
                else:
                    storage.conn.execute('INSERT INTO publication_import_items(job_id,source_key,paper_id) VALUES (?,?,?) ON CONFLICT(job_id,source_key) DO UPDATE SET paper_id=excluded.paper_id',(job_id,key,publication['paper_id']))
                    if not item:
                        storage.conn.execute('UPDATE publication_import_jobs SET seen=seen+1,added=added+?,reused=reused+?,updated_at=? WHERE id=?',(int(not existed),int(existed),now_iso(),job_id))
                storage.conn.commit()
        rejected = storage.conn.execute('SELECT rejected FROM publication_import_jobs WHERE id=?',(job_id,)).fetchone()[0]
        final_status = ('partial' if rejected else 'complete') if page['finished'] else 'queued'
        message = 'Some articles need identity review; continue to retry failed articles.' if rejected else ('All profile pages imported' if page['finished'] else '')
        storage.conn.execute("UPDATE publication_import_jobs SET status=?,page_offset=?,page_signature=?,message=?,updated_at=? WHERE id=? AND status='running'", (final_status, page['next_offset'], signature, message, now_iso(), job_id))
        storage.conn.commit()
    except Exception as exc:
        message = report_publication_error(exc)
        if isinstance(exc, ui.GoogleScholarBlockedError):
            ui.start_google_scholar_global_cooldown(storage,message=str(exc))
        storage.conn.execute("UPDATE publication_import_jobs SET status='error',message=?,updated_at=? WHERE id=? AND status IN ('queued','running')",(message,now_iso(),job_id))
        storage.conn.commit()
    return True


def run_identifier_step(storage):
    from . import ui_server as ui
    with MUTATION_LOCK:
        row = storage.conn.execute("SELECT publication_id FROM publication_identifier_tasks WHERE status='pending' ORDER BY publication_id LIMIT 1").fetchone()
        if not row:
            return False
        publication_id = row[0]
        paper = storage.get_my_publication(publication_id=publication_id)
        storage.conn.execute("UPDATE publication_identifier_tasks SET status='working',attempts=attempts+1,updated_at=? WHERE publication_id=?",(now_iso(),publication_id))
        storage.conn.commit()
    status, message = 'unresolved', 'No confident DOI or arXiv match'
    try:
        if ui.author_monitor_paper_has_identifier(paper):
            status, message = 'matched', 'Identifier already available'
        else:
            normalized = ui.resolve_google_scholar_candidate_to_identifier(ui.author_monitor_candidate_from_paper(paper))
            if normalized:
                with MUTATION_LOCK:
                    # Re-read after network work: deletion, manual metadata and
                    # shared Author Monitor updates must win over an old task.
                    current = storage.get_my_publication(publication_id=publication_id)
                    if not current:
                        return True
                    if not ui.author_monitor_paper_has_identifier(current):
                        reasons = storage.paper_identity_conflict_reasons(current,normalized)
                        if reasons:
                            storage.record_paper_identity_conflict(current,normalized,reasons)
                            raise ValueError('Identifier match needs identity review')
                        storage.refresh_paper_metadata(current['paper_id'],ui.merge_refreshed_metadata(current,normalized))
                        ui.sync_my_publication_alias(storage,current['paper_id'])
                    status, message = 'matched', 'DOI/arXiv metadata updated'
    except Exception as exc:
        status, message = 'error', report_publication_error(exc, operation='Identifier lookup')
    storage.conn.execute('UPDATE publication_identifier_tasks SET status=?,message=?,updated_at=? WHERE publication_id=?',(status,message,now_iso(),publication_id))
    storage.conn.commit()
    return True


def recover_interrupted_work(storage):
    storage.conn.execute("UPDATE publication_import_jobs SET status='queued' WHERE status='running'")
    storage.conn.execute("UPDATE publication_identifier_tasks SET status='pending' WHERE status='working'")
    storage.conn.commit()


def start_workers(db_path):
    """One import and one identifier worker per running server/database."""
    key = str(db_path.resolve())
    with _WORKERS_LOCK:
        if key in _WORKERS:
            return
        _WORKERS.add(key)
        storage = Storage(db_path)
        try:
            recover_interrupted_work(storage)
        finally:
            storage.close()
        def loop(step, import_worker=False):
            while True:
                work = False
                storage = None
                try:
                    storage = Storage(db_path)
                    work = step(storage)
                except Exception:
                    # A transient SQLite failure must not kill the queue. Each
                    # item is checkpointed before moving to the next one.
                    if storage:
                        storage.conn.rollback()
                        try:
                            table = 'publication_import_jobs' if import_worker else 'publication_identifier_tasks'
                            old, new = ('running', 'queued') if import_worker else ('working', 'pending')
                            storage.conn.execute(f"UPDATE {table} SET status=? WHERE status=?",(new,old))
                            storage.conn.commit()
                        except Exception:
                            storage.conn.rollback()
                finally:
                    if storage:
                        storage.close()
                time.sleep(random.uniform(12,24) if work and import_worker else (0.5 if work else 3))
        threading.Thread(target=loop,args=(run_import_step,True),name='publication-import',daemon=True).start()
        threading.Thread(target=loop,args=(run_identifier_step,),name='publication-identifiers',daemon=True).start()
