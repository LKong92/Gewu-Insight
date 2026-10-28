"""Explicit, scoped writes. Imports never extract identifiers or query metadata."""
from __future__ import annotations
from contextlib import ExitStack, nullcontext
import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from .ai_contract import WRITE_SCOPES, METADATA_FIELDS, METADATA_REQUIRED
from .ai_store import authenticate, fail, utc_now
from . import ai_uploads


def writable_folders(storage, grant):
    from .ai_service import ACTIVE_FOLDERS
    roots = grant.get('write_folder_ids', [])
    if not roots or not set(grant['scopes']).intersection(WRITE_SCOPES.values()): return set()
    marks = ','.join('?' for _ in roots)
    return {r[0] for r in storage.conn.execute(ACTIVE_FOLDERS + f''', writable(id) AS (
      SELECT id FROM active_folders WHERE id IN ({marks}) UNION
      SELECT f.id FROM library_folders f JOIN writable w ON f.parent_id=w.id
      JOIN active_folders a ON a.id=f.id) SELECT id FROM writable''', roots)}


def require_folder(storage, grant, value):
    from .ai_service import integer
    folder_id = integer(value, 0, 1, 2**63-1)
    if folder_id not in writable_folders(storage, grant):
        fail(403, 'write_scope_required', 'Choose a folder in this connection’s writable collection.')
    return folder_id


def require_paper(storage, grant, key):
    from .ai_service import paper_for_key
    paper = paper_for_key(storage, grant, key)
    roots = writable_folders(storage, grant)
    if not any(r[0] in roots for r in storage.conn.execute("SELECT folder_id FROM library_items WHERE paper_id=? AND COALESCE(trashed_at,'')=''", (paper['paper_id'],))):
        fail(403, 'write_scope_required', 'This paper is outside the writable collection.')
    return paper


def validate_metadata(value, *, partial=False):
    from .paper_identity import doi
    from .text import normalize_arxiv_identifier
    if not isinstance(value, dict) or not value or set(value)-set(METADATA_FIELDS):
        fail(400, 'invalid_metadata', 'Provide the documented metadata fields. Obtain missing facts yourself; do not use Resolve as part of import.')
    missing = [k for k in (['source_url'] if partial else METADATA_REQUIRED) if k not in value]
    if missing:
        fail(400, 'metadata_required', 'AI must supply metadata before import. Missing: ' + ', '.join(missing) + '. Find these facts externally and retry; import never invokes Resolve.')
    result = dict(value)
    for key, val in value.items():
        if key == 'publication_notice':
            from .publication_notices import KINDS
            valid = (isinstance(val,dict) and set(val)=={'kind','related_dois','evidence_url'}
                     and val.get('kind') in KINDS and isinstance(val.get('related_dois'),list)
                     and 0 < len(val['related_dois']) <= 20
                     and all(isinstance(d,str) and re.fullmatch(r'10\.\d{4,9}/\S+',doi(d)) for d in val['related_dois'])
                     and isinstance(val.get('evidence_url'),str))
            if valid:
                u = urlparse(val['evidence_url'])
                valid = u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password
            if not valid: fail(400,'invalid_notice_relation','Supply a notice kind, original article DOI(s), and an HTTP(S) evidence URL without credentials.')
            result[key] = {**val,'related_dois':sorted({doi(d) for d in val['related_dois']})}
        elif key == 'authors':
            valid = isinstance(val, list) and 0 < len(val) <= 1000 and all(isinstance(a,str) and a.strip() and len(a)<=300 for a in val)
        elif key in ('doi', 'arxiv_id'):
            valid = val is None or isinstance(val,str) and bool(val.strip())
        else:
            valid = isinstance(val,str) and len(val) <= METADATA_FIELDS[key].get('maxLength', 2000)
            if key in METADATA_REQUIRED: valid = valid and bool(val.strip())
        if not valid: fail(400, 'invalid_metadata', f'Provide a valid {key}; genuinely absent DOI/arXiv uses null, unknown facts must be researched before import.')
    if 'publication_type' in value and value['publication_type'] not in ('journal_article','preprint','other'):
        fail(400, 'invalid_metadata', 'Choose journal_article, preprint or other.')
    if value.get('doi'):
        result['doi'] = doi(value['doi'])
        if not re.fullmatch(r'10\.\d{4,9}/\S+', result['doi']): fail(400, 'invalid_metadata', 'Provide a valid DOI.')
    if value.get('arxiv_id'):
        result['arxiv_id'] = normalize_arxiv_identifier(value['arxiv_id'])
        if not result['arxiv_id']: fail(400, 'invalid_metadata', 'Provide a valid arXiv ID.')
    if 'publication_date' in value:
        stamp = value['publication_date']
        try:
            if not re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', stamp): raise ValueError()
            date.fromisoformat(stamp + ('-01-01' if len(stamp)==4 else '-01' if len(stamp)==7 else ''))
        except ValueError: fail(400, 'invalid_metadata', 'Use a known publication year, YYYY-MM or YYYY-MM-DD.')
    if 'source_url' in value:
        u = urlparse(value['source_url'])
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
            fail(400, 'invalid_metadata', 'Provide an HTTP(S) metadata source URL without credentials.')
    return result


def metadata_payload(meta, paper_id, grant):
    from .paper_website import website_url
    raw = {'authors': meta.get('authors', []), 'ai_metadata': {'connection_id': grant['id'],
           'source_url': meta.get('source_url',''), 'supplied_at': utc_now(), 'verified_by_gewu': False}}
    if meta.get('arxiv_id'): raw['arxiv_id'] = meta['arxiv_id']
    if meta.get('publication_notice'): raw['publication_notice'] = meta['publication_notice']
    raw.update({k:meta[k] for k in ('volume','issue','pages') if k in meta})
    url = website_url({'doi': meta.get('doi'), 'url': meta.get('source_url'), 'raw': raw})
    return {'paper_id': paper_id, 'title': meta.get('title',''), 'doi': meta.get('doi') or '',
            'journal': meta.get('journal',''), 'publication_date':meta.get('publication_date',''),
            'abstract':meta.get('abstract',''), 'abstract_source':'AI supplied', 'source':'ai_import',
            'url':url, 'landing_url':url,
            'type':meta.get('publication_type',''), 'raw':raw}


def receipt(storage, grant, operation, args):
    key = ai_uploads.request_id(args.get('request_id'))
    digest = hashlib.sha256(json.dumps(args,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    row = storage.conn.execute('SELECT * FROM ai_write_requests WHERE connection_id=? AND request_id=?', (grant['id'],key)).fetchone()
    if row and (row['operation'] != operation or row['payload_hash'] != digest):
        fail(409, 'request_conflict', 'This request_id belongs to another operation or payload. Reuse it only for an exact retry.')
    return key, digest, json.loads(row['result_json']) if row else None


def save_receipt(storage, grant, operation, key, digest, result):
    storage.conn.execute('INSERT INTO ai_write_requests VALUES(?,?,?,?,?,?)',
        (grant['id'],key,operation,digest,json.dumps(result,ensure_ascii=False),utc_now()))


def safe_directory(path, roots):
    resolved = path.resolve()
    if not any(resolved == root.resolve() or root.resolve() in resolved.parents for root in roots):
        fail(403,'invalid_destination','The managed destination is outside the Library/Space storage roots.')
    return path


def recover_imports(storage):
    """Only undo our journaled, unregistered copies, never registered originals."""
    for journal in (storage.db_path.parent / 'ai-import-recovery').glob('*.json'):
        entry = json.loads(journal.read_text())
        destination = Path(entry['path'])
        registered = storage.conn.execute('SELECT 1 FROM resources WHERE stored_path=?', (str(destination),)).fetchone()
        if not registered:
            unlink_owned(destination, entry['identity'])
        if entry.get('temporary_path'):
            unlink_owned(Path(entry['temporary_path']), entry['identity'])
        journal.unlink()


def unlink_owned(path, identity):
    """Rollback must never unlink an unrelated file that won a name collision."""
    try:
        st = path.lstat()
        if (st.st_dev, st.st_ino) == tuple(identity):
            path.unlink()
    except FileNotFoundError:
        pass


def finish_import(storage, grant, result):
    from .ai_service import paper_for_key, file_metadata
    from .download import paper_download_lock
    from .file_layout import reconcile
    paper = paper_for_key(storage, grant, result['gewu_key'])
    resource = None
    if result.get('file'):
        resource = storage.get_paper_resource(result['file']['file_id'])
        if not resource or resource['paper_id'] != paper['paper_id'] or not Path(storage.resource_local_path(resource)).is_file():
            fail(410,'import_removed','The previously imported file is unavailable. A retry will not recreate deleted content.')
    else:
        member = storage.get_library_item(result['membership_id'])
        if not member or member['paper_id'] != paper['paper_id'] or member['folder_id'] != result['folder_id'] or member.get('trashed_at'):
            fail(410,'import_removed','The previously imported placement is unavailable. A retry will not recreate a removed or moved item.')
    if result.get('folder_id'): require_folder(storage,grant,result['folder_id'])
    else: require_paper(storage,grant,paper['storage_key'])
    try:
        with paper_download_lock(storage.db_path, paper['paper_id'], blocking=False):
            reconcile(storage, paper['paper_id'])
        result['layout_pending'] = False
        result.pop('message', None)
    except (OSError, ValueError):
        storage.conn.rollback()
        result['layout_pending'] = True
        result['message'] = 'Import saved; shortcut synchronization is pending. Retry this exact request to finish.'
    if resource:
        resource = storage.get_paper_resource(resource['id'])
        default = storage._select_default_paper_resource(storage.get_paper(paper['paper_id']),storage.list_paper_resources(paper['paper_id'],ensure_primary=False))
        result['file'] = file_metadata(resource, (default or {}).get('id',0))
        ai_uploads.consume(storage,result['upload_id'])
    return result


def apply_metadata(storage, grant, paper, meta):
    """Fill missing values; preserve originals and report competing facts."""
    from . import paper_identity, ui_server as ui
    incoming = metadata_payload(meta,paper['paper_id'],grant)
    from .publication_notices import describe_known
    if describe_known(storage,incoming):
        fail(409,'publication_notice_requires_attachment','A publication notice cannot replace article metadata. Import it with its original article relation instead.')
    candidates = paper_identity.find(storage,incoming)
    if any(p['paper_id'] != paper['paper_id'] for p in candidates):
        fail(409,'identity_conflict','The supplied identifiers belong to another record. Existing identities were preserved.')
    raw = ui.parse_raw_json(paper); fields=[]; conflicts=[]
    updates={}
    for field in ('title','doi','journal','publication_date','abstract'):
        value=incoming.get(field)
        if not value: continue
        if paper.get(field) and paper[field] != value: conflicts.append(field)
        elif not paper.get(field): updates[field]=value; fields.append(field)
    for field in ('authors','arxiv_id','volume','issue','pages'):
        value=incoming['raw'].get(field)
        if not value: continue
        if raw.get(field) and raw[field] != value: conflicts.append(field)
        elif not raw.get(field): raw[field]=value; fields.append(field)
    if fields:
        raw.setdefault('ai_metadata_updates',[]).append(incoming['raw']['ai_metadata'])
        raw['ai_metadata_updates']=raw['ai_metadata_updates'][-50:]
        updates['raw_json']=json.dumps(raw,ensure_ascii=False)
        storage.conn.execute('UPDATE papers SET '+','.join(k+'=?' for k in updates)+' WHERE paper_id=?', [*updates.values(),paper['paper_id']])
        paper_identity.register(storage,storage.get_paper(paper['paper_id']))
    return {'gewu_key':paper['storage_key'],'updated_fields':fields,'preserved_conflicts':conflicts}


def execute_write(storage, authorization, operation, args):
    from .ai_service import WRITE_LOCK, require_scope
    from .ai_contract import ORGANIZE_TOOLS
    from .publication_notices import NoticeReviewRequired
    from .publication_jobs import MUTATION_LOCK
    if operation in ORGANIZE_TOOLS:
        from .ai_organize import execute_organize
        return execute_organize(storage, authorization, operation, args)
    if operation in ('resolve_paper','get_resolve_status'):
        from .ai_resolve import execute_resolve
        return execute_resolve(storage,authorization,operation,args)
    import_lock = MUTATION_LOCK if operation in ('import_paper', 'import_file', 'add_paper_file') else nullcontext()
    with WRITE_LOCK, import_lock, ai_uploads.LOCK:
        grant=authenticate(storage,authorization); require_scope(grant,WRITE_SCOPES[operation])
        allowed={
            'create_space':{'name','request_id'}, 'create_folder':{'parent_id','name','request_id'},
            'import_paper':{'folder_id','upload_id','metadata','file_type','request_id'},
            'import_file':{'folder_id','upload_id','file_type','request_id'},
            'add_paper_file':{'gewu_key','upload_id','file_type','request_id'},
            'update_paper_metadata':{'gewu_key','metadata','request_id'},
        }[operation]
        if set(args)-allowed: fail(400,'invalid_arguments','Use only the documented arguments; import has no Resolve option.')
        key,digest,prior=receipt(storage,grant,operation,args)
        recover_imports(storage)
        if prior:
            if 'file' in prior: return {**finish_import(storage,grant,prior),'reused_request':True}
            if 'folder_id' in prior: require_folder(storage,grant,prior['folder_id'])
            if 'gewu_key' in prior: require_paper(storage,grant,prior['gewu_key'])
            return {**prior,'reused_request':True}
        if operation in ('create_space','create_folder'):
            return create_folder(storage,authorization,grant,operation,args,key,digest)
        if operation == 'update_paper_metadata':
            paper=require_paper(storage,grant,args.get('gewu_key'))
            meta=validate_metadata(args.get('metadata'),partial=True)
            storage.conn.execute('BEGIN IMMEDIATE')
            try:
                grant=authenticate(storage,authorization); require_scope(grant,WRITE_SCOPES[operation])
                paper=require_paper(storage,grant,paper['storage_key'])
                result=apply_metadata(storage,grant,paper,meta)
                save_receipt(storage,grant,operation,key,digest,result);storage.conn.commit()
                return result
            except BaseException: storage.conn.rollback();raise
        try:
            return import_file(storage,authorization,grant,operation,args,key,digest)
        except NoticeReviewRequired as exc:
            fail(409,'notice_review_required',str(exc))


def create_folder(storage,authorization,grant,operation,args,key,digest):
    from . import ui_server as ui
    from .ai_service import require_scope
    name=ai_uploads.filename(args.get('name'))
    if len(name)>80: fail(400,'invalid_name','Use a folder name of at most 80 characters.')
    created=None
    storage.conn.execute('BEGIN IMMEDIATE')
    try:
        grant=authenticate(storage,authorization);require_scope(grant,WRITE_SCOPES[operation])
        if operation=='create_folder':
            parent=require_folder(storage,grant,args.get('parent_id'))
            if parent == 1 and name.casefold() == 'recycle':
                fail(400,'reserved_name','Recycle is reserved for the App’s trash collection.')
            folder=storage.create_library_folder(parent_id=parent,name=name,commit=False)
        else:
            folder=storage.create_library_root_folder(name=name,commit=False)
        destination=ui.local_copy_dir_for_library_folder(storage,folder['id'])
        safe_directory(destination,[ui.LIBRARY_LOCAL_COPY_ROOT,ui.SPACES_LOCAL_COPY_ROOT])
        # Do not silently adopt an unrelated directory not represented in SQLite.
        if destination.exists(): fail(409,'destination_exists','A directory already occupies this name. Choose another name.')
        destination.mkdir(parents=True,exist_ok=False);created=destination
        if operation=='create_space':
            roots=sorted(set(grant.get('write_folder_ids',[])+[folder['id']]))
            storage.conn.execute('UPDATE ai_connections SET write_roots_json=? WHERE id=?',(json.dumps(roots),grant['id']))
        result={'folder_id':folder['id'],'name':folder['name'],'parent_id':folder['parent_id'],
                'kind':'space' if operation=='create_space' else 'folder'}
        save_receipt(storage,grant,operation,key,digest,result);storage.conn.commit()
        return result
    except BaseException:
        storage.conn.rollback()
        if created:
            try: created.rmdir()
            except OSError: pass
        raise


def import_file(storage,authorization,grant,operation,args,key,digest):
    from . import ui_server as ui, paper_identity, publication_notices as notices
    from .ai_service import require_scope, file_metadata
    from .resource_dedup import find_content, remember_source
    from .resource_fingerprint import sha256_for_file
    from .file_layout import bundle_path
    from .file_layout_journal import write_json
    from .ai_import_identity import reusable_paper
    from .download import paper_download_lock
    meta=validate_metadata(args.get('metadata')) if operation=='import_paper' else None
    notice = notices.describe_known(storage,meta) if meta else None
    if meta and (notice or args.get('file_type') in notices.KINDS):
        if not notice or not meta.get('publication_notice'):
            fail(400,'notice_relation_required','This is a publication notice. Supply metadata.publication_notice with its kind, original article DOI and evidence_url. Import the original article first; import never runs Resolve.')
    if operation=='add_paper_file': paper=require_paper(storage,grant,args.get('gewu_key')); folder_id=None
    else: folder_id=require_folder(storage,grant,args.get('folder_id'));paper=None
    metadata_only = operation == 'import_paper' and 'upload_id' not in args
    upload = None
    if metadata_only:
        if 'file_type' in args:
            fail(400,'upload_required','Omit file_type when importing metadata without a PDF. Add and classify the file later with add_paper_file.')
    else:
        # A supplied but invalid/missing upload never silently becomes metadata-only.
        upload,source=ai_uploads.get_upload(storage,grant,args.get('upload_id'))
        suffix=Path(upload['filename']).suffix.lower()
        if operation=='import_paper' and suffix!='.pdf': fail(400,'pdf_required','Use import_file for a standalone non-PDF file.')
        if operation=='import_file' and suffix=='.pdf': fail(400,'metadata_required','Import an independent PDF with import_paper and AI-supplied metadata.')
        kind=args.get('file_type') or ('unknown' if suffix=='.pdf' else 'other')
        if notice: kind=notice['kind']
        elif suffix=='.pdf': kind=notices.title_kind(Path(upload['filename']).stem) or kind
        if meta and not notice and kind in notices.KINDS:
            fail(400,'notice_relation_required','A notice PDF needs explicit original-article relation metadata before import. The upload remains available for retry.')
        if kind not in ui.PAPER_FILE_TYPES or kind=='invalid_file': fail(400,'invalid_file_type','Choose an available Paper Files classification.')
        if suffix=='.pdf' and not ui.is_valid_pdf_file(source): fail(400,'invalid_pdf','The uploaded PDF is invalid.')
        # Exact-byte identity is sufficient; do not decompress every PDF stream.
        if sha256_for_file(source)!=upload['sha256']: fail(409,'file_changed','The staged file changed. Upload it again.')
    destination=None;temporary=None;identity=None;journal=None;committed=False
    locks=ExitStack()
    def lock_paper(paper_id):
        # Never wait for a downloader while holding SQLite's writer lock: its
        # registration needs that transaction too. The staged upload is retryable.
        try:
            locks.enter_context(paper_download_lock(storage.db_path,paper_id,blocking=False))
        except ValueError:
            fail(409,'paper_busy','This paper is being updated. Retry this request after it finishes; any staged upload is still available.')
    storage.conn.execute('BEGIN IMMEDIATE')
    try:
        grant=authenticate(storage,authorization);require_scope(grant,WRITE_SCOPES[operation])
        if folder_id: require_folder(storage,grant,folder_id)
        if paper:
            lock_paper(paper['paper_id'])
            paper=require_paper(storage,grant,paper['storage_key'])
        reused=False
        notice_id=None
        if notice:
            parent=notices.target(storage,notice)
            if not parent:
                fail(409,'notice_target_required','The notice needs one unambiguous original article already in the writable collection. Import that article first, or resolve multiple/uncertain relations externally, then retry. No PDF scan or Resolve ran.')
            lock_paper(parent['paper_id'])
            paper=require_paper(storage,grant,parent['storage_key']);reused=True
            notice_id=notices.record(storage,meta,notice,paper)
        elif meta:
            incoming=metadata_payload(meta,'ai_'+uuid.uuid4().hex,grant)
            candidates=paper_identity.find(storage,incoming)
            if len(candidates)>1: fail(409,'identity_conflict','The supplied identifiers point to multiple records. No new identity or file was created.')
            if candidates:
                lock_paper(candidates[0]['paper_id'])
                paper=reusable_paper(storage,grant,candidates[0]);reused=True
                old_ids={k:v for k,v in paper_identity.identifiers(storage,paper) if k in ('doi','arxiv')}
                new_ids={k:v for k,v in paper_identity.identifiers(storage,incoming) if k in ('doi','arxiv')}
                if any(k in old_ids and old_ids[k]!=v for k,v in new_ids.items()):
                    fail(409,'identity_conflict','The supplied DOI/arXiv combination conflicts with the existing identity.')
                raw = ui.parse_raw_json(paper)
                if raw.get('manual_preprint_identifier_override') and 'arxiv' in new_ids and old_ids.get('arxiv') != new_ids['arxiv']:
                    fail(409,'identity_conflict','The supplied arXiv ID conflicts with a manually confirmed identity.')
                # Preserve bibliography, but retain newly supplied identity evidence
                # so a future arXiv-only/DOI-only import finds this same work.
                identity_meta = {k:meta[k] for k in ('doi','arxiv_id','source_url') if meta.get(k)}
                apply_metadata(storage,grant,paper,identity_meta)
                paper=storage.get_paper(paper['paper_id'])
            else:
                if not storage.upsert_paper(incoming,commit=False): fail(409,'identity_conflict','The supplied identity conflicts with an existing record.')
                paper=storage.get_paper(incoming['paper_id'])
        elif not paper:
            incoming={'paper_id':'ai_file_'+uuid.uuid4().hex,'title':upload['filename'],'source':'ai_import',
                      'type':'imported_file','journal':'Imported File','raw':{'file':{'kind':suffix.lstrip('.') or 'file','extension':suffix,'mime_type':mimetypes.guess_type(upload['filename'])[0] or 'application/octet-stream'}}}
            storage.upsert_paper(incoming,commit=False);paper=storage.get_paper(incoming['paper_id'])
        paper_id=paper['paper_id']
        storage.ensure_primary_pdf_resource(paper_id,commit=False)
        paper=storage.get_paper(paper_id)
        resources=storage.list_paper_resources(paper_id,ensure_primary=False)
        default=storage._select_default_paper_resource(paper,resources)
        member=storage.add_library_item(paper_id=paper_id,folder_id=folder_id,commit=False) if folder_id else None
        if metadata_only:
            result={'gewu_key':paper['storage_key'],'item_kind':'paper',
                    'folder_id':folder_id,'membership_id':member['id'],'reused_paper':reused,
                    'reused_file':False,'file':None,
                    'metadata_resolution':'not_requested','layout_pending':True}
            if notice_id: result['publication_notice_id']=notice_id
            save_receipt(storage,grant,operation,key,digest,result)
            storage.conn.commit();committed=True
            return finish_import(storage,grant,result)
        duplicate=find_content(storage,paper_id,upload['sha256'],upload['size_bytes'])
        role,version,label=ui.legacy_role_projection(kind)
        if duplicate:
            resource=duplicate
        else:
            if default:
                canonical=Path(storage.resource_local_path(default)).resolve()
                directory=bundle_path(ui,canonical,paper['storage_key']) or ui.associated_work_dir_for_paper(storage,paper_id)
                directory=directory/ui.associated_resource_subdir(role)
            elif kind in notices.KINDS:
                directory=ui.associated_work_dir_for_paper(storage,paper_id)/ui.associated_resource_subdir(role)
            else:
                if not folder_id:
                    folder_id=next(r[0] for r in storage.conn.execute("SELECT folder_id FROM library_items WHERE paper_id=? AND COALESCE(trashed_at,'')='' ORDER BY id",(paper_id,)) if r[0] in writable_folders(storage,grant))
                directory=ui.local_copy_dir_for_library_folder(storage,folder_id)
            safe_directory(directory,[ui.LIBRARY_LOCAL_COPY_ROOT,ui.SPACES_LOCAL_COPY_ROOT,ui.ASSOCIATED_FILES_ROOT,ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT])
            directory.mkdir(parents=True,exist_ok=True)
            destination=ui.unique_path_in_dir(directory/ui.finder_safe_name(upload['filename'],preserve_extension=True))
            # Journal an owned inode before publishing the final name. Linking is
            # exclusive: a racing external file is never overwritten or deleted.
            fd, temp_name=tempfile.mkstemp(prefix='.gewu-ai-',dir=directory)
            temporary=Path(temp_name)
            st=os.fstat(fd);identity=[st.st_dev,st.st_ino]
            journal=storage.db_path.parent/'ai-import-recovery'/(uuid.uuid4().hex+'.json')
            with os.fdopen(fd,'wb') as output, source.open('rb') as input_file:
                write_json(journal,{'path':str(destination),'temporary_path':str(temporary),'identity':identity})
                shutil.copyfileobj(input_file,output,256*1024);output.flush();os.fsync(output.fileno())
            os.link(temporary,destination)
            temporary.unlink();temporary=None
            resource=storage.create_paper_resource(paper_id=paper_id,stored_path=str(destination),display_name=destination.name,
                file_type=kind,file_role=role,version_role=version,version_label=label,file_source='user_import',
                source_detail='AI import · '+grant['name'],source_url=(meta or {}).get('source_url',''),
                added_via='ai_import_attachment' if default else 'ai_import',sha256=upload['sha256'],
                annotation_state='unknown' if suffix=='.pdf' else 'unannotated',
                mime_type=mimetypes.guess_type(upload['filename'])[0] or 'application/octet-stream',commit=False)
            if not default and kind not in notices.KINDS:
                raw=ui.parse_raw_json(paper)
                raw['file_layout']={'canonical_path':str(destination),'default_resource_id':resource['id'],'version':1,'links_pending':True}
                storage.conn.execute('UPDATE papers SET primary_resource_id=?,main_pdf_path=?,merged_pdf_path=?,original_filename=?,import_kind=?,raw_json=? WHERE paper_id=?',
                    (resource['id'] if suffix=='.pdf' else None,str(destination) if suffix=='.pdf' else '',str(destination) if suffix=='.pdf' else '',upload['filename'],suffix.lstrip('.') or 'file',json.dumps(raw,ensure_ascii=False),paper_id))
        if notice_id:
            notices.attach(storage,notice_id,resource['id'])
            resource=storage.get_paper_resource(resource['id'])
        remember_source(storage,resource['id'],{'source_path':'ai-upload:'+upload['upload_id'],'size_bytes':upload['size_bytes'],'kind':suffix.lstrip('.'),'connection_id':grant['id'],'source_url':(meta or {}).get('source_url','')},upload['sha256'],key)
        result={'gewu_key':paper['storage_key'],'item_kind':'file' if operation=='import_file' else 'paper',
                'folder_id':folder_id,'membership_id':(member or {}).get('id'),'reused_paper':reused,
                'reused_file':bool(duplicate),'file':file_metadata(resource),'upload_id':upload['upload_id'],
                'metadata_resolution':'not_requested','layout_pending':True}
        if notice_id: result['publication_notice_id']=notice_id
        save_receipt(storage,grant,operation,key,digest,result);storage.conn.commit();committed=True
        if journal: journal.unlink(missing_ok=True)
        return finish_import(storage,grant,result)
    except BaseException:
        storage.conn.rollback()
        if not committed:
            if destination and identity: unlink_owned(destination,identity)
            if temporary and identity: unlink_owned(temporary,identity)
            if journal: journal.unlink(missing_ok=True)
        raise
    finally:
        locks.close()
