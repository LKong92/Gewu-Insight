"""Exercise the real startup renderer with folders, not only paper fixtures."""
import re
import shutil
import subprocess
import unittest
from paper_monitor.ui_server import INDEX_HTML


def function(name):
    start = re.search(r'    (?:async )?function ' + name + r'\(', INDEX_HTML).start()
    return INDEX_HTML[start:INDEX_HTML.index('\n    }', start) + 6]


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LibraryDetailStartupTests(unittest.TestCase):
    def test_startup_no_selection_and_nested_folder_render_without_paper(self):
        script = '\n'.join(function(n) for n in ('renderLibraryDetail', 'escapeHtml')) + '''
const assert = require('node:assert/strict');
const root = {dataset:{metadataPaperId:'previous'},innerHTML:''};
const $ = () => root, state = {librarySelection:null};
const runtimeBrandedEmptyMarkup = text => text;
const runtimeEmptyBrandArtMarkup = () => '<div class="brand"></div>';
const libraryFolderById = id => ({name:id === 1 ? 'Library' : 'Nested Folder'});
const libraryChildFolders = id => id === 1 ? [{id:2}] : [];
const libraryFolderItems = id => id === 1 ? [] : [{id:3}];
const closeMetadataRefreshTooltip = () => {};
const metadataRefreshButtonMarkup = () => {throw Error('Folder must never read paper metadata');};
renderLibraryDetail();
assert.match(root.innerHTML,/Select a folder or paper/);
for (const id of [1,2]) {
 state.librarySelection = {type:'folder',id};
 renderLibraryDetail();
 assert.match(root.innerHTML,id === 1 ? /Library/ : /Nested Folder/);
 assert.match(root.innerHTML,id === 1 ? /1 folders · 0 items/ : /0 folders · 1 items/);
 assert.equal(root.dataset.metadataPaperId,undefined);
}
'''
        result = subprocess.run(['node','-'],input=script,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__ == '__main__':unittest.main()
