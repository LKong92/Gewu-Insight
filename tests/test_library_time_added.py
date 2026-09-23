"""Placement times retain their meaning across views and file organization."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage


class LibraryTimeAddedTests(unittest.TestCase):
    def test_existing_placement_time_survives_metadata_rename_move_and_duplicate_add(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = Storage(Path(temp) / 'library.sqlite')
            self.addCleanup(storage.close)
            folder = storage.create_library_folder(parent_id=1, name='Folder')
            space = ui.add_library_workspace_tab(storage, name='Space')
            paper = {'paper_id': 'paper', 'title': 'Original', 'journal': 'Test Journal', 'publication_date': '2026-01-01'}
            storage.upsert_paper(paper)
            with patch('paper_monitor.storage.now_iso', return_value='2026-09-20T02:00:00Z'):
                item = storage.add_library_item(paper_id='paper', folder_id=folder['id'])
            with patch('paper_monitor.storage.now_iso', return_value='2026-09-21T02:00:00Z'):
                second = storage.add_library_item(paper_id='paper', folder_id=space['root_folder_id'])
                repeated = storage.add_library_item(paper_id='paper', folder_id=folder['id'])
                storage.upsert_paper(dict(paper, title='Updated'))
                storage.rename_library_item(item_id=item['id'], name='Renamed')
                moved = storage.move_library_item(item_id=item['id'], folder_id=1)
            self.assertEqual(repeated['created_at'], item['created_at'])
            self.assertEqual(moved['created_at'], item['created_at'])
            self.assertNotEqual(second['created_at'], item['created_at'])
            self.assertEqual(ui.library_item_to_api(moved, storage.get_paper('paper'))['created_at'], item['created_at'])
            self.assertEqual(ui.library_item_to_api(second, storage.get_paper('paper'))['created_at'], second['created_at'])
            self.assertEqual(ui.library_folder_to_api(folder)['created_at'], folder['created_at'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_actual_sort_handles_timezones_missing_values_ties_folders_and_list_view(self):
        names = ['normalizeLibraryTableSort', 'libraryTableSortValue', 'libraryAddedTimeMs',
                 'libraryAddedTimeText', 'sortLibraryEntries', 'compareLibraryEntries', 'libraryEntrySortName']
        source = '\n'.join('function ' + name + ui.INDEX_HTML.split('function ' + name, 1)[1].split('\n    function ', 1)[0] for name in names)
        harness = r'''
const assert=require('node:assert/strict');
const state={libraryTableSort:{key:'added',direction:'asc'},librarySortMode:'name'};
let table=true;
const items=new Map([
 [1,{id:1,display_name:'Alpha',created_at:'2026-09-21T10:00:00+08:00'}],
 [2,{id:2,display_name:'Beta',created_at:'2026-09-20T23:00:00-04:00'}],
 [3,{id:3,display_name:'Gamma',created_at:'2026-09-21T01:30:00Z'}],
 [4,{id:4,display_name:'Missing',paper:{first_seen_at:'2026-01-01'}}],
 [5,{id:5,display_name:'Invalid',created_at:'not-a-date'}],
 [6,{id:6,display_name:'Epoch',created_at:'1970-01-01T00:00:00Z'}],
 [7,{id:7,display_name:'Tie',created_at:'2026-09-21T02:00:00Z'}],
 [8,{id:8,display_name:'Before',created_at:'2026-09-21T01:59:59.999Z'}]
]);
const folders=new Map([
 [11,{id:11,name:'Later folder',created_at:'2026-09-23T01:00:00Z'}],
 [12,{id:12,name:'Earlier folder',created_at:'2026-09-20T01:00:00Z'}]
]);
const entries=[...items.keys()].map(id=>({type:'item',id})).concat([...folders.keys()].map(id=>({type:'folder',id})));
function libraryItemById(id){return items.get(id);}
function libraryFolderById(id){return folders.get(id);}
function libraryTableViewActive(){return table;}
function libraryFolderSpecialRank(){return 0;}
function libraryPaperDisplayName(){return '';}
function libraryPaperTableTitle(item){return item.display_name;}
function normalizeLibrarySortMode(value){return value;}
''' + source + r'''
const unchanged=JSON.stringify(entries);
assert.deepEqual(sortLibraryEntries(entries).map(e=>e.id),[12,11,6,3,8,1,7,2,5,4]);
state.libraryTableSort.direction='desc';
assert.deepEqual(sortLibraryEntries(entries).map(e=>e.id),[11,12,2,1,7,8,3,6,5,4]);
assert.equal(JSON.stringify(entries),unchanged);
assert.equal(libraryAddedTimeText(items.get(1)),'2026-09-21 10:00');
assert.equal(libraryAddedTimeText(items.get(2)),'2026-09-21 11:00');
assert.equal(libraryAddedTimeText(items.get(6)),'1970-01-01 08:00');
assert.equal(libraryAddedTimeText(items.get(4)),'—');
assert.equal(libraryAddedTimeText(items.get(5)),'—');
table=false;
assert.deepEqual(sortLibraryEntries(entries).filter(e=>e.type==='item').map(e=>e.id),[1,8,2,6,3,5,4,7]);
assert.deepEqual(normalizeLibraryTableSort({key:'added',direction:'desc'}),{key:'added',direction:'desc'});
assert.equal(normalizeLibraryTableSort({key:'invalid',direction:'desc'}),null);
'''
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'added.js'
            script.write_text(harness)
            result = subprocess.run([shutil.which('node'), str(script)], capture_output=True, text=True,
                                    env={**os.environ, 'TZ': 'Asia/Shanghai'}, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
