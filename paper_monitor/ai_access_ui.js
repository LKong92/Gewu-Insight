/* Opt-in settings only. No polling or AI requests while this dialog is closed. */
(() => {
  let backdrop, snapshot, busy = false, generation = 0, selectedFolder = 0, secret = null, previousFocus;
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
  function render(data) {
    const {token, mcp_config, ...state} = data;
    snapshot = state;
    window.setGewuAIAccessEnabled?.(data.enabled);
    byId('aiAccessEnabled').checked = data.enabled;
    byId('aiAccessState').textContent = data.enabled ? 'Enabled for the active connections below.' : 'Disabled. All AI connections are paused.';
    const list = byId('aiConnections');
    list.replaceChildren();
    if (!data.connections.length) appendText(list, 'p', 'No AI connections yet.', 'ai-muted');
    for (const connection of data.connections) {
      const row = appendText(list, 'div', '', 'ai-connection');
      const text = appendText(row, 'div', '');
      appendText(text, 'strong', connection.name);
      const selection = connection.selection;
      const range = selection.kind === 'saved' ? 'Library, Spaces and My Publications' : selection.kind === 'papers' ? `${selection.keys.length} selected papers` :
        data.folders.find(f => f.id === selection.folder_id)?.path || 'Unavailable folder';
      const permissions = ['Metadata', ...(connection.scopes.includes('files:read') ? ['File contents'] : []), ...(connection.scopes.includes('analysis:write') ? ['Add analyses'] : [])];
      appendText(text, 'p', range + ' · ' + permissions.join(', '), 'ai-muted');
      const expired = Date.parse(connection.expires_at) <= Date.now();
      appendText(text, 'small', connection.revoked_at ? 'Revoked' : expired ? 'Expired' : `Expires ${new Date(connection.expires_at).toLocaleDateString()}`);
      if (!connection.revoked_at) {
        const revoke = appendText(row, 'button', 'Revoke', 'smallbtn');
        revoke.type = 'button';
        revoke.addEventListener('click', () => mutate({action: 'revoke', connection_id: connection.id}, 'Connection revoked.'));
      }
    }
    const activity = byId('aiActivity');
    activity.replaceChildren();
    if (!data.activity.length) appendText(activity, 'p', 'No API activity yet.', 'ai-muted');
    for (const event of data.activity) appendText(activity, 'p',
      `${new Date(event.created_at).toLocaleString()} · ${event.name || 'Connection'} · ${event.operation} · ${event.gewu_key || ''} · ${event.outcome}`);
  }
  async function mutate(payload, message) {
    if (busy) return;
    generation++;
    busy = true;
    backdrop.setAttribute('aria-busy', 'true');
    backdrop.querySelectorAll('button,input,select,textarea').forEach(el => { el.disabled = true; });
    status('Saving...');
    try {
      const data = await request(payload);
      render(data);
      if (data.token) {
        secret = {token: data.token, config: data.mcp_config};
        byId('aiToken').value = data.token;
        byId('aiMcpConfig').value = JSON.stringify(data.mcp_config, null, 2);
        byId('aiCreated').hidden = false;
        byId('aiNewConnection').open = false;
        byId('aiName').value = '';
      }
      status(message);
    } catch (error) {
      if (snapshot) render(snapshot);
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
            <label><input id="aiReadFiles" type="checkbox"> Read PDF, attachment and note contents</label>
            <label><input id="aiWriteAnalysis" type="checkbox"> Add new Markdown analyses to Paper Files</label>
            <p class="ai-muted">Existing files, Default choices, metadata and folders cannot be changed or deleted through this connection.</p></fieldset>
          <label>Expires after<select id="aiExpiry"><option value="7">7 days</option><option value="30" selected>30 days</option><option value="90">90 days</option><option value="365">1 year</option></select></label>
          <button class="smallbtn" type="submit">Create Connection</button></form></details>
        <div id="aiCreated" hidden><h3>Connect your AI client</h3><p>This token is shown only now. Save the configuration in your AI client's MCP settings, not in a chat message.</p>
          <label>API token<input id="aiToken" type="password" readonly autocomplete="off"></label>
          <button id="aiCopyToken" class="smallbtn" type="button">Copy Token</button>
          <button id="aiCopyMcp" class="smallbtn" type="button">Copy MCP Configuration</button>
          <details><summary>Configuration</summary><textarea id="aiMcpConfig" readonly rows="9" aria-label="MCP connection configuration"></textarea></details>
        </div>
        <h3>Connections</h3><div id="aiConnections"></div>
        <details><summary>Recent Activity</summary><div id="aiActivity"></div></details>
        <p id="aiAccessStatus" class="citation-settings-status" role="status" aria-live="polite"></p>
        <button id="aiRefresh" class="smallbtn" type="button">Refresh</button>
      </div></section>`;
    document.body.appendChild(backdrop);
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
      if (byId('aiReadFiles').checked) scopes.push('files:read');
      if (byId('aiWriteAnalysis').checked) scopes.push('analysis:write');
      mutate({action: 'create', name: byId('aiName').value, selection, scopes, expires_days: Number(byId('aiExpiry').value)}, 'Connection created. Copy its configuration before closing this window.');
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
        const controls = [...backdrop.querySelectorAll('button,input,select,textarea,summary')].filter(el => !el.disabled && el.getClientRects().length);
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
