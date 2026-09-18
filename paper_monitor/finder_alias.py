"""Filesystem shortcuts: native Finder bookmarks on macOS, symlinks elsewhere.

SQLite always points at real files. Shortcuts are placement projections only.
The target xattr lets cleanup recognize a managed alias even after its target
has moved or disappeared; bookmark resolution never mounts disks or shows UI.
"""
from __future__ import annotations

import ctypes as C
from functools import lru_cache
import os
from pathlib import Path
import sys
import uuid

TARGET_ATTRIBUTE = "org.gewu-insight.alias-target"


@lru_cache(maxsize=1)
def _libc():
    lib = C.CDLL(None, use_errno=True)
    for name in ("getxattr", "setxattr", "listxattr"):
        getattr(lib, name).restype = C.c_ssize_t
    lib.getxattr.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_size_t, C.c_uint32, C.c_int]
    lib.setxattr.argtypes = lib.getxattr.argtypes
    lib.listxattr.argtypes = [C.c_char_p, C.c_void_p, C.c_size_t, C.c_int]
    return lib


def get_attribute(path, name):
    if hasattr(os, "getxattr"):
        return os.getxattr(path, name, follow_symlinks=False)
    if sys.platform != "darwin":
        raise OSError("Extended attributes unavailable")
    lib = _libc()
    size = lib.getxattr(os.fsencode(path), os.fsencode(name), None, 0, 0, 1)
    if size < 0:
        raise OSError(C.get_errno(), os.strerror(C.get_errno()))
    data = C.create_string_buffer(size)
    size = lib.getxattr(os.fsencode(path), os.fsencode(name), data, size, 0, 1)
    if size < 0:
        raise OSError(C.get_errno(), os.strerror(C.get_errno()))
    return data.raw[:size]


def set_attribute(path, name, value):
    if hasattr(os, "setxattr"):
        return os.setxattr(path, name, value, follow_symlinks=False)
    if _libc().setxattr(os.fsencode(path), os.fsencode(name), value, len(value), 0, 1) < 0:
        raise OSError(C.get_errno(), os.strerror(C.get_errno()))


def attributes(path):
    if hasattr(os, "listxattr"):
        names = os.listxattr(path)
    else:
        lib = _libc()
        size = lib.listxattr(os.fsencode(path), None, 0, 1)
        if size < 0:
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        buffer = C.create_string_buffer(size)
        size = lib.listxattr(os.fsencode(path), buffer, size, 1)
        if size < 0:
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        names = [os.fsdecode(name) for name in buffer.raw[:size].split(b"\0") if name]
    return {name: get_attribute(path, name) for name in names}


@lru_cache(maxsize=1)
def _cf():
    cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ptr, integer, boolean = C.c_void_p, C.c_long, C.c_ubyte
    signatures = {
        "CFURLCreateFromFileSystemRepresentation": (ptr, [ptr, C.c_char_p, integer, boolean]),
        "CFURLCreateBookmarkData": (ptr, [ptr, ptr, C.c_ulong, ptr, ptr, ptr]),
        "CFURLWriteBookmarkDataToFile": (boolean, [ptr, ptr, C.c_ulong, ptr]),
        "CFURLCreateBookmarkDataFromFile": (ptr, [ptr, ptr, ptr]),
        "CFURLCreateByResolvingBookmarkData": (ptr, [ptr, ptr, C.c_ulong, ptr, ptr, ptr, ptr]),
        "CFURLGetFileSystemRepresentation": (boolean, [ptr, boolean, ptr, integer]),
        "CFRelease": (None, [ptr]),
    }
    for name, (restype, argtypes) in signatures.items():
        function = getattr(cf, name)
        function.restype, function.argtypes = restype, argtypes
    return cf


def _url(path):
    raw = os.fsencode(Path(path).absolute())
    return _cf().CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), Path(path).is_dir())


def recorded_target(path: Path) -> Path | None:
    try:
        return Path(os.fsdecode(get_attribute(path, TARGET_ATTRIBUTE)))
    except OSError:
        return None


def is_alias(path: Path) -> bool:
    path = Path(path)
    if path.is_symlink() or recorded_target(path) is not None:
        return True
    if sys.platform == "darwin":
        try:
            info = get_attribute(path, "com.apple.FinderInfo")
            return len(info) >= 10 and bool(int.from_bytes(info[8:10], "big") & 0x8000)
        except OSError:
            pass
    return False


def resolve(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink() or not is_alias(path) or sys.platform != "darwin":
        return path.resolve()
    cf = _cf()
    url = _url(path)
    data = result = None
    try:
        data = cf.CFURLCreateBookmarkDataFromFile(None, url, None)
        if data:
            result = cf.CFURLCreateByResolvingBookmarkData(None, data, (1 << 8) | (1 << 9), None, None, None, None)
        if result:
            buffer = C.create_string_buffer(32768)
            if cf.CFURLGetFileSystemRepresentation(result, True, buffer, len(buffer)):
                return Path(os.fsdecode(buffer.value)).resolve()
    finally:
        for obj in (result, data, url):
            if obj:
                cf.CFRelease(obj)
    return (recorded_target(path) or path).resolve()


def points_to(path: Path, target: Path) -> bool:
    if not is_alias(path):
        return False
    expected = Path(target).expanduser().resolve()
    recorded = recorded_target(path)
    return (recorded is not None and recorded.resolve() == expected) or resolve(path) == expected


def create(target: Path, path: Path) -> Path:
    """Install without overwriting any unrelated file, including dangling links."""
    target, path = Path(target).expanduser().resolve(), Path(path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        raise FileExistsError(str(path))
    if sys.platform != "darwin":
        os.symlink(target, path)
        return path
    if not target.exists():
        raise FileNotFoundError(str(target))
    temporary = path.with_name(f".gewu-alias-{uuid.uuid4().hex}")
    cf = _cf()
    source_url = _url(target)
    destination_url = _url(temporary)
    bookmark = None
    try:
        bookmark = cf.CFURLCreateBookmarkData(None, source_url, 1 << 10, None, None, None)
        if not bookmark or not cf.CFURLWriteBookmarkDataToFile(bookmark, destination_url, 0, None):
            raise OSError(f"Could not create Finder alias: {path}")
        set_attribute(temporary, TARGET_ATTRIBUTE, os.fsencode(target))
        # link() is atomic and exclusive: a concurrent Finder save cannot be
        # overwritten. Unlinking the staging name leaves one alias file.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
        for obj in (bookmark, source_url, destination_url):
            if obj:
                cf.CFRelease(obj)
    return path


def ensure(target: Path, path: Path) -> Path:
    """Refresh an alias to this target; never replace an ordinary file."""
    if not os.path.lexists(path):
        return create(target, path)
    if not points_to(path, target):
        raise FileExistsError(str(path))
    if sys.platform != "darwin" or (not path.is_symlink() and recorded_target(path) == target.resolve()):
        return path
    return retarget(target, path)


def retarget(target: Path, path: Path) -> Path:
    if not is_alias(path):
        raise ValueError("Only an existing shortcut can be retargeted")
    saved = snapshot(path)
    path.unlink()
    try:
        return create(target, path)
    except Exception:
        restore(path, saved)
        raise


def snapshot(path: Path) -> dict:
    if path.is_symlink():
        return {"link": os.readlink(path)}
    return {"data": path.read_bytes(), "mode": path.stat().st_mode,
            "attrs": attributes(path)}


def restore(path: Path, saved: dict) -> None:
    if os.path.lexists(path):
        raise FileExistsError(str(path))
    if "link" in saved:
        os.symlink(saved["link"], path)
    else:
        with path.open("xb") as file:
            file.write(saved["data"])
        os.chmod(path, saved["mode"])
        for name, value in saved["attrs"].items():
            set_attribute(path, name, value)
