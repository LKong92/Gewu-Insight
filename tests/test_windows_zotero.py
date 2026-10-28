"""Windows companion setup and service discovery, using disposable files only."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from paper_monitor import zotero_integration as integration, windows_service, windows_database


class WindowsZoteroTests(unittest.TestCase):
    def test_windows_profile_and_bundled_plugin_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'Program Files' / 'Gewu Insight for Zotero.xpi'
            package.parent.mkdir(); package.write_bytes(b'fixture')
            with patch.object(integration.sys, 'platform', 'win32'), patch.dict(os.environ, {
                'APPDATA': str(root / 'Roaming'), 'GEWU_APP_PATH': str(package.parent / 'Gewu Insight.exe')}):
                self.assertEqual(integration.package_path(), package)
                self.assertEqual(integration.profile_directory(), root / 'Roaming/Zotero/Zotero')

    def test_windows_launch_uses_zotero_url_handler_without_a_shell(self):
        # Zotero's command-line handler only ingests links supplied with -url.
        # The same route carries workspace handoff, bundled updates and imports.
        with patch.object(integration.sys, 'platform', 'win32'), \
             patch.object(integration, 'zotero_application', return_value=Path('C:/Program Files/Zotero/zotero.exe')), \
             patch.object(integration.subprocess, 'Popen') as launch:
            for action in ('open', 'update', 'import'):
                with self.subTest(action=action):
                    url = 'zotero://gewu-insight/' + action + '?request=test-request'
                    integration.launch_zotero(url)
                    self.assertEqual(launch.call_args.args[0],
                                     [str(Path('C:/Program Files/Zotero/zotero.exe')), '-url', url])
                    self.assertNotIn('shell', launch.call_args.kwargs)
            integration.launch_zotero()
            self.assertEqual(launch.call_args.args[0], [str(Path('C:/Program Files/Zotero/zotero.exe'))])

    def test_windows_setup_writes_private_request_but_no_workspace_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = []
            def private_stream(path):
                created.append(path)
                return path.open('x', encoding='ascii')
            with patch.object(integration.sys, 'platform', 'win32'), \
                 patch('paper_monitor.local_access._create_windows_token_stream', side_effect=private_stream), \
                 patch.object(integration, 'database_identity', return_value='fixture-identity'), \
                 patch.object(integration, 'package_info', return_value=(root / 'plugin.xpi', {})), \
                 patch.object(integration, 'launch_zotero') as launch:
                result = integration.configure(root / 'Database', 'http://127.0.0.1:12345', 'open', root / 'Support')
                record = json.loads((root / 'Support/zotero-connection.json').read_text())
            self.assertEqual(len(created), 1)
            self.assertFalse(created[0].exists())
            self.assertEqual(record['request_id'], result['request_id'])
            self.assertEqual(record['database_uuid'], 'fixture-identity')
            self.assertNotIn('token', record)
            self.assertFalse((root / 'Database').exists())
            self.assertTrue(launch.call_args.args[0].startswith('zotero://gewu-insight/open?request='))

    def test_live_service_requires_matching_authenticated_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'data').mkdir()
            (root / 'data/.gewu-api-url').write_text('http://127.0.0.1:12345')
            (root / 'data/.gewu-workspace-token').write_text('a' * 64)
            response = {'ok': True, 'database_uuid': 'identity', 'database_path': str(root / 'data/paper_monitor.sqlite'), 'integrations': {'zotero': 1}}
            with patch.object(windows_service, 'build_opener') as factory:
                factory.return_value.open.side_effect = lambda *a, **k: io.BytesIO(json.dumps(response).encode())
                result = windows_service.live_status(root, 'identity')
                self.assertEqual(result['origin'], 'http://127.0.0.1:12345')
                request = factory.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('X-gewu-workspace'), 'a' * 64)
                self.assertIsNone(windows_service.live_status(root, 'other'))
                response['database_path'] = str(root / 'other/data/paper_monitor.sqlite')
                self.assertIsNone(windows_service.live_status(root, 'identity'))
                del response['database_path']
                self.assertIsNone(windows_service.live_status(root, 'identity'))

    def test_malformed_health_never_counts_as_a_live_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'data').mkdir()
            (root / 'data/.gewu-api-url').write_text('http://127.0.0.1:12345')
            (root / 'data/.gewu-workspace-token').write_text('a' * 64)
            with patch.object(windows_service, 'build_opener') as factory:
                for body in [[], None, {'ok': True, 'integrations': None}]:
                    factory.return_value.open.return_value = io.BytesIO(json.dumps(body).encode())
                    self.assertIsNone(windows_service.live_status(root, 'identity'))

    def test_untrusted_endpoint_never_receives_workspace_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'data').mkdir()
            (root / 'data/.gewu-workspace-token').write_text('a' * 64)
            with patch.object(windows_service, 'build_opener') as factory:
                for address in ['https://example.org', 'http://127.0.0.1:1234/secret', 'http://user@127.0.0.1:1234', 'http://127.0.0.1:1234?query=1']:
                    (root / 'data/.gewu-api-url').write_text(address)
                    self.assertIsNone(windows_service.live_status(root, 'identity'))
                factory.assert_not_called()

    def test_attaching_live_service_never_attempts_second_database_lease(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(windows_database, 'check_database', return_value=(1, 'identity')), \
             patch.object(windows_service, 'live_status', return_value={'ok': True}), \
             patch.object(windows_database, 'FileLease') as lease, \
             patch.object(windows_database, 'save_locator') as locator:
            result = windows_database.prepare(Path(directory), expected_identity='identity')
            self.assertEqual(result['identity'], 'identity')
            lease.assert_not_called(); locator.assert_not_called()
