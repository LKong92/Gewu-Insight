"""Recoverable Windows Paper Files deletion with a private SQLite journal.

Only the resource-delete transaction is enabled. Other legacy bulk-removal
paths must remain blocked until they have an equivalent transaction boundary.
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
    finally:
        pythoncom.CoUninitialize()


def restore_shell_item(recycled, source):
    import pythoncom
    import win32com.client
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
    finally:
        pythoncom.CoUninitialize()


def open_journal(storage):
    directory = storage.db_path.resolve().parent / ".file-recovery"
    directory.mkdir(parents=True, exist_ok=True)
    journal = sqlite3.connect(directory / "recovery.sqlite")
    journal.row_factory = sqlite3.Row
    journal.execute("PRAGMA synchronous=FULL")
    journal.execute("CREATE TABLE IF NOT EXISTS removals (id TEXT PRIMARY KEY, resource_id INTEGER, paper_id TEXT, source TEXT, backup TEXT, sha256 TEXT, recycled TEXT NOT NULL DEFAULT '')")
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
            resource = storage.get_paper_resource(record["resource_id"])
            if resource:
                if resource["paper_id"] != record["paper_id"] or Path(resource["stored_path"]).resolve() != Path(record["source"]):
                    raise OSError("File recovery found a changed resource. Its backup was preserved.")
                restore_record(record)
            finish_record(journal, record)
        return len(records)
    finally:
        journal.close()


class ResourceRemoval:
    def __init__(self, storage, paper_id, resource_id):
        self.storage, self.paper_id, self.resource_id = storage, paper_id, resource_id
        self.journal = self.record = None

    def recycle(self, source):
        resource = self.storage.get_paper_resource(self.resource_id)
        source = Path(source).resolve()
        if not resource or resource["paper_id"] != self.paper_id or Path(resource["stored_path"]).resolve() != source:
            raise OSError("The selected file changed before deletion.")
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
                           source=str(source), backup=str(backup), sha256=before, recycled="")
        self.journal.execute("INSERT INTO removals VALUES (:id,:resource_id,:paper_id,:source,:backup,:sha256,:recycled)", self.record)
        self.journal.commit()
        destination = recycle_file(source)
        self.record["recycled"] = str(destination)
        self.journal.execute("UPDATE removals SET recycled = ? WHERE id = ?", (str(destination), operation_id))
        self.journal.commit()
        return destination


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
        raise OSError("Bulk permanent removal is unavailable in this Windows Preview; the file has been preserved. Paper Files deletion supports recovery. Library Recycle remains available.")
    return removal.recycle(path)
