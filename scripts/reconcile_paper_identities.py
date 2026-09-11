#!/usr/bin/env python3
"""Explicit offline reconciliation; default action only creates a read-only plan."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_monitor.storage import Storage
from paper_monitor import paper_identity


def read_only_storage(path):
    # Avoid Storage startup migrations/backfills while reviewing real records.
    storage = object.__new__(Storage)
    storage.db_path = path
    storage.conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    storage.conn.row_factory = sqlite3.Row
    storage.conn.execute('PRAGMA query_only=ON')
    return storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--plan', type=Path, help='Write a review plan without changing SQLite')
    parser.add_argument('--apply', type=Path, help='Apply this reviewed plan with the App stopped')
    parser.add_argument('--backup', type=Path, help='New private SQLite backup, required with --apply')
    args = parser.parse_args()
    if bool(args.plan) == bool(args.apply) or (args.apply and not args.backup):
        parser.error('Choose --plan, or --apply with --backup')
    path = args.db.expanduser().resolve(strict=True)
    source = read_only_storage(path)
    try:
        if args.plan:
            plan = paper_identity.reconciliation_plan(source)
            with args.plan.open('x', encoding='utf-8') as output:
                json.dump(plan, output, ensure_ascii=False, indent=2)
                output.write('\n')
            ready = [g for g in plan['groups'] if not g['blockers']]
            print(json.dumps({'ready_groups': len(ready), 'redundant_records': sum(len(g['sources']) for g in ready),
                              'blocked_groups': len(plan['groups'])-len(ready)}))
            return
        plan = json.loads(args.apply.read_text())
        # An existing backup is never overwritten; its name is chosen explicitly.
        fd = os.open(args.backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        backup = sqlite3.connect(args.backup)
        try:
            source.conn.backup(backup)
            if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup verification failed')
        finally:
            backup.close()
    finally:
        source.close()
    storage = Storage(path)
    try:
        merged = paper_identity.apply_reconciliation(storage, plan)
        print(json.dumps({'merged_records': len(merged), 'files_moved_or_deleted': 0,
                          'backup': str(args.backup), 'foreign_keys_valid': True}))
    finally:
        storage.close()


if __name__ == '__main__':
    main()
