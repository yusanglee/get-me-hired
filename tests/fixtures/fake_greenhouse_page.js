// A tiny stand-in for a Playwright page holding Greenhouse react-select dropdowns, enough to run a
// generated fill plan (tools/fillers/fill_greenhouse.js) under Node without a browser.
//   node fake_greenhouse_page.js <fillplan.js> <fields.json>
// fields.json: [{id, label, name?, options, showIf?: {id, value}}]; name is the accessible name when it differs
// from the visible <label> (default: the label). A field with showIf appears only once that
// other field holds that value (Greenhouse shows the race question only after "Hispanic/Latino: No").
// A file field, {id, label, file: true, failFirst?: n}, is an upload group whose first n uploads attach nothing
// (Greenhouse's upload script not ready yet); after that it shows the file name.
// Prints {report, values}.
const fs = require('fs'), vm = require('vm');
const [planPath, fieldsPath] = process.argv.slice(2);
const fields = JSON.parse(fs.readFileSync(fieldsPath, 'utf8'));
const values = {}, uploads = {};
let open = null;  // the dropdown whose menu is showing
const norm = (s) => String(s).replace(/\s+/g, ' ').trim();
const visible = () => fields.filter(f => !f.showIf || values[f.showIf.id] === f.showIf.value);
const matches = (text, name, exact) => name === undefined ? true : name instanceof RegExp ? name.test(text)
  : exact ? norm(text) === norm(name) : norm(text).toLowerCase().includes(norm(name).toLowerCase());

function loc(items, ctx = {}) {
  const l = {
    count: async () => items().length,
    first: () => loc(() => items().slice(0, 1), ctx),
    nth: (i) => loc(() => items().slice(i, i + 1), ctx),
    all: async () => items().map((_, i) => loc(() => items().slice(i, i + 1), ctx)),
    one() { const x = items()[0]; if (!x) throw new Error(`no element for ${ctx.desc}`); return x; },
    click: async () => { const x = l.one(); if (x.kind === 'combobox') open = x.field; else if (x.kind === 'option') { values[open.id] = x.text; open = null; } },
    pressSequentially: async () => { l.one(); },
    getAttribute: async (a) => (a === 'id' ? l.one().field?.id : null),
    innerText: async () => { const x = l.one(); return x.kind === 'group' ? (values[x.field.id] || '') : x.text; },
    locator: () => loc(() => items().map(x => ({ kind: 'file', field: x.field })), ctx),
    setInputFiles: async (path) => { const f = l.one().field; uploads[f.id] = (uploads[f.id] || 0) + 1;
      if (uploads[f.id] > (f.failFirst || 0)) values[f.id] = path.split('/').pop() + ' Remove'; },
    evaluate: async () => { const x = l.one(); return x.field ? (values[x.field.id] || '') : ''; },  // the react-select value shown
    getByRole: (role, o = {}) => page.getByRole(role, o),
    check: async () => {}, isChecked: async () => false, inputValue: async () => '', fill: async () => {},
  };
  return l;
}

const page = {
  getByRole(role, { name, exact } = {}) {
    if (role === 'combobox') return loc(() => visible().filter(f => !f.file && matches(f.name ?? f.label, name, exact)).map(f => ({ kind: 'combobox', field: f, text: f.label })), { desc: `combobox ${name}` });
    if (role === 'group') return loc(() => visible().filter(f => f.file && matches(f.label, name, exact)).map(f => ({ kind: 'group', field: f })), { desc: `group ${name}` });
    if (role === 'option') return loc(() => (open ? open.options : []).filter(o => matches(o, name, exact)).map(o => ({ kind: 'option', text: o })), { desc: `option ${name}` });
    return loc(() => [], { desc: `${role} ${name}` });
  },
  locator(sel) {
    const m = /^label\[for="(.+)"\]$/.exec(sel);
    return loc(() => (m ? visible().filter(f => f.id === m[1]).map(f => ({ kind: 'label', text: f.label })) : []), { desc: sel });
  },
  keyboard: { press: async (k) => { if (k === 'Escape' || k === 'Enter') open = null; } },
  waitForTimeout: async () => {},
  waitForLoadState: async () => {},
  evaluate: async () => '(form check skipped)',
};

const src = fs.readFileSync(planPath, 'utf8');
vm.runInThisContext('(' + src + '\n)')(page).then(report => {
  console.log(JSON.stringify({ report, values, uploads }));
}).catch(e => { console.error(e); process.exit(1); });
