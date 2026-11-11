// Design tokens shared by resume.js and cover_letter.js. Defaults live in templates/design.json; the payload's
// `design` object (built by engine/design.py from <workspace>/design.json) overrides any key.
// Tokens are in points and inches; Word wants twips (1/20 pt) and half-points.
const fs = require('fs');
const path = require('path');

const DEFAULTS = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'templates', 'design.json'), 'utf8'));

const merge = (a, b) => {
  if (!b || typeof b !== 'object' || Array.isArray(b)) return b === undefined ? a : b;
  const out = Object.assign({}, a);
  for (const k of Object.keys(b)) out[k] = (a && typeof a[k] === 'object' && !Array.isArray(a[k])) ? merge(a[k], b[k]) : b[k];
  return out;
};

const tw = (pt) => Math.round(pt * 20);        // points -> twips
const hp = (pt) => Math.round(pt * 2);         // points -> half-points
const lines = (mult) => Math.round(mult * 240); // line-height multiple -> Word's 240ths
const hex = (c) => String(c).replace(/^#/, '').toUpperCase();

const load = (override) => merge(DEFAULTS, override || {});

module.exports = { load, merge, tw, hp, lines, hex, DEFAULTS };
