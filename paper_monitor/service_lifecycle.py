"""Stop admitting work and drain database users before releasing process locks."""
import threading
import weakref

STOP = threading.Event()
_condition = threading.Condition()
_active = weakref.WeakSet()


def enter(storage):
    with _condition:
        if STOP.is_set():
            raise RuntimeError("Gewu Insight is shutting down. Wait for it to finish before reopening the database.")
        _active.add(storage)


def leave(storage):
    with _condition:
        _active.discard(storage)
        _condition.notify_all()


def drain():
    STOP.set()
    with _condition:
        while _active:
            _condition.wait(0.25)
