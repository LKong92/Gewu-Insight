// Only the trusted workspace receives native operations. Remote Browser views
// have messaging disabled and never load this script.
(() => {
  if (location.origin !== __WORKSPACE_ORIGIN__) return;
  const send = (channel, payload = {}) => chrome.webview.postMessage({channel, payload});
  window.gewuPlatform = {os: 'windows', capture: true, captureDownload: true, build: 'preview'};
  window.webkit = {messageHandlers: Object.fromEntries(
    ['browser', 'appReady', 'paperFileChooser', 'authorPhotoChooser'].map(channel => [channel, {postMessage: payload => send(channel, payload)}]))};
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
  addEventListener('dragstart', event => {
    const handle = event.target.closest?.('[data-native-file-drag-handle][data-native-drag-path]');
    if (!handle || !handle.dataset.nativeDragPath) return;
    event.preventDefault(); event.stopImmediatePropagation();
    send('nativeFileDrag', {path:handle.dataset.nativeDragPath});
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
    chrome.webview.postMessageWithAdditionalObjects({channel: 'fileDrop', payload: {x: event.clientX, y: event.clientY}}, Array.from(event.dataTransfer.files).slice(0, 256));
  }, true);
  addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = `
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
