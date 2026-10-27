"""Bounded, restart-safe metadata completion; never fetches Scholar profiles."""
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
import json
import threading
import time
from . import update_runtime

from .storage import Storage

SETTING = 'author_monitor_metadata_work'
BATCH_SIZE = 20
DAILY_LIMIT = 80
SLICE_SECONDS = 120
REST_SECONDS = 300
MAX_ATTEMPTS = 3
LOCK = threading.Lock()
_SUMMARY_LOCK = threading.Lock()
_SUMMARIES = {}


def read(storage):
    try:
        value = json.loads(storage.get_setting(SETTING, '{}'))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def save(storage, state):
    storage.set_setting(SETTING, json.dumps(state, sort_keys=True))


def attempt_count(paper, ui):
    marker = ui.author_monitor_enrichment_marker(paper)
    try:
        # Older releases recorded a timestamp but no counter. Retain that attempt.
        return max(0, int(marker.get('automatic_attempts', bool(marker.get('attempted_at')))))
    except (ValueError, TypeError):
        return int(bool(marker.get('attempted_at')))


def plan(rows, ui, *, last_author=0):
    groups = defaultdict(list)
    waiting = 0
    manual = 0
    retry_times = []
    for paper in rows:
        if not ui.author_monitor_paper_needs_enrichment(paper):
            continue
        if attempt_count(paper, ui) >= MAX_ATTEMPTS:
            manual += 1
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
    return selected, waiting, min(retry_times, default=''), manual


def combined_plan(storage, ui, *, last_author=0, now=None):
    # Scope is Author Monitor only. Library/Space/My Publications refreshes are
    # explicit jobs, not periodic work owned by this completion worker.
    rows = storage.list_author_monitor_enrichment_candidates()
    return plan(rows, ui, last_author=last_author)


def current_counts(storage, ui):
    """Reuse unchanged counts briefly; committed edits invalidate them at once.

    Do not retain a SQLite connection or large paper payloads. Expiration also
    catches eligibility changing as the seven-day retry deadline passes.
    """
    path = Path(storage.db_path).resolve()
    stamps = []
    for file in (path, Path(str(path) + '-wal'), Path(str(path) + '-journal')):
        try:
            stat = file.stat()
            stamps.append((stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            stamps.append(None)
    signature = (tuple(stamps), storage.conn.total_changes)
    with _SUMMARY_LOCK:
        cached = _SUMMARIES.get(path)
        if cached and cached[0] == signature and time.monotonic() - cached[1] < 15:
            return cached[2]
        selected, waiting, retry, manual = combined_plan(storage, ui)
        counts = (len(selected), waiting, retry, manual)
        if len(_SUMMARIES) >= 4:
            _SUMMARIES.clear()
        _SUMMARIES[path] = (signature, time.monotonic(), counts)
        return counts


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
        selected, waiting, retry_at, manual = combined_plan(storage, ui,
            last_author=int(state.get('last_author') or 0), now=now)
        state.update(eligible=len(selected), waiting_retry=waiting, retry_at=retry_at, needs_manual=manual,
                     updated_at=now.isoformat(timespec='seconds'), daily_limit=DAILY_LIMIT)
        remaining = max(0, DAILY_LIMIT - int(state.get('used') or 0))
        batch = selected[:min(BATCH_SIZE, remaining)]
        state['next_run_at'] = (now + timedelta(seconds=REST_SECONDS)).isoformat(timespec='seconds')
        if not batch:
            state['status'] = 'daily_limit' if selected else ('waiting_retry' if waiting else ('needs_manual' if manual else 'complete'))
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
            paper_ids=[pid for _, pid in batch],
            max_papers=len(batch), time_budget_seconds=SLICE_SECONDS)
        job = ui.get_author_monitor_enrichment_job(job_id) or {}
        attempted = min(len(batch), int(job.get('current') or 0))
        state['used'] -= len(batch) - attempted
        if attempted:
            state['last_author'] = batch[attempted - 1][0]
        selected, waiting, retry_at, manual = combined_plan(storage, ui, last_author=int(state.get('last_author') or 0), now=now)
        state.update(eligible=len(selected), waiting_retry=waiting, retry_at=retry_at, needs_manual=manual,
                     status='resting' if selected else ('waiting_retry' if waiting else ('needs_manual' if manual else 'complete')),
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
    # Recount even during the daily pause: explicit refreshes and new profile
    # results may have changed the collection since the last worker slice.
    eligible, waiting, retry, manual = current_counts(storage, ui)
    state.update(eligible=eligible, waiting_retry=waiting, retry_at=retry,
                 needs_manual=manual, scope='all_authors', daily_limit=DAILY_LIMIT)
    job = ui.active_author_monitor_enrichment_job()
    if job and job.get('automatic'):
        state = {**state, 'status': 'running', 'current': job.get('current', 0), 'total': job.get('total', 0)}
    elif state.get('status') == 'running':
        previous = ui.get_author_monitor_enrichment_job(state.get('job_id')) or {}
        state = {**state, 'status': 'error' if previous.get('status') == 'failed' else 'resting'}
        # After shutdown no memory job remains, but the reservation/rest survive.
    if not (job and job.get('automatic')):
        now = datetime.now().astimezone()
        if not eligible:
            state['status'] = 'waiting_retry' if waiting else ('needs_manual' if manual else 'complete')
        elif state.get('status') not in {'error', 'resting'}:
            at_limit = state.get('day') == now.date().isoformat() and int(state.get('used') or 0) >= DAILY_LIMIT
            state['status'] = 'daily_limit' if at_limit else 'resting'
    return state


def run_scheduler(db_path):
    time.sleep(30)
    while True:
        try:
            with update_runtime.work("Author metadata"):
                run_slice(db_path)
        except Exception as exc:
            print(f'Author metadata scheduler error: {type(exc).__name__}')
        time.sleep(REST_SECONDS)
