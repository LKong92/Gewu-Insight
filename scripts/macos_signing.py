#!/usr/bin/env python3
"""Validate macOS build identities and installations without accessing secrets."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


BUNDLE_IDENTIFIER = 'com.zhengranwu.gewuinsight'


class SigningError(RuntimeError):
    pass


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise SigningError(result.stderr.strip() or result.stdout.strip()
                           or f"{arguments[0]} failed ({result.returncode})")
    return result.stdout + result.stderr


def signing_info(app):
    output = run(['/usr/bin/codesign', '-dv', '--verbose=4', str(app)])
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def check_local_identity(info):
    if info.get('Identifier') != BUNDLE_IDENTIFIER:
        raise SigningError('The App has an unexpected bundle identifier.')
    if info.get('Signature') != 'adhoc' or info.get('TeamIdentifier') != 'not set':
        raise SigningError('This local workflow uses ad-hoc signing. Refusing to '
                           'replace a differently signed App automatically.')


def check_stopped(app):
    executable = str(app.resolve() / 'Contents/MacOS/Gewu Insight')
    output = run(['/bin/ps', '-axo', 'pid=,comm='])
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and str(Path(parts[1]).resolve()) == executable:
            raise SigningError('Quit Gewu Insight before replacing its App bundle. '
                               f'The installed App is running (PID {parts[0]}).')


def preflight(installed, output, development=False):
    installed = installed.resolve()
    output = output.resolve()
    if output.exists() and output != installed:
        raise SigningError('The isolated output path already exists; choose a fresh path.')
    if installed in output.parents or output in installed.parents:
        raise SigningError('The output path must be separate from the installed App.')
    if development and output == installed:
        raise SigningError('Development builds require a separate --output path. '
                           'They cannot replace the installed App.')
    check_local_identity(signing_info(installed))
    if output == installed:
        check_stopped(installed)
    return '-'


def verify(app, previous=None):
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
    info = signing_info(app)
    check_local_identity(info)
    if previous:
        old = signing_info(previous)
        if info.get('Identifier') != old.get('Identifier'):
            raise SigningError('The update changed the application bundle identifier.')
        check_local_identity(old)


def extended_attributes(path):
    if hasattr(os, 'listxattr'):
        return [(name, os.getxattr(path, name, follow_symlinks=False))
                for name in sorted(os.listxattr(path, follow_symlinks=False))]
    # CPython's os xattr API is absent on macOS. Use the public libc API without
    # a third-party dependency; XATTR_NOFOLLOW also covers symlinks safely.
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    library.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    library.listxattr.restype = ctypes.c_ssize_t
    library.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    library.getxattr.restype = ctypes.c_ssize_t
    encoded = os.fsencode(path)
    size = library.listxattr(encoded, None, 0, 1)
    if size < 0:
        raise OSError(ctypes.get_errno(), 'Cannot inspect App signing attributes', str(path))
    buffer = ctypes.create_string_buffer(size)
    count = library.listxattr(encoded, buffer, size, 1)
    if count < 0:
        raise OSError(ctypes.get_errno(), 'App attributes changed during inspection', str(path))
    attributes = []
    for name in sorted(buffer.raw[:count].split(b'\0')):
        if not name:
            continue
        size = library.getxattr(encoded, name, None, 0, 0, 1)
        if size < 0:
            raise OSError(ctypes.get_errno(), 'App attribute disappeared during inspection', str(path))
        value = ctypes.create_string_buffer(size)
        count = library.getxattr(encoded, name, value, size, 0, 1)
        if count < 0:
            raise OSError(ctypes.get_errno(), 'App attribute changed during inspection', str(path))
        attributes.append((os.fsdecode(name), value.raw[:count]))
    return attributes


def fingerprint(app):
    """Cover bytes, modes and signing xattrs to detect changes while building."""
    import hashlib
    digest = hashlib.sha256()
    for path in sorted([app] + list(app.rglob('*'))):
        stat = path.lstat()
        digest.update(str(path.relative_to(app)).encode())
        digest.update(str(stat.st_mode).encode())
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
        for attribute, value in extended_attributes(path):
            # Finder's display metadata is not application content.
            if attribute == 'com.apple.FinderInfo' or attribute.startswith('com.apple.fileprovider.'):
                continue
            digest.update(attribute.encode())
            digest.update(value)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['preflight', 'verify', 'stopped', 'fingerprint'])
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--development-adhoc', action='store_true')
    args = parser.parse_args()
    try:
        if args.operation == 'preflight':
            print(preflight(args.app, args.output or args.app, args.development_adhoc))
        elif args.operation == 'verify':
            verify(args.app, args.previous)
        elif args.operation == 'stopped':
            check_stopped(args.app)
        else:
            print(fingerprint(args.app))
    except (SigningError, OSError) as error:
        print(f'Gewu build refused: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
