"""Preserve source note HTML and multipart snapshots as ordinary Paper Files."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from .files import fingerprint


def copy_into_zip(archive, name, item, check):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name:
        raise ValueError('Snapshot contains an unsafe relative path.')
    path = Path(item['path']).resolve(strict=True)
    with path.open('rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Snapshot resource is not a regular file.')
        if item.get('size', before.st_size) != before.st_size or (item.get('mtime') and abs(item['mtime']-before.st_mtime*1000)>2):
            raise ValueError('Snapshot or note image changed after preview. Scan again.')
        with archive.open(name, 'w') as target:
            while True:
                check()
                chunk = source.read(1024*1024)
                if not chunk: break
                target.write(chunk)
        if fingerprint(before) != fingerprint(os.fstat(source.fileno())) or fingerprint(before) != fingerprint(path.stat()):
            raise ValueError('Snapshot or note image changed while exporting. Scan again.')


def snapshot(directory, attachment, check):
    fd, name = tempfile.mkstemp(suffix='.zip', dir=directory); os.close(fd)
    path = Path(name)
    try:
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            used = set()
            for item in attachment['snapshot_files']:
                if item['relative'] in used:
                    raise ValueError('Snapshot contains duplicate paths.')
                used.add(item['relative'])
                copy_into_zip(archive, item['relative'], item, check)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def note(directory, value, check):
    fd, name = tempfile.mkstemp(suffix='.zip', dir=directory); os.close(fd)
    path = Path(name)
    try:
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for name, content in [('original-note.html', value.get('html', '')),
                                  ('zotero-note.json', json.dumps(value.get('data', {}), ensure_ascii=False, indent=2, sort_keys=True))]:
                info = ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED
                archive.writestr(info, content)
            for image in value.get('images', []):
                if not image.get('path'): continue
                name = image['key'] + Path(image.get('filename', '')).suffix
                copy_into_zip(archive, 'images/'+name, image, check)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
