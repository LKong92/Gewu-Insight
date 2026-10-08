// Only the trusted workspace receives native operations. Remote Browser views
// have messaging disabled and never load this script.
(() => {
  if (location.origin !== __WORKSPACE_ORIGIN__) return;
  const send = (channel, payload = {}) => chrome.webview.postMessage({channel, payload});
  window.gewuPlatform = {os: 'windows', capture: true, captureDownload: true, build: 'preview'};
  // App-owned confirmations avoid WebView2's origin-labelled script dialog.
  // A modal dialog makes the workspace inert and keeps keyboard focus inside.
  let deletionDialog = null;
  const guardDeletionKey = event => {
    if (!deletionDialog) return;
    // Install before the workspace's capture-phase keyboard shortcuts.
    event.stopImmediatePropagation();
    if (event.type === 'keydown' && event.key === 'Escape') {
      event.preventDefault(); deletionDialog.close();
    } else if (event.type === 'keydown' && event.key === 'Tab') {
      // WebView2 can otherwise move focus out to the native window controls.
      event.preventDefault();
      const buttons = Array.from(deletionDialog.querySelectorAll('button'));
      const current = buttons.indexOf(document.activeElement);
      buttons[(current + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length].focus();
    }
  };
  window.addEventListener('keydown', guardDeletionKey, true);
  window.addEventListener('keyup', guardDeletionKey, true);
  window.gewuConfirmDeletion = ({title, message, detail = '', button = 'Delete'}) => {
    if (deletionDialog) return Promise.resolve(false);
    return new Promise(resolve => {
      const previousFocus = document.activeElement;
      const dialog = document.createElement('dialog');
      deletionDialog = dialog;
      dialog.className = 'gewu-delete-dialog';
      dialog.setAttribute('aria-labelledby', 'gewuDeleteTitle');
      dialog.setAttribute('aria-describedby', 'gewuDeleteMessage gewuDeleteDetail');
      const icon = document.createElement('img');
      icon.src = '/api/app-icon'; icon.alt = ''; icon.className = 'gewu-delete-icon';
      const heading = document.createElement('h2');
      heading.id = 'gewuDeleteTitle'; heading.textContent = title;
      const body = document.createElement('p');
      body.id = 'gewuDeleteMessage'; body.textContent = message;
      const note = document.createElement('p');
      note.id = 'gewuDeleteDetail'; note.className = 'gewu-delete-detail'; note.textContent = detail;
      const actions = document.createElement('div'); actions.className = 'gewu-delete-actions';
      const cancel = document.createElement('button');
      cancel.type = 'button'; cancel.textContent = 'Cancel';
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = button; remove.className = 'gewu-delete-action'; remove.autofocus = true;
      actions.append(cancel, remove); dialog.append(icon, heading, body, note, actions);
      let finished = false;
      const finish = confirmed => {
        if (finished) return;
        finished = true;
        window.removeEventListener('pagehide', onPageHide);
        dialog.close(); dialog.remove(); deletionDialog = null;
        if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
        resolve(confirmed);
      };
      const onPageHide = () => finish(false);
      cancel.addEventListener('click', () => finish(false));
      remove.addEventListener('click', () => finish(true));
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
      dialog.addEventListener('close', () => finish(false));
      window.addEventListener('pagehide', onPageHide, {once: true});
      document.body.append(dialog);
      dialog.showModal(); remove.focus({preventScroll: true});
    });
  };
  window.webkit = {messageHandlers: Object.fromEntries(
    ['browser', 'appReady', 'paperFileChooser', 'authorPhotoChooser', 'nativeFileDrag', 'libraryItemDrag', 'publisherPdfDownload', 'libraryLoaderWindow'].map(channel => [channel, {postMessage: payload => send(channel, payload)}]))};
  const pending = new Map();
  window.gewuChoosePath = kind => new Promise((resolve, reject) => {
    const request_id = crypto.randomUUID();
    pending.set(request_id, {resolve, reject});
    send('choosePath', {request_id, kind});
  });
  window.gewuPathChosen = result => {
    const request = pending.get(result.request_id);
    if (!request) return;
    pending.delete(result.request_id);
    if (result.error) request.reject(new Error(result.error)); else request.resolve(result);
  };
  addEventListener('pointerdown', () => send('dismissMenus'), true);
  addEventListener('keydown', event => { if (event.key === 'Escape') send('dismissMenus'); }, true);
  addEventListener('mousedown', event => {
    if (event.button !== 0) return;
    const handle = event.target.closest?.('[data-native-file-drag-handle][data-native-drag-path]');
    if (handle && !handle.closest('#libraryShell')) send('nativeFileDrag', {path: handle.dataset.nativeDragPath});
  }, true);
  addEventListener('dragstart', event => {
    const handle = event.target.closest?.('[data-native-file-drag-handle][data-native-drag-path]');
    if (!handle || !handle.dataset.nativeDragPath) return;
    event.preventDefault(); event.stopImmediatePropagation();
    // The shared mousedown handler already armed the native operation. The
    // native threshold also works for folder handles (draggable=false).
  }, true);
  const dropSurface = event => event.target.closest?.('#libraryShell, #libraryLoaderBackdrop.open')
    && !event.target.closest?.('input, textarea, [contenteditable], .browser-capture-overlay');
  addEventListener('dragover', event => {
    if (!dropSurface(event) || !Array.from(event.dataTransfer?.types || []).includes('Files')) return;
    event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
  }, true);
  addEventListener('drop', event => {
    if (!dropSurface(event) || !event.dataTransfer?.files.length) return;
    event.preventDefault(); event.stopImmediatePropagation();
    chrome.webview.postMessageWithAdditionalObjects({channel: 'fileDrop', payload: {x: event.clientX, y: event.clientY, drag_id: window.gewuNativeDragId || ''}}, Array.from(event.dataTransfer.files).slice(0, 256));
  }, true);
  addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = `
      .gewu-delete-dialog{box-sizing:border-box;width:360px;max-width:calc(100vw - 40px);max-height:calc(100vh - 40px);padding:24px 24px 20px;border:1px solid #c8c8ca;border-radius:14px;background:#ececee;color:#202024;box-shadow:0 18px 64px #17243c40;font:13px/1.45 "Segoe UI",sans-serif;text-align:center;overflow:auto}
      .gewu-delete-dialog::backdrop{background:rgba(24,34,51,.22)}
      .gewu-delete-dialog .gewu-delete-icon{display:block;width:64px;height:64px;object-fit:contain;margin:0 auto 16px}
      .gewu-delete-dialog h2{font:600 17px/1.3 "Segoe UI",sans-serif;color:#202024;margin:0 0 10px;overflow-wrap:anywhere}
      .gewu-delete-dialog p{font:13px/1.45 "Segoe UI",sans-serif;color:#202024;margin:0 0 12px;white-space:pre-line;overflow-wrap:anywhere}
      .gewu-delete-dialog .gewu-delete-detail{max-height:320px;overflow:auto}
      .gewu-delete-dialog .gewu-delete-actions{display:flex;gap:8px;margin-top:20px}
      .gewu-delete-dialog button{flex:1;min-width:0;min-height:32px;padding:6px 12px;border:1px solid #c8c8ca;border-radius:7px;background:#fff;color:#202024;font:400 13px/1.3 "Segoe UI",sans-serif;cursor:pointer}
      .gewu-delete-dialog button:hover{background:#edf0f5}
      .gewu-delete-dialog button.gewu-delete-action{background:#087cf0;border-color:#087cf0;color:#fff}
      .gewu-delete-dialog button.gewu-delete-action:hover{background:#006dde}
      .gewu-delete-dialog button:focus-visible{outline:3px solid #759de5;outline-offset:3px}
      .view-switcher,.sidebar-view-switcher{left:8px!important;right:62px;overflow-x:auto;scrollbar-width:none}
      .view-switch{flex-shrink:0;padding-left:10px!important;padding-right:10px!important}
      .window-drag-region{pointer-events:none}
      .library-detail{--runtime-empty-brand-right:16px;--runtime-empty-brand-bottom:16px}
      .runtime-empty-brand-art{opacity:.24;width:clamp(140px,14vw,190px)}
      .runtime-empty-brand-crop{z-index:0}
      .library-detail>:not(.runtime-empty-brand-crop){position:relative;z-index:1}
      .settings-modal-close,.preferences-modal .settings-modal-close{left:auto;right:12px;top:12px;width:28px;min-width:28px;height:28px;min-height:28px;border-radius:4px;background:transparent;border:1px solid #cbd0d8;cursor:pointer}
      .settings-modal-close,.preferences-modal .settings-modal-close{transform:none}
      .settings-modal-close::after,.preferences-modal .settings-modal-close::after{color:#344054;font-size:21px;inset:0}
      .settings-modal-close:hover,.preferences-modal .settings-modal-close:hover{background:#e5e8ed}
      .settings-modal-close:hover::after,.preferences-modal .settings-modal-close:hover::after{color:#1d2939}
    `;
    document.head.append(style);
  }, {once: true});
})();
