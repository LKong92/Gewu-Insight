const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function host(isWin = true) {
  const context = vm.createContext({Zotero: {isWin}, Error, URL});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../integrations/zotero/monitor.js'), 'utf8'), context);
  return context.GewuMonitor;
}

test('Windows health refreshes its local token before each authenticated retry', async () => {
  const monitor = host();
  const tab = {};
  let generation = 0;
  monitor.refreshWindowsEndpoint = async active => { active.token = String(++generation); };
  monitor.request = async active => active.token === '1' ? {ok: true} : {ok: true, database_uuid: 'fixture', database_path: 'C:/Fixture/data/paper_monitor.sqlite'};
  await assert.rejects(monitor.workspaceHealth(tab, 'C:/Fixture'), error => error.unreachable === true);
  const health = await monitor.workspaceHealth(tab, 'C:/Fixture');
  assert.equal(health.database_uuid, 'fixture');
  assert.equal(tab.token, '2');
});

test('a Windows health failure does not replace the selected database', async () => {
  const monitor = host();
  const tab = {folder: 'C:/Chosen Fixture'};
  monitor.refreshWindowsEndpoint = async () => {};
  monitor.request = async () => { throw new Error('network unavailable'); };
  await assert.rejects(monitor.workspaceHealth(tab, tab.folder), /network unavailable/);
  assert.equal(tab.folder, 'C:/Chosen Fixture');
});

test('Mac health keeps the existing request and validation path', async () => {
  const monitor = host(false);
  const original = {ok: true};
  monitor.request = async () => original;
  assert.equal(await monitor.workspaceHealth({}, '/Fixture'), original);
});
