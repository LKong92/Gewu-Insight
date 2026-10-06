"""OS file integration. Placements are references; never duplicate paper bytes."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


LINK_DESCRIPTION = "Gewu Insight managed placement v1"


@contextmanager
def shell_link():
    import pythoncom
    from win32com.shell import shell

    pythoncom.CoInitialize()
    try:
        yield pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    finally:
        pythoncom.CoUninitialize()


@lru_cache(maxsize=2048)
def _link_target(path: str, modified_ns: int, size: int) -> str | None:
    import pythoncom
    from win32com.shell import shell

    try:
        with shell_link() as link:
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(path, 0)
            # Never execute a shortcut or ask the Shell to search for a moved
            # target. Only our direct, argument-free file references qualify.
            if link.GetDescription() != LINK_DESCRIPTION or link.GetArguments():
                return None
            target = link.GetPath(shell.SLGP_RAWPATH)[0]
            return target if target and Path(target).is_absolute() else None
    except pythoncom.com_error:
        return None


def managed_link_target(path: Path) -> Path | None:
    if sys.platform != "win32" or path.suffix.lower() != ".lnk":
        return None
    try:
        stat = path.stat()
        target = _link_target(str(path.absolute()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    return Path(target) if target else None


def is_placement(path: Path) -> bool:
    return path.is_symlink() or managed_link_target(path) is not None


def resolve_placement(path: Path) -> Path:
    return (managed_link_target(path) or path).expanduser().resolve()


def placement_path(path: Path) -> Path:
    """Physical entry for a logical filename (the real owner stays unchanged)."""
    return path.with_name(path.name + ".lnk") if sys.platform == "win32" else path


def placement_name(path: Path) -> str:
    return path.name[:-4] if managed_link_target(path) is not None else path.name


def safe_filename(value: str) -> str:
    if sys.platform != "win32":
        return value
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).rstrip(" .")
    # Reserved device stems remain reserved when an extension is appended.
    stem = clean.split(".", 1)[0].rstrip(" .").upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
        clean = "_" + clean
    return clean or "Untitled"


def create_placement(canonical: Path, logical_path: Path) -> Path:
    canonical = resolve_placement(canonical)
    logical_path.parent.mkdir(parents=True, exist_ok=True)
    if canonical == logical_path.resolve():
        return canonical
    for index in range(1, 1000):
        logical = logical_path if index == 1 else logical_path.with_name(f"{logical_path.stem} {index}{logical_path.suffix}")
        candidate = placement_path(logical)
        if is_placement(candidate) and resolve_placement(candidate) == canonical:
            return candidate
        if candidate.exists() or candidate.is_symlink() or (candidate != logical and logical.exists()):
            continue
        if sys.platform != "win32":
            os.symlink(str(canonical), candidate)
            return candidate
        import pythoncom

        descriptor, temporary = tempfile.mkstemp(suffix=".lnk", prefix=".gewu-placement-", dir=logical.parent)
        os.close(descriptor)
        try:
            with shell_link() as link:
                link.SetPath(str(canonical))
                link.SetWorkingDirectory(str(canonical.parent))
                link.SetDescription(LINK_DESCRIPTION)
                link.QueryInterface(pythoncom.IID_IPersistFile).Save(temporary, 1)
            # Windows rename is atomic and fails if another entry won the name.
            try:
                os.rename(temporary, candidate)
            except FileExistsError:
                continue
            _link_target.cache_clear()
            return candidate
        finally:
            Path(temporary).unlink(missing_ok=True)
    raise FileExistsError(str(logical_path))


def open_file(path: Path, *, macos_application: str = "") -> None:
    requested = resolve_placement(path)
    if not requested.exists():
        raise FileNotFoundError(str(requested))
    if sys.platform == "win32":
        os.startfile(str(requested))
    elif sys.platform == "darwin":
        args = ["open"] + (["-a", macos_application] if macos_application else [])
        subprocess.run([*args, str(requested)], check=True)
    else:
        subprocess.run(["xdg-open", str(requested)], check=True)


def reveal_windows_file(path: Path) -> None:
    import pythoncom
    from win32com.shell import shell

    requested = path.expanduser().absolute()
    if not requested.exists():
        raise FileNotFoundError(str(requested))
    if requested.is_dir():
        os.startfile(str(requested))
        return
    pythoncom.CoInitialize()
    try:
        item, _attributes = shell.SHParseDisplayName(str(requested), 0)
        shell.SHOpenFolderAndSelectItems(item, [], 0)
    finally:
        pythoncom.CoUninitialize()


def create_exact_placement(canonical: Path, path: Path) -> Path:
    """Write one exact Windows shortcut name, including journal staging names."""
    import pythoncom
    canonical, path = Path(canonical).absolute(), Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(suffix='.lnk', prefix='.gewu-placement-', dir=path.parent)
    os.close(descriptor)
    try:
        with shell_link() as link:
            link.SetPath(str(canonical))
            link.SetWorkingDirectory(str(canonical.parent))
            link.SetDescription(LINK_DESCRIPTION)
            link.QueryInterface(pythoncom.IID_IPersistFile).Save(temporary, 1)
        os.rename(temporary, path)
        _link_target.cache_clear()
        return path
    finally:
        Path(temporary).unlink(missing_ok=True)
