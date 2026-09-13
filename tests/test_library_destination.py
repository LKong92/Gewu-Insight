"""Default destinations with temporary SQLite; no network or user file writes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_monitor import ui_server as ui
from paper_monitor.library_destination import (
    DEFAULT_ADD_FOLDER_SETTING, active_folders, default_add_destination, save_default_add_folder,
)
from paper_monitor.storage import Storage


class LibraryDestinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        self.storage = Storage(self.path)
        self.addCleanup(self.storage.close)
        self.handler = object.__new__(ui.PaperMonitorUiHandler)
        self.handler.configured_db_path = self.path
        self.handler.send_json = Mock()
        self.handler.send_error_json = Mock()
        for name in ('LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT'):
            p = patch.object(ui, name, Path(self.tmp.name) / name)
            p.start(); self.addCleanup(p.stop)

    def test_read_default_is_pure_and_reset_does_not_move_existing_papers(self):
        s = self.storage
        before = s.conn.total_changes
        self.assertEqual(default_add_destination(s), {'folder_id':None, 'title':'Library / unsorted', 'fallback':False})
        self.assertEqual(s.conn.total_changes, before)
        folder = s.create_library_folder(parent_id=1, name='Inbox')
        s.upsert_paper({'paper_id':'existing','title':'Existing paper','source':'fixture','journal':'Fixture'})
        s.add_library_item(paper_id='existing', folder_id=folder['id'])
        rows = [tuple(r) for r in s.conn.execute('SELECT * FROM library_items')]
        version = s.conn.execute('PRAGMA user_version').fetchone()[0]
        self.handler.handle_set_library_destination_settings({'folder_id':folder['id']})
        reopened = Storage(self.path)
        try:
            self.assertEqual(default_add_destination(reopened)['folder_id'], folder['id'])
        finally:
            reopened.close()
        self.handler.handle_set_library_destination_settings({'folder_id':0})
        self.assertEqual(default_add_destination(s)['title'], 'Library / unsorted')
        self.assertEqual(rows, [tuple(r) for r in s.conn.execute('SELECT * FROM library_items')])
        self.assertEqual(version, s.conn.execute('PRAGMA user_version').fetchone()[0])

    def test_stable_folder_id_survives_rename_move_and_falls_back_if_trashed_or_deleted(self):
        s = self.storage
        parent = s.create_library_folder(parent_id=1, name='Reading')
        child = s.create_library_folder(parent_id=parent['id'], name='Inbox')
        space = s.create_library_root_folder(name='Research Space')
        save_default_add_folder(s, child['id'])
        s.rename_library_folder(folder_id=parent['id'], name='Papers')
        self.assertEqual(default_add_destination(s)['title'], 'Library / Papers / Inbox')
        s.move_library_folder(folder_id=parent['id'], parent_id=space['id'])
        self.assertEqual(default_add_destination(s)['title'], 'Research Space / Papers / Inbox')
        recycle = ui.ensure_library_special_folders(s)['recycle']
        s.move_library_folder_to_trash(folder_id=parent['id'], recycle_folder_id=recycle['id'])
        self.assertTrue(default_add_destination(s)['fallback'])
        self.assertEqual(default_add_destination(s)['title'], 'Library / unsorted')
        self.assertNotIn(child['id'], {f['id'] for f in active_folders(s)})
        s.recover_library_folder(folder_id=parent['id'], fallback_parent_id=1)
        self.assertEqual(default_add_destination(s)['folder_id'], child['id'])
        s.conn.execute('DELETE FROM library_folders WHERE id=?', (child['id'],)); s.conn.commit()
        self.assertTrue(default_add_destination(s)['fallback'])

    def test_invalid_settings_rejected_without_overwriting_valid_choice(self):
        s = self.storage
        folder = s.create_library_folder(parent_id=1, name='Inbox')
        recycle = ui.ensure_library_special_folders(s)['recycle']
        nested = s.create_library_folder(parent_id=recycle['id'], name='Nested')
        save_default_add_folder(s, folder['id'])
        for value in (None, True, False, -1, 1.5, '1', 'file:///tmp', [], {}, 999999, recycle['id'], nested['id']):
            self.handler.handle_set_library_destination_settings({'folder_id':value})
            self.assertEqual(self.handler.send_error_json.call_args.args[0], 400)
            self.assertEqual(default_add_destination(s)['folder_id'], folder['id'])
        s.set_setting(DEFAULT_ADD_FOLDER_SETTING, '<invalid>')
        self.assertTrue(default_add_destination(s)['fallback'])

    def test_shared_monitor_api_default_explicit_override_and_legacy_unsorted(self):
        s = self.storage
        folder = s.create_library_folder(parent_id=1, name='Inbox')
        other = s.create_library_root_folder(name='Other Space')
        save_default_add_folder(s, folder['id'])
        for source in ('journal', 'subject', 'author'):
            s.upsert_paper({'paper_id':source,'title':source+' fixture','source':'fixture','journal':'Fixture'})
            self.handler.handle_add_library_item({'paper_id':source, 'snapshot':False})
            data = self.handler.send_json.call_args.args[0]
            self.assertEqual(data['item']['folder_id'], folder['id'])
        self.handler.handle_add_library_item({'paper_id':'journal','folder_id':other['id'],'snapshot':False})
        self.assertEqual(self.handler.send_json.call_args.args[0]['item']['folder_id'],other['id'])
        self.handler.handle_add_library_item({'paper_id':'author','unsorted':True,'snapshot':False})
        self.assertEqual(self.handler.send_json.call_args.args[0]['folder']['name'], 'unsorted')
        self.assertEqual(ui.library_add_targets_snapshot(s)['default_add_folder_id'],folder['id'])

    def test_default_rechecked_after_folder_disappears_before_add(self):
        s = self.storage
        folder = s.create_library_folder(parent_id=1, name='Inbox')
        save_default_add_folder(s, folder['id'])
        recycle = ui.ensure_library_special_folders(s)['recycle']
        s.move_library_folder_to_trash(folder_id=folder['id'], recycle_folder_id=recycle['id'])
        s.upsert_paper({'paper_id':'new','title':'New fixture','source':'fixture','journal':'Fixture'})
        self.handler.handle_add_library_item({'paper_id':'new','snapshot':False})
        self.assertEqual(self.handler.send_json.call_args.args[0]['folder']['name'],'unsorted')
        count=s.conn.execute('SELECT count(*) FROM library_items').fetchone()[0]
        self.handler.handle_add_library_item({'paper_id':'new','folder_id':folder['id'],'snapshot':False})
        self.assertEqual(self.handler.send_error_json.call_args.args[0],400)
        self.assertEqual(s.conn.execute('SELECT count(*) FROM library_items').fetchone()[0],count)
