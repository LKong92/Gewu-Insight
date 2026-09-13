"""Shared Add to Library destinations; settings refer to folders, never disk paths."""
from collections import defaultdict


DEFAULT_ADD_FOLDER_SETTING = "library_default_add_folder_id"


def active_folders(storage):
    nodes = {int(n["id"]): n for n in storage.list_library_folders()}
    children = defaultdict(list)
    for node in nodes.values():
        children[node.get("parent_id")].append(int(node["id"]))
    result = []

    def walk(node_id, prefix, seen):
        if node_id in seen or node_id not in nodes:
            return
        node = nodes[node_id]
        if node.get("trashed_at") or (node.get("parent_id") == 1 and node.get("name") == "Recycle"):
            return
        title = "Library" if node_id == 1 else (prefix + " / " if prefix else "") + node["name"]
        result.append({"id": node_id, "title": title})
        for child in children[node_id]:
            walk(child, title, seen | {node_id})

    walk(1, "", set())
    for node_id in children[None]:
        if node_id != 1:
            walk(node_id, "", set())
    return result


def default_add_destination(storage, *, create=False, folders=None):
    """Resolve again at use time; read-only review must not create unsorted."""
    folders = active_folders(storage) if folders is None else folders
    active = {int(folder["id"]): folder for folder in folders}
    raw = storage.get_setting(DEFAULT_ADD_FOLDER_SETTING, "0")
    try:
        configured = int(raw or 0)
    except (TypeError, ValueError):
        configured = 0
    folder = active.get(configured)
    if folder:
        return {"folder_id": configured, "title": folder["title"], "fallback": False}
    row = storage.conn.execute(
        "SELECT id FROM library_folders WHERE parent_id=1 AND name='unsorted'"
    ).fetchone()
    folder_id = int(row["id"]) if row and int(row["id"]) in active else None
    if folder_id is None and create:
        folder_id = int(storage.ensure_library_folder(parent_id=1, name="unsorted")["id"])
        if folder_id not in {f["id"] for f in active_folders(storage)}:
            raise ValueError("The unsorted folder is unavailable. Choose an active Library folder.")
    return {"folder_id": folder_id, "title": "Library / unsorted", "fallback": raw not in ("0", "", None)}


def save_default_add_folder(storage, folder_id):
    if type(folder_id) is not int or folder_id < 0:
        raise ValueError("Choose an active Library or Space folder.")
    if folder_id and folder_id not in {f["id"] for f in active_folders(storage)}:
        raise ValueError("This folder is unavailable. Choose an active Library or Space folder.")
    storage.set_setting(DEFAULT_ADD_FOLDER_SETTING, str(folder_id))
    return default_add_destination(storage)
