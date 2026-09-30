"""Publication notices are evidence about a work, never another research identity.

All classification here uses supplied metadata. No network or PDF scanning is
performed, including when this module is called by an MCP import.
"""
from __future__ import annotations

import hashlib
import json
import re

from .time_utils import now_iso

KINDS = {
    'correction_notice': 'Correction notice',
    'retraction_notice': 'Retraction notice',
    'expression_of_concern': 'Expression of concern',
    'withdrawal_notice': 'Withdrawal notice',
    'addendum': 'Addendum',
}
ALIASES = {
    'correction': 'correction_notice', 'erratum': 'correction_notice',
    'corrigendum': 'correction_notice', 'retraction': 'retraction_notice',
    'partial_retraction': 'retraction_notice', 'withdrawal': 'withdrawal_notice',
    'expression-of-concern': 'expression_of_concern',
}
_PREFIX = re.compile(
    r'^\s*(?:\d{4}\s+)?(?:(?:author|publisher|editorial)\s+)?'
    r'(correction|erratum|corrigendum|retraction(?:\s+note|\s+notice)?|'
    r'withdrawal(?:\s+notice)?|expression\s+of\s+concern|addendum)'
    r'(?:\s+(?:to|for|of))?\s*(?:[:：\[\(\-–—]|$)', re.I)


class NoticeReviewRequired(ValueError):
    def __init__(self, message=None):
        super().__init__(message or
            'This is a publication notice, not a standalone paper. Supply its '
            'original article DOI and evidence, then attach it to that article. '
            'No paper identity or Default was changed.')


def title_kind(title):
    title=str(title or '').replace('_', ' ')
    labelled=re.match(r'^\s*(?:\d{4}\s+)?(?:author|publisher|editorial)\s+correction\b',title,re.I)
    if labelled: return 'correction_notice'
    match = _PREFIX.match(title)
    if not match:
        return ''
    word = match[1].lower()
    if word.startswith('retraction'): return 'retraction_notice'
    if word.startswith('withdrawal'): return 'withdrawal_notice'
    if word.startswith('expression'): return 'expression_of_concern'
    return ALIASES.get(word, word)


def _raw(paper):
    value = paper.get('raw', paper.get('raw_json', {}))
    if isinstance(value, str):
        try: value = json.loads(value)
        except (ValueError, TypeError): value = {}
    return value if isinstance(value, dict) else {}


def describe(paper):
    """Only explicit notice titles/types and outgoing Crossmark updates qualify.

    is_retracted/update-by describe an ORIGINAL work; they are not notices.
    A corrected full text, reply or comment is not a correction notice either.
    """
    from .paper_identity import doi
    raw = _raw(paper)
    explicit = paper.get('publication_notice') or raw.get('publication_notice') or {}
    kind = explicit.get('kind', '') if isinstance(explicit, dict) else ''
    kind = ALIASES.get(kind, kind)
    targets = list(explicit.get('related_dois') or []) if isinstance(explicit, dict) else []
    evidence = explicit.get('evidence_url', '') if isinstance(explicit, dict) else ''
    kind = kind if kind in KINDS else title_kind(paper.get('title'))
    for record in (paper, raw, raw.get('crossref') or {}):
        if not isinstance(record, dict): continue
        record_kind = str(record.get('type') or '').lower()
        if not kind: kind = ALIASES.get(record_kind, record_kind if record_kind in KINDS else '')
        for update in record.get('update-to') or []:
            if not isinstance(update, dict): continue
            update_kind = ALIASES.get(update.get('type'), update.get('type'))
            if update_kind in KINDS:
                kind = kind or update_kind
                if update.get('DOI'): targets.append(update['DOI'])
    if not kind: return None
    own = doi(paper.get('doi') or paper.get('DOI'))
    normalized = sorted({doi(value) for value in targets if isinstance(value, str) and doi(value)})
    # A self-update is not evidence identifying another original article.
    return dict(kind=kind, related_dois=normalized,
                evidence_url=evidence or paper.get('url') or paper.get('source_url') or '',
                doi=own, title=str(paper.get('title') or ''),
                publication_date=str(paper.get('publication_date') or ''),
                source_url=str(paper.get('source_url') or paper.get('landing_url') or paper.get('url') or ''))


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS publication_notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, identity TEXT NOT NULL UNIQUE,
        paper_id TEXT REFERENCES papers(paper_id) ON DELETE SET NULL,
        kind TEXT NOT NULL, doi TEXT NOT NULL DEFAULT '', title TEXT NOT NULL,
        publication_date TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_notice_paper ON publication_notices(paper_id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS publication_notice_files (
        notice_id INTEGER NOT NULL REFERENCES publication_notices(id) ON DELETE CASCADE,
        resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
        PRIMARY KEY(notice_id, resource_id))''')


def describe_known(storage, paper):
    notice = describe(paper)
    if notice: return notice
    from .paper_identity import doi
    identifier=doi(paper.get('doi'))
    if identifier:
        row=storage.conn.execute('SELECT evidence_json FROM publication_notices WHERE identity=?',('doi:'+identifier,)).fetchone()
        if row: return json.loads(row[0])
    return None


def target(storage, notice):
    ids = notice['related_dois']
    if len(ids) != 1 or ids[0] == notice['doi']:
        return None
    rows = storage.conn.execute('SELECT * FROM papers WHERE lower(doi)=? LIMIT 2', (ids[0],)).fetchall()
    if len(rows) != 1 or describe(dict(rows[0])):
        return None
    return dict(rows[0])


def record(storage, paper, notice, parent=None, *, commit=False):
    """Keep unresolved evidence without inventing a paper or public Gewu Key."""
    identity = 'doi:' + notice['doi'] if notice['doi'] else 'metadata:' + hashlib.sha256(
        json.dumps([notice['title'], notice['publication_date'], notice['source_url']], ensure_ascii=False).encode()).hexdigest()
    old = storage.conn.execute('SELECT * FROM publication_notices WHERE identity=?', (identity,)).fetchone()
    parent_id = parent['paper_id'] if parent else None
    if old and old['paper_id'] and parent_id and old['paper_id'] != parent_id:
        raise NoticeReviewRequired('This notice is already associated with a different article. Review the relation; existing files were preserved.')
    if old and old['kind'] != notice['kind']:
        raise NoticeReviewRequired('The notice type conflicts with its saved evidence. Review the existing notice before changing it.')
    timestamp = now_iso()
    if old:
        old_evidence = json.loads(old['evidence_json'])
        if old['paper_id'] and notice['related_dois'] and old_evidence.get('related_dois') != notice['related_dois']:
            raise NoticeReviewRequired('The supplied notice relation conflicts with its saved evidence.')
        # Do not replace complete evidence with a less informative later observation.
        if not old['paper_id'] and parent:
            storage.conn.execute('UPDATE publication_notices SET paper_id=?,evidence_json=?,status=?,updated_at=? WHERE id=?',
                                 (parent_id,json.dumps(notice,ensure_ascii=False),'linked',timestamp,old['id']))
        notice_id = old['id']
    else:
        cursor = storage.conn.execute('''INSERT INTO publication_notices
            (identity,paper_id,kind,doi,title,publication_date,source_url,evidence_json,metadata_json,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (identity,parent_id,notice['kind'],notice['doi'],notice['title'],notice['publication_date'],notice['source_url'],
             json.dumps(notice,ensure_ascii=False),json.dumps(paper,ensure_ascii=False,default=str),
             'linked' if parent else 'needs_relation',timestamp,timestamp))
        notice_id = cursor.lastrowid
    if commit: storage.conn.commit()
    return int(notice_id)


def attach(storage, notice_id, resource_id):
    event = storage.conn.execute('SELECT * FROM publication_notices WHERE id=?',(notice_id,)).fetchone()
    resource = storage.get_paper_resource(resource_id)
    if not event or not resource or event['paper_id'] != resource['paper_id']:
        raise NoticeReviewRequired('The notice and file must belong to the same original article.')
    from .storage import legacy_role_projection, AUTOMATIC_DEFAULT_FILE_TYPE_RANK
    if resource.get('file_type') in AUTOMATIC_DEFAULT_FILE_TYPE_RANK:
        raise NoticeReviewRequired('These bytes already belong to an article version. A notice import cannot reclassify or replace that file.')
    role,version,label = legacy_role_projection(event['kind'])
    storage.conn.execute('UPDATE resources SET file_type=?,file_role=?,version_role=?,version_label=? WHERE id=?',
                         (event['kind'],role,version,label,resource_id))
    storage.conn.execute('INSERT OR IGNORE INTO publication_notice_files VALUES(?,?)',(notice_id,resource_id))


def for_paper(storage, paper_id):
    result = []
    for row in storage.conn.execute('SELECT * FROM publication_notices WHERE paper_id=? ORDER BY publication_date,id',(paper_id,)):
        event = {key:row[key] for key in ('id','kind','doi','title','publication_date','source_url','status')}
        event['relation'] = json.loads(row['evidence_json'])
        event['file_ids'] = [r[0] for r in storage.conn.execute('SELECT f.resource_id FROM publication_notice_files f JOIN resources r ON r.id=f.resource_id WHERE f.notice_id=? AND r.paper_id=?',(row['id'],paper_id))]
        result.append(event)
    return result


def adopt_pending_files(storage, notice_id, parent):
    """Local Loader continuation, never implicitly invoked by a scoped AI client."""
    storage.conn.execute('''UPDATE resources SET paper_id=? WHERE paper_id IS NULL
        AND id IN (SELECT resource_id FROM publication_notice_files WHERE notice_id=?)''',
        (parent['paper_id'],notice_id))
    storage.conn.commit()


def rehome_legacy(storage, source_id, target_id, notice, notice_file_ids):
    """Explicit, rehearsable repair; never run on startup or as part of import.

    The caller backs up SQLite and reconciles managed layout afterwards. Files
    and saved note bytes are not edited; old Keys resolve to the original work.
    Unknown/non-library relationships stop the repair instead of discarding data.
    """
    from . import paper_identity
    from .storage import legacy_role_projection
    with paper_identity.transaction(storage):
        source=storage.get_paper(source_id); parent=storage.get_paper(target_id)
        if not source or not parent or source['paper_id']==parent['paper_id']:
            raise NoticeReviewRequired('Choose two distinct existing records for this explicit repair.')
        if not describe(source) or notice['doi'] != paper_identity.doi(source.get('doi')) or (target(storage,notice) or {}).get('paper_id') != parent['paper_id']:
            raise NoticeReviewRequired('The repair requires notice metadata and an explicit matching original DOI.')
        allowed={'resources','ai_analyses','library_items','paper_identifiers','paper_aliases','paper_source_observations', 'author_monitor_card_cache'}
        tables={r[0] for r in storage.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        snapshot={'source':source,'target':parent,'source_relationships':{}}
        for table in tables:
            for fk in storage.conn.execute('PRAGMA foreign_key_list("'+table.replace('"','""')+'")'):
                if fk['table']!='papers': continue
                rows=[dict(r) for r in storage.conn.execute('SELECT * FROM "'+table.replace('"','""')+'" WHERE "'+fk['from']+'"=?',(source['paper_id'],))]
                if rows and table not in allowed:
                    raise NoticeReviewRequired('Repair needs review of existing relationship: '+table)
                if rows: snapshot['source_relationships'][table]=rows
        resources=snapshot['source_relationships'].get('resources',[])
        pdf_ids={r['id'] for r in resources if storage.resource_is_pdf(r)}
        if not pdf_ids or set(notice_file_ids)!=pdf_ids:
            raise NoticeReviewRequired('Explicitly verify every notice PDF file ID before repair.')
        snapshot['target_library_items']=[dict(r) for r in storage.conn.execute('SELECT * FROM library_items WHERE paper_id=?',(parent['paper_id'],))]
        event_id=record(storage,source,notice,parent)
        for r in resources:
            storage.conn.execute('UPDATE resources SET paper_id=? WHERE id=?',(parent['paper_id'],r['id']))
            if r['id'] in pdf_ids:
                role,version,label=legacy_role_projection(notice['kind'])
                storage.conn.execute('UPDATE resources SET file_type=?,file_role=?,version_role=?,version_label=? WHERE id=?',(notice['kind'],role,version,label,r['id']))
            storage.conn.execute('INSERT OR IGNORE INTO publication_notice_files VALUES(?,?)',(event_id,r['id']))
        for item in snapshot['source_relationships'].get('library_items',[]):
            prior=storage.conn.execute('SELECT id FROM library_items WHERE paper_id=? AND folder_id=?',(parent['paper_id'],item['folder_id'])).fetchone()
            if prior:
                storage.conn.execute('DELETE FROM library_items WHERE id=?',(item['id'],))
            else:
                storage.conn.execute("UPDATE library_items SET paper_id=?,display_name='' WHERE id=?",(parent['paper_id'],item['id']))
        storage.conn.execute('UPDATE ai_analyses SET paper_id=? WHERE paper_id=?',(parent['paper_id'],source['paper_id']))
        storage.conn.execute('UPDATE paper_aliases SET paper_id=? WHERE paper_id=?',(parent['paper_id'],source['paper_id']))
        paper_identity.add_alias(storage,source['paper_id'],parent['paper_id'])
        paper_identity.add_alias(storage,source['storage_key'],parent['paper_id'])
        storage.conn.execute('INSERT INTO paper_identity_history(target_paper_id,source_paper_id,source_key,reason,snapshot_json,created_at) VALUES(?,?,?,?,?,?)',
            (parent['paper_id'],source['paper_id'],source['storage_key'],'publication_notice_rehomed',json.dumps(snapshot,ensure_ascii=False),now_iso()))
        # Source identifiers and observations remain in event metadata/history,
        # NOT in the original article's canonical identity/projection.
        storage.conn.execute('DELETE FROM papers WHERE paper_id=?',(source['paper_id'],))
        return {'notice_id':event_id,'gewu_key':parent['storage_key'],'previous_key':source['storage_key'],'file_ids':[r['id'] for r in resources]}


def guard(storage, paper, *, commit=True):
    notice = describe_known(storage,paper)
    if notice:
        record(storage,paper,notice,target(storage,notice),commit=commit)
        raise NoticeReviewRequired()


def record_for_ingestion(storage, paper):
    """Route one monitor observation inside its caller's transaction.

    A retained notice is an expected outcome, not a rejected paper. Relation
    conflicts still raise NoticeReviewRequired and must remain reviewable.
    Ordinary writers and their notice guard keep their existing contract.
    """
    notice = describe_known(storage, paper)
    if notice is None:
        return None
    return record(storage, paper, notice, target(storage, notice), commit=False)


def from_front_matter(title, text):
    """Use front matter ALREADY read by the ordinary PDF importer, not MCP."""
    from .paper_identity import doi
    kind = title_kind(title)
    if not kind:
        kind = next((title_kind(line) for line in text.splitlines()[:20] if title_kind(line)), '')
    if not kind: return None
    # Only an explicitly labelled relation; never all DOI mentions/references.
    matches = re.findall(r'(?:Correction\s+to|Erratum\s+(?:to|for)|Corrigendum\s+to|Retraction\s+(?:of|to)|Retraction\s+Note\s+to)\s*:\s*[^\n]{0,120}?(10\.\d{4,9}/[^\s<>]+)', text, re.I)
    return {'kind':kind,'related_dois':sorted({doi(m) for m in matches}), 'evidence_url':''}
