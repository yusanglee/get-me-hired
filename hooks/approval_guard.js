#!/usr/bin/env node
'use strict';
/*
 * PreToolUse guard: nothing submits a job application without the user's approval.
 *
 * Reads the hook payload (JSON) on stdin. For a Playwright browser call that could submit an application it
 * answers per --mode:
 *   --mode ask   (Claude Code) permissionDecision "ask": the user sees a permission prompt.
 *   --mode deny  (Codex)       permissionDecision "deny": Codex ignores "ask" and runs the call, so it is blocked
 *                              and the user is told to click Submit in the browser themselves.
 *   --mode antigravity (Antigravity CLI, experimental) the payload is {toolCall: {name, args}} (documented at
 *                              antigravity.google/docs/hooks); the answer is {decision: "force_ask", reason} (documented;
 *                              force_ask ignores "Always Allow") plus the Claude-shaped hookSpecificOutput as a
 *                              belt-and-braces. The MCP tool-name format is undocumented, so any name ending in
 *                              browser_<tool> matches. Untested against a real Antigravity.
 * Anything else: exit 0, no output. If the payload cannot be parsed, or anything throws, it fails closed
 * (ask / deny) rather than letting a possible submit through.
 *
 * Detected: a submit script (tools/submit/), code that clicks a Submit button or submits a form, a click on an
 * element described as Submit, browser_type with submit:true, browser_press_key with Enter.
 * Tracker writes are not guarded; the prompt-level approval rule covers them.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const SUBMIT_CODE_RE = new RegExp(
  "tools[\\\\/]+submit[\\\\/]|submit_(?:greenhouse|ashby|lever)\\b|" +
  "getByRole\\(\\s*['\"]button['\"]\\s*,\\s*\\{[^}]*name\\s*:[^}]*submit|" +
  "#btn-submit|\\[type=['\"]?submit|:has-text\\(\\s*['\"][^'\"]*submit|text=['\"]?submit|" +
  "requestSubmit\\s*\\(|\\.submit\\s*\\(\\s*\\)", 'i');
const SUBMIT_ELEMENT_RE = /\bsubmit|send application/i;
const ENTER_RE = /(^|\+)(numpad)?enter$/i;
// Claude/Codex: mcp__playwright__browser_x, mcp__plugin_<x>_playwright__browser_x; Gemini: mcp_playwright_browser_x
const TOOL_RE = /^mcp__?(?:plugin_[A-Za-z0-9_-]+_)?playwright_+browser_([a-z_]+)$/;

// Antigravity: the MCP tool-name format is not documented, so tolerate any prefix.
const TOOL_RE_ANY = /(?:^|_|\/)browser_([a-z_]+)$/;

const WHY = {
  ask: 'get-me-hired: this could submit a job application. Allow only if you approved this specific application in chat.',
  antigravity: 'get-me-hired: this could submit a job application. Allow only if you approved this specific application in chat.',
  deny: 'get-me-hired: this could submit a job application, so it is blocked. Ask the user to click Submit in the ' +
        'browser themselves after they have approved this specific application. Do not retry or work around it.',
};

function code(inp) {
  let c = String(inp.code || inp.function || '');
  const fn = inp.filename ? String(inp.filename) : '';
  if (fn) {
    c += '\n' + fn;
    try {
      const p = fn.startsWith('~') ? path.join(os.homedir(), fn.slice(1)) : fn;
      c += '\n' + fs.readFileSync(p, 'utf8');
    } catch (e) { /* unreadable: judge by the name */ }
  }
  return c;
}

function isSubmit(tool, inp, anyPrefix) {
  const m = (anyPrefix ? TOOL_RE_ANY : TOOL_RE).exec(tool || '');
  if (!m) return false;
  inp = (inp && typeof inp === 'object') ? inp : {};
  switch (m[1]) {
    case 'click': return SUBMIT_ELEMENT_RE.test(String(inp.element || ''));
    case 'type': return inp.submit === true || inp.submit === 'true';
    case 'press_key': return ENTER_RE.test(String(inp.key || '').trim());
    default: return SUBMIT_CODE_RE.test(code(inp));
  }
}

function emit(mode, why) {
  const out = { hookSpecificOutput: {
    hookEventName: 'PreToolUse', permissionDecision: mode === 'antigravity' ? 'ask' : mode, permissionDecisionReason: why } };
  if (mode === 'antigravity') { out.decision = 'force_ask'; out.reason = why; }
  process.stdout.write(JSON.stringify(out) + '\n');
}

function main() {
  const i = process.argv.indexOf('--mode');
  const want = i >= 0 ? process.argv[i + 1] : '';
  const mode = (want === 'deny' || want === 'antigravity') ? want : 'ask';
  let raw = '';
  try { raw = fs.readFileSync(0, 'utf8'); } catch (e) { raw = ''; }
  try {
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('bad payload');
    const tc = (data.toolCall && typeof data.toolCall === 'object') ? data.toolCall : null;
    const tool = tc ? tc.name : data.tool_name;
    const inp = tc ? tc.args : data.tool_input;
    if (isSubmit(tool, inp, mode === 'antigravity')) emit(mode, WHY[mode]);
  } catch (e) {
    emit(mode, WHY[mode] + ' (guard could not read the call, so it failed closed)');
  }
}

if (require.main === module) main();
module.exports = { isSubmit, TOOL_RE };
