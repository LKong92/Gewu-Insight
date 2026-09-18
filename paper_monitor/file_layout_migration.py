"""One-time, backed-up reconciliation at startup, before background workers."""
from __future__ import annotations

from datetime import datetime
import logging
import sqlite3

from .file_layout import reconcile
from .file_layout_journal import recover, write_json

SETTING = "managed_file_layout_finder_alias_v1"


def migrate(storage):
    from . import ui_server as ui
    # A custom database must never reorganize the production App's roots.
    if storage.db_path.parent.resolve() != ui.LIBRARY_LOCAL_COPY_ROOT.resolve().parent:
        return {"skipped": "custom database roots"}
    recovered = recover(storage)
    completed = storage.get_setting(SETTING, "") == "1"
    pending = {row[0] for row in storage.conn.execute("""SELECT paper_id FROM papers
        WHERE json_valid(raw_json) AND json_extract(raw_json, '$.file_layout.links_pending') = 1""")}
    if completed and not recovered and not pending:
        return {"skipped": "already reconciled"}
    rows = storage.conn.execute("""
        SELECT p.paper_id FROM papers p
        WHERE (EXISTS (SELECT 1 FROM library_items i WHERE i.paper_id=p.paper_id)
            OR EXISTS (SELECT 1 FROM my_publications m WHERE m.paper_id=p.paper_id))
        AND (SELECT count(*) FROM resources r WHERE r.paper_id=p.paper_id) > 0
        AND ((SELECT count(*) FROM resources r WHERE r.paper_id=p.paper_id) > 1
            OR (SELECT count(*) FROM library_items i WHERE i.paper_id=p.paper_id) > 1
            OR EXISTS (SELECT 1 FROM my_publications m WHERE m.paper_id=p.paper_id)
            OR EXISTS (SELECT 1 FROM resources r WHERE r.paper_id=p.paper_id AND r.stored_path LIKE ?))
        ORDER BY p.paper_id
    """, (str(ui.ASSOCIATED_FILES_ROOT.resolve()) + "/%",)).fetchall()
    if completed and not recovered:
        rows = [{"paper_id": paper_id} for paper_id in sorted(pending)]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory = storage.db_path.parent / "file-layout-backups" / stamp
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / "before.sqlite"
    with sqlite3.connect(backup) as connection:
        storage.conn.backup(connection)
    report = {"backup": str(backup), "recovered": recovered, "papers": [], "errors": []}
    for row in rows:
        paper_id = row["paper_id"]
        before = [dict(r) for r in storage.conn.execute(
            "SELECT id,stored_path,source_path FROM resources WHERE paper_id=?", (paper_id,))]
        try:
            outcome = reconcile(storage, paper_id)
            after = [dict(r) for r in storage.conn.execute(
                "SELECT id,stored_path,source_path FROM resources WHERE paper_id=?", (paper_id,))]
            report["papers"].append({"paper_id": paper_id, "before": before, "after": after, "outcome": outcome})
        except Exception as exc:
            storage.conn.rollback()
            logging.getLogger(__name__).exception("File layout repair deferred for %s", paper_id)
            report["errors"].append({"paper_id": paper_id, "error": str(exc)})
    write_json(directory / "report.json", report)
    # Failures remain explicit in the report. Retrying a whole Library on every
    # launch is avoided; later operations retry only their touched work.
    storage.set_setting(SETTING, "1")
    storage.set_setting(SETTING + "_report", str(directory / "report.json"))
    return report
