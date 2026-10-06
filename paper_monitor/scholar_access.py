"""Bind Scholar requests to the workspace whose persistent cooldown they obey."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import sqlite3

_DATABASE = ContextVar('scholar_database', default=None)


@contextmanager
def database(path):
    token = _DATABASE.set(Path(path).resolve())
    try:
        yield
    finally:
        _DATABASE.reset(token)


def for_database(function):
    @wraps(function)
    def run(db_path, *args, **kwargs):
        with database(db_path):
            return function(db_path, *args, **kwargs)
    return run


def for_storage(function):
    @wraps(function)
    def run(storage, *args, **kwargs):
        with database(storage.db_path):
            return function(storage, *args, **kwargs)
    return run


def check():
    """Called under the shared request lock, after any spacing wait."""
    path = _DATABASE.get()
    if path is None:
        return  # Standalone parsers/tests have no workspace session.
    from . import ui_server as ui
    # A read must not run Storage's startup migrations on each network request.
    storage = ui.Storage.__new__(ui.Storage)
    storage.db_path = path
    storage.conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    storage.conn.row_factory = sqlite3.Row
    try:
        cooldown = ui.google_scholar_global_cooldown(storage)
    finally:
        storage.close()
    if cooldown.get('active'):
        raise ui.GoogleScholarBlockedError(ui.google_scholar_global_cooldown_message(cooldown))


def blocked(message):
    """Persist the circuit breaker before releasing the shared request lock."""
    path = _DATABASE.get()
    if path is not None:
        from . import ui_server as ui
        ui.start_google_scholar_global_cooldown_for_db(path, message=message)
