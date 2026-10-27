"""Signing identity policy and failure-safe App replacement regressions."""

import importlib.util
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('macos_signing', ROOT / 'scripts/macos_signing.py')
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)
LOCAL_IDENTITY = {'Signature': 'adhoc', 'TeamIdentifier': 'not set',
                  'Identifier': signing.BUNDLE_IDENTIFIER}


class SigningPolicyTests(unittest.TestCase):
    def test_default_build_uses_adhoc_without_certificate_discovery(self):
        with patch.object(signing, 'run', return_value='\n'.join(
                f'{key}={value}' for key, value in LOCAL_IDENTITY.items())) as command:
            self.assertEqual(signing.preflight(Path('/tmp/Installed.app'), Path('/tmp/New.app')), '-')
        self.assertTrue(all('/usr/bin/security' not in call.args[0]
                            for call in command.call_args_list))

    def test_process_inspection_failure_is_not_treated_as_no_running_app(self):
        with patch.object(signing, 'run', side_effect=signing.SigningError('permission denied')):
            with self.assertRaises(signing.SigningError):
                signing.check_stopped(Path('/tmp/Gewu Insight.app'))

    def test_running_app_path_with_spaces_blocks_replacement(self):
        app = Path('/tmp/a workspace/Gewu Insight.app')
        with patch.object(signing, 'run', return_value=f'  123 {app}/Contents/MacOS/Gewu Insight\n'):
            with self.assertRaisesRegex(signing.SigningError, 'running'):
                signing.check_stopped(app)

    def test_development_output_cannot_alias_or_contain_the_installed_app(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            installed = parent / 'Gewu Insight.app'
            installed.mkdir()
            alias = parent / 'alias.app'
            alias.symlink_to(installed)
            for output in [installed, alias, installed / 'inner.app', parent]:
                with self.subTest(output=output), self.assertRaises(signing.SigningError):
                    signing.preflight(installed, output, True)
            with patch.object(signing, 'signing_info', return_value=LOCAL_IDENTITY):
                self.assertEqual(signing.preflight(installed, parent / 'QA.app', True), '-')

    def test_existing_isolated_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'Installed.app'
            output = Path(directory) / 'QA.app'
            installed.mkdir()
            output.mkdir()
            with self.assertRaisesRegex(signing.SigningError, 'already exists'):
                signing.preflight(installed, output, True)

    def test_replacing_installed_app_requires_it_to_be_stopped(self):
        with patch.object(signing, 'signing_info', return_value=LOCAL_IDENTITY), \
             patch.object(signing, 'check_stopped') as stopped:
            app = Path('/tmp/Installed.app')
            self.assertEqual(signing.preflight(app, app), '-')
            stopped.assert_called_once_with(app.resolve())

    def test_adhoc_updates_still_receive_strict_signature_verification(self):
        app = Path('/tmp/New.app')
        previous = Path('/tmp/Old.app')
        with patch.object(signing, 'run') as command, \
             patch.object(signing, 'signing_info', return_value=LOCAL_IDENTITY):
            signing.verify(app, previous)
            self.assertIn(('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)),
                          [tuple(call.args[0]) for call in command.call_args_list])

    def test_unexpected_bundle_or_nonlocal_identity_is_rejected(self):
        for new, old in [
            ({**LOCAL_IDENTITY, 'TeamIdentifier': 'ABCDEFGHIJ'}, LOCAL_IDENTITY),
            ({**LOCAL_IDENTITY, 'Signature': 'certificate'}, LOCAL_IDENTITY),
            ({**LOCAL_IDENTITY, 'Identifier': 'different'}, LOCAL_IDENTITY),
            (LOCAL_IDENTITY, {**LOCAL_IDENTITY, 'Identifier': 'different'}),
            (LOCAL_IDENTITY, {**LOCAL_IDENTITY, 'Signature': 'certificate'}),
        ]:
            with self.subTest(new=new), patch.object(signing, 'run'), \
                 patch.object(signing, 'signing_info', side_effect=[new, old]):
                with self.assertRaises(signing.SigningError):
                    signing.verify(Path('/tmp/New.app'), Path('/tmp/Old.app'))

    def test_invalid_signature_stops_before_identity_checks(self):
        with patch.object(signing, 'run', side_effect=signing.SigningError('invalid signature')), \
             patch.object(signing, 'signing_info') as info:
            with self.assertRaises(signing.SigningError):
                signing.verify(Path('/tmp/Broken.app'))
            info.assert_not_called()

    def test_fingerprint_detects_bytes_modes_and_signing_attributes(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            file = app / 'launcher'
            file.write_bytes(b'original')
            original = signing.fingerprint(app)
            file.write_bytes(b'changed')
            self.assertNotEqual(signing.fingerprint(app), original)
            file.write_bytes(b'original')
            file.chmod(0o700)
            self.assertNotEqual(signing.fingerprint(app), original)
            if sys.platform == 'darwin':
                before = signing.fingerprint(app)
                subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.cs.TestFixture', 'signature-one', str(file)],
                               check=True, capture_output=True)
                self.assertNotEqual(signing.fingerprint(app), before)


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('zsh'), 'macOS build workflow required')
class StagedBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gewu-signing-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ['build_macos_app.sh', 'macos_signing.py', 'make_release.sh']:
            shutil.copy2(ROOT / 'scripts' / name, scripts / name)
        # This fixture tests atomic replacement, not framework/plugin fetching.
        # The real dependencies are checked in the standalone updater workflow.
        (scripts / 'macos_update_framework.py').write_text('# isolated packaging stub\n')
        (scripts / 'build_zotero_plugin.py').write_text(
            'import pathlib,sys\npathlib.Path(sys.argv[sys.argv.index("--output")+1]).write_bytes(b"plugin fixture")\n')
        self.installed = self.root / 'Gewu Insight.app'
        macos = self.installed / 'Contents/MacOS'
        macos.mkdir(parents=True)
        shutil.copyfile('/bin/echo', macos / 'Gewu Insight')
        (macos / 'Gewu Insight').chmod(0o755)
        (macos / 'Gewu Insight Server').write_text('#!/bin/zsh\nexit 0\n')
        (macos / 'Gewu Insight Server').chmod(0o755)
        resources = self.installed / 'Contents/Resources'
        resources.mkdir()
        (resources / 'PaperMonitor.icns').write_bytes(b'icon fixture')
        with (self.installed / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleIconFile': 'Icon', 'CFBundleShortVersionString': '1.0.0',
                          'CFBundleVersion': '1', 'LSMinimumSystemVersion': '14.0',
                          'CFBundleIdentifier': signing.BUNDLE_IDENTIFIER,
                          'CFBundleExecutable': 'Gewu Insight',
                          'CFBundlePackageType': 'APPL'}, stream)
        for target in [macos / 'Gewu Insight Server', self.installed]:
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(target)],
                           check=True, capture_output=True)
        package = self.root / 'paper_monitor'
        package.mkdir()
        (package / '__init__.py').write_text('__version__="1.0.0"\n__build__="1"\n')
        (package / 'Gewu_Insight_User_Guide.pdf').write_bytes(b'guide fixture')
        assets = self.root / 'assets/branding'
        assets.mkdir(parents=True)
        (assets / 'README.md').write_text('fixture provenance')
        (assets / 'GewuSealGlyphs.provenance.json').write_text('{}')
        for path in [assets / 'GewuSealGlyphs.png', assets / 'GewuAboutCalligraphy.png',
                     assets.parent / 'gewu-insight-app-icon.png']:
            path.write_bytes(b'icon fixture')
        for name in ['LICENSE', 'CONTRIBUTING.md', 'THIRD_PARTY_NOTICES.md']:
            (self.root / name).write_text('notice fixture')
        for name in ['GewuBrowserCaptureProbe.js', 'GewuBrowserLoginProbe.js', 'GewuBrowserNavigationProbe.js']:
            (scripts / name).write_text('// fixture')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.environment = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin',
                                GEWU_BUILD_PYTHON=sys.executable)
        self.environment.pop('GEWU_SIGNING_IDENTITY', None)
        self.environment.pop('GEWU_SIGNING_TEAM_ID', None)

    def executable(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o700)
        return path

    def build(self, *arguments):
        return subprocess.run(['/bin/zsh', str(self.root / 'scripts/build_macos_app.sh'), *arguments],
                              capture_output=True, text=True, env=self.environment, timeout=40)

    def compile_fixture(self):
        self.executable('xcrun', 'while [ "$1" != "-o" ]; do shift; done\n/bin/cp /bin/echo "$2"\n')
        self.executable('sips', 'exit 0\n')
        self.executable('iconutil', ': > "$4"\n')

    def test_default_build_without_certificate_installs_a_valid_adhoc_app(self):
        self.compile_fixture()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        signing.verify(self.installed)
        self.assertEqual(signing.signing_info(self.installed)['Signature'], 'adhoc')
        self.assertEqual(list(self.root.glob('.gewu-app-build.*')), [])

    def test_identical_rebuild_keeps_the_installed_bundle(self):
        self.compile_fixture()
        first = self.build()
        self.assertEqual(first.returncode, 0, first.stderr)
        original = signing.fingerprint(self.installed)
        inode = self.installed.stat().st_ino
        second = self.build()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('App content unchanged', second.stdout)
        self.assertEqual(signing.fingerprint(self.installed), original)
        self.assertEqual(self.installed.stat().st_ino, inode)

    def test_identical_code_with_invalid_finder_metadata_receives_verified_replacement(self):
        self.compile_fixture()
        first = self.build()
        self.assertEqual(first.returncode, 0, first.stderr)
        original = signing.fingerprint(self.installed)
        inode = self.installed.stat().st_ino
        subprocess.run(['/usr/bin/xattr', '-w', '-x', 'com.apple.FinderInfo',
                        '01' + '00' * 31, str(self.installed)], check=True, capture_output=True)
        with self.assertRaises(signing.SigningError):
            signing.verify(self.installed)
        second = self.build()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn('App content unchanged', second.stdout)
        self.assertNotEqual(self.installed.stat().st_ino, inode)
        signing.verify(self.installed)
        self.assertEqual(signing.fingerprint(self.installed), original)

    def test_default_release_without_certificate_verifies_the_extracted_app(self):
        self.compile_fixture()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = signing.fingerprint(self.installed)
        release = subprocess.run(['/bin/bash', str(self.root / 'scripts/make_release.sh'), 'local'],
                                 capture_output=True, text=True, env=self.environment, timeout=40)
        self.assertEqual(release.returncode, 0, release.stderr)
        extracted = self.root / 'recipient'
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(self.root / 'dist/GewuInsight-local.zip'),
                        str(extracted)], check=True, capture_output=True)
        signing.verify(extracted / 'GewuInsight-local/Gewu Insight.app', self.installed)
        self.assertEqual(signing.fingerprint(self.installed), original)

    def release_fixture(self, fail_extracted=False):
        source_script = self.installed / 'Contents/MacOS/Gewu Insight Server'
        subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.cs.TestFixture', 'fixture-signature',
                        str(source_script)], check=True, capture_output=True)
        shim = self.bin / 'release-python-shim'
        shim.write_text(f'''#!{sys.executable}
import importlib.util, os, sys
if len(sys.argv) > 2 and sys.argv[2] == 'verify':
    app = sys.argv[sys.argv.index('--app') + 1]
    spec = importlib.util.spec_from_file_location('signing', sys.argv[1])
    signing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signing)
    attrs = dict(signing.extended_attributes(signing.Path(app) / 'Contents/MacOS/Gewu Insight Server'))
    with open({str(self.root / 'release-trace')!r}, 'a') as stream:
        stream.write(app + '\\n')
    if attrs.get('com.apple.cs.TestFixture') != b'fixture-signature':
        sys.exit(17)
    if {fail_extracted!r} and '/extracted/' in app:
        sys.exit(19)
    sys.exit(0)
os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
''')
        shim.chmod(0o700)
        self.environment['GEWU_BUILD_PYTHON'] = str(shim)
        dist = self.root / 'dist'
        previous = dist / 'GewuInsight-test'
        previous.mkdir(parents=True)
        (previous / 'previous.txt').write_text('previous package')
        zip_path = dist / 'GewuInsight-test.zip'
        zip_path.write_bytes(b'previous ZIP')
        return previous, zip_path

    def test_release_preserves_launcher_signing_attributes_through_zip_extraction(self):
        previous, zip_path = self.release_fixture()
        original = signing.fingerprint(self.installed)
        result = subprocess.run(['/bin/bash', str(self.root / 'scripts/make_release.sh'), 'test'],
                                capture_output=True, text=True, env=self.environment, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = (self.root / 'release-trace').read_text().splitlines()
        self.assertEqual(len(trace), 3)
        self.assertIn('/extracted/', trace[-1])
        self.assertTrue(zip_path.read_bytes().startswith(b'PK'))
        self.assertFalse((previous / 'previous.txt').exists())
        self.assertEqual(signing.fingerprint(self.installed), original)
        self.assertEqual(list((self.root / 'dist').glob('.gewu-release.*')), [])

    def test_bad_extracted_signature_keeps_the_previous_release(self):
        previous, zip_path = self.release_fixture(fail_extracted=True)
        result = subprocess.run(['/bin/bash', str(self.root / 'scripts/make_release.sh'), 'test'],
                                capture_output=True, text=True, env=self.environment, timeout=40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('/extracted/', (self.root / 'release-trace').read_text().splitlines()[-1])
        self.assertEqual(zip_path.read_bytes(), b'previous ZIP')
        self.assertEqual((previous / 'previous.txt').read_text(), 'previous package')
        self.assertEqual(list((self.root / 'dist').glob('.gewu-release.*')), [])

    def test_zip_publication_failure_restores_both_previous_release_artifacts(self):
        previous, zip_path = self.release_fixture()
        self.executable('mv', '''case "$1" in
  */.gewu-release.*/GewuInsight-test.zip) exit 23 ;;
esac
exec /bin/mv "$@"
''')
        result = subprocess.run(['/bin/bash', str(self.root / 'scripts/make_release.sh'), 'test'],
                                capture_output=True, text=True, env=self.environment, timeout=40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(zip_path.read_bytes(), b'previous ZIP')
        self.assertEqual((previous / 'previous.txt').read_text(), 'previous package')
        self.assertEqual(list((self.root / 'dist').glob('.gewu-release.*')), [])

    def test_failed_compilation_leaves_installed_app_and_output_untouched(self):
        self.executable('xcrun', 'exit 42\n')
        original = signing.fingerprint(self.installed)
        output = self.root / 'QA.app'
        result = self.build('--development-adhoc', '--output', str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(signing.fingerprint(self.installed), original)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob('.gewu-app-build.*')), [])

    def test_post_install_verification_failure_restores_the_original_app(self):
        self.executable('xcrun', 'while [ "$1" != "-o" ]; do shift; done\nprintf compiled > "$2"\n')
        self.executable('sips', 'exit 0\n')
        self.executable('iconutil', ': > "$4"\n')
        self.executable('codesign', 'exit 0\n')
        shim = self.bin / 'python-shim'
        shim.write_text(f'''#!{sys.executable}
import os, subprocess, sys
if len(sys.argv) > 2 and sys.argv[2] == 'preflight':
    print('-')
    sys.exit(0)
if len(sys.argv) > 2 and sys.argv[2] == 'verify':
    app = sys.argv[sys.argv.index('--app') + 1]
    with open({str(self.root / 'verification-trace')!r}, 'a') as stream:
        stream.write(app + '\\n')
    sys.exit(0 if '.gewu-app-build.' in app else 9)
os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
''')
        shim.chmod(0o700)
        self.environment['GEWU_BUILD_PYTHON'] = str(shim)
        original = signing.fingerprint(self.installed)
        result = self.build()
        self.assertNotEqual(result.returncode, 0, result.stderr)
        trace = (self.root / 'verification-trace').read_text().splitlines()
        self.assertEqual(len(trace), 2)
        self.assertEqual(Path(trace[-1]).resolve(), self.installed.resolve())
        self.assertEqual(signing.fingerprint(self.installed), original)
        self.assertEqual(list(self.root.glob('.gewu-app-build.*')), [])


if __name__ == '__main__':
    unittest.main()
