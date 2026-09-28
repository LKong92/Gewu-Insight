"""Canonical identities for every writer; merges retain files and old references.

No historical sweep runs at startup. Historical reconciliation requires an explicit
plan. SQLite write transactions serialize resolution and creation across workers.
"""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlparse
from .time_utils import now_iso
from .text import normalize_arxiv_identifier


def metadata_records(paper, raw):
    """Known provider envelopes, without changing which provider is queried."""
    raw = raw if isinstance(raw, dict) else {}
    records = [paper, raw]
    for key in ('openalex', 'crossref', 'google_scholar', 'semantic_scholar', 'datacite'):
        if isinstance(raw.get(key), dict):
            records.append(raw[key])
    return records


def work_kind(paper, raw):
    title = str(paper.get('title') or '')
    if re.match(r'^\s*(?:raw\s+data|dataset|data\s+(?:for|from))\s*:', title, re.I):
        return 'dataset'
    kinds = set()
    for record in metadata_records(paper, raw):
        value = record.get('type') or record.get('resourceTypeGeneral')
        types = record.get('types')
        if isinstance(types, dict):
            value = types.get('resourceTypeGeneral') or value
        if isinstance(value, str):
            kinds.add(value.casefold())
    if 'dataset' in kinds:
        return 'dataset'
    return 'article' if kinds & {'article', 'journal-article', 'posted-content', 'preprint'} else ''


def stored_work_kind(storage, paper):
    # Old enrichment may already have replaced a dataset's title. Retain the
    # original monitored title as a guard; never infer dataset from host alone.
    kind = work_kind(paper, storage._paper_raw_dict(paper))
    if kind != 'dataset':
        titles = storage.conn.execute(
            'SELECT scholar_title FROM author_monitor_papers WHERE paper_id=?',
            (paper.get('paper_id') or '',))
        if any(work_kind({'title': row['scholar_title']}, {}) == 'dataset' for row in titles):
            kind = 'dataset'
    return kind


def review_reasons(storage, existing, incoming):
    reference = dict(existing, paper_id=incoming.get('paper_id') or existing['paper_id'])
    reasons = storage.paper_identity_conflict_reasons(reference, incoming)
    old_kind = stored_work_kind(storage, existing)
    new_kind = work_kind(incoming, storage._paper_raw_dict(incoming))
    if ((old_kind == 'dataset' and new_kind != 'dataset'
         and (new_kind == 'article' or incoming.get('title')))
            or (old_kind != 'dataset' and stored_work_kind(storage, incoming) == 'dataset')):
        reasons = sorted(set(reasons + ['dataset_article_conflict']))
    return reasons


class IdentityReviewRequired(ValueError):
    """A single publication needs review; unrelated refresh items may proceed."""
    def __init__(self, existing, incoming, reasons):
        self.existing = dict(existing)
        self.incoming = dict(incoming)
        self.reasons = list(reasons)
        labels = {
            'insufficient_same_work_evidence': 'not enough evidence to merge existing records',
            'dataset_article_conflict': 'a dataset and an article must remain separate',
            'different_doi': 'the DOI values differ',
            'incoming_doi_url_mismatch': 'the incoming DOI disagrees with its URL',
            'existing_doi_conflicts_with_incoming_url': 'the incoming URL identifies a different DOI',
            'incoming_doi_conflicts_with_existing_url': 'the DOI disagrees with the existing URL',
            'title_and_authors_conflict': 'the titles and authors disagree',
            'title_and_journal_conflict': 'the titles and journals disagree',
        }
        explanation = '; '.join(labels.get(reason, reason.replace('_', ' ')) for reason in reasons)
        def label(paper):
            title = str(paper.get('title') or 'Untitled publication')
            key = paper.get('storage_key') or paper.get('paper_id') or 'incoming record'
            return f'“{title}” [{key}]'
        super().__init__(f'{label(incoming)} / {label(existing)}: {explanation}. Existing papers and files were preserved.')


def doi(value):
    value = unquote(str(value or '')).strip()
    value = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value, flags=re.I)
    return value.casefold() if re.fullmatch(r'10\.\d{4,9}/\S+', value, re.I) else ''


def title_key(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'[^\W_]+', value, re.UNICODE))


def scholar_identity(value):
    parsed = urlparse(str(value or ''))
    if not re.fullmatch(r'(?:[a-z]+\.)?scholar\.google\.[a-z.]+', parsed.hostname or ''):
        return ''
    values = parse_qs(parsed.query).get('citation_for_view') or []
    return values[0] if len(values) == 1 and re.fullmatch(r'[\w-]+:[\w-]+', values[0]) else ''


def identifiers(storage, paper):
    raw = storage._paper_raw_dict(paper)
    result = set()
    if value := doi(paper.get('doi')):
        result.add(('doi', value))
    if raw.get('manual_preprint_identifier_override'):
        values = [raw.get('manual_preprint_identifier') or '']
    else:
        values = storage._paper_arxiv_identifiers({**paper, 'raw_json': json.dumps(raw)})
        for name in ('url', 'landing_url', 'pdf_url'):
            u = urlparse(str(paper.get(name) or ''))
            if u.hostname in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
                values.append(re.sub(r'^/(?:abs|pdf)/', '', u.path))
        if doi(paper.get('doi')).startswith('10.48550/arxiv.'):
            values.append(doi(paper['doi']).split('arxiv.', 1)[1])
    for value in values:
        value = normalize_arxiv_identifier(value)
        if value:
            result.add(('arxiv', value))
    scholar = raw.get('google_scholar') or {}
    urls = [paper.get(k) for k in ('url', 'landing_url')]
    if isinstance(scholar, dict):
        urls.append(scholar.get('publication_url'))
    for url in urls:
        if value := scholar_identity(url):
            result.add(('scholar', value))
    return result


def ensure_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS paper_aliases (
      alias TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_paper_alias_target ON paper_aliases(paper_id);
    CREATE TABLE IF NOT EXISTS paper_identifiers (
      kind TEXT NOT NULL, value TEXT NOT NULL,
      paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
      PRIMARY KEY(kind,value)
    );
    CREATE INDEX IF NOT EXISTS idx_paper_identifiers_target ON paper_identifiers(paper_id);
    CREATE TABLE IF NOT EXISTS paper_identity_history (
      id INTEGER PRIMARY KEY, target_paper_id TEXT NOT NULL, source_paper_id TEXT NOT NULL,
      source_key TEXT NOT NULL, reason TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_papers_identity_doi ON papers(lower(trim(doi)));
    CREATE TRIGGER IF NOT EXISTS trg_papers_unique_new_doi BEFORE INSERT ON papers
      WHEN COALESCE(trim(NEW.doi),'') != '' AND EXISTS
        (SELECT 1 FROM papers WHERE lower(trim(doi))=lower(trim(NEW.doi)))
      BEGIN SELECT RAISE(ABORT,'DOI already belongs to a paper; resolve its identity first'); END;
    CREATE TRIGGER IF NOT EXISTS trg_papers_unique_changed_doi BEFORE UPDATE OF doi ON papers
      WHEN COALESCE(lower(trim(NEW.doi)),'') != ''
       AND COALESCE(lower(trim(NEW.doi)),'') != COALESCE(lower(trim(OLD.doi)),'')
       AND EXISTS (SELECT 1 FROM papers WHERE paper_id != OLD.paper_id AND lower(trim(doi))=lower(trim(NEW.doi)))
      BEGIN SELECT RAISE(ABORT,'DOI already belongs to a paper; resolve its identity first'); END;
    ''')


@contextmanager
def transaction(storage, commit=True):
    conn = storage.conn
    outer = conn.in_transaction
    if not outer:
        conn.execute('BEGIN IMMEDIATE')
    conn.execute('SAVEPOINT identity_write')
    try:
        yield
        conn.execute('RELEASE identity_write')
        if commit:
            conn.commit()
    except Exception:
        conn.execute('ROLLBACK TO identity_write')
        conn.execute('RELEASE identity_write')
        if not outer:
            conn.rollback()
        raise


def resolve(storage, value):
    if value is None:
        return None
    value = str(value or '')
    row = storage.conn.execute('SELECT paper_id FROM paper_aliases WHERE alias=?', (value,)).fetchone()
    return row['paper_id'] if row else value


def for_key(storage, key):
    # Match the existing partial-index predicate so an absent old Key does not
    # scan all paper rows before resolving its alias.
    row = storage.conn.execute("SELECT paper_id FROM papers WHERE storage_key=? AND storage_key IS NOT NULL AND storage_key != ''", (key,)).fetchone()
    return storage.get_paper(row['paper_id'] if row else resolve(storage, key))


def add_alias(storage, alias, paper_id):
    if alias and alias != paper_id:
        owner = storage.conn.execute('SELECT paper_id FROM paper_aliases WHERE alias=?', (alias,)).fetchone()
        if owner and owner['paper_id'] != paper_id:
            raise ValueError('An existing paper alias belongs to another identity.')
        storage.conn.execute('INSERT OR IGNORE INTO paper_aliases VALUES(?,?,?)', (alias, paper_id, now_iso()))


def rank(storage, paper):
    pid = paper['paper_id']
    user_refs = storage.conn.execute('SELECT (SELECT count(*) FROM my_publications WHERE paper_id=?) + (SELECT count(*) FROM library_items WHERE paper_id=?)', (pid,pid)).fetchone()[0]
    return (-bool(user_refs), -bool(paper.get('preferred_resource_manual')), str(paper.get('first_seen_at') or ''), pid)


def find(storage, paper):
    candidates = {}
    if row := storage.get_paper(str(paper.get('paper_id') or '')):
        candidates[row['paper_id']] = row
    for kind,value in identifiers(storage, paper):
        rows = storage.conn.execute('SELECT p.* FROM paper_identifiers i JOIN papers p ON p.paper_id=i.paper_id WHERE kind=? AND value=?', (kind,value)).fetchall()
        if kind in {'doi','arxiv'}:
            rows = [r for r in rows if (kind,value) in identifiers(storage,dict(r))]
        if kind == 'doi':
            rows = list(rows) + list(storage.conn.execute('SELECT * FROM papers WHERE lower(trim(doi))=?', (value,)))
        elif kind == 'scholar':
            # Legacy links are read until their stable identities have been registered.
            rows = list(rows) + [r for r in storage.conn.execute('SELECT p.*, a.scholar_key FROM author_monitor_papers a JOIN papers p ON p.paper_id=a.paper_id WHERE instr(a.scholar_key,?)>0', (value,)) if scholar_identity(r['scholar_key']) == value]
        elif kind == 'arxiv' and not rows:
            rows = [r for r in storage.conn.execute("SELECT * FROM papers WHERE paper_id=? OR instr(raw_json,?)>0", ('arxiv_'+value,value)) if (kind,value) in identifiers(storage,dict(r))]
        for row in rows:
            item=dict(row)
            # A corrected/cleared DOI or arXiv must not retain a stale registry claim.
            if kind != 'scholar' and (kind,value) not in identifiers(storage,item):
                continue
            candidates[item['paper_id']] = item
    return sorted(candidates.values(), key=lambda p:rank(storage,p))


def compatible(storage, left, right):
    # Keep the established conflict checks, also when an incoming record lacks DOI.
    if doi(left.get('doi')) and doi(right.get('doi')) and doi(left['doi']) != doi(right['doi']):
        return False
    return not review_reasons(storage, left, right)


def same_work_evidence(storage, left, right):
    """Positive evidence for merging two existing records, beyond a shared DOI."""
    if not compatible(storage, left, right):
        return False
    shared = identifiers(storage, left) & identifiers(storage, right)
    if any(kind in {'scholar', 'arxiv'} for kind, _ in shared):
        return True
    def openalex_id(paper):
        raw = storage._paper_raw_dict(paper)
        record = raw.get('openalex') if isinstance(raw.get('openalex'), dict) else raw
        value = str(record.get('id') or '').rstrip('/').rsplit('/', 1)[-1]
        return value.upper() if re.fullmatch(r'W\d+',value,re.I) else ''
    if openalex_id(left) and openalex_id(left) == openalex_id(right):
        return True
    # Typographical differences alone are not a second publication. Require
    # author agreement too; an accidentally assigned DOI must not join strangers.
    return bool(title_key(left.get('title'))
                and title_key(left.get('title')) == title_key(right.get('title'))
                and storage._identity_authors(left) & storage._identity_authors(right))


def register(storage, paper):
    pid = paper['paper_id']
    ids = identifiers(storage,paper)
    for kind in ('doi','arxiv'):
        for row in storage.conn.execute('SELECT value FROM paper_identifiers WHERE paper_id=? AND kind=?',(pid,kind)).fetchall():
            if (kind,row['value']) not in ids:
                storage.conn.execute('DELETE FROM paper_identifiers WHERE kind=? AND value=? AND paper_id=?',(kind,row['value'],pid))
    for kind,value in ids:
        if kind in {'doi','arxiv'}:
            owner = storage.conn.execute('SELECT paper_id FROM paper_identifiers WHERE kind=? AND value=?',(kind,value)).fetchone()
            if owner and owner['paper_id'] != pid:
                current = storage.get_paper(owner['paper_id'])
                if current and (kind,value) not in identifiers(storage,current):
                    storage.conn.execute('DELETE FROM paper_identifiers WHERE kind=? AND value=?',(kind,value))
        # Existing historical duplicates are reconciled explicitly, never swept on startup.
        storage.conn.execute('INSERT OR IGNORE INTO paper_identifiers VALUES(?,?,?)',(kind,value,pid))


def prepare(storage, paper, *, current_id='', linked_preprint_id=''):
    payload=dict(paper)
    original_id=str(current_id or payload.get('paper_id') or '')
    payload['paper_id']=resolve(storage, original_id)
    if payload.get('doi'):
        payload['doi']=doi(payload['doi']) or str(payload['doi']).strip().casefold()
    current=storage.get_paper(payload['paper_id'])
    if current:
        kind_reasons = review_reasons(storage, current, payload)
        if 'dataset_article_conflict' in kind_reasons:
            raise IdentityReviewRequired(current, payload, kind_reasons)
        reference=storage.metadata_refresh_identity_reference(current,payload,linked_preprint_id=linked_preprint_id)
        if storage.paper_identity_conflict_reasons(reference,payload):
            return payload  # The existing writer records/rejects this conflict.
        old_ids=identifiers(storage,current)
        new_ids=identifiers(storage,payload)
        if not (new_ids-old_ids):
            return payload
        candidates=find(storage,payload)
        others=[p for p in candidates if p['paper_id']!=current['paper_id'] and (identifiers(storage,p)&new_ids)]
        if others:
            target=others[0]
            if not same_work_evidence(storage,target,payload):
                reasons = review_reasons(storage, target, payload)
                if doi(target.get('doi')) and doi(payload.get('doi')) and doi(target['doi']) != doi(payload['doi']):
                    reasons.append('different_doi')
                raise IdentityReviewRequired(target, payload, reasons or ['insufficient_same_work_evidence'])
            if rank(storage,current) < rank(storage,target):
                target, current = current, target
            merge(storage,target['paper_id'],current['paper_id'],reason='identifier_completed',evidence=payload)
            payload['paper_id']=target['paper_id']
            survivor_raw = storage._paper_raw_dict(storage.get_paper(target['paper_id']))
            payload['raw'] = {**survivor_raw, **storage._paper_raw_dict(payload)}
            for key, value in survivor_raw.items():
                if key.startswith('manual_'):
                    payload['raw'][key] = value
    else:
        candidates=find(storage,payload)
        if not candidates:
            return payload
        target=candidates[0]
        if not compatible(storage,target,payload):
            storage.record_paper_identity_conflict(target,payload,['canonical_identifier_conflict'],commit=False)
            return None
        payload['paper_id']=target['paper_id']
        add_alias(storage,original_id,target['paper_id'])
        add_alias(storage,storage.storage_key_for_paper_id(original_id),target['paper_id'])
    return payload


# Tables with one paper foreign key; each key describes a relationship that may
# already exist on the survivor. Never discard an unknown referencing table.
RELATIONS = {
 'library_items':('folder_id',), 'my_publications':(), 'author_monitor_papers':('author_monitor_id',),
 'paper_source_observations':('source_kind','source_name','source_key'),
 'journal_monitor_papers':('fetch_run_id','source'), 'theme_results':('group_key','window_start','window_end'),
 'theme_candidates':('source','window_start','window_end','query_plan_hash'),
 'aps_rss_entries':('journal_slug',), 'paper_reads':(),
 # Older installations retain feed history even though current ingestion no
 # longer creates this table. Preserve its feed/paper membership on merge.
 'journal_feed_entries':('feed_key',),
}
SIMPLE = {'resources','publication_import_items','paper_metadata_refreshes','ai_analyses','publication_notices'}
SPECIAL = {'paper_aliases','paper_identifiers','paper_identity_conflicts','author_monitor_card_cache','author_monitor_card_cache_dirty'}


def merge_blockers(storage, target, source):
    problems=[]
    if target.get('preferred_resource_manual') and source.get('preferred_resource_manual') and target.get('preferred_resource_id') != source.get('preferred_resource_id'):
        problems.append('Different manual Default files need a choice')
    for p in (target,source):
        resources=list(storage.conn.execute('SELECT * FROM resources WHERE paper_id=?',(p['paper_id'],)))
        paths={str(r[k]) for r in resources for k in ('stored_path','source_path') if r[k]}
        legacy={str(p[k]) for k in ('main_pdf_path','merged_pdf_path','source_path','analysis_path') if p.get(k)}
        try: legacy.update(json.loads(p.get('supplement_pdf_paths') or '[]'))
        except (ValueError,TypeError): problems.append('Invalid legacy file list')
        if legacy-paths:
            problems.append('Legacy file paths must be registered before reconciliation')
    left, right = storage._paper_raw_dict(target), storage._paper_raw_dict(source)
    for kind in ('doi', 'preprint'):
        if (left.get('manual_'+kind+'_identifier_override')
                and right.get('manual_'+kind+'_identifier_override')
                and left.get('manual_'+kind+'_identifier') != right.get('manual_'+kind+'_identifier')):
            problems.append('Conflicting manual identifiers need a choice')
    # Distinct marks and editable text survive as snapshots, but conflicting
    # manual bibliographic identities must remain separate until reviewed.
    if not compatible(storage,target,source):
        problems.append('Bibliographic identities disagree')
    return problems


def _json_union(left,right):
    if isinstance(left,dict) and isinstance(right,dict):
        return {k:_json_union(left.get(k),right.get(k)) if k in left and k in right else left.get(k,right.get(k)) for k in left.keys()|right.keys()}
    if isinstance(left,list) and isinstance(right,list):
        values=left+right;return list({json.dumps(x,sort_keys=True,ensure_ascii=False):x for x in values}.values())
    if isinstance(left,bool) and isinstance(right,bool): return left or right
    return left if left not in (None,'') else right


def merge(storage, target_id, source_id, *, reason, evidence=None):
    from .download import paper_download_lock
    target_id, source_id = resolve(storage,target_id), resolve(storage,source_id)
    # Never wait for a downloader while holding the SQLite writer lock: it
    # may need that same lock to finish registering its files.
    with ExitStack() as stack:
        for pid in sorted({target_id,source_id}):
            stack.enter_context(paper_download_lock(storage.db_path,pid,blocking=False))
        return _merge_locked(storage,target_id,source_id,reason=reason,evidence=evidence)


def _merge_locked(storage, target_id, source_id, *, reason, evidence=None):
    """Inside a caller's write transaction. No file I/O, no nested commits."""
    if not storage.conn.in_transaction:
        raise RuntimeError('Identity reconciliation requires a write transaction')
    target=storage.get_paper(target_id);source=storage.get_paper(source_id)
    if not target or not source: raise ValueError('Paper disappeared before reconciliation')
    target_id,source_id=target['paper_id'],source['paper_id']
    if target_id==source_id:return target
    blockers=merge_blockers(storage,target,source)
    if evidence and compatible(storage,target,evidence):
        blockers=[b for b in blockers if b!='Bibliographic identities disagree']
    if blockers: raise IdentityReviewRequired(target, source, blockers)
    tables={r['name'] for r in storage.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    refs={}
    for table in tables:
        quoted='"'+table.replace('"','""')+'"'
        for fk in storage.conn.execute('PRAGMA foreign_key_list('+quoted+')'):
            if fk['table']=='papers':
                if table not in set(RELATIONS)|SIMPLE|SPECIAL or fk['from'] not in ('paper_id','existing_paper_id'):
                    raise ValueError('Unreviewed paper relationship: '+table)
                refs[table]=[dict(r) for r in storage.conn.execute('SELECT * FROM '+quoted+' WHERE "'+fk['from']+'"=?',(source_id,))]
    snapshot={'source':source,'target':target,'source_relationships':refs}
    # Retain the target's relation state too for an auditable/reversible plan.
    snapshot['target_relationships']={t:[dict(r) for r in storage.conn.execute('SELECT * FROM '+t+' WHERE paper_id=?',(target_id,))] for t in (set(RELATIONS)|SIMPLE)&tables}
    publication_ids = [r['id'] for r in refs.get('my_publications',[])]
    publication_ids += [r['id'] for r in snapshot['target_relationships'].get('my_publications',[])]
    snapshot['identifier_tasks'] = [dict(r) for pid in publication_ids for r in storage.conn.execute(
        'SELECT * FROM publication_identifier_tasks WHERE publication_id=?',(pid,))]
    history_id = storage.conn.execute('INSERT INTO paper_identity_history(target_paper_id,source_paper_id,source_key,reason,snapshot_json,created_at) VALUES(?,?,?,?,?,?)',(target_id,source_id,source['storage_key'],reason,json.dumps(snapshot,ensure_ascii=False),now_iso())).lastrowid
    for table,keys in RELATIONS.items():
        for row in refs.get(table,[]):
            condition=' AND '.join(k+' IS ?' for k in keys)
            prior=storage.conn.execute('SELECT * FROM '+table+' WHERE paper_id=?'+(' AND '+condition if condition else ''),(target_id,*(row[k] for k in keys))).fetchone()
            if not prior:
                where='id=?' if 'id' in row else 'paper_id=?'+(' AND '+condition if condition else '')
                params=(row['id'],) if 'id' in row else (source_id,*(row[k] for k in keys))
                storage.conn.execute('UPDATE '+table+' SET paper_id=? WHERE '+where,(target_id,*params));continue
            prior=dict(prior);updates={}
            for k in ('is_unread','starred','first_author','corresponding_author','review_article','export_excluded','score'):
                if k in row:updates[k]=max(prior.get(k) or 0,row.get(k) or 0)
            for k in ('first_seen_at','created_at'):
                if row.get(k):updates[k]=min(prior.get(k) or row[k],row[k])
            for k in ('last_seen_at','updated_at','late_arrival_seen_at','fetched_at','searched_at'):
                if row.get(k):updates[k]=max(prior.get(k) or '',row[k])
            for k in ('author_marks','hits_json'):
                if row.get(k):updates[k]=json.dumps(_json_union(json.loads(prior.get(k) or '{}'),json.loads(row[k])),ensure_ascii=False)
            if table=='my_publications':
                task=storage.conn.execute('SELECT * FROM publication_identifier_tasks WHERE publication_id=?',(row['id'],)).fetchone()
                if task:
                    existing_task=storage.conn.execute('SELECT 1 FROM publication_identifier_tasks WHERE publication_id=?',(prior['id'],)).fetchone()
                    if not existing_task:storage.conn.execute('UPDATE publication_identifier_tasks SET publication_id=? WHERE publication_id=?',(prior['id'],row['id']))
                    elif task['status'] in {'pending','working'}:
                        storage.conn.execute('UPDATE publication_identifier_tasks SET status=?,updated_at=? WHERE publication_id=?',
                            ('pending',now_iso(),prior['id']))
            where='id=?' if 'id' in prior else 'paper_id=?'+(' AND '+condition if condition else '')
            params=(prior['id'],) if 'id' in prior else (target_id,*(prior[k] for k in keys))
            if updates:storage.conn.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in updates)+' WHERE '+where,(*updates.values(),*params))
            where='id=?' if 'id' in row else 'paper_id=?'+(' AND '+condition if condition else '')
            params=(row['id'],) if 'id' in row else (source_id,*(row[k] for k in keys))
            storage.conn.execute('DELETE FROM '+table+' WHERE '+where,params)
    for table in SIMPLE & tables:
        storage.conn.execute('UPDATE '+table+' SET paper_id=? WHERE paper_id=?',(target_id,source_id))
    # Conflict snapshots remain immutable in the merge history; re-point live
    # conflicts where possible without losing distinct evidence.
    for row in refs.get('paper_identity_conflicts',[]):
        existing=storage.conn.execute('SELECT id FROM paper_identity_conflicts WHERE existing_paper_id=? AND incoming_paper_id=? AND incoming_doi=? AND conflict_reasons_json=?',(target_id,row['incoming_paper_id'],row['incoming_doi'],row['conflict_reasons_json'])).fetchone()
        if existing:
            storage.conn.execute('UPDATE paper_identity_conflicts SET occurrence_count=occurrence_count+? WHERE id=?',(row['occurrence_count'],existing['id']))
        else:storage.conn.execute('UPDATE paper_identity_conflicts SET existing_paper_id=? WHERE id=?',(target_id,row['id']))
    storage.conn.execute('UPDATE paper_aliases SET paper_id=? WHERE paper_id=?',(target_id,source_id))
    storage.conn.execute('UPDATE paper_identifiers SET paper_id=? WHERE paper_id=?',(target_id,source_id))
    add_alias(storage,source_id,target_id);add_alias(storage,source['storage_key'],target_id)
    updates={}
    # Keep user-owned survivor metadata; fill its blanks from the removed record.
    skip={'paper_id','storage_key','import_copy_mode','doi','raw_json','preferred_resource_id','preferred_resource_manual'}
    columns={r['name'] for r in storage.conn.execute('PRAGMA table_info(papers)')}
    for k in columns-skip:
        if target.get(k) in (None,'') and source.get(k) not in (None,''):updates[k]=source[k]
    updates['raw_json']=json.dumps(_json_union(storage._paper_raw_dict(target),storage._paper_raw_dict(source)),ensure_ascii=False)
    if source.get('preferred_resource_manual') and not target.get('preferred_resource_manual'):
        updates.update(preferred_resource_manual=1,preferred_resource_id=source.get('preferred_resource_id'))
    elif not target.get('preferred_resource_id') and source.get('preferred_resource_id'):
        updates['preferred_resource_id']=source['preferred_resource_id']
    supplements=list(dict.fromkeys(json.loads(target.get('supplement_pdf_paths') or '[]')+json.loads(source.get('supplement_pdf_paths') or '[]')))
    if supplements:updates['supplement_pdf_paths']=json.dumps(supplements)
    storage.conn.execute('UPDATE papers SET '+','.join(k+'=?' for k in updates)+' WHERE paper_id=?',(*updates.values(),target_id))
    storage.conn.execute('DELETE FROM papers WHERE paper_id=?',(source_id,))
    storage.conn.execute('DELETE FROM author_monitor_card_cache WHERE paper_id=?',(target_id,))
    storage._sync_paper_source_projection(target_id)
    storage.conn.execute('UPDATE paper_identity_history SET snapshot_json=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),history_id))
    register(storage,storage.get_paper(target_id))
    return storage.get_paper(target_id)


def fingerprint(storage, paper_ids):
    """Include all reviewed relationships; reject a plan after concurrent edits."""
    placeholders = ','.join('?' for _ in paper_ids)
    state = {'papers': [dict(r) for r in storage.conn.execute(
        'SELECT * FROM papers WHERE paper_id IN ('+placeholders+') ORDER BY paper_id', paper_ids)]}
    tables = {r[0] for r in storage.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in sorted(set(RELATIONS) | SIMPLE | SPECIAL):
        field = 'existing_paper_id' if table == 'paper_identity_conflicts' else 'paper_id'
        # Card caches are disposable and may refresh between planning and apply.
        if table.startswith('author_monitor_card_cache'):
            continue
        if table not in tables:
            state[table] = []
            continue
        rows = [dict(r) for r in storage.conn.execute(
            'SELECT * FROM '+table+' WHERE '+field+' IN ('+placeholders+')', paper_ids)]
        state[table] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reconciliation_plan(storage):
    """Read-only plan of legacy DOI duplicates involving Author Monitor.

    No startup deletion: each proposed group has positive same-work evidence,
    file/default checks and a content fingerprint for a later explicit apply.
    """
    groups = []
    rows = storage.conn.execute('''SELECT lower(trim(doi)) AS doi FROM papers
        WHERE trim(COALESCE(doi,'')) != '' GROUP BY lower(trim(doi)) HAVING count(*)>1
        AND sum(EXISTS(SELECT 1 FROM author_monitor_papers a WHERE a.paper_id=papers.paper_id))>0''').fetchall()
    by_doi = {}
    values = [row['doi'] for row in rows]
    if values:
        for paper in storage.conn.execute('SELECT * FROM papers WHERE lower(trim(doi)) IN ('+
                                          ','.join('?' for _ in values)+')', values):
            by_doi.setdefault(doi(paper['doi']), []).append(dict(paper))
    for row in rows:
        if not doi(row['doi']):
            continue
        papers = by_doi.get(row['doi'], [])
        papers.sort(key=lambda p: rank(storage,p))
        target = papers[0]
        sources = papers[1:]
        blockers = []
        for source in sources:
            if not same_work_evidence(storage,target,source):
                blockers.append('Same-work evidence is insufficient')
            blockers += merge_blockers(storage,target,source)
        # A third member can conflict with the survivor chosen by an earlier merge.
        defaults = {p['preferred_resource_id'] for p in papers if p.get('preferred_resource_manual')}
        if len(defaults)>1:
            blockers.append('Different manual Default files need a choice')
        ids = [p['paper_id'] for p in papers]
        groups.append({'doi': row['doi'], 'target': target['paper_id'],
                       'target_key': target['storage_key'], 'sources': ids[1:],
                       'source_keys': [p['storage_key'] for p in sources],
                       'blockers': sorted(set(blockers)), 'fingerprint': fingerprint(storage,ids)})
    return {'version': 1, 'groups': groups}


def apply_reconciliation(storage, plan):
    """Apply a reviewed plan atomically; files are never moved or removed."""
    if plan.get('version') != 1:
        raise ValueError('Unsupported reconciliation plan')
    merged = []
    with transaction(storage):
        for group in plan['groups']:
            if group['blockers']:
                continue
            ids = [group['target'], *group['sources']]
            if fingerprint(storage,ids) != group['fingerprint']:
                raise ValueError('Paper records changed after planning; create a fresh plan')
            for source in group['sources']:
                target, incoming = storage.get_paper(group['target']), storage.get_paper(source)
                if not same_work_evidence(storage,target,incoming):
                    raise ValueError('Same-work evidence changed after planning')
                merge(storage,group['target'],source,reason='reviewed_author_duplicate')
                merged.append(source)
        if storage.conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Foreign-key validation failed; reconciliation rolled back')
    return merged
