"""Move/rename placements and filenames without changing bytes or file identity.

The existing relocation journal commits registered paths and the logical item
together. New folder projections are reconciled after commit (and on an exact
MCP retry), using the same layout rules as imports and the App.
"""
import json
import logging
from pathlib import Path

from . import desktop_files, finder_alias, folder_rename as relocation
from .time_utils import now_iso


def organize(storage, paper_id, *, item_id=None, resource_id=None, folder_id=None,
             name=None, validate=None, before_commit=None, validate_paths=None):
    """Caller holds the mutation and paper download locks before entering."""
    from . import ui_server as ui
    from .file_layout import bundle_path

    if any((storage.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')):
        raise ValueError('An interrupted relocation needs recovery. Restart Gewu Insight before retrying.')
    journal = None
    storage.conn.execute('BEGIN IMMEDIATE')
    try:
        if validate:
            validate()
        paper = storage.get_paper(paper_id)
        canonical = ui.canonical_file_path_for_paper(paper)
        canonical = relocation._path(canonical) if canonical else None
        item = storage.get_library_item(item_id) if item_id else None
        old_item = dict(item) if item else None
        old_projection = ui.library_item_local_pdf_path(storage, item, paper) if item else None
        old_projection = relocation._path(old_projection) if old_projection else None
        old_bundle = ui.existing_associated_work_dir(storage, paper_id)
        old_bundle = relocation._path(old_bundle) if old_bundle else None
        pairs, dropped = [], {}

        if item:
            if folder_id is not None:
                item = storage.move_library_item(item_id=item_id, folder_id=folder_id, commit=False)
            else:
                item = storage.rename_library_item(item_id=item_id, name=name, commit=False)
            if canonical:
                directory = relocation._path(ui.local_copy_dir_for_library_folder(storage, item['folder_id']))
                destination = directory / ui.library_item_pdf_filename(item, paper, canonical)
                if old_projection and finder_alias.is_alias(old_projection) and destination != canonical:
                    destination = desktop_files.placement_path(destination)
                if old_projection and str(old_projection) != str(destination):
                    if finder_alias.is_alias(old_projection) and (destination == canonical or finder_alias.points_to(destination, canonical)):
                        dropped[old_projection] = (None, canonical)
                    else:
                        pairs.append((old_projection, destination))
                # The mirrored bundle shortcut follows an alias-only placement.
                old_directory = relocation._path(ui.local_copy_dir_for_library_folder(storage, old_item['folder_id']))
                old_projected_file = old_projection or old_directory / ui.library_item_pdf_filename(old_item, paper, canonical)
                old_link = bundle_path(ui, old_projected_file, paper['storage_key'])
                if old_link and old_link != old_bundle:
                    old_link = desktop_files.placement_path(old_link)
                new_link = bundle_path(ui, destination, paper['storage_key'])
                if new_link and new_link != old_bundle:
                    new_link = desktop_files.placement_path(new_link)
                if old_link and new_link and old_link != new_link and finder_alias.is_alias(old_link):
                    if new_link == old_bundle or finder_alias.points_to(new_link, old_bundle):
                        dropped[relocation._path(old_link)] = (None, old_bundle)
                    else:
                        pairs.append((relocation._path(old_link), relocation._path(new_link)))
        else:
            resource = storage.get_paper_resource(resource_id)
            source = relocation._path(storage.resource_local_path(resource))
            if not source.is_file() or finder_alias.is_alias(source):
                raise ValueError('The registered original is unavailable or is a shortcut.')
            destination = source.with_name(name)
            if str(source) != str(destination):
                pairs.append((source, destination))
            storage.conn.execute('UPDATE resources SET display_name=?, updated_at=? WHERE id=?',
                                 (name, now_iso(), resource_id))
            if source == canonical:
                # Preserve the user's filename on later normal layout syncs.
                for row in storage.conn.execute('SELECT * FROM library_items WHERE paper_id=? ORDER BY id', (paper_id,)):
                    directory = relocation._path(ui.local_copy_dir_for_library_folder(storage, row['folder_id']))
                    if directory == source.parent:
                        storage.rename_library_item(item_id=row['id'], name=name, commit=False)

        new_canonical = relocation._remap(canonical, pairs) if canonical else None
        if canonical and str(new_canonical) != str(canonical) and old_bundle:
            new_bundle = bundle_path(ui, new_canonical, paper['storage_key'])
            if new_bundle and str(new_bundle) != str(old_bundle):
                pairs.append((old_bundle, relocation._path(new_bundle)))
        pairs = list(dict.fromkeys((old, new) for old, new in pairs if str(old) != str(new)))
        roots = [Path(p).resolve() for p in (ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT, ui.ASSOCIATED_FILES_ROOT)]
        for old, new in pairs:
            if not all(any(relocation._within(p.parent.resolve(), root) for root in roots) for p in (old, new)):
                raise ValueError('Only managed Library, Space and Associated Files locations can be moved or renamed.')
            if finder_alias.points_to(new, old):
                dropped[new] = (None, old)
        references = relocation._references(storage, pairs)
        if {pid for pid, _, _ in references} - {paper_id}:
            raise ValueError('These bytes are shared with another record. Resolve shared ownership before organizing this file.')
        files, directories, aliases = relocation._plan(storage, pairs)
        aliases.update(dropped)
        if validate_paths:
            validate_paths(pairs, files, directories, aliases)
        if files or directories or aliases:
            journal = relocation.RenameJournal(storage, pairs, files, directories, aliases, create_root=False)
            journal.apply()
            for pid, old, new in references:
                ui.update_paper_file_path_references(storage, pid, old, new, commit=False)
            raw = ui.parse_raw_json(storage.get_paper(paper_id))
            layout = raw.get('file_layout', {})
            if isinstance(layout.get('associated_aliases'), list):
                layout['associated_aliases'] = [str(relocation._remap(relocation._path(p), pairs))
                                                 for p in layout['associated_aliases'] if relocation._path(p) not in dropped]
                storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?', (json.dumps(raw, ensure_ascii=False), paper_id))
            storage.conn.execute('INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,?)', (journal.key, '1', now_iso()))
        result = {'gewu_key': paper['storage_key'], 'membership_id': item['id'] if item else None,
                  'folder_id': item['folder_id'] if item else None, 'file_ids': [resource_id] if resource_id else [],
                  'name': item.get('display_name') if item else name, 'layout_pending': True}
        if before_commit:
            before_commit(result)
        storage.conn.commit()
    except Exception:
        storage.conn.rollback()
        if journal:
            journal.rollback()
        raise
    if journal:
        try:
            journal.finish(storage)
        except Exception:
            storage.conn.rollback()
            logging.getLogger(__name__).exception('File organized; journal cleanup will resume at startup')
    return result
