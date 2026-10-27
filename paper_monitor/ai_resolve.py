"""Standalone, explicitly authorized Resolve jobs; never called by import."""
from __future__ import annotations
import json
import threading
from . import update_runtime
import uuid
from .ai_store import APIError, authenticate, fail
from .ai_writes import require_paper, receipt, save_receipt, apply_metadata

SESSION = uuid.uuid4().hex
SLOTS = threading.BoundedSemaphore(2)


def execute_resolve(storage, authorization, operation, args):
    from .ai_service import WRITE_LOCK, require_scope
    from .ai_uploads import request_id
    with WRITE_LOCK:
        grant=authenticate(storage,authorization);require_scope(grant,'papers:resolve')
        key=request_id(args.get('request_id'))
        if operation=='get_resolve_status':
            if set(args)!={'request_id'}: fail(400,'invalid_arguments','Provide only the Resolve request_id.')
            row=storage.conn.execute("SELECT result_json FROM ai_write_requests WHERE connection_id=? AND request_id=? AND operation='resolve_paper'",(grant['id'],key)).fetchone()
            if not row: fail(404,'job_unavailable','This Resolve request is unavailable.')
            result=json.loads(row[0]);require_paper(storage,grant,result['gewu_key'])
            if result.get('status') in ('queued','running') and result.get('_session')!=SESSION:
                result.update(status='interrupted',message='The service restarted. Retry resolve_paper with the original arguments and request_id.')
            return {k:v for k,v in result.items() if not k.startswith('_')}
        if set(args)-{'gewu_key','request_id','purpose'} or args.get('purpose')!='standalone':
            fail(400,'standalone_required','Resolve requires purpose=standalone. It must never supply metadata for an import workflow.')
        paper=require_paper(storage,grant,args.get('gewu_key'))
        key,digest,prior=receipt(storage,grant,operation,args)
        if prior and (prior.get('status') not in ('queued','running') or prior.get('_session')==SESSION):
            return {k:v for k,v in prior.items() if not k.startswith('_')}
        if not SLOTS.acquire(blocking=False): fail(429,'resolve_busy','Two Resolve jobs are running. Retry later; imports remain available.')
        result={'gewu_key':paper['storage_key'],'request_id':key,'status':'queued','_session':SESSION}
        try:
            if prior:
                storage.conn.execute('UPDATE ai_write_requests SET result_json=? WHERE connection_id=? AND request_id=?',(json.dumps(result),grant['id'],key))
            else: save_receipt(storage,grant,operation,key,digest,result)
            storage.conn.commit()
            thread=update_runtime.Thread(target=run,args=(storage.db_path,authorization,grant['id'],key,paper['storage_key']),daemon=True)
            thread.start()
        except BaseException: SLOTS.release();raise
        return {k:v for k,v in result.items() if not k.startswith('_')}


def run(db_path,authorization,connection_id,key,gewu_key):
    from .storage import Storage
    from .ai_service import WRITE_LOCK, require_scope
    from . import ui_server as ui
    storage=None
    result={'gewu_key':gewu_key,'request_id':key,'status':'running','_session':SESSION}
    def save():
        storage.conn.execute('UPDATE ai_write_requests SET result_json=? WHERE connection_id=? AND request_id=?',(json.dumps(result),connection_id,key));storage.conn.commit()
    try:
        storage=Storage(db_path)
        with WRITE_LOCK:
            grant=authenticate(storage,authorization);require_scope(grant,'papers:resolve')
            paper=require_paper(storage,grant,gewu_key);save()
        identifier=paper.get('doi') or ui.arxiv_identifier_for_paper(paper)
        if not identifier:
            require_scope(grant,'files:read')
            path=ui.local_pdf_path_for_identifier_extraction(paper)
            if path:
                found=ui.extract_identifier_from_pdf_or_title(path,paper,title_lookup=ui.identifier_from_title_lookup)
                identifier=found.get('identifier') or ''
        if not identifier: fail(422,'identifier_unresolved','No DOI/arXiv identifier was found for this standalone Resolve.')
        found=ui.library_workspace_publication_from_query(identifier)
        if not found: fail(422,'metadata_unresolved','No confident metadata match was found.')
        meta={k:found[k] for k in ('title','doi','journal','publication_date','abstract') if found.get(k)}
        meta.update(authors=ui.full_author_names(found),arxiv_id=ui.arxiv_identifier_for_paper(found) or None,
                    source_url=found.get('url') or found.get('landing_url') or '')
        with WRITE_LOCK:
            storage.conn.execute('BEGIN IMMEDIATE')
            grant=authenticate(storage,authorization);require_scope(grant,'papers:resolve')
            current=require_paper(storage,grant,gewu_key)
            if any(current.get(k)!=paper.get(k) for k in ('doi','raw_json')):
                fail(409,'paper_changed','The paper changed during Resolve. No metadata was applied.')
            result.update(apply_metadata(storage,grant,current,meta),status='completed')
            save()
    except Exception as exc:
        if storage is None:
            return
        storage.conn.rollback()
        result.update(status='failed',code=exc.code if isinstance(exc,APIError) else 'resolve_failed',
                      message=str(exc) if isinstance(exc,APIError) else 'Resolve could not finish. Existing files and Default are preserved.')
        with WRITE_LOCK: save()
    finally:
        if storage is not None: storage.close()
        SLOTS.release()
