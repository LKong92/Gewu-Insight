"""Receive Zotero records through existing Gewu storage/file-layout interfaces.

Only this adapter's copies become managed files. Existing bibliography, manual
Default choices, classifications, source files and Zotero itself are preserved.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import tempfile
import uuid

from bs4 import BeautifulSoup

from .. import paper_identity
from ..download import paper_download_lock
from ..library_destination import active_folders
from ..resource_dedup import find_content
from . import archives, files, store


def payload(entry):
    data = entry['data']
    creators = data.get('creators', [])
    authors = [c.get('name') or ' '.join(filter(None, [c.get('firstName'), c.get('lastName')]))
               for c in creators if c.get('creatorType', 'author') in ('author', 'bookAuthor', 'inventor', 'artist')]
    raw = {'authors': authors, 'zotero': {'key': data['key'], 'item_type': data.get('itemType')},
           **{field: data.get(field, '') for field in ('volume', 'issue', 'pages')}}
    extra = data.get('extra', '')
    match = re.search(r'(?im)^arxiv(?:\s*id)?\s*:\s*(\S+)', extra)
    if match:
        from ..text import normalize_arxiv_identifier
        raw['arxiv_id'] = normalize_arxiv_identifier(match.group(1))
    title = data.get('title') or (BeautifulSoup(data.get('note', ''), 'html.parser').get_text(' ', strip=True)[:160]) or 'Untitled Zotero item'
    if data.get('itemType') == 'attachment':
        raw['file'] = {'kind': 'file'}
    return {'paper_id': 'zotero_' + uuid.uuid4().hex, 'doi': paper_identity.doi(data.get('DOI')),
            'title': title, 'journal': data.get('publicationTitle') or data.get('bookTitle') or data.get('publisher') or '',
            'publication_date': data.get('date', ''), 'abstract': data.get('abstractNote', ''),
            'abstract_source': 'Zotero', 'source': 'zotero_import', 'url': data.get('url', ''),
            'landing_url': data.get('url', ''), 'raw': raw,
            'type': {'journalArticle': 'journal-article', 'attachment': 'imported_file', 'note': 'imported_file'}.get(data.get('itemType'), data.get('itemType', ''))}


def source_id(job):
    return str(job['config']['source_id'])


def active(storage, folder_id):
    if folder_id not in {f['id'] for f in active_folders(storage)}:
        raise ValueError('The destination folder was removed or moved to Recycle. Choose an active destination.')


def mapped_folder(storage, source, target, key, parent, name):
    row = storage.conn.execute('SELECT folder_id FROM zotero_import_folders WHERE source_id=? AND target_id=? AND source_key=?',
                               (source, target, key)).fetchone()
    if row:
        active(storage, row['folder_id'])
        return row['folder_id']
    active(storage, parent)
    folder = storage.create_library_folder(parent_id=parent, name=name, commit=False)
    storage.conn.execute('INSERT INTO zotero_import_folders VALUES(?,?,?,?)', (source, target, key, folder['id']))
    return folder['id']


def destinations(storage, job):
    from ..publication_jobs import MUTATION_LOCK
    with MUTATION_LOCK:
        return _destinations(storage, job)


def _destinations(storage, job):
    source, config = source_id(job), job['config']
    target = int(config['target_id'])
    active(storage, target)
    storage.conn.execute('BEGIN IMMEDIATE')
    try:
        root = mapped_folder(storage, source, target, '@root', target, config['root_name'])
        mapping = {'': root}
        collections = {c['key']: c for c in config.get('collections', [])}
        def add(key, visiting=frozenset()):
            if key in mapping:
                return mapping[key]
            if key in visiting or key not in collections:
                raise ValueError('The Zotero collection hierarchy is invalid. Scan again.')
            item = collections[key]
            parent = item.get('parent') or ''
            parent_id = add(parent, visiting | {key}) if parent in collections else root
            mapping[key] = mapped_folder(storage, source, target, key, parent_id, item['name'])
            return mapping[key]
        for key in collections:
            add(key)
        from .. import ui_server as ui
        paths = []
        owners = {}
        for folder_id in mapping.values():
            directory = ui.local_copy_dir_for_library_folder(storage, folder_id)
            # Retain the existing Library/Space naming and Associated Files mirror.
            base = next(root for root in (ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT)
                        if directory.is_relative_to(root))
            directory = base.resolve() / directory.relative_to(base)
            if directory in owners and owners[directory] != folder_id:
                raise ValueError('Two Zotero collections map to the same filesystem folder. Use distinct collection names: ' + str(directory))
            owners[directory] = folder_id
            scope = ui.associated_scope_for_path(directory)
            if not scope:
                raise ValueError('The import folder is outside the managed Library or Spaces.')
            label, relative = scope
            paths.extend((directory, ui.ASSOCIATED_FILES_ROOT.resolve() / label / relative))
        protected = list(job['catalog'].get('protected_roots', []))
        protected.extend(row['path'] for row in storage.conn.execute(
            'SELECT path FROM zotero_import_sources WHERE job_id=?', (job['id'],)))
        with files.collection_directories(paths, protected):
            storage.conn.commit()
        return mapping
    except BaseException:
        storage.conn.rollback()
        raise


def match(storage, source, entry):
    incoming = payload(entry)
    mapped = storage.conn.execute('SELECT paper_id FROM zotero_import_papers WHERE source_id=? AND source_key=?',
                                  (source, entry['data']['key'])).fetchone()
    if mapped:
        paper = storage.get_paper(storage.resolve_paper_id(mapped['paper_id']))
        if not paper:
            raise ValueError('The previously imported paper was removed from Gewu. It will not be recreated automatically.')
        # Preserve later manual bibliography edits. Changed identifiers still require review.
        old_ids = dict(paper_identity.identifiers(storage, paper))
        new_ids = dict(paper_identity.identifiers(storage, incoming))
        if any(k in old_ids and old_ids[k] != v for k, v in new_ids.items()):
            raise ValueError('The Zotero identifier conflicts with the previously imported Gewu paper.')
        return paper, incoming
    candidates = paper_identity.find(storage, incoming)
    if len(candidates) > 1:
        raise ValueError('Identifiers match several Gewu papers. Review the identifiers before retrying.')
    if candidates:
        paper = storage.get_paper(candidates[0]['paper_id'])
        reasons = paper_identity.review_reasons(storage, paper, incoming)
        if reasons:
            raise ValueError('Metadata conflicts with an existing Gewu paper: ' + ', '.join(reasons))
        return paper, incoming
    return None, incoming


def adopt(storage, job, entry, folders):
    source = source_id(job)
    storage.conn.execute('BEGIN IMMEDIATE')
    try:
        paper, incoming = match(storage, source, entry)
        reused = bool(paper)
        if not paper:
            if not storage.upsert_paper(incoming, commit=False):
                raise ValueError('The incoming identity needs review; no existing record was changed.')
            paper = storage.get_paper(incoming['paper_id'])
        elif storage.conn.execute("SELECT 1 FROM library_items WHERE paper_id=? AND COALESCE(trashed_at,'')!=''", (paper['paper_id'],)).fetchone():
            raise ValueError('This paper has a recycled Gewu placement. Restore or review it before importing.')
        selected = [folders[k] for k in entry['data'].get('collections', []) if k in folders]
        if not selected:
            selected = [folders['']]
        for folder_id in selected:
            active(storage, folder_id)
            storage.add_library_item(paper_id=paper['paper_id'], folder_id=folder_id, commit=False)
        storage.conn.execute('INSERT OR IGNORE INTO zotero_import_papers VALUES(?,?,?)',
                             (source, entry['data']['key'], paper['paper_id']))
        storage.conn.commit()
        return paper, selected[0], reused
    except BaseException:
        storage.conn.rollback()
        raise


def source_roots(job, entry):
    roots = list(job['catalog'].get('protected_roots', []))
    # An arbitrary linked attachment can live outside all configured roots.
    roots.extend(str(Path(a['path']).resolve()) for a in entry.get('attachments', []) if a.get('path'))
    roots.extend(str(Path(i['path']).resolve()) for n in entry.get('notes', []) for i in n.get('images', []) if i.get('path'))
    return roots


def attach(storage, job, entry, paper, folder_id, attachment, check, verified=None):
    from .. import ui_server as ui
    source = source_id(job)
    paper_id = paper['paper_id']
    # PDF exporters can emit fresh internal IDs for unchanged source content.
    # A server-derived revision identifies the original PDF + annotations.
    if attachment.get('revision'):
        attachment = dict(attachment, key=attachment['key'] + ':' + attachment['revision'])
        receipt = storage.conn.execute('SELECT resource_id,digest FROM zotero_import_files WHERE source_id=? AND source_key=? AND paper_id=?',
                                       (source, attachment['key'], paper_id)).fetchone()
        if receipt:
            resource = storage.get_paper_resource(receipt['resource_id'])
            path = storage.resource_local_path(resource) if resource else ''
            if not path or not Path(path).is_file():
                raise ValueError('A previously imported annotated PDF was removed from Gewu; it will not be restored automatically.')
            # User edits in Gewu must be kept as well: do not overwrite the copy.
            return resource['id']
    directory = ui.local_copy_dir_for_library_folder(storage, folder_id)
    files.protect_destination(directory, source_roots(job, entry))
    for root in (ui.ASSOCIATED_FILES_ROOT, ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT, ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT):
        files.protect_destination(root, source_roots(job, entry))
    filename = ui.finder_safe_name(attachment.get('filename') or Path(attachment['path']).name, preserve_extension=True)
    copy = files.copy_verified(storage, job['id'], attachment['path'], directory,
                               expected=attachment, check=check, filename=filename)
    if verified is not None:
        verified[attachment['key']] = copy['digest']
    resource = None
    try:
        check()
        with paper_download_lock(storage.db_path, paper_id, blocking=False):
            storage.conn.execute('BEGIN IMMEDIATE')
            receipt = storage.conn.execute('SELECT resource_id FROM zotero_import_files WHERE source_id=? AND source_key=? AND digest=? AND paper_id=?',
                                            (source, attachment['key'], copy['digest'], paper_id)).fetchone()
            if receipt:
                resource = storage.get_paper_resource(receipt['resource_id'])
                if not resource or not Path(storage.resource_local_path(resource)).is_file():
                    raise ValueError('A previously imported attachment was removed from Gewu; it will not be restored automatically: ' + filename)
            if not resource:
                resource = find_content(storage, paper_id, copy['digest'], copy['size'])
                if resource:
                    candidate = storage.resource_local_path(resource)
                    external = resource.get('storage_mode') == 'linked'
                    try:
                        files.protect_destination(candidate, source_roots(job, entry))
                    except ValueError:
                        external = True
                    external = external or storage.conn.execute('SELECT 1 FROM zotero_import_sources WHERE job_id=? AND path=?',
                                                                 (job['id'], str(Path(candidate).resolve()))).fetchone()
                    if external:
                        resource = None # Keep an independent copy, not a link back into Zotero.
            if not resource:
                resource = storage.create_paper_resource(paper_id=paper_id, stored_path=str(copy['path']),
                    source_path='zotero:' + source + '/' + attachment['key'] + '#' + copy['digest'], display_name=filename,
                    file_type='unknown' if filename.lower().endswith('.pdf') else 'other',
                    file_role='note' if attachment.get('note') else 'other',
                    storage_mode='managed', sha256=copy['digest'], mime_type=attachment.get('contentType') or mimetypes.guess_type(filename)[0] or '',
                    file_source='user_import', source_detail='Imported from Zotero', added_via='zotero_import',
                    annotation_state='annotated' if attachment.get('annotated') else 'unknown',
                    annotation_count=int(attachment.get('annotation_count', 0)), commit=False)
                storage.conn.execute('UPDATE zotero_import_copies SET resource_id=? WHERE id=?', (resource['id'], copy['id']))
            storage.conn.execute('INSERT OR IGNORE INTO zotero_import_files VALUES(?,?,?,?,?)',
                                 (source, attachment['key'], copy['digest'], paper_id, resource['id']))
            storage.conn.commit()
        if storage.resource_local_path(resource) != str(copy['path']):
            files.discard(storage, copy)
        else:
            storage.conn.execute('DELETE FROM zotero_import_copies WHERE id=?', (copy['id'],))
            storage.conn.commit()
        return resource['id']
    except BaseException:
        storage.conn.rollback()
        # Once registered, an interrupted response must never delete its copy.
        registered = storage.conn.execute('SELECT 1 FROM resources WHERE stored_path=?', (str(copy['path']),)).fetchone()
        if not registered:
            files.discard(storage, copy)
        raise


def readable_metadata(entry):
    data = entry['data']
    lines = ['# Zotero Metadata', '', 'Original Zotero fields retained during import. Existing Gewu metadata was not overwritten.', '']
    for key, value in data.items():
        if key in ('note', 'relations', 'collections', 'tags', 'creators') or value in ('', None, []):
            continue
        lines.extend(['**' + str(key) + ':** ' + str(value), ''])
    for key in ('creators', 'tags', 'collections', 'relations'):
        if data.get(key):
            lines.extend(['## ' + key.title(), '', '```json', json.dumps(data[key], ensure_ascii=False, indent=2), '```', ''])
    links = [a for a in entry.get('attachments', []) if not a.get('path') and a.get('url')]
    if links:
        lines.extend(['## Linked attachments', ''])
        for a in links:
            lines.extend([str(a.get('title') or a.get('filename') or 'Attachment'), str(a['url']), ''])
    return '\n'.join(lines)


def readable_note(note):
    soup = BeautifulSoup(note.get('html', ''), 'html.parser')
    for node in soup(['script', 'style', 'iframe', 'object']):
        node.decompose()
    # Preserve readable text without executing source HTML or loading remote URLs.
    for node in soup.find_all(['p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'tr']):
        node.insert_before('\n')
    lines = ['# ' + (note.get('title') or 'Zotero Note'), '', soup.get_text().strip(), '']
    for image in note.get('images', []):
        if image.get('path') and Path(image['path']).is_file():
            if Path(image['path']).stat().st_size > 20 * 1024 * 1024:
                raise ValueError('A note image is too large to embed; the original note is retained in the migration record.')
            mime = image.get('contentType', '')
            if mime in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
                path = Path(image['path'])
                before = path.stat()
                if image.get('size', before.st_size) != before.st_size or (image.get('mtime') and abs(image['mtime']-before.st_mtime*1000)>2):
                    raise ValueError('A note image changed after preview. Scan again.')
                data = base64.b64encode(path.read_bytes()).decode()
                if files.fingerprint(before) != files.fingerprint(path.stat()):
                    raise ValueError('A note image changed while reading. Scan again.')
                lines.extend(['![Zotero note image](data:' + mime + ';base64,' + data + ')', ''])
    for link in soup.find_all('a', href=True):
        lines.extend([link.get_text(' ', strip=True) + ': ' + link['href'], ''])
    return '\n'.join(lines)


def import_entry(storage, job, entry, exports, check=lambda: None):
    from .. import ui_server as ui
    from ..file_layout import reconcile
    check()
    folders = job['config'].get('folder_map') or destinations(storage, job)
    paper, folder_id, reused = adopt(storage, job, entry, folders)
    result = {'gewu_key': paper['storage_key'], 'paper_id': paper['paper_id'], 'reused': reused, 'files': [], 'issues': list(entry.get('warnings', []))}
    result['issues'].extend(exports.get('warnings', []))
    items = entry.get('attachments', [])
    items = sorted(items, key=lambda a: not (a.get('contentType') == 'application/pdf' or a.get('filename', '').lower().endswith('.pdf')))
    originals = {}
    verified = {}
    for attachment in items + exports.get('attachments', []):
        check()
        if not attachment.get('path'):
            if attachment.get('missing'):
                result['issues'].append(attachment['missing'])
            continue
        try:
            if attachment.get('annotated'):
                original_key = attachment['key'].removesuffix(':annotated')
                original = originals.get(original_key)
                if not original:
                    raise ValueError('The annotated copy was skipped because its original PDF could not be verified.')
                source_file = next(a for a in items if a['key'] == original_key)
                revision = hashlib.sha256((original + store.dumps(source_file.get('annotations', []))).encode()).hexdigest()
                attachment = dict(attachment, revision=revision)
            resource_id = attach(storage, job, entry, paper, folder_id, attachment, check, verified)
            result['files'].append(resource_id)
            if not attachment.get('annotated'):
                originals[attachment['key']] = verified[attachment['key']]
        except files.Paused:
            raise
        except (OSError, ValueError) as exc:
            result['issues'].append(str(exc))
    generated = [(entry['data']['key'] + ':metadata', 'Zotero Metadata.md', readable_metadata(entry))]
    for note in entry.get('notes', []):
        try:
            generated.append((note['key'] + ':note', (note.get('title') or 'Zotero Note')[:80] + '.md', readable_note(note)))
        except (OSError, ValueError) as exc:
            result['issues'].append(str(exc))
    for attachment in items:
        if attachment.get('annotations'):
            text = ['# Zotero Annotations', '']
            for annotation in attachment['annotations']:
                text.extend(['## Page ' + str(annotation.get('pageLabel', '?')), '',
                             str(annotation.get('text') or ''), '', str(annotation.get('comment') or ''), ''])
                if str(annotation.get('image', '')).startswith('data:image/png;base64,'):
                    text.extend(['![Annotation image](' + annotation['image'] + ')', ''])
            generated.append((attachment['key'] + ':annotations', 'Zotero Annotations.md', '\n'.join(text)))
    staging = storage.db_path.parent / 'zotero-import-staging' / job['id']
    files.protect_destination(staging, source_roots(job, entry))
    staging.mkdir(parents=True, exist_ok=True)
    for key, name, content in generated:
        check()
        fd, temp = tempfile.mkstemp(suffix='.md', dir=staging)
        import os
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(content)
            resource = attach(storage, job, entry, paper, folder_id,
                              {'key': key, 'path': temp, 'filename': name, 'note': True}, check)
            result['files'].append(resource)
        except files.Paused:
            raise
        except (OSError, ValueError) as exc:
            result['issues'].append(str(exc))
        finally:
            Path(temp).unlink(missing_ok=True)
    bundles = [(a['key'] + ':snapshot', (Path(a['filename']).stem or 'Web Snapshot') + ' — Snapshot.zip',
                lambda a=a: archives.snapshot(staging, a, check)) for a in items if a.get('snapshot_files')]
    bundles.extend((n['key'] + ':original-note', (n.get('title') or 'Zotero Note')[:80] + ' — Original.zip',
                    lambda n=n: archives.note(staging, n, check)) for n in entry.get('notes', []))
    for key, name, make in bundles:
        check()
        path = None
        try:
            path = make()
            result['files'].append(attach(storage, job, entry, paper, folder_id,
                                         {'key': key, 'filename': name, 'path': str(path)}, check))
        except files.Paused:
            raise
        except (OSError, ValueError) as exc:
            result['issues'].append(str(exc))
        finally:
            if path: path.unlink(missing_ok=True)
    check()
    try:
        # Reuse existing managed layout only after all registered paths are copies.
        with paper_download_lock(storage.db_path, paper['paper_id'], blocking=False):
            for resource in storage.list_paper_resources(paper['paper_id'], ensure_primary=False):
                if resource.get('storage_mode') != 'linked' and storage.resource_local_path(resource):
                    files.protect_destination(storage.resource_local_path(resource), source_roots(job, entry))
                    if storage.conn.execute('SELECT 1 FROM zotero_import_sources WHERE job_id=? AND path=?',
                                            (job['id'], str(Path(storage.resource_local_path(resource)).resolve()))).fetchone():
                        raise ValueError('An existing Gewu managed file is a Zotero source. Its location was preserved for review.')
            reconcile(storage, paper['paper_id'])
    except (OSError, ValueError) as exc:
        result['issues'].append('Files saved; folder layout needs retry: ' + str(exc))
    result['files'] = sorted(set(result['files']))
    return result
