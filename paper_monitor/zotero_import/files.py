"""Copy-only file boundary. Never rename, edit, link to, or remove source files."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile
import time
import uuid


class Paused(Exception):
    pass


def digest_file(path, check=lambda: None):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            check()
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def protect_destination(directory, source_roots):
    destination = Path(directory).resolve()
    for root in source_roots:
        source = Path(root).resolve()
        if destination == source or source in destination.parents:
            raise ValueError('The Gewu destination overlaps a Zotero source folder. Choose a separate Gewu database.')
    return destination


@contextmanager
def collection_directories(paths, source_roots):
    """Materialize import folders; rollback only our own, still-empty directories.

    Paths use resolved managed roots. Refuse shortcuts below those roots rather
    than creating folders in another location. A crash may leave empty folders;
    a retry reuses them without deleting or overwriting their contents.
    """
    protected = {Path(root).resolve() for root in source_roots}
    paths = list(dict.fromkeys(paths))
    created = []

    def validate(path):
        if path.resolve() != path:
            raise ValueError('An import folder points to another location. Choose a regular Gewu destination folder.')
        if any(parent in protected for parent in (path, *path.parents)):
            raise ValueError('The Gewu destination overlaps a Zotero source folder. Choose a separate Gewu database.')
        if os.path.lexists(path) and not path.is_dir():
            raise ValueError('An existing file blocks the import folder: ' + str(path))

    # Validate the entire hierarchy before the first filesystem write.
    for path in paths:
        validate(path)
    try:
        for path in paths:
            missing, current = [], path
            while not current.exists():
                missing.append(current)
                current = current.parent
            for directory in reversed(missing):
                validate(directory)
                try:
                    directory.mkdir()
                except FileExistsError:
                    validate(directory)
                else:
                    info = directory.lstat()
                    created.append((directory, info.st_dev, info.st_ino))
        for path in paths:
            validate(path)
        yield
    except BaseException:
        for path, device, inode in reversed(created):
            try:
                info = path.lstat()
                if (path.resolve() == path and stat.S_ISDIR(info.st_mode)
                        and (info.st_dev, info.st_ino) == (device, inode)):
                    path.rmdir()  # Never remove contents added by another operation.
            except OSError:
                pass
        raise


def remove_owned(path, device, inode):
    """Only a file created by this adapter can be cleaned up."""
    try:
        info = Path(path).lstat()
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (device, inode):
            Path(path).unlink()
    except FileNotFoundError:
        pass


def copy_verified(storage, job_id, source, directory, expected=None, check=lambda: None, filename=None):
    source = Path(source).resolve(strict=True)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    expected = expected or {}
    fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    path, inode, device, receipt = None, None, None, uuid.uuid4().hex
    try:
        with os.fdopen(fd, 'rb') as original:
            before = os.fstat(original.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('Only regular attachment files can be imported.')
            if ('size' in expected and int(expected['size']) != before.st_size
                    or expected.get('mtime') and abs(float(expected['mtime']) - before.st_mtime * 1000) > 2):
                raise ValueError('Attachment changed after preview. Scan again before importing: ' + source.name)
            label = Path(filename or source.name)
            stem = label.stem.encode('utf-8')[:120].decode('utf-8', errors='ignore')
            out_fd, name = tempfile.mkstemp(prefix=stem + '-', suffix=label.suffix[:20], dir=directory)
            path = Path(name)
            info = os.fstat(out_fd)
            device, inode = info.st_dev, info.st_ino
            storage.conn.execute('INSERT INTO zotero_import_copies VALUES(?,?,?,?,?,?,?,?)',
                                 (receipt, job_id, str(path), device, inode, '', None, time.time()))
            storage.conn.commit()
            digest = hashlib.sha256()
            with os.fdopen(out_fd, 'wb') as target:
                for chunk in iter(lambda: original.read(1024 * 1024), b''):
                    check()
                    target.write(chunk)
                    digest.update(chunk)
                target.flush()
                os.fsync(target.fileno())
            if fingerprint(before) != fingerprint(os.fstat(original.fileno())) or fingerprint(before) != fingerprint(source.stat()):
                raise ValueError('The source changed while copying. The copy was not imported: ' + source.name)
            value = digest.hexdigest()
            # Verify both the completed copy and a fresh read of the source.
            if digest_file(path, check) != value or digest_file(source, check) != value:
                raise ValueError('File verification failed: ' + source.name)
            if fingerprint(before) != fingerprint(source.stat()):
                raise ValueError('The source changed during verification: ' + source.name)
            storage.conn.execute('UPDATE zotero_import_copies SET digest=? WHERE id=?', (value, receipt))
            storage.conn.commit()
            return {'id': receipt, 'path': path, 'device': device, 'inode': inode, 'digest': value, 'size': before.st_size}
    except BaseException:
        if path is not None:
            remove_owned(path, device, inode)
            storage.conn.execute('DELETE FROM zotero_import_copies WHERE id=?', (receipt,))
            storage.conn.commit()
        raise


def discard(storage, copy):
    remove_owned(copy['path'], copy['device'], copy['inode'])
    storage.conn.execute('DELETE FROM zotero_import_copies WHERE id=?', (copy['id'],))
    storage.conn.commit()


def recover(storage, job_id):
    """Explicit resume cleans only journaled, unregistered copies of this job."""
    for row in storage.conn.execute('SELECT * FROM zotero_import_copies WHERE job_id=?', (job_id,)).fetchall():
        registered = storage.conn.execute('SELECT 1 FROM resources WHERE id=? OR stored_path=?',
                                          (row['resource_id'], row['path'])).fetchone()
        if not registered and Path(row['path']).exists() and (not row['digest'] or digest_file(row['path']) != row['digest']):
            # An interrupted or subsequently edited copy cannot be proven safe
            # to delete after a restart. Retain it and its receipt for review.
            continue
        if not registered:
            remove_owned(row['path'], row['device'], row['inode'])
        storage.conn.execute('DELETE FROM zotero_import_copies WHERE id=?', (row['id'],))
    storage.conn.commit()
