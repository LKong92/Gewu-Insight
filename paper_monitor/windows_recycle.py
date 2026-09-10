"""Recoverable Windows Paper Files deletion with a private SQLite journal.

Resource, reference-aware My Publications and Library Recycle transactions use
verified recovery copies and the main SQLite database as commit authority.
The Shell owns its Recycle Bin records; never edit $I/$R internals directly.
"""
from contextlib import contextmanager
from pathlib import Path
import contextvars
import hashlib
import os
import shutil
import sqlite3
import time
import uuid

_current = contextvars.ContextVar("windows_resource_removal", default=None)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def recycle_file(path):
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.util import wrap
    from win32com.server.exception import COMException
    import pywintypes

    class Sink:
        _com_interfaces_ = [shell.IID_IFileOperationProgressSink]
        _public_methods_ = ["StartOperations", "FinishOperations", "PreRenameItem", "PostRenameItem",
                            "PreMoveItem", "PostMoveItem", "PreCopyItem", "PostCopyItem",
                            "PreDeleteItem", "PostDeleteItem", "PreNewItem", "PostNewItem",
                            "UpdateProgress", "ResetTimer", "PauseTimer", "ResumeTimer"]
        destination = None
        result = None

        def noop(self, *args):
            return None
        StartOperations = FinishOperations = PreRenameItem = PostRenameItem = noop
        PreMoveItem = PostMoveItem = PreCopyItem = PostCopyItem = noop
        PreNewItem = PostNewItem = UpdateProgress = ResetTimer = PauseTimer = ResumeTimer = noop

        def PreDeleteItem(self, flags, item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                raise COMException("This volume cannot recycle the file.", scode=-2147467260)

        def PostDeleteItem(self, flags, item, result, recycled):
            self.result = result
            if result >= 0 and recycled is not None:
                self.destination = recycled.GetDisplayName(shellcon.SIGDN_FILESYSPATH)

    requested = Path(path).resolve()
    pythoncom.CoInitialize()
    try:
        sink = Sink()
        operation = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IFileOperation)
        operation.SetOperationFlags(shellcon.FOF_SILENT | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI | 0x00080000 | 0x00100000)
        source = shell.SHCreateItemFromParsingName(str(requested), None, shell.IID_IShellItem)
        operation.DeleteItem(source, wrap(sink))
        operation.PerformOperations()
        if operation.GetAnyOperationsAborted() or sink.result is None or sink.result < 0 or not sink.destination:
            raise OSError("Windows did not confirm a recoverable Recycle Bin item.")
        destination = Path(sink.destination)
        if requested.exists() or not destination.is_file():
            raise OSError("Windows did not confirm the recycled file.")
        return destination
    except pywintypes.com_error as exc:
        raise OSError("Windows could not recycle the file; its recovery copy has been preserved.") from exc
    finally:
        pythoncom.CoUninitialize()


def restore_shell_item(recycled, source):
    import pythoncom
    import win32com.client
    import pywintypes
    source, recycled = Path(source), Path(recycled)
    if source.exists():
        raise FileExistsError(str(source))
    source.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    try:
        folder = win32com.client.Dispatch("Shell.Application").NameSpace(10)
        matches = [item for item in folder.Items() if str(item.Path).casefold() == str(recycled).casefold()]
        if len(matches) != 1:
            raise OSError("The exact Recycle Bin item is no longer available.")
        matches[0].InvokeVerb("undelete")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pythoncom.PumpWaitingMessages()
            if source.is_file() and not recycled.exists():
                return
            time.sleep(.05)
        raise OSError("Windows did not finish restoring the file.")
    except pywintypes.com_error as exc:
        raise OSError("Windows could not restore the exact Recycle Bin item.") from exc
    finally:
        pythoncom.CoUninitialize()


def open_journal(storage):
    directory = storage.db_path.resolve().parent / ".file-recovery"
    directory.mkdir(parents=True, exist_ok=True)
    journal = sqlite3.connect(directory / "recovery.sqlite")
    journal.row_factory = sqlite3.Row
    journal.execute("PRAGMA synchronous=FULL")
    journal.execute("CREATE TABLE IF NOT EXISTS removals (id TEXT PRIMARY KEY, resource_id INTEGER, paper_id TEXT, source TEXT, backup TEXT, sha256 TEXT, recycled TEXT NOT NULL DEFAULT '')")
    if "batch_id" not in {row[1] for row in journal.execute("PRAGMA table_info(removals)")}:
        journal.execute("ALTER TABLE removals ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''")
    journal.commit()
    return journal, directory


def restore_record(record):
    source, backup = Path(record["source"]), Path(record["backup"])
    if source.exists():
        if not source.is_file() or digest(source) != record["sha256"]:
            raise OSError(f"File recovery found a changed file and preserved the backup: {backup}")
        return
    if not backup.is_file() or digest(backup) != record["sha256"]:
        raise OSError(f"The file recovery backup is missing or changed: {backup}")
    if record["recycled"]:
        try:
            restore_shell_item(record["recycled"], source)
        except OSError:
            pass
    if not source.exists():
        # Crash between Shell completion and receipt persistence: restore the
        # verified backup without guessing which Shell record to remove.
        source.parent.mkdir(parents=True, exist_ok=True)
        with source.open("xb") as output, backup.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
    if digest(source) != record["sha256"]:
        raise OSError(f"File restoration needs attention; backup retained: {backup}")


def finish_record(journal, record):
    Path(record["backup"]).unlink(missing_ok=True)
    journal.execute("DELETE FROM removals WHERE id = ?", (record["id"],))
    journal.commit()


def recover_pending(storage):
    directory = storage.db_path.resolve().parent / ".file-recovery"
    if not (directory / "recovery.sqlite").exists():
        return 0
    journal, _ = open_journal(storage)
    try:
        records = journal.execute("SELECT * FROM removals").fetchall()
        for record in records:
            if record["batch_id"]:
                if not batch_committed(storage, record["batch_id"]):
                    restore_record(record)
                finish_record(journal, record)
                continue
            if record["resource_id"] is None:
                # Publication cleanup is committed only when its canonical paper
                # disappeared in the same SQLite transaction as its placement.
                if storage.get_paper(record["paper_id"]):
                    restore_record(record)
                finish_record(journal, record)
                continue
            resource = storage.get_paper_resource(record["resource_id"])
            if resource:
                if resource["paper_id"] != record["paper_id"] or Path(resource["stored_path"]).resolve() != Path(record["source"]):
                    raise OSError("File recovery found a changed resource. Its backup was preserved.")
                restore_record(record)
            finish_record(journal, record)
        clear_batch_markers(storage, journal)
        return len(records)
    finally:
        journal.close()


class ResourceRemoval:
    def __init__(self, storage, paper_id, resource_id, batch_id=""):
        self.storage, self.paper_id, self.resource_id = storage, paper_id, resource_id
        self.batch_id = batch_id
        self.journal = self.record = None

    def recycle(self, source):
        resource = self.storage.get_paper_resource(self.resource_id)
        source = Path(source).resolve()
        if not resource or resource["paper_id"] != self.paper_id or Path(resource["stored_path"]).resolve() != source:
            raise OSError("The selected file changed before deletion.")
        return self.recycle_verified(source)

    def recycle_verified(self, source):
        self.journal, directory = open_journal(self.storage)
        operation_id = uuid.uuid4().hex
        backup = directory / (operation_id + ".backup")
        before = digest(source)
        with source.open("rb") as input_file, backup.open("xb") as output:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if digest(backup) != before or digest(source) != before:
            backup.unlink()
            raise OSError("The file changed while preparing recovery. Retry after saving it.")
        self.record = dict(id=operation_id, resource_id=self.resource_id, paper_id=self.paper_id,
                           source=str(source), backup=str(backup), sha256=before, recycled="", batch_id=self.batch_id)
        self.journal.execute("INSERT INTO removals (id,resource_id,paper_id,source,backup,sha256,recycled,batch_id) VALUES (:id,:resource_id,:paper_id,:source,:backup,:sha256,:recycled,:batch_id)", self.record)
        self.journal.commit()
        destination = recycle_file(source)
        self.record["recycled"] = str(destination)
        self.journal.execute("UPDATE removals SET recycled = ? WHERE id = ?", (str(destination), operation_id))
        self.journal.commit()
        return destination


class PublicationRemoval:
    def __init__(self, storage):
        self.storage = storage
        self.removals = []

    def recycle(self, source, paper_id):
        if not self.storage.get_paper(paper_id):
            raise OSError("The publication changed before deletion.")
        removal = ResourceRemoval(self.storage, paper_id, None)
        self.removals.append(removal)
        return removal.recycle_verified(Path(source).resolve())

    def finish(self):
        error = None
        for removal in reversed(self.removals):
            try:
                if removal.record:
                    if self.storage.get_paper(removal.paper_id):
                        restore_record(removal.record)
                    finish_record(removal.journal, removal.record)
            except Exception as exc:
                error = error or exc
            finally:
                if removal.journal:
                    removal.journal.close()
        if error:
            raise error


@contextmanager
def resource_removal(storage, paper_id, resource_id):
    removal = ResourceRemoval(storage, paper_id, resource_id)
    token = _current.set(removal)
    try:
        yield
    finally:
        _current.reset(token)
        if removal.record:
            try:
                # The main SQLite resource row is the commit authority even
                # when failure happens after commit, before the reply is sent.
                if storage.get_paper_resource(resource_id):
                    restore_record(removal.record)
                finish_record(removal.journal, removal.record)
            finally:
                removal.journal.close()
        elif removal.journal:
            removal.journal.close()


def recycle_resource_path(path):
    removal = _current.get()
    if removal is None:
        raise OSError("File removal requires a recoverable transaction; the file has been preserved.")
    return removal.recycle(path)


BATCH_PREFIX = "windows_recycle_commit:"


def batch_committed(storage, batch_id):
    return storage.conn.execute("SELECT 1 FROM app_settings WHERE key = ?", (BATCH_PREFIX + batch_id,)).fetchone() is not None


def clear_batch_markers(storage, journal):
    pending = {row[0] for row in journal.execute("SELECT DISTINCT batch_id FROM removals WHERE batch_id != ''")}
    for row in storage.conn.execute("SELECT key FROM app_settings WHERE substr(key,1,?) = ?", (len(BATCH_PREFIX), BATCH_PREFIX)).fetchall():
        if row[0][len(BATCH_PREFIX):] not in pending:
            storage.conn.execute("DELETE FROM app_settings WHERE key = ?", (row[0],))
    storage.conn.commit()


class LibraryRemoval:
    """One durable receipt per file, with one main-DB commit for the selection."""
    def __init__(self, storage):
        self.storage = storage
        self.batch_id = uuid.uuid4().hex
        self.removals = []

    def recycle(self, source):
        removal = ResourceRemoval(self.storage, "", None, self.batch_id)
        self.removals.append(removal)
        return removal.recycle_verified(Path(source).resolve())

    def mark_committed(self):
        # Called inside the SAME SQLite transaction as the selected row deletes.
        self.storage.conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES (?, '1', strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (BATCH_PREFIX + self.batch_id,))

    def finish(self):
        error = None
        committed = batch_committed(self.storage, self.batch_id)
        for removal in reversed(self.removals):
            try:
                if removal.record:
                    if not committed:
                        restore_record(removal.record)
                    finish_record(removal.journal, removal.record)
            except Exception as exc:
                error = error or exc
            finally:
                if removal.journal:
                    removal.journal.close()
        if error:
            raise error
        self.storage.conn.execute("DELETE FROM app_settings WHERE key = ?", (BATCH_PREFIX + self.batch_id,))
        self.storage.conn.commit()
