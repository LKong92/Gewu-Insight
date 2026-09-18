"""Recover interrupted managed-file relocations before the next UI startup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


class MoveJournal:
    def __init__(self, storage, paper_id):
        self.path = storage.db_path.parent / "file-layout-recovery" / f"{uuid.uuid4().hex}.json"
        self.data = {"paper_id": paper_id, "moves": []}

    def move(self, source, destination, resource_id):
        stat = source.stat()
        self.data["moves"].append({"source": str(source), "destination": str(destination),
                                   "resource_id": resource_id, "device": stat.st_dev, "inode": stat.st_ino})
        write_json(self.path, self.data)
        # Exclusive hard-link + unlink preserves bytes/inode/extended attrs,
        # cannot overwrite a Finder save, and is recoverable between steps.
        os.link(source, destination)
        try:
            source.unlink()
        except Exception:
            destination.unlink()
            raise

    def finish(self):
        self.path.unlink(missing_ok=True)


def recover(storage):
    root = storage.db_path.parent / "file-layout-recovery"
    recovered = 0
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text())
        for move in reversed(data["moves"]):
            source, destination = Path(move["source"]), Path(move["destination"])
            resource = storage.get_paper_resource(int(move["resource_id"]))
            registered = storage.resource_local_path(resource)
            if registered and Path(registered).resolve() == destination.resolve():
                continue  # SQLite committed; the destination is authoritative.
            if not registered or Path(registered).resolve() != source.resolve():
                raise ValueError(f"Interrupted file move needs review: {path}")
            if not destination.exists():
                if not source.exists():
                    raise FileNotFoundError(str(source))
                continue
            stat = destination.stat()
            if (stat.st_dev, stat.st_ino) != (move["device"], move["inode"]):
                if source.exists():
                    continue  # The exclusive link failed on an unrelated file.
                raise ValueError(f"Interrupted file destination changed: {destination}")
            if source.exists():
                if not os.path.samefile(source, destination):
                    raise FileExistsError(str(source))
            else:
                source.parent.mkdir(parents=True, exist_ok=True)
                os.link(destination, source)
            destination.unlink()
        path.unlink()
        recovered += 1
    return recovered
