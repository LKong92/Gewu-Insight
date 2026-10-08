"""Deletion confirmation choices must gate the existing mutation workflows."""
import unittest

from tests import test_paper_files_interactions as interactions


class WindowsDeleteDialogTests(unittest.TestCase):
    run_js = interactions.PaperFilesInteractionTests.run_js

    def test_windows_recycle_summary_omits_internal_paths_and_records(self):
        self.run_js(['confirmRecycleDeletion', 'confirmPaperFileDeletion'], r'''
let options;
global.window = {gewuConfirmDeletion: async value => { options = value; return false; },
  confirm: () => { throw Error('Browser confirm must not run'); }};
const preview = {requires_confirmation:true,metadata_paper_count:2,shortcut_only_paper_count:1,
  local_copy_paths:['C:\\private\\Library\\secret.pdf'],folder_paths:['C:\\private\\folder'],orphan_local_copy_paths:['secret-orphan']};
assert.equal(await confirmRecycleDeletion('3 selected Recycle items', preview), false);
assert.match(options.detail, /2 papers will be permanently removed/);
assert.match(options.detail, /Windows Recycle Bin/);
assert.match(options.detail, /still used elsewhere/);
assert.doesNotMatch(JSON.stringify(options), /private|secret|metadata|source\/resource|managed/i);
await confirmRecycleDeletion('all items in Recycle', preview);
assert.equal(options.button, 'Delete');
assert.equal(options.message, 'Delete all items in Recycle?');
await confirmRecycleDeletion('one entry', {requires_confirmation:true,shortcut_only_paper_count:1});
assert.doesNotMatch(options.detail, /permanently|will move/);
options = null;
assert.equal(await confirmRecycleDeletion('nothing', {}), true);
assert.equal(options, null);
await confirmPaperFileDeletion('notes.txt');
assert.equal(options.title, 'Delete File');
assert.match(options.message, /notes.txt/);
assert.doesNotMatch(options.detail, /managed|private/);
''')

    def test_paper_file_cancel_never_starts_a_delete(self):
        self.run_js(['deleteSelectedLibraryPaperResource'], r'''
global.state = {libraryPaperResourceSelection:{paperId:'fixture',resourceId:9},deletingPaperResources:new Set()};
global.confirmPaperFileDeletion = async () => false;
global.deletePaperFile = () => { throw Error('Unexpected deletion'); };
const before = JSON.stringify(state.libraryPaperResourceSelection);
assert.equal(await deleteSelectedLibraryPaperResource({id:9,display_name:'notes.txt'}), true);
assert.equal(state.deletingPaperResources.size, 0);
assert.equal(JSON.stringify(state.libraryPaperResourceSelection), before);
''')

    def test_cancel_keeps_single_batch_and_empty_recycle_unchanged(self):
        self.run_js(['deleteLibraryEntry','deleteSelectedLibraryEntries','deleteAllLibraryRecycle'], r'''
global.window = {gewuConfirmDeletion:()=>{}};
global.libraryFolderById = id => ({id,name:'Fixture folder'});
global.libraryItemById = id => ({id,title:'Fixture paper'});
global.libraryEntryIsInRecycle = () => true;
global.previewRecycleDeletion = async () => ({requires_confirmation:true});
global.confirmRecycleDeletion = async () => false;
global.libraryRangeSelectionEntries = () => [{type:'item',id:1},{type:'folder',id:2}];
global.libraryRecycleFolderId = () => 5;
global.withLibraryActivityStatus = () => { throw Error('Mutation started after Cancel'); };
await deleteLibraryEntry('item',1);
await deleteSelectedLibraryEntries();
await deleteAllLibraryRecycle(5);
''')


if __name__ == '__main__':
    unittest.main()
