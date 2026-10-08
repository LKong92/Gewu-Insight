"""Windows private-session creation and legacy failed-start recovery."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import local_access as access


@unittest.skipUnless(sys.platform == 'win32', 'Windows file security')
class WindowsLocalAccessTests(unittest.TestCase):
    def setUp(self):
        import win32security
        self.security = win32security
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / '研究 data base'
        self.root.mkdir()
        self.db = self.root / 'paper_monitor.sqlite'
        self.path = self.root / '.gewu-workspace-token'
        self.user = access._windows_user()

    def assert_private(self):
        s = self.security
        descriptor = s.GetNamedSecurityInfo(str(self.path), s.SE_FILE_OBJECT,
            s.OWNER_SECURITY_INFORMATION | s.DACL_SECURITY_INFORMATION)
        self.assertEqual(descriptor.GetSecurityDescriptorOwner(), self.user)
        self.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED)
        acl = descriptor.GetSecurityDescriptorDacl()
        self.assertEqual(acl.GetAceCount(), 1)
        self.assertEqual(acl.GetAce(0)[2], self.user)
        self.assertEqual(self.path.stat().st_nlink, 1)

    def test_explicit_user_owner_private_creation_and_restart(self):
        first = access.WorkspaceAccess(self.db)
        self.assert_private()
        second = access.WorkspaceAccess(self.db)
        self.assertNotEqual(first.token, second.token)
        self.assertFalse(second.matches(first.token))
        self.assertEqual(self.path.read_text(), second.token)
        self.assert_private()
        self.assertEqual(len(first.token), 64)

    def test_existing_valid_token_rotated_without_reading_its_owner(self):
        self.path.write_text('a' * 64)
        with patch.object(self.security, 'GetSecurityInfo', side_effect=AssertionError('Owner must not be queried')):
            self.assertNotEqual(access.WorkspaceAccess(self.db).token, 'a' * 64)
        self.assert_private()

    def test_empty_current_user_residue_recovers_without_database_changes(self):
        self.db.write_bytes(b'database sentinel')
        self.path.touch()
        first = access.WorkspaceAccess(self.db)
        self.assertEqual(len(first.token), 64)
        self.assertNotEqual(first.token, access.WorkspaceAccess(self.db).token)
        self.assertEqual(self.db.read_bytes(), b'database sentinel')
        self.assert_private()

    def test_invalid_nonempty_session_is_renewed(self):
        self.path.write_text('invalid')
        renewed = access.WorkspaceAccess(self.db)
        self.assertEqual(len(renewed.token), 64)
        self.assert_private()

    def test_hardlinked_empty_or_valid_file_is_not_touched(self):
        target = self.root / 'keep'
        for content in ('', 'a' * 64):
            with self.subTest(empty=not content):
                target.write_text(content)
                os.link(target, self.path)
                try:
                    with self.assertRaises(PermissionError):
                        access.WorkspaceAccess(self.db)
                    self.assertEqual(target.read_text(), content)
                finally:
                    self.path.unlink()

    def test_failed_private_creation_never_publishes_or_leaves_empty_file(self):
        with patch.object(access.os, 'fsync', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                access.WorkspaceAccess(self.db)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_publish_preserves_previous_session(self):
        self.path.write_text('a' * 64)
        with patch.object(access.os, 'replace', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                access.WorkspaceAccess(self.db)
        self.assertEqual(self.path.read_text(), 'a' * 64)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_existing_file_and_directory_permissions_do_not_query_owner(self):
        with patch.object(self.security, 'GetSecurityInfo', side_effect=AssertionError('Owner must not be queried')), \
                patch.object(self.security, 'GetNamedSecurityInfo', side_effect=AssertionError('Owner must not be queried')):
            with self.path.open('w') as stream:
                access.protect_token_file(stream, self.path)
            directory = self.root / 'staging'
            directory.mkdir()
            access.protect_directory(directory)
        self.assert_private()

    def test_symlink_target_untouched(self):
        target = self.root / 'keep'
        target.write_text('sentinel')
        try:
            self.path.symlink_to(target)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Symlink privilege unavailable')
            raise
        with self.assertRaises(PermissionError):
            access.WorkspaceAccess(self.db)
        self.assertEqual(target.read_text(), 'sentinel')


if __name__ == '__main__':
    unittest.main()
