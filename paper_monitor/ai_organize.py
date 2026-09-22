"""Opt-in organization of Library/Space placements and existing Paper Files."""
from contextlib import ExitStack
from pathlib import Path

from .ai_contract import WRITE_SCOPES
from .ai_store import authenticate, fail
from .ai_writes import require_folder, require_paper, writable_folders, receipt, save_receipt
from .download import paper_download_lock
from .publication_jobs import MUTATION_LOCK


def identifier(value):
    from .ai_service import integer
    if value is None:
        fail(400, 'invalid_argument', 'Provide a positive integer ID.')
    return integer(value, 0, 1, 2**63 - 1)


def name_value(value, *, folder=False):
    from .ai_uploads import filename
    from . import ui_server as ui
    value = filename(value)
    if len(value) > (80 if folder else 180) or ui.finder_safe_name(value) != value:
        fail(400, 'invalid_name', 'Use a plain filename without path separators or reserved characters; folders allow 80 characters, files 180.')
    return value


def require_owned_paper(storage, grant, key):
    """Physical rename/ownership changes affect every projection, not one grant."""
    paper = require_paper(storage, grant, key)
    folders = writable_folders(storage, grant)
    rows = storage.conn.execute('SELECT folder_id,trashed_at FROM library_items WHERE paper_id=?', (paper['paper_id'],)).fetchall()
    if (not rows or any(r['folder_id'] not in folders or r['trashed_at'] for r in rows)
            or storage.conn.execute('SELECT 1 FROM my_publications WHERE paper_id=?', (paper['paper_id'],)).fetchone()):
        fail(403, 'write_scope_required', 'All locations affected by this operation must be writable. My Publications writes are not available.')
    return paper


def source_object(storage, grant, source):
    if not isinstance(source, dict):
        fail(400, 'invalid_source', 'Choose a membership_id or an exact gewu_key and file_id.')
    if set(source) == {'membership_id'}:
        item = storage.get_library_item(identifier(source['membership_id']))
        if not item:
            fail(404, 'item_not_found', 'The membership is unavailable.')
        require_folder(storage, grant, item['folder_id'])
        paper = storage.get_paper(item['paper_id'])
        return require_owned_paper(storage, grant, paper['storage_key']), item, None
    if set(source) == {'gewu_key', 'file_id'}:
        paper = require_owned_paper(storage, grant, source['gewu_key'])
        resource = storage.get_paper_resource(identifier(source['file_id']))
        if not resource or resource['paper_id'] != paper['paper_id']:
            fail(404, 'file_not_found', 'The file does not belong to the selected record.')
        return paper, None, resource
    fail(400, 'invalid_source', 'Choose only membership_id, or gewu_key with a numeric file_id. Do not use default for a move or rename.')


def writable_directories(storage, grant):
    from . import ui_server as ui, folder_rename
    active = writable_folders(storage, grant)
    return [directory for root in grant['write_folder_ids'] if root in active
            for directory in folder_rename._roots(ui, folder_rename._path(ui.local_copy_dir_for_library_folder(storage, root)))]


def require_paths(paths, roots):
    from .folder_rename import _within, _path
    if any(not any(_within(_path(path), root) for root in roots) for path in paths):
        fail(403, 'write_scope_required', 'A file or shortcut affected by this operation is outside the writable collections. No broader filesystem access is granted.')


def finish(storage, authorization, operation, result):
    from .ai_service import require_scope, file_metadata
    from .file_layout import reconcile
    grant = authenticate(storage, authorization)
    require_scope(grant, WRITE_SCOPES[operation])
    if operation.endswith('_folder'):
        require_folder(storage, grant, result['folder_id'])
        return result
    paper = require_owned_paper(storage, grant, result['gewu_key'])
    if result.get('membership_id'):
        item = storage.get_library_item(result['membership_id'])
        if not item or item['paper_id'] != paper['paper_id']:
            fail(410, 'item_changed', 'The previous membership is no longer available. The retry will not recreate it.')
        require_folder(storage, grant, item['folder_id'])
    for file_id in result['file_ids']:
        resource = storage.get_paper_resource(file_id)
        if not resource or resource['paper_id'] != paper['paper_id']:
            fail(410, 'file_changed', 'A previously moved file has changed ownership. The retry will not move it again.')
    papers = [paper]
    if result.get('remaining_source_key'):
        papers.append(require_owned_paper(storage, grant, result['remaining_source_key']))
    result = {**result, 'layout_pending': False}
    try:
        with ExitStack() as locks:
            for pid in sorted({owner['paper_id'] for owner in papers}):
                locks.enter_context(paper_download_lock(storage.db_path, pid, blocking=False))
            for owner in papers:
                reconcile(storage, owner['paper_id'])
    except (OSError, ValueError):
        storage.conn.rollback()
        result.update(layout_pending=True, message='The operation is saved; some folder links need synchronization. Retry this exact request_id to finish.')
    resources = storage.list_paper_resources(paper['paper_id'], ensure_primary=False)
    default = storage._select_default_paper_resource(storage.get_paper(paper['paper_id']), resources)
    result['files'] = [file_metadata(r, (default or {}).get('id', 0)) for r in resources if r['id'] in result['file_ids']]
    return result


def execute_organize(storage, authorization, operation, args):
    from .ai_service import WRITE_LOCK, require_scope
    from . import ui_server as ui, folder_rename, file_organize, file_reassignment

    allowed = {
        'move_folder': {'folder_id', 'parent_id', 'request_id'},
        'rename_folder': {'folder_id', 'name', 'request_id'},
        'move_file': {'source', 'target', 'request_id'},
        'rename_file': {'source', 'name', 'request_id'},
    }[operation]
    if set(args) != allowed:
        fail(400, 'invalid_arguments', 'Supply exactly the documented arguments for this operation.')
    with WRITE_LOCK, MUTATION_LOCK, ExitStack() as locks:
        grant = authenticate(storage, authorization)
        require_scope(grant, WRITE_SCOPES[operation])
        request, digest, previous = receipt(storage, grant, operation, args)
        if previous:
            return {**finish(storage, authorization, operation, previous), 'reused_request': True}
        result = None
        directories = []

        def fresh():
            current = authenticate(storage, authorization)
            require_scope(current, WRITE_SCOPES[operation])
            directories[:] = writable_directories(storage, current)
            return current

        def validate_paths(pairs, files, folders, aliases):
            # A directly granted child/root keeps its grant when renamed/moved.
            # Also check unregistered shortcuts discovered by the App's planner.
            roots = [*directories, *(folder_rename._remap(p, pairs) for p in directories)]
            paths = [*files, *folders, *aliases, *(new for new, _ in aliases.values() if new),
                     *(folder_rename._remap(p, pairs) for p in [*files, *folders])]
            require_paths(paths, roots)

        def saved(value):
            nonlocal result
            result = value
            save_receipt(storage, grant, operation, request, digest, result)

        try:
            if operation.endswith('_folder'):
                folder_id = identifier(args['folder_id'])
                parent_id = identifier(args['parent_id']) if operation == 'move_folder' else None
                name = name_value(args['name'], folder=True) if operation == 'rename_folder' else None

                def validate_folder(paper_ids=()):
                    current = fresh()
                    require_folder(storage, current, folder_id)
                    folder = storage.get_library_folder(folder_id)
                    if folder_id == 1 or (folder['parent_id'] == 1 and folder['name'] in (ui.LIBRARY_UNSORTED_FOLDER_NAME, ui.LIBRARY_RECYCLE_FOLDER_NAME)):
                        fail(400, 'protected_folder', 'Library, Unsorted and Recycle cannot be moved or renamed through MCP.')
                    if parent_id is not None:
                        require_folder(storage, current, parent_id)
                        if parent_id == folder_id or storage._folder_is_descendant(parent_id, folder_id):
                            fail(400, 'folder_cycle', 'A folder cannot be moved into itself or its descendants.')
                        if folder['parent_id'] is None and ui.library_folder_chain(storage, parent_id)[0]['id'] != 1:
                            fail(400, 'space_destination', 'A Space can be moved into Library using the existing App workflow; choose a Library folder.')
                    if name and folder['parent_id'] == 1 and name.casefold() == 'recycle':
                        fail(400, 'reserved_name', 'Recycle is reserved for the App’s trash collection.')
                    for pid in paper_ids:
                        require_owned_paper(storage, current, storage.get_paper(pid)['storage_key'])

                validate_folder()
                def saved_folder(folder):
                    saved({'folder_id': folder['id'], 'name': folder['name'], 'parent_id': folder['parent_id'],
                           'kind': 'space' if folder['parent_id'] is None else 'folder', 'layout_pending': False})
                folder_rename.relocate(storage, folder_id, name=name, parent_id=parent_id,
                                      workspace_tabs=ui.library_workspace_tabs(storage),
                                      validate=validate_folder, before_commit=saved_folder, validate_paths=validate_paths)
            else:
                paper, item, resource = source_object(storage, grant, args['source'])
                target, destination_folder = None, None
                name = name_value(args['name']) if operation == 'rename_file' else None
                if operation == 'move_file':
                    value = args['target']
                    if isinstance(value, dict) and set(value) == {'folder_id'}:
                        destination_folder = require_folder(storage, grant, value['folder_id'])
                    elif isinstance(value, dict) and set(value) == {'gewu_key'}:
                        target = require_owned_paper(storage, grant, value['gewu_key'])
                    else:
                        fail(400, 'invalid_target', 'Choose only a folder_id or a target gewu_key.')
                if name and resource:
                    old_name = Path(storage.resource_local_path(resource)).name
                    if Path(old_name).suffix.lower() != Path(name).suffix.lower():
                        fail(400, 'extension_changed', 'Keep the existing file extension when renaming a Paper File.')
                for pid in sorted({paper['paper_id']} | ({target['paper_id']} if target else set())):
                    locks.enter_context(paper_download_lock(storage.db_path, pid, blocking=False))

                def validate_file():
                    current = fresh()
                    source_object(storage, current, args['source'])
                    if target:
                        require_owned_paper(storage, current, target['storage_key'])
                    if destination_folder is not None:
                        require_folder(storage, current, destination_folder)

                def saved_transfer(transfer):
                    membership = storage.conn.execute('SELECT id FROM library_items WHERE paper_id=? AND folder_id=?',
                        (transfer['target_paper_id'], destination_folder)).fetchone() if destination_folder else None
                    saved({'gewu_key': transfer['target_gewu_key'], 'file_ids': transfer['resource_ids'],
                           'membership_id': membership['id'] if membership else None, 'folder_id': destination_folder,
                           'source_removed': transfer['source_removed'], 'removed_membership_ids': transfer['removed_item_ids'],
                           'created_item': transfer['created_paper'], 'remaining_source_key': None if transfer['source_removed'] else paper['storage_key'],
                           'layout_pending': True})

                if target and item:
                    file_reassignment.attach_library_item(storage, item['id'], target['paper_id'],
                        validate=validate_file, before_commit=saved_transfer, validate_paths=lambda paths: require_paths(paths, directories))
                elif operation == 'move_file' and resource:
                    file_reassignment.reassign_paper_file(storage, paper['paper_id'], resource['id'],
                        target_paper_id=target['paper_id'] if target else '',
                        new_title=(resource.get('display_name') or Path(storage.resource_local_path(resource)).name) if not target else '',
                        folder_id=destination_folder or 0, validate=validate_file, before_commit=saved_transfer,
                        validate_paths=lambda paths: require_paths(paths, directories))
                else:
                    file_organize.organize(storage, paper['paper_id'], item_id=item['id'] if item else None,
                        resource_id=resource['id'] if resource else None, folder_id=destination_folder, name=name,
                        validate=validate_file, before_commit=saved, validate_paths=validate_paths)
            return finish(storage, authorization, operation, result)
        except (ValueError, KeyError, FileExistsError):
            fail(409, 'organization_conflict', 'The operation could not be completed safely. Check for a duplicate name, unavailable or shared file, changed ownership, or an interrupted relocation. Existing file contents are preserved.')
        except OSError:
            fail(503, 'organization_unavailable', 'The filesystem operation could not finish. Check local storage availability and retry with the same request_id.')
