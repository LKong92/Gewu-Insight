// Pure synthetic DOM contract test. Any attempted credential-value access throws.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../scripts/GewuBrowserLoginProbe.js'), 'utf8');
class Input {
  constructor(attrs = {}) {
    this.attrs = attrs; this.type = attrs.type || 'text'; this.id = attrs.id || '';
    this.disabled = !!attrs.disabled; this.readOnly = !!attrs.readonly; this.form = null;
  }
  get value() { throw Error('Credential values must never be read'); }
  getAttribute(name) { if (name === 'value') throw Error('Value attribute read'); return this.attrs[name] || null; }
  closest() { return this.attrs.inert || this.attrs.searchRole ? {} : null; }
  getBoundingClientRect() { return {width:this.attrs.tiny ? 1 : 200, height:30}; }
}
let checks = 0;
function fixture(attrs = {}, options = {}) {
  const input = new Input(attrs);
  const formAttrs = options.formAttrs || {};
  if (options.form !== false) {
    const fields = [input, ...(options.fields || []).map(a => new Input(a))];
    input.form = {id:formAttrs.id || '', elements:options.huge ? Array(81).fill(input) : fields,
      getAttribute:n => formAttrs[n] || null};
  }
  const win = {}; win.top = options.frame ? {} : win;
  const context = vm.createContext({window:win, HTMLInputElement:Input, URL,
    location:{protocol:options.http ? 'http:' : 'https:', origin:'https://example.org', href:'https://example.org/login', pathname:options.path || '/login'},
    document:{hasFocus:() => !options.noFocus, activeElement:options.otherActive ? {} : input,
      elementFromPoint:() => options.overlay ? {} : input},
    getComputedStyle:() => ({visibility:options.hidden ? 'hidden' : 'visible', opacity:options.transparent ? '0' : '1'})});
  const run = (mode='inspect', token=1, origin='https://example.org') => {
    context.clickX = 50; context.clickY = 30; context.expectedOrigin = origin;
    context.mode = mode; context.token = token;
    return vm.runInContext('(function(){'+script+'})()', context);
  };
  return {run, context, input};
}
function check(attrs, options, expected) {
  const f = fixture(attrs, options); assert.equal(f.run(), expected, JSON.stringify({attrs,options}));
  assert.equal(f.run('confirm'), expected); checks++;
}
check({autocomplete:'username'}, {}, 'username');
check({autocomplete:'section-login username webauthn', type:'email'}, {path:'/v3/signin/identifier'}, 'username');
check({autocomplete:'username'}, {path:'/', formAttrs:{id:'login-form'}}, 'username');
check({autocomplete:'username'}, {path:'/', fields:[{type:'password',autocomplete:'current-password'}]}, 'username');
check({type:'password',autocomplete:'current-password'}, {path:'/',form:false}, 'current-password');
for (const attrs of [
  {type:'search',autocomplete:'username'}, {type:'email',autocomplete:'email'}, {type:'email'}, {},
  {type:'password'}, {type:'password',autocomplete:'new-password'}, {autocomplete:'one-time-code'},
  {autocomplete:'off'}, {autocomplete:'shipping username'}, {autocomplete:'username current-password'},
  {type:'text',autocomplete:'current-password'}, {type:'password',autocomplete:'username'},
  {autocomplete:'username',name:'search'}, {autocomplete:'username',id:'otp'},
  {autocomplete:'username',disabled:true}, {autocomplete:'username',readonly:true},
  {autocomplete:'username',inert:true}, {autocomplete:'username',searchRole:true}, {autocomplete:'username',tiny:true}
]) check(attrs, {}, '');
for (const options of [
  {path:'/'}, {path:'/signup'}, {path:'/register'}, {path:'/password/reset'}, {path:'/search'},
  {formAttrs:{id:'signup'}}, {formAttrs:{'aria-label':'Create account'}}, {huge:true},
  {formAttrs:{action:'/search'}}, {formAttrs:{action:'/reset-password'}},
  {fields:[{type:'password',autocomplete:'new-password'}]}, {fields:[{autocomplete:'one-time-code'}]},
  {fields:[{type:'password',autocomplete:'current-password'}, {type:'password'}]},
  {frame:true}, {http:true}, {noFocus:true}, {otherActive:true}, {overlay:true}, {hidden:true}, {transparent:true}
]) check({autocomplete:'username'}, options, '');
for (const options of [{path:'/change-password'}, {path:'/register'}, {fields:[{type:'password',autocomplete:'new-password'}]}]) {
  check({type:'password',autocomplete:'current-password'}, options, '');
}
let f = fixture({autocomplete:'username'});
assert.equal(f.run('confirm'), ''); checks++;
assert.equal(f.run(), 'username'); assert.equal(f.run('confirm', 2), ''); checks++;
f = fixture({autocomplete:'username'}); f.run(); f.context.document.activeElement = {}; assert.equal(f.run('confirm'), ''); checks++;
f = fixture({autocomplete:'username'}); f.run(); f.context.location.origin = 'https://other.example'; assert.equal(f.run('confirm'), ''); checks++;
f = fixture({autocomplete:'username'}); f.run(); f.input.attrs.autocomplete = 'email'; assert.equal(f.run('confirm'), ''); checks++;
f = fixture({autocomplete:'username'}); f.run();
const replacement = new Input({autocomplete:'username'}); f.context.document.activeElement = replacement;
f.context.document.elementFromPoint = () => replacement; assert.equal(f.run('confirm'), ''); checks++;
assert(!/addEventListener|setInterval|setTimeout|\.value\b|\.focus\(|\.submit\(|postMessage|fetch\(/.test(script));
console.log(`${checks} conservative login-classification checks passed`);
