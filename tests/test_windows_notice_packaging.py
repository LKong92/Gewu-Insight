"""Check actual staged notice bytes and links without building or running Setup."""
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "package_windows_notices", ROOT / "scripts/package_windows_notices.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class WindowsNoticePackagingTests(unittest.TestCase):
    def test_notice_bundle_preserves_bytes_and_resolves_local_document_links(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            component_notice = payload / "licenses/runtime/LICENSE"
            component_notice.parent.mkdir(parents=True)
            component_notice.write_bytes(b"independent component notice")
            packaging.copy_notices(ROOT, payload)
            for relative in packaging.DOCUMENTS:
                with self.subTest(document=relative):
                    original = ROOT / relative
                    staged = payload / relative
                    self.assertEqual(staged.read_bytes(), original.read_bytes())
                    text = staged.read_text(encoding="utf-8")
                    for link in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
                        if urlsplit(link).scheme or link.startswith("#"):
                            continue
                        target = unquote(link.split("#", 1)[0])
                        self.assertTrue((staged.parent / target).is_file(),
                                        f"Missing packaged link: {relative} -> {link}")
            self.assertEqual(component_notice.read_bytes(), b"independent component notice")

    def test_missing_source_document_fails_before_writing_a_partial_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            (root / "LICENSE").write_text("fixture", encoding="utf-8")
            output = Path(directory) / "payload"
            with self.assertRaises(FileNotFoundError):
                packaging.copy_notices(root, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
