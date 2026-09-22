/* Opt-in settings only. No polling or AI requests while this dialog is closed. */
(() => {
  let backdrop, snapshot, busy = false, generation = 0, selectedFolder = 0, secret = null, previousFocus;
  const writePermissions = [
    ['spaces:create', 'Create Spaces'], ['folders:create', 'Create folders'],
    ['papers:import', 'Import papers with AI-supplied metadata'], ['files:import', 'Import standalone files'],
    ['files:add', 'Add Paper Files'], ['metadata:write', 'Fill missing metadata supplied by AI'],
    ['folders:move', 'Move folders'], ['folders:rename', 'Rename folders and Spaces'],
    ['files:move', 'Move files and change Paper Files ownership'], ['files:rename', 'Rename files'],
    ['papers:resolve', 'Resolve an existing paper separately (never during import)']
  ];
  let newWriteControls;
  const writeEditors = new Map();
  const writeValue = value => JSON.stringify({scopes: [...value.scopes].sort(),
    write_folder_ids: [...value.write_folder_ids].sort((a, b) => a - b)});
  const byId = id => document.getElementById(id);
  const visible = () => backdrop?.classList.contains('open');
  const status = (message, error = false) => {
    byId('aiAccessStatus').textContent = message;
    byId('aiAccessStatus').className = 'citation-settings-status' + (error ? ' err' : '');
  };
  function clearSecret() {
    secret = null;
    byId('aiToken').value = '';
    byId('aiMcpConfig').value = '';
    byId('aiCreated').hidden = true;
  }
  function close() {
    if (busy) return;
    generation++;
    clearSecret();
    window.closeLibraryAddMenus?.();
    backdrop.classList.remove('open');
    backdrop.setAttribute('aria-hidden', 'true');
    previousFocus?.focus?.();
  }
  async function request(payload) {
    const response = await fetch('/api/settings/ai-access', payload ? {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    } : {});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'AI Access is unavailable. Please retry.');
    return data;
  }
  function appendText(parent, tag, text, className = '') {
    const node = document.createElement(tag);
    node.textContent = text;
    node.className = className;
    parent.appendChild(node);
    return node;
  }
  function writeControls(parent, connection = {}, onChange = () => {}) {
    const field = appendText(parent, 'fieldset', '', 'ai-write-controls');
    appendText(field, 'legend', 'Optional write access');
    const boxes = writePermissions.map(([scope, title]) => {
      const label = appendText(field, 'label', '');
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
      checkbox.checked = (connection.scopes || []).includes(scope);
      checkbox.dataset.scope = scope; label.appendChild(checkbox); appendText(label, 'span', title);
      checkbox.addEventListener('change', onChange);
      return checkbox;
    });
    appendText(field, 'p', 'Imports require metadata supplied by the AI and never run Resolve. Move and rename permissions preserve file contents and update local storage. All affected locations must be writable.', 'ai-muted');
    appendText(field, 'p', 'Writable collections', 'ai-write-heading');
    appendText(field, 'p', 'Click to select or deselect. Blue selections include all subfolders. Choose operations above, then save below.', 'ai-muted');
    const choices = appendText(field, 'div', '', 'ai-write-collections');
    choices.setAttribute('role', 'group');
    choices.setAttribute('aria-label', 'Writable collections' + (connection.name ? ' for ' + connection.name : ''));
    let selectedIds = new Set(connection.write_folder_ids || []);
    appendText(field, 'p', 'Unselected collections grant no write access. Existing read permissions stay unchanged. Selected collections are also readable. Create Spaces grants access to each new Space this connection creates.', 'ai-muted');
    const refreshFolders = folders => {
      const parents = new Map(folders.map(folder => [folder.id, folder.parent_id]));
      const belongsTo = (id, root) => {
        const seen = new Set();
        while (id != null && !seen.has(id)) {
          if (id === root) return true;
          seen.add(id); id = parents.get(id);
        }
        return false;
      };
      choices.replaceChildren();
      const roots = folders.filter(folder => folder.parent_id === null);
      roots.sort((a, b) => (a.id === 1 ? -1 : b.id === 1 ? 1 : a.name.localeCompare(b.name)));
      for (const root of roots) {
        const label = appendText(choices, 'label', '', 'ai-write-destination');
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
        checkbox.setAttribute('aria-label', root.name);
        label.appendChild(checkbox);
        appendText(label, 'span', root.name);
        const detail = appendText(label, 'small', '');
        const update = () => {
          checkbox.checked = selectedIds.has(root.id);
          checkbox.indeterminate = !checkbox.checked && [...selectedIds].some(id => belongsTo(id, root.id));
          label.dataset.state = checkbox.checked ? 'selected' : checkbox.indeterminate ? 'partial' : 'unselected';
          detail.textContent = checkbox.checked ? 'All subfolders' : checkbox.indeterminate ? 'Some subfolders only' : '';
          label.title = checkbox.indeterminate ? 'Earlier folder permissions are preserved. Select this collection to include all subfolders, then save.' : '';
        };
        checkbox.onchange = () => {
          const selected = checkbox.checked;
          selectedIds = new Set([...selectedIds].filter(id => !belongsTo(id, root.id)));
          if (selected) selectedIds.add(root.id);
          update(); onChange();
        };
        update();
      }
    };
    refreshFolders(snapshot?.folders || []);
    return {refreshFolders, read: () => ({scopes: boxes.filter(b => b.checked).map(b => b.dataset.scope),
      write_folder_ids: [...selectedIds]})};
  }
  function render(data, savedConnectionId = null) {
    const previous = new Map([...writeEditors].map(([id, view]) => [id, {
      open: view.editor.open, draft: view.controls.read(), dirty: view.dirty, message: view.feedback.textContent,
      error: view.error
    }]));
    writeEditors.clear();
    const {token, mcp_config, ...state} = data;
    snapshot = state;
    newWriteControls?.refreshFolders(data.folders);
    window.setGewuAIAccessEnabled?.(data.enabled);
    byId('aiAccessEnabled').checked = data.enabled;
    byId('aiAccessState').textContent = data.enabled ? 'Enabled for the active connections below.' : 'Disabled. All AI connections are paused.';
    const list = byId('aiConnections');
    list.replaceChildren();
    const connections = data.connections.filter(connection => !connection.revoked_at);
    if (secret && !connections.some(connection => connection.id === secret.connectionId)) clearSecret();
    if (!connections.length) appendText(list, 'p', 'No AI connections. Create a new connection to get started.', 'ai-muted');
    for (const connection of connections) {
      const row = appendText(list, 'div', '', 'ai-connection');
      const text = appendText(row, 'div', '');
      appendText(text, 'strong', connection.name);
      const selection = connection.selection;
      const range = selection.kind === 'saved' ? 'Library, Spaces and My Publications' : selection.kind === 'papers' ? `${selection.keys.length} selected papers` :
        data.folders.find(f => f.id === selection.folder_id)?.path || 'Unavailable folder';
      const permissions = ['Metadata', ...(connection.scopes.includes('folders:read') ? ['Directory browsing'] : []), ...(connection.scopes.includes('files:read') ? ['File contents'] : []), ...(connection.scopes.includes('analysis:write') ? ['Add analyses'] : [])];
      appendText(text, 'p', range + ' · ' + permissions.concat(writePermissions.filter(([scope]) => connection.scopes.includes(scope)).map(([,label]) => label)).join(', '), 'ai-muted');
      const expired = Date.parse(connection.expires_at) <= Date.now();
      appendText(text, 'small', expired ? 'Expired' : `Expires ${new Date(connection.expires_at).toLocaleDateString()}`);
      const folderLabel = appendText(text, 'label', '', 'ai-folder-access');
      const folderToggle = document.createElement('input');
      folderToggle.type = 'checkbox';
      folderToggle.checked = connection.scopes.includes('folders:read');
      folderToggle.setAttribute('aria-label', `Allow directory browsing for ${connection.name}`);
      folderLabel.appendChild(folderToggle);
      appendText(folderLabel, 'span', 'Allow directory browsing');
      folderToggle.addEventListener('change', () => mutate({action: 'folder_access', connection_id: connection.id, allowed: folderToggle.checked},
        folderToggle.checked ? 'Directory browsing allowed. Reconnect your AI client to refresh its tools.' : 'Directory browsing disabled.'));
      const old = previous.get(connection.id);
      const editor = appendText(text, 'details', '', 'ai-write-editor');
      editor.open = old?.open || false;
      const summary = appendText(editor, 'summary', 'Edit write permissions');
      const badge = appendText(summary, 'span', '', 'ai-write-badge');
      const baseline = writeValue({scopes: connection.scopes.filter(scope => writePermissions.some(([key]) => key === scope)),
        write_folder_ids: connection.write_folder_ids || []});
      const draft = old?.dirty && connection.id !== savedConnectionId ? {...connection, ...old.draft} : connection;
      const view = {editor, badge, dirty: false, error: false};
      const controls = writeControls(editor, draft, () => {
        view.error = false;
        updateWriteFeedback(view, baseline);
      });
      view.controls = controls;
      const save = appendText(editor, 'button', 'Save Write Access', 'smallbtn'); save.type = 'button';
      const feedback = appendText(editor, 'p', '', 'ai-write-feedback');
      feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
      view.feedback = feedback;
      updateWriteFeedback(view, baseline);
      if (old?.dirty && old.error && connection.id !== savedConnectionId) {
        view.error = true; badge.textContent = 'Not saved'; feedback.textContent = old.message;
        badge.dataset.state = 'unsaved';
        feedback.classList.add('err');
      }
      writeEditors.set(connection.id, view);
      save.onclick = () => mutate({action: 'write_access', connection_id: connection.id, ...controls.read()},
        'Write access saved. Reconnect your AI client to refresh its tools.');
      const revoke = appendText(row, 'button', 'Revoke', 'smallbtn');
      revoke.type = 'button';
      revoke.addEventListener('click', () => mutate({action: 'revoke', connection_id: connection.id}, 'Connection revoked.'));
    }
    const activity = byId('aiActivity');
    activity.replaceChildren();
    byId('aiActivityTitle').textContent = `Recent Activity (${data.activity.length})`;
    if (!data.activity.length) appendText(activity, 'p', 'No API activity yet.', 'ai-muted');
    for (const event of data.activity) {
      const row = appendText(activity, 'div', '', 'ai-activity-row');
      appendText(row, 'p', [event.name || 'Connection', event.operation, event.outcome].join(' · '));
      appendText(row, 'p', [new Date(event.created_at).toLocaleString(), event.gewu_key].filter(Boolean).join(' · '), 'ai-muted');
    }
  }
  function updateWriteFeedback(view, baseline) {
    view.dirty = writeValue(view.controls.read()) !== baseline;
    view.badge.textContent = view.dirty ? 'Unsaved changes' : 'Saved';
    view.badge.dataset.state = view.dirty ? 'unsaved' : 'saved';
    view.feedback.dataset.state = view.dirty ? 'unsaved' : 'saved';
    view.feedback.classList.remove('err');
    view.feedback.textContent = view.dirty ? 'Changes are not saved yet. Click Save Write Access to apply them.' :
      'Saved. These selections stay saved when you collapse this panel, close Settings or restart Gewu Insight.';
  }
  async function mutate(payload, message) {
    if (busy) return;
    generation++;
    busy = true;
    backdrop.setAttribute('aria-busy', 'true');
    backdrop.querySelectorAll('button,input,select,textarea').forEach(el => { el.disabled = true; });
    status('Saving...');
    const writeId = payload.action === 'write_access' ? payload.connection_id : null;
    const pending = writeEditors.get(writeId);
    if (pending) { pending.badge.textContent = 'Saving…'; pending.badge.dataset.state = 'unsaved'; pending.feedback.textContent = 'Saving…'; }
    try {
      const data = await request(payload);
      render(data, writeId);
      if (writeId !== null) {
        writeEditors.get(writeId).feedback.textContent = 'Saved. You can collapse this panel; your selections are kept. Reconnect your AI client to refresh its tools.';
      }
      if (data.token) {
        secret = {token: data.token, config: data.mcp_config, connectionId: data.connection.id};
        byId('aiToken').value = data.token;
        byId('aiMcpConfig').value = JSON.stringify(data.mcp_config, null, 2);
        byId('aiCreated').hidden = false;
        byId('aiNewConnection').open = false;
        byId('aiName').value = '';
      }
      status(message);
    } catch (error) {
      if (snapshot) render(snapshot);
      const failed = writeEditors.get(writeId);
      if (failed) {
        failed.error = true; failed.badge.textContent = 'Not saved';
        failed.badge.dataset.state = 'unsaved';
        failed.feedback.textContent = 'Not saved. Your changes are still here. ' + error.message;
        failed.feedback.classList.add('err');
      }
      status(error.message, true);
    } finally {
      busy = false;
      backdrop.setAttribute('aria-busy', 'false');
      backdrop.querySelectorAll('button,input,select,textarea').forEach(el => { el.disabled = false; });
    }
  }
  function createDialog() {
    backdrop = document.createElement('div');
    backdrop.id = 'aiAccessBackdrop';
    backdrop.className = 'settings-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    backdrop.innerHTML = `<section class="settings-modal preferences-modal ai-access-modal" role="dialog" aria-modal="true" aria-labelledby="aiAccessTitle" tabindex="-1">
      <div class="settings-modal-head"><div><h2 id="aiAccessTitle">AI Access</h2><p>Choose which papers and files an AI connection can use.</p></div>
        <button class="settings-modal-close" id="aiClose" type="button" aria-label="Close AI Access">×</button></div>
      <div class="settings-modal-body">
        <label class="ai-enable"><input id="aiAccessEnabled" type="checkbox"> Enable AI access</label><p class="ai-muted" id="aiAccessState"></p>
        <p class="ai-muted">Your normal use of Gewu Insight is unchanged. Connections run only when an AI client uses them. An AI client may send authorized content to its model provider.</p>
        <details id="aiNewConnection"><summary>New Connection</summary><form id="aiConnectionForm">
          <label>Connection name<input id="aiName" maxlength="80" placeholder="Research assistant" required autocomplete="off"></label>
          <label>Accessible papers<select id="aiSelection"><option value="saved">Library, Spaces and My Publications</option><option value="folder">One folder and its subfolders</option><option value="papers">Specific Gewu Keys</option></select></label>
          <div id="aiFolderControl" class="library-add-control" hidden><button id="aiChooseFolder" data-action="add-library" class="smallbtn" type="button" aria-haspopup="dialog">Choose Folder ▸</button><div class="library-add-menu" data-role="library-add-menu" aria-hidden="true"></div></div>
          <label id="aiKeysLabel" hidden>Gewu Keys<textarea id="aiKeys" rows="3" placeholder="gw_0123456789, gw_abcdef0123"></textarea></label>
          <fieldset><legend>Permissions</legend><p>Read article metadata and file names</p>
            <label><input id="aiReadFolders" type="checkbox"> Browse authorized directories and paper memberships</label>
            <label><input id="aiReadFiles" type="checkbox"> Read PDF, attachment and note contents</label>
            <label><input id="aiWriteAnalysis" type="checkbox"> Add new Markdown analyses to Paper Files</label>
            <p class="ai-muted">These permissions only read files or append analyses. Additional write operations are opt-in below.</p></fieldset>
          <div id="aiNewWriteControls"></div>
          <label>Expires after<select id="aiExpiry"><option value="7">7 days</option><option value="30" selected>30 days</option><option value="90">90 days</option><option value="365">1 year</option></select></label>
          <button class="smallbtn" type="submit">Create Connection</button></form></details>
        <div id="aiCreated" hidden><h3>Connect your AI client</h3><p>This token is shown only now. Save the configuration in your AI client's MCP settings, not in a chat message.</p>
          <label>API token<input id="aiToken" type="password" readonly autocomplete="off"></label>
          <button id="aiCopyToken" class="smallbtn" type="button">Copy Token</button>
          <button id="aiCopyMcp" class="smallbtn" type="button">Copy MCP Configuration</button>
          <details><summary>Configuration</summary><textarea id="aiMcpConfig" readonly rows="9" aria-label="MCP connection configuration"></textarea></details>
        </div>
        <p id="aiAccessStatus" class="citation-settings-status" role="status" aria-live="polite"></p>
        <h3>Connections</h3><p class="ai-muted">Directory browsing reveals folder names and paper placements within the selected collection. For specific Gewu Keys, only their containing folders and necessary parent paths are visible. Existing tokens and other permissions stay unchanged.</p><div id="aiConnections"></div>
        <section class="ai-activity-section" aria-labelledby="aiActivityTitle">
          <h3 id="aiActivityTitle">Recent Activity</h3>
          <p class="ai-muted" id="aiActivityHint">Latest requests first · up to 50 shown</p>
          <div id="aiActivity" role="region" aria-labelledby="aiActivityTitle" aria-describedby="aiActivityHint" tabindex="0"></div>
        </section>
        <button id="aiRefresh" class="smallbtn" type="button">Refresh</button>
      </div></section>`;
    document.body.appendChild(backdrop);
    newWriteControls = writeControls(byId("aiNewWriteControls"));
    byId('aiClose').onclick = close;
    byId('aiRefresh').onclick = refresh;
    byId('aiAccessEnabled').onchange = event => mutate({action: 'enable', enabled: event.target.checked}, event.target.checked ? 'AI access enabled.' : 'AI access disabled.');
    byId('aiSelection').onchange = () => {
      byId('aiFolderControl').hidden = byId('aiSelection').value !== 'folder';
      byId('aiKeysLabel').hidden = byId('aiSelection').value !== 'papers';
    };
    byId('aiChooseFolder').onclick = event => {
      event.preventDefault(); event.stopPropagation();
      if (typeof window.openLibraryAddMenu !== 'function') { status('The folder picker is unavailable. Reopen Gewu Insight.', true); return; }
      window.openLibraryAddMenu(byId('aiFolderControl'), '', byId('aiChooseFolder'), null, {
        portalRoot: backdrop, selectedFolderId: selectedFolder, confirmLabel: 'Choose Folder',
        onSelect: choice => {
          selectedFolder = Number(choice.folderId);
          byId('aiChooseFolder').textContent = choice.path || 'Selected Folder';
        }
      }).catch(error => status(error.message, true));
    };
    byId('aiConnectionForm').onsubmit = event => {
      event.preventDefault();
      if (busy) return;
      const kind = byId('aiSelection').value;
      const selection = kind === 'folder' ? {kind, folder_id: selectedFolder} : kind === 'papers' ? {kind, keys: byId('aiKeys').value.split(/[\s,;]+/).filter(Boolean)} : {kind};
      if (kind === 'folder' && !selectedFolder) { status('Choose a folder first.', true); return; }
      const scopes = ['papers:read'];
      if (byId('aiReadFolders').checked) scopes.push('folders:read');
      if (byId('aiReadFiles').checked) scopes.push('files:read');
      if (byId('aiWriteAnalysis').checked) scopes.push('analysis:write');
      const writes = newWriteControls.read();
      scopes.push(...writes.scopes);
      mutate({action: 'create', name: byId('aiName').value, selection, scopes, write_folder_ids: writes.write_folder_ids, expires_days: Number(byId('aiExpiry').value)}, 'Connection created. Copy its configuration before closing this window.');
    };
    async function copy(value) {
      try {
        await window.copyTextToClipboard(value);
        status('Copied. Store this in your AI client configuration.');
      } catch (_) { status('Copy failed. Select and copy the configuration text below.', true); }
    }
    byId('aiCopyToken').onclick = () => secret && copy(secret.token);
    byId('aiCopyMcp').onclick = () => secret && copy(JSON.stringify(secret.config, null, 2));
    backdrop.onclick = event => { if (event.target === backdrop) close(); };
    document.addEventListener('keydown', event => {
      if (!visible()) return;
      const picker = document.querySelector('.library-add-menu.open');
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopImmediatePropagation();
        if (picker) window.closeLibraryAddMenus?.(); else close();
      } else if (event.key === 'Tab' && !picker) {
        const controls = [...backdrop.querySelectorAll('button,input,select,textarea,summary,[tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }, true);
  }
  async function refresh() {
    if (busy) return;
    const current = ++generation;
    status('Loading connections...');
    try {
      const data = await request();
      if (current !== generation || !visible()) return;
      render(data); status('');
    } catch (error) { if (current === generation && visible()) status(error.message, true); }
  }
  window.openAIAccessSettings = () => {
    if (busy) return;
    if (!backdrop) createDialog();
    previousFocus = document.activeElement;
    backdrop.classList.add('open'); backdrop.setAttribute('aria-hidden', 'false');
    byId('aiClose').focus(); refresh();
  };
})();
