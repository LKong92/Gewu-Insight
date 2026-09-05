// Invoked once for a native, unmodified mouse click, in an isolated WKContentWorld.
// Read semantics/geometry only: never read input values, page text or credentials.
// There are no persistent page listeners, timers, DOM changes or message handlers.
return (() => {
  const prior = globalThis.__gewuLoginTriggerCandidate;
  globalThis.__gewuLoginTriggerCandidate = undefined;
  if (location.protocol !== 'https:' || location.origin !== expectedOrigin ||
      window !== window.top || !document.hasFocus()) return '';
  const input = document.elementFromPoint(clickX, clickY);
  if (mode === 'confirm' && (!prior || prior.input !== input || prior.token !== token)) return '';
  if (!(input instanceof HTMLInputElement) || input !== document.activeElement ||
      input.disabled || input.readOnly || input.closest('[inert], [role="search"]')) return '';
  const type = input.type.toLowerCase();
  if (!['text', 'email', 'password'].includes(type)) return '';
  const tokens = (input.getAttribute('autocomplete') || '').trim().toLowerCase().split(/\s+/);
  if (tokens[0]?.startsWith('section-')) tokens.shift();
  if (tokens.at(-1) === 'webauthn') tokens.pop();
  if (tokens.length !== 1 || !['username', 'current-password'].includes(tokens[0])) return '';
  const kind = tokens[0];
  if ((kind === 'current-password') !== (type === 'password')) return '';

  const excluded = /(?:search|query|newsletter|subscribe|register|registration|sign[\s_-]*up|signup|create|new[\s_-]*(?:account|password)|confirm|reset|recover|change|one[\s_-]*time|otp|verification|验证码|註冊|注册|搜索)/i;
  const semanticName = element => [element.id, element.getAttribute('name'),
    element.getAttribute('role'), element.getAttribute('aria-label')].filter(Boolean).join(' ');
  if (excluded.test(semanticName(input)) || excluded.test(location.pathname)) return '';
  const rect = input.getBoundingClientRect();
  const style = getComputedStyle(input);
  if (rect.width < 8 || rect.height < 8 || style.visibility !== 'visible' ||
      Number(style.opacity) === 0) return '';

  const form = input.form;
  let loginContext = /(?:^|[\/\s_-])(?:login|log[\s_-]*in|signin|sign[\s_-]*in)(?:$|[\/\s_.-])/i.test(location.pathname);
  if (form) {
    if (excluded.test(semanticName(form))) return '';
    const action = form.getAttribute('action');
    if (action) {
      try { if (excluded.test(new URL(action, location.href).pathname)) return ''; }
      catch (_) { return ''; }
    }
    // A bounded inspection of this form, never a scan of the whole document.
    if (form.elements.length > 80) return '';
    const fields = Array.from(form.elements).filter(e => e instanceof HTMLInputElement);
    if (fields.some(e => /(?:new-password|one-time-code)/i.test(e.getAttribute('autocomplete') || '') ||
      excluded.test(semanticName(e)))) return '';
    if (fields.filter(e => e.type === 'password').length > 1) return '';
    loginContext ||= /(?:^|[\s_-])(?:login|log[\s_-]*in|signin|sign[\s_-]*in)(?:$|[\s_-])/i.test(semanticName(form));
    loginContext ||= fields.some(e => e.type === 'password' &&
      (e.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/).includes('current-password'));
  }
  // Explicit current-password is sufficient unless contradicted above.
  // A username alone needs additional login evidence (registration also uses it).
  if (kind !== 'current-password' && !loginContext) return '';
  if (mode === 'inspect') globalThis.__gewuLoginTriggerCandidate = {input, token};
  return kind;
})();
