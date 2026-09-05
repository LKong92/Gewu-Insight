"""Product website routing; synthetic destinations, no browser profile or network."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from paper_monitor.ui_server import INDEX_HTML

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceWebLinkTests(unittest.TestCase):
    def run_js(self, script):
        if not shutil.which("node"):
            self.skipTest("Node.js required")
        result = subprocess.run([shutil.which("node"), "-"], input=script,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_audited_entry_points_have_no_server_side_safari_bypass(self):
        self.assertNotIn('/api/open-url', INDEX_HTML)
        self.assertNotIn('window.open(', INDEX_HTML)
        self.assertNotIn('openUrlExternally', INDEX_HTML)
        self.assertNotIn('Open publisher page in Safari', INDEX_HTML)
        for route in [
            'openWebsite(paper.url)', 'openWebsite(paper.google_scholar_url)',
            'openWebsite(author.url)', 'openWebsite(author.homepage_url)',
            'openWebsite(destination)', 'openLibraryWebsite(paper)',
            'openLibraryWebsiteURL(paper.google_scholar_url',
            'openLibraryWebsiteURL(url, "Opening preprint in Browser...")',
            'openWebsite("https://www.overleaf.com/project")',
        ]:
            self.assertIn(route, INDEX_HTML)
        profile = INDEX_HTML.split('async function openMyPublicationScholarProfile()', 1)[1].split('function scholarProfileInitials', 1)[0]
        self.assertIn('openWebsite(url)', profile)
        legacy = INDEX_HTML.split('function openInternalBrowser(', 1)[1].split('function closeInternalBrowser', 1)[0]
        self.assertIn('openWebsite(url)', legacy)
        self.assertNotIn('page-proxy', legacy)

    def test_cold_and_warm_browser_routing_preserve_source_and_existing_tabs(self):
        source = (ROOT / 'paper_monitor/browser_ui.js').read_text()
        functions = 'function setActive(' + source.split('function setActive(', 1)[1].split('async function edit(', 1)[0]
        self.run_js(r'''
const assert=require('node:assert/strict');
const global={open:(...args)=>external.push(args)}, external=[], commands=[];
const HOME='https://www.google.com/';
const state={mode:'library', libraryQuickLookOpen:false, librarySelectedId:4,
  authorMonitorSelectedId:7, selectedDate:'2026-09-06', selectedPaper:'example'};
const data={opened:false, active:false}, root={hidden:true};
let hasBridge=true;
const bridge=()=>hasBridge, native=p=>commands.push(p);
const closeContext=()=>{},closeSuggestions=()=>{},render=()=>{},message=()=>{},fail=e=>{throw e;};
const refresh=async()=>{}, layout=()=>native({action:'layout',active:data.active});
const elements={}, $=id=>elements[id] ||= {};
function setPrimaryView(view) { setActive(view==='browser'); }
''' + functions + r'''
const before={...state};
assert.equal(openURL('https://www.nature.com/articles/example.pdf'),'Browser');
assert.deepEqual(commands.filter(c=>c.action!=='layout'),[{action:'navigate',url:'https://www.nature.com/articles/example.pdf'}]);
assert.equal(commands[0].action,'layout'); assert.equal(commands[0].active,true);
assert.equal(state.mode,'browser');
for(const mode of ['library','my-publications','report','theme','author']) {
  state.mode=mode; setActive(false); commands.length=0;
  openURL('https://example.org/'+mode);
  assert.deepEqual(commands.filter(c=>c.action!=='layout'),[{action:'new-tab',url:'https://example.org/'+mode}]);
}
for(const key of Object.keys(before).filter(k=>k!=='mode')) assert.deepEqual(state[key],before[key]);
assert.equal(external.length,0);
commands.length=0;
for(const url of ['javascript:alert(1)','file:///tmp/a.pdf','data:text/html,hello','not a URL','https://u:p@example.org/'])
  assert.throws(()=>openURL(url));
assert.equal(commands.length,0);
hasBridge=false; state.mode='library';
assert.equal(openURL('https://example.org/fallback'),'browser tab');
assert.deepEqual(external,[['https://example.org/fallback','_blank','noopener,noreferrer']]);
assert.equal(state.mode,'library'); assert.equal(commands.length,0);
''')

    def test_delegated_dynamic_links_and_native_local_boundaries(self):
        functions = 'function wireWorkspaceWebsiteLinks(' + INDEX_HTML.split('function wireWorkspaceWebsiteLinks(', 1)[1].split('async function openLibraryWebsite(', 1)[0]
        self.run_js(r'''
const assert=require('node:assert/strict');
const opened=[], handlers={};
const openWebsite=url=>opened.push(url);
const window={location:{href:'http://127.0.0.1:8765/',origin:'http://127.0.0.1:8765'}};
const document={addEventListener:(name,fn,capture)=>{assert.equal(capture,true); handlers[name]=fn;}};
''' + functions + r'''
wireWorkspaceWebsiteLinks();
function click(href,{type='click',button=0,download=false,chrome=false,prevented=false,metaKey=false}={}) {
  const link={href,closest:()=>chrome,hasAttribute:()=>download};
  const event={type,button,metaKey,defaultPrevented:prevented,target:{closest:()=>link},
    preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;}};
  handlers[type](event); return event;
}
for(const url of ['https://example.org/citing','https://api.semanticscholar.org/paper',
 'https://example.org/paper.pdf','https://ui.adsabs.harvard.edu/',
 'https://pubmed.ncbi.nlm.nih.gov/1/','https://pmc.ncbi.nlm.nih.gov/articles/PMC1/',
 'https://example.org/note#section']) {
  const e=click(url); assert.ok(e.defaultPrevented&&e.stopped); assert.equal(opened.at(-1),url);
}
click('https://example.org/middle',{type:'auxclick',button:1});
click('https://example.org/cmd',{metaKey:true});
assert.equal(opened.length,9);
for(const href of ['http://127.0.0.1:8765/#section','http://127.0.0.1:8765/api/file?path=example',
 'blob:http://127.0.0.1:8765/example','file:///tmp/example.pdf','mailto:example@example.org'])
  assert.equal(click(href).defaultPrevented,false);
for(const options of [{download:true},{chrome:true},{button:2},{type:'auxclick',button:0},{prevented:true}])
  click('https://example.org/excluded',options);
assert.equal(opened.length,9);
''')

    def test_workspace_return_restores_viewports_without_reloading_or_stale_reentry(self):
        source = (ROOT / 'paper_monitor/browser_ui.js').read_text()
        functions = 'function setActive(' + source.split('function setActive(', 1)[1].split('async function edit(', 1)[0]
        capture = 'function captureBrowserWorkspaceReturn(' + INDEX_HTML.split('function captureBrowserWorkspaceReturn(', 1)[1].split('function setPrimaryView(', 1)[0]
        self.run_js(r'''
const assert=require('node:assert/strict');
const global={}, HOME='https://www.google.com/', commands=[];
const state={mode:'library',libraryTab:'library',librarySelectedId:17,selectedDate:'2026-09-06',
  authorMonitorSelectedId:9,reportSelectedPaperId:'paper',libraryQuickLookOpen:false};
const scroller={isConnected:true,scrollTop:0,scrollLeft:0};
const focus={isConnected:true,focus(options){assert.equal(options.preventScroll,true);this.restored=true;}};
const document={activeElement:focus,querySelectorAll:()=>[scroller]};
const data={opened:false,active:false}, root={hidden:true};
let dialog=false, hasBridge=true, returnedView='';
const bridge=()=>hasBridge, native=p=>commands.push(p), visibleDialog=()=>dialog;
const closeContext=()=>{},closeSuggestions=()=>{},render=()=>{},message=()=>{},fail=e=>{throw e;};
const refresh=async()=>{}, layout=()=>{};
const $=()=>({});
function setPrimaryView(view, options={}) {
  setActive(view==='browser');
  if(view!=='browser') {returnedView=view; assert.equal(options.preserveViewport,true);}
}
''' + capture + functions + r'''
for(const view of ['library','my-publications','report','theme','author']) {
  state.mode=view==='my-publications'?'library':view;
  state.libraryTab=view==='my-publications'?view:'workspace-2';
  const before={...state}; scroller.scrollTop=471;scroller.scrollLeft=93;
  openURL('https://example.org/'+view);
  const checkpoint=data.workspaceReturn;
  openURL('https://example.org/another');
  assert.equal(data.workspaceReturn,checkpoint,'Browser-internal navigation cannot replace the source');
  scroller.scrollTop=0;scroller.scrollLeft=0;commands.length=0;
  dialog=true;assert.equal(returnToWorkspace(),false);dialog=false;
  assert.equal(returnToWorkspace(),true);assert.equal(returnedView,view);
  assert.deepEqual(state,before);assert.equal(scroller.scrollTop,471);assert.equal(scroller.scrollLeft,93);
  assert.ok(focus.restored);assert.deepEqual(commands,[],'return cannot navigate/reload/close a webpage');
  assert.equal(returnToWorkspace(),false,'one-shot return');
  open();assert.equal(returnToWorkspace(),false,'manual Browser entry has no stale source');
  setActive(false);
}
state.mode='author';openURL('https://example.org/a');setActive(false);
state.mode='library';open();assert.equal(returnToWorkspace(),false,'manually leaving invalidates origin');
setActive(false);hasBridge=false;global.open=()=>{};state.mode='library';
openURL('https://example.org/external');assert.equal(data.workspaceReturn,null);
''')

    def test_browser_detour_keeps_the_current_monitor_dom(self):
        primary = INDEX_HTML.split('function setPrimaryView(', 1)[1].split('function wireWindowDragRegion(', 1)[0]
        self.assertIn('view !== "browser" &&', primary)
        self.assertIn('switchingToMonitor && !options.preserveViewport', primary)
        native = (ROOT / 'scripts/GewuBrowserController.m').read_text()
        self.assertIn('if ([self handleWorkspaceReturnKeyEvent:event]) return nil;', native)

    def test_real_button_bindings_use_the_shared_router(self):
        bindings = [line for line in INDEX_HTML.splitlines()
                    if 'root.querySelector(' in line and '.addEventListener("click"' in line
                    and re.search(r'=> open(?:Website|LibraryWebsite)', line)]
        self.assertEqual(len(bindings), 6)
        self.run_js(r'''
const assert=require('node:assert/strict');
const calls=[], callbacks=[];
const paper={url:'https://example.org/paper',google_scholar_url:'https://scholar.google.com/scholar?q=example'};
const root={querySelector:()=>({addEventListener:(type,fn)=>callbacks.push(fn)})};
const openWebsite=url=>calls.push(url),openLibraryWebsite=p=>openWebsite(p.url),openLibraryWebsiteURL=openWebsite;
''' + '\n'.join(bindings) + r'''
callbacks.forEach(fn=>fn());
assert.deepEqual(calls,[paper.url,paper.google_scholar_url,paper.url,paper.google_scholar_url,paper.url,paper.google_scholar_url]);
''')

    def test_native_workspace_does_not_share_privileged_configuration(self):
        source = (ROOT / 'scripts/PaperMonitorApp.m').read_text()
        self.assertIn('self.webView.navigationDelegate = self;', source)
        fallback = source.split('- (void)openWorkspaceWebsiteRequest:', 1)[1].split('@end', 1)[0]
        self.assertIn('GewuWorkspaceWebsiteRequest', fallback)
        self.assertIn('window.openWebsite', fallback)
        self.assertIn('WKNavigationActionPolicyCancel', fallback)
        workspace_popup = fallback.split('if (webView == self.webView) {', 1)[1].split('return nil;', 1)[0]
        self.assertNotIn('openURL:', workspace_popup)
        self.assertNotIn('configuration:configuration', workspace_popup)
        self.assertNotIn('loadRequest:', workspace_popup)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS compiler required')
    def test_actual_app_navigation_delegates_with_inert_views(self):
        with tempfile.TemporaryDirectory(prefix='gewu-workspace-link-test-') as directory:
            executable = Path(directory) / 'routing-test'
            build = subprocess.run([
                'xcrun', 'clang', '-fobjc-arc', '-framework', 'Cocoa', '-framework', 'Quartz',
                '-framework', 'WebKit', '-framework', 'ImageIO', '-framework', 'UniformTypeIdentifiers',
                '-I', str(ROOT / 'scripts'), str(ROOT / 'tests/workspace_navigation_probe.m'),
                str(ROOT / 'scripts/GewuBrowserController.m'), str(ROOT / 'scripts/GewuBrowserFavicons.m'),
                str(ROOT / 'scripts/GewuBrowserAutoFill.m'), '-o', str(executable),
            ], capture_output=True, text=True, timeout=90,
                env=dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(directory) / 'modules')))
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('checks passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
