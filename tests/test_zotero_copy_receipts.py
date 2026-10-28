"""Lossless Windows file identity receipts and failed-copy handle cleanup."""
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import os
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from paper_monitor.zotero_import import files


class CopyReceiptTests(unittest.TestCase):
    def test_sqlite_integer_affinity_preserves_wide_file_ids(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE copies(device INTEGER, inode INTEGER)')
            for device, inode in [(1, 2), (2**64-1, 2**127+12345)]:
                db.execute('INSERT INTO copies VALUES(?,?)', (files.stored_identity(device), files.stored_identity(inode)))
                row = db.execute('SELECT device,inode FROM copies ORDER BY rowid DESC LIMIT 1').fetchone()
                self.assertEqual(tuple(map(files.identity_number, row)), (device, inode))

    def test_cleanup_requires_the_exact_recorded_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'copy.pdf'; path.write_bytes(b'preserve replacement')
            device, inode = 2**64-1, 2**127+12345
            info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=device, st_ino=inode)
            with patch.object(Path, 'lstat', return_value=info):
                files.remove_owned(path, files.stored_identity(device), files.stored_identity(inode+1))
                files.remove_owned(path, float(device), float(inode))
                files.remove_owned(path, 'hex:broken', 'hex:broken')
                self.assertTrue(path.is_file())
                files.remove_owned(path, files.stored_identity(device), files.stored_identity(inode))
            self.assertFalse(path.exists())

    def test_stat_and_fstat_clock_difference_keeps_valid_copy(self):
        # Reproduce Windows stat creation-time versus fstat change-time values.
        with tempfile.TemporaryDirectory() as temp, closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE zotero_import_copies(id, job_id, path, device INTEGER, inode INTEGER, digest, resource_id, created)')
            source = Path(temp) / 'source.pdf'; source.write_bytes(b'original data')
            real_fstat = os.fstat
            def different_clock(fd):
                st = real_fstat(fd)
                values = {name: getattr(st, name) for name in ('st_mode', 'st_dev', 'st_ino', 'st_size', 'st_mtime', 'st_mtime_ns', 'st_ctime_ns')}
                values['st_ctime_ns'] += 1000000
                return SimpleNamespace(**values)
            with patch.object(files.os, 'fstat', side_effect=different_clock):
                result = files.copy_verified(SimpleNamespace(conn=db), 'fixture', source, Path(temp) / 'copies')
            self.assertEqual(result['path'].read_bytes(), source.read_bytes())

    def test_change_time_only_mutation_still_rejects_copy(self):
        with tempfile.TemporaryDirectory() as temp, closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE zotero_import_copies(id, job_id, path, device INTEGER, inode INTEGER, digest, resource_id, created)')
            source = Path(temp) / 'source.pdf'; source.write_bytes(b'original data')
            real_fstat = os.fstat; calls = 0
            def changed_clock(fd):
                nonlocal calls
                calls += 1
                st = real_fstat(fd)
                values = {name: getattr(st, name) for name in ('st_mode', 'st_dev', 'st_ino', 'st_size', 'st_mtime', 'st_mtime_ns', 'st_ctime_ns')}
                if calls >= 3: values['st_ctime_ns'] += 1000000
                return SimpleNamespace(**values)
            with patch.object(files.os, 'fstat', side_effect=changed_clock):
                with self.assertRaisesRegex(ValueError, 'source changed while copying'):
                    files.copy_verified(SimpleNamespace(conn=db), 'fixture', source, Path(temp) / 'copies')
            self.assertEqual(source.read_bytes(), b'original data')
            self.assertEqual(list((Path(temp) / 'copies').iterdir()), [])

    def test_failed_receipt_closes_copy_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.pdf'; source.write_bytes(b'unchanged original')
            destination = Path(temp) / 'copies'
            conn = MagicMock()
            def execute(sql, args):
                if sql.startswith('INSERT'):
                    raise sqlite3.OperationalError('synthetic receipt failure')
            conn.execute.side_effect = execute
            with self.assertRaisesRegex(sqlite3.OperationalError, 'synthetic receipt failure'):
                files.copy_verified(SimpleNamespace(conn=conn), 'fixture', source, destination)
            self.assertEqual(source.read_bytes(), b'unchanged original')
            self.assertEqual(list(destination.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
