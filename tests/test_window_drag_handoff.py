import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from paper_monitor.ui_server import INDEX_HTML

ROOT = Path(__file__).resolve().parents[1]


class WindowDragHandoffTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_real_javascript_gesture_boundaries(self):
        result = subprocess.run(['node', str(ROOT / 'tests/window_drag_handoff_probe.cjs')],
            input=INDEX_HTML, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS compiler required')
    def test_native_original_event_handoff(self):
        with tempfile.TemporaryDirectory(prefix='gewu-window-handoff-') as directory:
            executable = Path(directory) / 'probe'
            command = ['xcrun', 'clang', '-fobjc-arc']
            for framework in ['Cocoa', 'Quartz', 'WebKit', 'ImageIO', 'UniformTypeIdentifiers']:
                command += ['-framework', framework]
            command += ['-I', str(ROOT / 'scripts'), str(ROOT / 'tests/window_drag_native_probe.m')]
            command += [str(ROOT / 'scripts' / name) for name in [
                'GewuBrowserController.m', 'GewuBrowserFavicons.m', 'GewuBrowserAutoFill.m', 'GewuBrowserCapture.m']]
            command += ['-o', str(executable)]
            build = subprocess.run(command, capture_output=True, text=True, timeout=90,
                env=dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory) / 'modules')))
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('native window handoff checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
