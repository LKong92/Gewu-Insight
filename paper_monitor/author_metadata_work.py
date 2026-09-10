"""Bounded, restart-safe metadata completion; never fetches Scholar profiles."""
from collections import defaultdict, deque
from datetime import datetime, timedelta
import json
import threading
import time

from .storage import Storage

SETTING = 'author_monitor_metadata_work'
BATCH_SIZE = 20
DAILY_LIMIT = 80
SLICE_SECONDS = 120
REST_SECONDS = 300
LOCK = threading.Lock()


def read(storage):
    try:
        value = json.loads(storage.get_setting(SETTING, '{}'))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def save(storage, state):
    storage.set_setting(SETTING, json.dumps(state, sort_keys=True))


def plan(rows, ui, *, last_author=0):
    groups = defaultdict(list)
    waiting = 0
    retry_times = []
    for paper in rows:
        if not ui.author_monitor_paper_needs_enrichment(paper):
            continue
        if ui.author_monitor_enrichment_recently_attempted(paper):
            waiting += 1
            stamp = ui.author_monitor_enrichment_marker(paper).get('attempted_at')
            if stamp:
                try:
                    retry_times.append((datetime.fromisoformat(stamp) + timedelta(days=ui.AUTHOR_MONITOR_ENRICHMENT_RETRY_DAYS)).isoformat())
                except ValueError:
                    pass
            continue
        authors = paper.get('author_monitor_ids') or [0]
        owner = min(int(a) for a in authors)
        groups[owner].append(paper)
    order = sorted(groups)
    order = [a for a in order if a > last_author] + [a for a in order if a <= last_author]
    # Each paper appears once in the canonical snapshot, even with several authors.
    queues = {a: deque(sorted(groups[a], key=lambda p: (str(p.get('author_first_seen_at') or ''), str(p.get('publication_date') or '')), reverse=True)) for a in order}
    selected = []
    while any(queues.values()):
        for author in order:
            if queues[author]:
                selected.append((author, queues[author].popleft()['paper_id']))
    return selected, waiting, min(retry_times, default='')


def run_slice(db_path, *, now=None):
    from . import ui_server as ui
    now = now or datetime.now().astimezone()
    if not LOCK.acquire(blocking=False):
        return
    storage = None
    job_id = None
    try:
        storage = Storage(db_path)
        state = read(storage)
        if state.get('day') != now.date().isoformat():
            state.update(day=now.date().isoformat(), used=0)
        try:
            if state.get('next_run_at') and datetime.fromisoformat(state['next_run_at']) > now:
                return
        except (ValueError, TypeError):
            pass
        if ui.active_author_monitor_enrichment_job():
            return  # Explicit work owns the same single worker slot.
        rows = storage.list_author_monitor_papers(0)
        selected, waiting, retry_at = plan(rows, ui, last_author=int(state.get('last_author') or 0))
        state.update(eligible=len(selected), waiting_retry=waiting, retry_at=retry_at,
                     updated_at=now.isoformat(timespec='seconds'), daily_limit=DAILY_LIMIT)
        remaining = max(0, DAILY_LIMIT - int(state.get('used') or 0))
        batch = selected[:min(BATCH_SIZE, remaining)]
        state['next_run_at'] = (now + timedelta(seconds=REST_SECONDS)).isoformat(timespec='seconds')
        if not batch:
            state['status'] = 'daily_limit' if selected else ('waiting_retry' if waiting else 'complete')
            if selected:
                state['next_run_at'] = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
            save(storage, state)
            return
        with ui.AUTHOR_MONITOR_ENRICHMENT_JOBS_LOCK:
            if ui.active_author_monitor_enrichment_job():
                return
            job_id = ui.create_author_monitor_enrichment_job(max_papers=len(batch), automatic=True)
        # Reserve before doing I/O: quitting cannot replenish the daily budget.
        state.update(status='running', job_id=job_id, used=int(state.get('used') or 0) + len(batch))
        save(storage, state)
        ui.run_author_monitor_enrichment_job(job_id=job_id, db_path=db_path,
            paper_ids=[pid for _, pid in batch], max_papers=len(batch), time_budget_seconds=SLICE_SECONDS)
        job = ui.get_author_monitor_enrichment_job(job_id) or {}
        attempted = min(len(batch), int(job.get('current') or 0))
        state['used'] -= len(batch) - attempted
        if attempted:
            state['last_author'] = batch[attempted - 1][0]
        selected, waiting, retry_at = plan(storage.list_author_monitor_papers(0), ui, last_author=int(state.get('last_author') or 0))
        state.update(eligible=len(selected), waiting_retry=waiting, retry_at=retry_at,
                     status='resting' if selected else ('waiting_retry' if waiting else 'complete'),
                     updated_at=ui.now_iso(), next_run_at=(datetime.now().astimezone() + timedelta(seconds=REST_SECONDS)).isoformat(timespec='seconds'))
        if job.get('status') == 'failed':
            state['status'] = 'error'
        elif selected and state['used'] >= DAILY_LIMIT:
            state['status'] = 'daily_limit'
            state['next_run_at'] = (datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
        state['last_batch_count'] = attempted
        state['completed_at'] = ui.now_iso()
        save(storage, state)
    except Exception:
        if job_id:
            ui.update_author_monitor_enrichment_job(job_id, status='failed', errors=['Background metadata work was interrupted.'])
        raise
    finally:
        if storage is not None:
            storage.close()
        LOCK.release()


def snapshot(storage):
    from . import ui_server as ui
    state = read(storage)
    job = ui.active_author_monitor_enrichment_job()
    if job and job.get('automatic'):
        state = {**state, 'status': 'running', 'current': job.get('current', 0), 'total': job.get('total', 0)}
    elif state.get('status') == 'running':
        previous = ui.get_author_monitor_enrichment_job(state.get('job_id')) or {}
        state = {**state, 'status': 'error' if previous.get('status') == 'failed' else 'resting'}
        # After shutdown no memory job remains, but the reservation/rest survive.
    return state


def run_scheduler(db_path):
    time.sleep(30)
    while True:
        try:
            run_slice(db_path)
        except Exception as exc:
            print(f'Author metadata scheduler error: {type(exc).__name__}')
        time.sleep(REST_SECONDS)
