"""Import and deletion read optimizations preserve identity and file boundaries."""
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from paper_monitor import finder_alias, recycle
from paper_monitor.importers import inventory


class ImportIdentityReadTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE papers(paper_id TEXT, doi TEXT, raw_json TEXT)")
        self.storage = SimpleNamespace(conn=self.conn)

    def test_projection_preserves_legacy_identity_and_source_fingerprints(self):
        records = [
            ("first", "10.1234/ABC", json.dumps({
                "arxiv_id": "https://arxiv.org/abs/2601.12345v2",
                "versioned_arxiv_id": "arXiv:2602.12345v3",
                "source_path": "/source/fallback.pdf", "size_bytes": 12,
                "import": {"source_path": "/source/original.pdf", "size_bytes": 0},
                "crossref": {"unrelated": "x" * 500000},
            })),
            ("second", "10.1234/abc", json.dumps({"arxiv_id": "2601.12345v8"})),
            ("null-size", "", json.dumps({"source_path": "/source/null.pdf", "size_bytes": 88,
                                           "import": {"size_bytes": None}})),
            ("fallback", "", json.dumps({"source_path": "/source/fallback.pdf", "size_bytes": 12,
                                          "import": {"source_path": ""}})),
            ("legacy", "", '{"arxiv_id":"2603.12345v1", "unused":NaN}'),
            ("broken", "10.1234/broken", "{broken"),
            ("list", "", "[]"), ("none", "", None),
        ]
        self.conn.executemany("INSERT INTO papers VALUES(?,?,?)", records)
        original_loads = json.loads
        lengths = []

        def decode(value, *args, **kwargs):
            lengths.append(len(value))
            return original_loads(value, *args, **kwargs)

        with patch.object(inventory.json, "loads", side_effect=decode):
            result = inventory.build_existing_index(self.storage)
        self.assertEqual(result, {
            "doi": {"10.1234/abc": "first", "10.1234/broken": "broken"},
            "arxiv_id": {"2601.12345": "first", "2602.12345": "first", "2603.12345": "legacy"},
            "source_path": {"/source/original.pdf|0": "first", "/source/null.pdf": "null-size",
                            "/source/fallback.pdf|12": "fallback"},
        })
        self.assertLess(max(lengths), 1000)  # No full provider payload enters the Python decoder.
        self.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id='first'", ('{"arxiv_id":"2604.12345"}',))
        fresh = inventory.build_existing_index(self.storage)
        self.assertEqual(fresh["arxiv_id"]["2601.12345"], "second")
        self.assertNotIn("2602.12345", fresh["arxiv_id"])


class RecycleReferenceReadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE papers(paper_id,main_pdf_path,merged_pdf_path,source_path,analysis_path,supplement_pdf_paths)")
        self.conn.execute("CREATE TABLE resources(id,paper_id,stored_path,source_path)")
        self.storage = SimpleNamespace(conn=self.conn)

    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_shared_directory_resolution_preserves_missing_and_symbolic_references(self):
        real = self.root / "real"
        real.mkdir()
        (real / "main.pdf").write_bytes(b"synthetic")
        directory_link = self.root / "directory-link"
        directory_link.symlink_to(real, target_is_directory=True)
        final_link = real / "final-link.pdf"
        final_link.symlink_to(real / "main.pdf")
        broken = real / "broken.pdf"
        broken.symlink_to(real / "absent.pdf")
        self.conn.execute("INSERT INTO papers VALUES(?,?,?,?,?,?)", (
            "p", str(directory_link / "main.pdf"), str(final_link), str(real / "missing.pdf"),
            str(broken), json.dumps([str(directory_link / "main.pdf")]),
        ))
        self.conn.execute("INSERT INTO resources VALUES(1,'shared',?,?)", (str(final_link), str(broken)))
        refs = recycle._references(self.storage)
        self.assertEqual(len(refs), 7)
        self.assertEqual([(r[-2], r[-1]) for r in refs[:4]], [
            (real / "main.pdf", real / "main.pdf"), (final_link, real / "main.pdf"),
            (real / "missing.pdf", real / "missing.pdf"), (broken, real / "absent.pdf"),
        ])
        self.assertEqual(refs[4][5], 0)  # Keep the supplement's list index for path updates.
        self.assertEqual(refs[5][2], "shared")
        # No cross-operation cache: a changed directory symlink is read again.
        other = self.root / "other"
        other.mkdir()
        directory_link.unlink()
        directory_link.symlink_to(other, target_is_directory=True)
        self.assertEqual(recycle._references(self.storage)[0][-1], other / "main.pdf")

    def test_selected_alias_never_selects_its_target_and_path_kinds_refresh(self):
        folder = self.root / "selected"
        folder.mkdir()
        target = self.root / "retained.pdf"
        target.write_bytes(b"retained")
        alias = self.root / "selected-alias.pdf"
        alias = finder_alias.create(target, alias)
        selected_ref = (alias, target)
        target_ref = (target, target)
        nested_ref = (folder / "nested.pdf", folder / "nested.pdf")
        with patch.object(finder_alias, "is_alias", wraps=finder_alias.is_alias) as reads:
            affected = recycle._affected_checker([folder, alias])
            for _ in range(100):
                self.assertTrue(affected(selected_ref))
                self.assertFalse(affected(target_ref))
                self.assertTrue(affected(nested_ref))
            self.assertEqual(reads.call_count, 2)
        alias.unlink()
        alias.mkdir()
        refreshed = recycle._affected_checker([alias])
        self.assertTrue(refreshed((alias / "child.pdf", alias / "child.pdf")))


class ShortcutDiscoveryTests(unittest.TestCase):
    @__import__("unittest").skipIf(__import__("sys").platform == "win32", "POSIX symlink privilege fixture; Windows Shell Links tested separately")
    def test_scan_finds_all_alias_types_without_following_directory_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            managed = root / "managed"
            nested = managed / "nested"
            nested.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            target = outside / "target.pdf"
            target.write_bytes(b"retained bytes")
            (nested / "ordinary.md").write_text("note")
            native = nested / "native.pdf"
            native = finder_alias.create(target, native)
            if not native.is_symlink():
                finder_info_only = nested / "finder-info-only.pdf"
                finder_info_only.write_bytes(native.read_bytes())
                finder_alias.set_attribute(finder_info_only, "com.apple.FinderInfo",
                                           finder_alias.get_attribute(native, "com.apple.FinderInfo"))
            link = managed / "link.pdf"
            link.symlink_to(target)
            (nested / "broken.pdf").symlink_to(outside / "missing.pdf")
            (managed / "outside-link").symlink_to(outside, target_is_directory=True)
            finder_alias.create(target, outside / "not-in-scope.pdf")
            expected = {p for p in managed.rglob("*") if finder_alias.is_alias(p)}
            self.assertEqual(set(finder_alias.iter_aliases(managed)), expected)
            self.assertNotIn(outside / "not-in-scope.pdf", expected)
            from paper_monitor import ui_server as ui
            ui.remove_symlinks_to(target, [managed])
            self.assertFalse(native.exists())
            self.assertFalse(link.is_symlink())
            self.assertTrue((nested / "broken.pdf").is_symlink())
            self.assertTrue((managed / "outside-link").is_symlink())
            self.assertTrue((outside / "not-in-scope.pdf").exists())
            self.assertEqual(target.read_bytes(), b"retained bytes")
            self.assertEqual((nested / "ordinary.md").read_text(), "note")
