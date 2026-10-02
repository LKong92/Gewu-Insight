"""Run the real native Science download delegate with ephemeral website state."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS compiler required')
class ScienceBrowserSessionTests(unittest.TestCase):
    def test_shared_session_and_native_download_protections(self):
        with tempfile.TemporaryDirectory(prefix='gewu-science-session-') as directory:
            executable = Path(directory) / 'probe'
            env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory) / 'modules'))
            build = subprocess.run([
                'xcrun', 'clang', '-fobjc-arc', '-mmacosx-version-min=14.0',
                '-framework', 'Cocoa', '-framework', 'Quartz', '-framework', 'WebKit',
                '-framework', 'ImageIO', '-framework', 'UniformTypeIdentifiers',
                '-I', str(ROOT / 'scripts'), str(ROOT / 'tests/science_download_webkit_probe.m'),
                *[str(ROOT / 'scripts' / name) for name in (
                    'GewuBrowserController.m', 'GewuBrowserAutoFill.m',
                    'GewuBrowserCapture.m', 'GewuBrowserFavicons.m')],
                '-o', str(executable),
            ], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
