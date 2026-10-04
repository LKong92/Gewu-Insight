"""Science ePDF original-file capture and scoped visibility regression."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS compiler required')
class ScienceBrowserCaptureTests(unittest.TestCase):
    def test_original_bytes_document_guards_and_science_only_resize(self):
        with tempfile.TemporaryDirectory(prefix='gewu-science-capture-') as directory:
            executable = Path(directory) / 'probe'
            build = subprocess.run([
                'xcrun', 'clang', '-fobjc-arc', '-mmacosx-version-min=14.0',
                '-framework', 'Cocoa', '-framework', 'WebKit',
                '-framework', 'UniformTypeIdentifiers', '-I', str(ROOT / 'scripts'),
                str(ROOT / 'tests/science_capture_webkit_probe.m'),
                *[str(ROOT / 'scripts' / name) for name in (
                    'GewuBrowserAutoFill.m', 'GewuBrowserCapture.m', 'GewuBrowserFavicons.m')],
                '-o', str(executable),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Science capture and layout checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
