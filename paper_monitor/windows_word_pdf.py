"""Convert a Word supplement in an owned, macro-disabled Office process."""
from pathlib import Path
import subprocess
import sys
import uuid


def convert(source: Path, target: Path) -> Path:
    from .pdf_utils import is_valid_pdf_file
    source, target = source.resolve(), target.resolve()
    if not source.is_file() or source.suffix.lower() not in {'.doc', '.docx'}:
        raise ValueError('Choose a readable DOC or DOCX supplement.')
    if target.exists():
        raise FileExistsError('The conversion destination already exists.')
    try:
        result = subprocess.run([sys.executable, '-B', '-m', __name__, str(source), str(target)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=70,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise OSError('Word supplement conversion timed out. Open the document locally and export it as PDF.') from exc
    if result.returncode or not is_valid_pdf_file(target):
        target.unlink(missing_ok=True)
        message = result.stderr.strip().splitlines()
        raise OSError(message[-1] if message else 'Word could not convert this supplement. Export it as PDF with Word or LibreOffice.')
    return target


def convert_in_owned_word(source: Path, target: Path):
    import pythoncom
    import win32api
    import win32com.client
    import win32con
    import win32job
    import win32process

    source, target = source.resolve(), target.resolve()
    if not source.is_file() or source.suffix.lower() not in {'.doc', '.docx'}:
        raise ValueError('Choose a readable DOC or DOCX supplement.')
    if target.exists():
        raise FileExistsError('The conversion destination already exists.')
    previous = set(win32process.EnumProcesses())
    app = document = job = process = None
    update_links = None
    owns_word = False
    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx('Word.Application')
        # Word exposes HWND on document windows, not Application. Identify the
        # new automation process before opening any document or changing options.
        executable = (Path(app.Path) / 'WINWORD.EXE').resolve()
        candidates = []
        for candidate in set(win32process.EnumProcesses()) - previous:
            handle = None
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, candidate)
                if Path(win32process.GetModuleFileNameEx(handle, 0)).resolve() == executable:
                    candidates.append(candidate)
            except Exception:
                pass
            finally:
                if handle is not None: handle.Close()
        if len(candidates) != 1:
            raise OSError('Word did not provide a separate conversion process. Export the supplement as PDF manually.')
        pid = candidates[0]
        owns_word = True
        process = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE | win32con.PROCESS_QUERY_INFORMATION, False, pid)
        job = win32job.CreateJobObject(None, 'GewuWord_' + uuid.uuid4().hex)
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        win32job.AssignProcessToJobObject(job, process)
        app.Visible = False
        app.DisplayAlerts = 0
        app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        update_links = app.Options.UpdateLinksAtOpen
        app.Options.UpdateLinksAtOpen = False
        document = app.Documents.Open(str(source), ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, Visible=False, OpenAndRepair=False, NoEncodingDialog=True,
            PasswordDocument='', WritePasswordDocument='')
        document.ExportAsFixedFormat(str(target), 17, OpenAfterExport=False)
    finally:
        if document is not None:
            try: document.Close(SaveChanges=0)
            except Exception: pass
        if owns_word:
            if update_links is not None:
                try: app.Options.UpdateLinksAtOpen = update_links
                except Exception: pass
            try: app.Quit(SaveChanges=0)
            except Exception: pass
        if job is not None: job.Close()
        if process is not None: process.Close()
        pythoncom.CoUninitialize()


if __name__ == '__main__':
    try:
        convert_in_owned_word(Path(sys.argv[1]), Path(sys.argv[2]))
    except Exception as exc:
        print('Word supplement conversion failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
