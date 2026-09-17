from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LibraryNativeDragTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS compiler required')
    def test_file_url_and_destination_operation_negotiation(self):
        with tempfile.TemporaryDirectory(prefix='gewu-native-drag-test-') as directory:
            executable = Path(directory) / 'drag-test'
            command = ['xcrun', 'clang', '-fobjc-arc']
            for framework in ['Cocoa', 'Quartz', 'WebKit', 'ImageIO', 'UniformTypeIdentifiers']:
                command += ['-framework', framework]
            command += ['-I', str(ROOT / 'scripts'), str(ROOT / 'tests/library_native_drag_probe.m')]
            command += [str(ROOT / 'scripts' / name) for name in [
                'GewuBrowserController.m', 'GewuBrowserFavicons.m', 'GewuBrowserAutoFill.m', 'GewuBrowserCapture.m']]
            command += ['-o', str(executable)]
            build = subprocess.run(command, capture_output=True, text=True, timeout=90,
                env=dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory) / 'modules')))
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('native drag contract checks passed', result.stdout)
