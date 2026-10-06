"""Directory grants and stateless enumeration against isolated SQLite only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ai_folders, ai_service
from paper_monitor.ai_store import APIError, create_connection, set_folder_access
from paper_monitor.storage import Storage


class AIFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = Storage(Path(self.temp.name) / 'test.sqlite')
        self.addCleanup(self.storage.close)
        s = self.storage
        s.set_setting('ai_access_enabled', 'true')
        self.ai = s.create_library_root_folder(name='AI')['id']
        self.private = s.create_library_root_folder(name='Private workspace')['id']
        self.project = s.create_library_folder(parent_id=self.ai, name='Project')['id']
        self.empty = s.create_library_folder(parent_id=self.project, name='Empty')['id']
        self.hidden = s.create_library_folder(parent_id=self.ai, name='Hidden sibling')['id']
        self.other = s.create_library_folder(parent_id=self.private, name='Project')['id']
        self.recycle = s.create_library_folder(parent_id=1, name='Recycle')['id']
        self.keys = {}
        for pid in ('one', 'two', 'secret', 'publication', 'recycled'):
            s.upsert_paper({'paper_id': pid, 'title': 'Synthetic ' + pid, 'journal': 'Fixture',
                            'source': 'fixture', 'raw': {}})
            self.keys[pid] = s.get_paper(pid)['storage_key']
        self.first = s.add_library_item(paper_id='one', folder_id=self.ai)['id']
        self.second = s.add_library_item(paper_id='one', folder_id=self.project)['id']
        s.add_library_item(paper_id='two', folder_id=self.project)
        s.add_library_item(paper_id='secret', folder_id=self.other)
        # Legacy entries with no trash flag still must not expose Recycle.
        s.add_library_item(paper_id='recycled', folder_id=self.recycle)
        s.add_my_publication(paper_id='publication')
        self.auth = self.grant()

    def grant(self, selection=None, scopes=None):
        result = create_connection(self.storage, {'name': 'Directory fixture',
            'selection': selection or {'kind': 'saved'},
            'scopes': ['papers:read', 'folders:read'] if scopes is None else scopes})
        self.connection = result['connection']['id']
        return 'Bearer ' + result['token']

    def call(self, op='list_folders', args=None, auth=None):
        return ai_service.execute(self.storage, auth or self.auth, op, args or {})

    def fails(self, status, op, args=None, auth=None):
        with self.assertRaises(APIError) as error:
            self.call(op, args, auth)
        self.assertEqual(error.exception.status, status)
        return error.exception.code

    def all_pages(self, op, args=None, auth=None):
        args, values = dict(args or {}), []
        while True:
            page = self.call(op, args, auth)
            values.extend(page['folders' if op == 'list_folders' else 'memberships'])
            if page['next_cursor'] is None:
                return values
            args['cursor'] = page['next_cursor']

    def test_roots_paths_repeated_names_empty_and_no_filesystem(self):
        roots = self.all_pages('list_folders', {'limit': 1})
        self.assertEqual([f['folder_id'] for f in roots], [1, self.ai, self.private])
        self.assertEqual([f['kind'] for f in roots], ['library', 'space', 'space'])
        project = self.call(args={'parent_id': self.ai})['folders'][0]
        other = self.call(args={'parent_id': self.private})['folders'][0]
        self.assertEqual(project['name'], other['name'])
        self.assertNotEqual(project['folder_id'], other['folder_id'])
        self.assertEqual(project['logical_path'], 'AI / Project')
        self.assertEqual(other['logical_path'], 'Private workspace / Project')
        self.assertEqual([p['folder_id'] for p in project['path']], [self.ai, self.project])
        empty = self.call(args={'parent_id': self.project})['folders'][0]
        self.assertEqual(empty['direct_paper_count'], 0)
        self.assertEqual(self.call('list_folder_papers', {'folder_id': self.empty})['memberships'], [])
        self.assertNotIn(self.temp.name, json.dumps(roots))
        self.assertEqual(self.call(args={'parent_id': 1})['folders'], [])
        self.fails(404, 'list_folders', {'parent_id': self.recycle})

    def test_direct_recursive_memberships_and_canonical_key_dedup(self):
        direct = self.call('list_folder_papers', {'folder_id': self.ai})
        self.assertEqual([m['membership_id'] for m in direct['memberships']], [self.first])
        recursive = self.all_pages('list_folder_papers', {'folder_id': self.ai, 'recursive': True, 'limit': 1})
        self.assertEqual(len(recursive), 3)
        self.assertEqual({m['gewu_key'] for m in recursive}, {self.keys['one'], self.keys['two']})
        self.assertEqual({m['folder_id'] for m in recursive}, {self.ai, self.project})
        self.assertEqual(len({m['membership_id'] for m in recursive}), 3)
        self.assertEqual(self.call('get_paper', {'gewu_key': recursive[0]['gewu_key']})['title'], 'Synthetic one')
        self.assertEqual(direct['folder']['direct_paper_count'], 1)
        # My Publications-only papers remain get/search accessible, not invented folders.
        self.assertEqual(self.call('get_paper', {'gewu_key': self.keys['publication']})['title'], 'Synthetic publication')
        self.fails(404, 'get_paper', {'gewu_key': self.keys['recycled']})

    def test_folder_grant_never_leaks_parents_siblings_or_other_placements(self):
        auth = self.grant({'kind': 'folder', 'folder_id': self.project})
        roots = self.call(auth=auth)['folders']
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]['parent_id'], None)
        self.assertEqual(roots[0]['logical_path'], 'Project')
        self.assertTrue(roots[0]['path_is_relative_to_grant'])
        self.assertEqual(roots[0]['path'], [{'folder_id': self.project, 'name': 'Project'}])
        result = self.call('list_folder_papers', {'folder_id': self.project, 'recursive': True}, auth)
        self.assertEqual({m['folder_id'] for m in result['memberships']}, {self.project})
        for fid in (1, self.ai, self.hidden, self.private, self.other, 999999):
            self.assertEqual(self.fails(404, 'list_folders', {'parent_id': fid}, auth), 'folder_unavailable')
            self.fails(404, 'list_folder_papers', {'folder_id': fid, 'recursive': True}, auth)
        self.assertEqual(len(self.call(args={'parent_id': self.project}, auth=auth)['folders']), 1)
        # Unrelated changes must not invalidate cursors/reveal private activity.
        revision = result['revision']
        self.storage.rename_library_folder(folder_id=self.private, name='Changed private name')
        self.storage.add_library_item(paper_id='secret', folder_id=self.hidden)
        self.assertEqual(self.call(auth=auth)['revision'], revision)

    def test_specific_keys_only_reveal_necessary_paths_and_filtered_counts(self):
        auth = self.grant({'kind': 'papers', 'keys': [self.keys['one']]})
        roots = self.call(auth=auth)
        self.assertEqual([f['folder_id'] for f in roots['folders']], [self.ai])
        self.assertEqual(roots['folders'][0]['child_folder_count'], 1)
        child = self.call(args={'parent_id': self.ai}, auth=auth)['folders'][0]
        self.assertEqual(child['direct_paper_count'], 1)
        self.assertEqual(child['child_folder_count'], 0)
        entries = self.all_pages('list_folder_papers', {'folder_id': self.ai, 'recursive': True, 'limit': 1}, auth)
        self.assertEqual(len(entries), 2)
        for fid in (self.empty, self.hidden, self.private, self.other):
            self.fails(404, 'list_folders', {'parent_id': fid}, auth)
        revision = roots['revision']
        self.storage.add_library_item(paper_id='secret', folder_id=self.project)
        self.storage.create_library_folder(parent_id=self.ai, name='Another secret empty folder')
        self.assertEqual(self.call(auth=auth)['revision'], revision)
        self.fails(404, 'get_paper', {'gewu_key': self.keys['secret']}, auth)

    def test_old_connection_opt_in_and_disable_preserve_token_other_scopes_and_selection(self):
        auth = self.grant(scopes=['papers:read', 'files:read'])
        row = dict(self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?', (self.connection,)).fetchone())
        self.fails(403, 'list_folders', auth=auth)
        set_folder_access(self.storage, self.connection, True)
        self.assertTrue(self.call(auth=auth)['folders'])
        current = dict(self.storage.conn.execute('SELECT * FROM ai_connections WHERE id=?', (self.connection,)).fetchone())
        self.assertEqual({k: v for k, v in row.items() if k not in ('scopes_json', 'last_used_at')},
                         {k: v for k, v in current.items() if k not in ('scopes_json', 'last_used_at')})
        self.assertEqual(set(json.loads(current['scopes_json'])), {'papers:read', 'files:read', 'folders:read'})
        set_folder_access(self.storage, self.connection, False)
        self.fails(403, 'list_folders', auth=auth)
        self.assertEqual(self.call('get_paper', {'gewu_key': self.keys['one']}, auth)['title'], 'Synthetic one')

    def test_cursor_binds_scope_operation_and_options_with_no_shared_directory(self):
        roots = self.call(args={'limit': 1})
        papers = self.call('list_folder_papers', {'folder_id': self.ai, 'recursive': True, 'limit': 1})
        self.call(args={'parent_id': self.private})
        second = self.call(args={'limit': 1, 'cursor': roots['next_cursor']})
        self.assertEqual(second['folders'][0]['folder_id'], self.ai)
        self.fails(400, 'list_folder_papers', {'folder_id': self.ai, 'cursor': roots['next_cursor']})
        self.fails(400, 'list_folder_papers', {'folder_id': self.ai, 'cursor': papers['next_cursor']})
        other_auth = self.grant()
        self.fails(409, 'list_folders', {'cursor': roots['next_cursor']}, other_auth)
        for args in ({'cursor': '!'}, {'cursor': 'a' * 1025}, {'parent_id': True}, {'parent_id': '../AI'},
                     {'path': '/etc'}, {'limit': 101}, {'revision': 'x'}, {'parent_id': -1}):
            self.fails(400, 'list_folders', args)
        self.fails(400, 'list_folder_papers')
        self.fails(400, 'list_folder_papers', {'folder_id': self.ai, 'recursive': 'false'})

    def test_walk_detects_renames_moves_deletion_and_membership_change(self):
        roots = self.call(args={'limit': 1})
        self.storage.rename_library_folder(folder_id=self.project, name='Renamed')
        self.assertEqual(self.fails(409, 'list_folders', {'cursor': roots['next_cursor']}), 'collection_changed')
        self.fails(409, 'list_folder_papers', {'folder_id': self.ai, 'revision': roots['revision']})
        fresh = self.call()
        self.storage.move_library_folder(folder_id=self.project, parent_id=self.private)
        self.fails(409, 'list_folders', {'revision': fresh['revision']})
        # Identity survives a move, and folder grants keep the same anchor.
        auth = self.grant({'kind': 'folder', 'folder_id': self.project})
        self.assertEqual(self.call(auth=auth)['folders'][0]['folder_id'], self.project)
        fresh = self.call(auth=auth)
        self.storage.add_library_item(paper_id='secret', folder_id=self.project)
        self.fails(409, 'list_folders', {'revision': fresh['revision']}, auth)
        self.storage.conn.execute('DELETE FROM library_folders WHERE id=?', (self.project,))
        self.storage.conn.commit()
        self.fails(404, 'list_folders', {'parent_id': self.project}, auth)
        self.assertEqual(self.call(auth=auth)['folders'], [])

    def test_trashed_ancestors_and_alias_keys(self):
        alias = 'gw_0123456789abcdef'
        self.storage.conn.execute("INSERT INTO paper_aliases(alias,paper_id,created_at) VALUES(?,?,'fixture')", (alias, 'one'))
        self.storage.conn.commit()
        auth = self.grant({'kind': 'papers', 'keys': [alias]})
        entries = self.call('list_folder_papers', {'folder_id': self.ai, 'recursive': True}, auth)['memberships']
        self.assertEqual({m['gewu_key'] for m in entries}, {self.keys['one']})
        self.storage.conn.execute("UPDATE library_folders SET trashed_at='now' WHERE id=?", (self.ai,))
        self.storage.conn.commit()
        self.assertEqual(self.call(auth=auth)['folders'], [])
        self.fails(404, 'list_folder_papers', {'folder_id': self.project}, auth)

    def test_concurrent_revoke_scope_removal_and_move_withhold_result(self):
        original = ai_folders.list_collection
        for mutation, status in [('move', 409), ('scope', 403), ('revoke', 401)]:
            with self.subTest(mutation=mutation):
                self.auth = self.grant()
                def change_after_listing(*args):
                    result = original(*args)
                    if mutation == 'move':
                        self.storage.move_library_folder(folder_id=self.project, parent_id=1)
                    elif mutation == 'scope':
                        set_folder_access(self.storage, self.connection, False)
                    else:
                        self.storage.conn.execute("UPDATE ai_connections SET revoked_at='now' WHERE id=?", (self.connection,))
                        self.storage.conn.commit()
                    return result
                with patch.object(ai_folders, 'list_collection', side_effect=change_after_listing):
                    self.fails(status, 'list_folders')

    def test_metadata_refresh_does_not_break_membership_pagination(self):
        first = self.call('list_folder_papers', {'folder_id': self.ai, 'recursive': True, 'limit': 1})
        self.storage.conn.execute("UPDATE papers SET title='Updated title' WHERE paper_id='one'")
        self.storage.conn.commit()
        second = self.call('list_folder_papers', {'folder_id': self.ai, 'recursive': True,
                                                'cursor': first['next_cursor'], 'revision': first['revision']})
        self.assertEqual(second['memberships'][0]['paper']['title'], 'Updated title')

    def test_large_enumeration_has_no_page_cap_or_missing_empty_directories(self):
        for index in range(205):
            folder = self.storage.create_library_folder(parent_id=self.project, name='Branch ' + str(index))
            self.storage.add_library_item(paper_id='one', folder_id=folder['id'])
        folders = self.all_pages('list_folders', {'parent_id': self.project, 'limit': 100})
        self.assertEqual(len(folders), 206)
        members = self.all_pages('list_folder_papers', {'folder_id': self.project, 'recursive': True, 'limit': 100})
        self.assertEqual(len(members), 207)
        self.assertEqual(len({m['membership_id'] for m in members}), 207)

    def test_expired_disabled_and_revoked_connections_are_denied(self):
        self.storage.set_setting('ai_access_enabled', 'false')
        self.fails(403, 'list_folders')
        self.storage.set_setting('ai_access_enabled', 'true')
        self.storage.conn.execute("UPDATE ai_connections SET expires_at='2000-01-01' WHERE id=?", (self.connection,))
        self.storage.conn.commit()
        self.fails(401, 'list_folders')
        with self.assertRaises(APIError):
            set_folder_access(self.storage, self.connection, True)


if __name__ == '__main__':
    unittest.main()
