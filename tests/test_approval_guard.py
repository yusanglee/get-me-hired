"""hooks/approval_guard.js: ask (Claude) or deny (Codex) before a submit, stay silent for everything else."""
import glob, json, os, re, shutil, subprocess, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, 'hooks', 'approval_guard.js')
NODE = shutil.which('node')
RUN = 'mcp__plugin_get-me-hired_playwright__browser_run_code_unsafe'


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def run(payload, mode, raw=False):
    p = subprocess.run([NODE, GUARD, '--mode', mode], input=payload if raw else json.dumps(payload),
                       capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
    assert p.returncode == 0, p.stderr
    return p.stdout


CASES = json.loads(_read(os.path.join(ROOT, 'tests', 'fixtures', 'guard_cases.json')))


@unittest.skipUnless(NODE, 'node not installed')
class Cases(unittest.TestCase):
    def test_every_case_in_both_modes(self):
        for c in CASES:
            for mode in ('ask', 'deny'):
                out = run({'tool_name': c['tool_name'], 'tool_input': c['tool_input']}, mode)
                label = (c['tool_name'], c['tool_input'], mode)
                if c['expect'] == 'pass':
                    self.assertEqual(out, '', label)
                    continue
                h = json.loads(out)['hookSpecificOutput']
                self.assertEqual(h['hookEventName'], 'PreToolUse', label)
                self.assertEqual(h['permissionDecision'], mode, label)
                self.assertIn('submit', h['permissionDecisionReason'].lower(), label)
                self.assertIn('click Submit' if mode == 'deny' else 'approved', h['permissionDecisionReason'])

    def test_antigravity_mode_shared_cases(self):
        # Antigravity sends {toolCall: {name, args}} and reads top-level decision/reason (antigravity.google/docs/hooks).
        for c in CASES:
            out = run({'toolCall': {'name': c['tool_name'], 'args': c['tool_input']}}, 'antigravity')
            label = (c['tool_name'], c['tool_input'])
            if c['expect'] == 'pass' and 'playwright' not in c['tool_name']:
                continue  # Antigravity mode matches any browser_<tool> name (unknown prefix), so other servers ask too
            if c['expect'] == 'pass':
                self.assertEqual(out, '', label)
                continue
            d = json.loads(out)
            self.assertEqual(d['decision'], 'force_ask', label)
            self.assertIn('submit', d['reason'].lower(), label)
            self.assertEqual(d['hookSpecificOutput']['permissionDecision'], 'ask', label)

    def test_antigravity_mode_tolerates_tool_name_prefixes(self):
        for name in ('browser_click', 'playwright_browser_click', 'mcp_playwright_browser_click',
                     'playwright/browser_click', 'mcp__playwright__browser_click'):
            d = json.loads(run({'toolCall': {'name': name, 'args': {'element': 'Submit application'}}}, 'antigravity'))
            self.assertEqual(d['decision'], 'force_ask', name)
        self.assertEqual(run({'toolCall': {'name': 'run_command', 'args': {'CommandLine': 'ls'}}}, 'antigravity'), '')
        self.assertEqual(run({'toolCall': {'name': 'browser_click', 'args': {'element': 'Next'}}}, 'antigravity'), '')

    def test_antigravity_malformed_fails_closed(self):
        for raw in ('', 'not json', '[1]'):
            self.assertEqual(json.loads(run(raw, 'antigravity', raw=True))['decision'], 'force_ask')

    def test_real_scripts(self):
        for f in glob.glob(os.path.join(ROOT, 'tools', 'submit', '*.js')):
            for inp in ({'filename': f}, {'code': _read(f)}):
                self.assertTrue(json.loads(run({'tool_name': RUN, 'tool_input': inp}, 'ask')), f)
        for f in glob.glob(os.path.join(ROOT, 'tools', 'fillers', '*.js')) + [os.path.join(ROOT, 'tests', 'fixtures', 'fake_greenhouse_page.js')]:
            self.assertEqual(run({'tool_name': RUN, 'tool_input': {'filename': f}}, 'ask'), '', f)

    def test_malformed_payload_fails_closed(self):
        for mode in ('ask', 'deny'):
            for raw in ('', 'not json', '[1,2]', 'null'):
                out = json.loads(run(raw, mode, raw=True))
                self.assertEqual(out['hookSpecificOutput']['permissionDecision'], mode, raw)

    def test_odd_inputs_on_guarded_tools_do_not_crash(self):
        for inp in (None, 'text', [], {'key': None}, {'filename': 5}):
            run({'tool_name': 'mcp__playwright__browser_press_key', 'tool_input': inp}, 'ask')
            run({'tool_name': RUN, 'tool_input': inp}, 'deny')


class Wiring(unittest.TestCase):
    def matchers(self):
        out = {}
        for rel in ('.claude/settings.json', 'hooks/claude.json', 'hooks/codex.json'):
            if rel == '.claude/settings.json' and not os.path.exists(os.path.join(ROOT, rel)):
                continue  # the repo-only session settings are not part of the shared copy
            out[rel] = [e['matcher'] for e in json.loads(_read(os.path.join(ROOT, rel)))['hooks']['PreToolUse']]
        return out

    def test_same_matcher_everywhere(self):
        m = self.matchers()
        if '.claude/settings.json' in m:
            self.assertEqual(m['.claude/settings.json'], m['hooks/claude.json'])
        self.assertEqual(m['hooks/codex.json'], m['hooks/claude.json'])
        self.assertEqual(len(m['hooks/claude.json']), 1)

    def test_matcher_covers_guarded_tools_only(self):
        rx = re.compile(self.matchers()['hooks/claude.json'][0])
        for server in ('mcp__playwright__', 'mcp__plugin_playwright_playwright__', 'mcp__plugin_get-me-hired_playwright__'):
            for t in ('run_code_unsafe', 'run_code', 'evaluate', 'click', 'type', 'press_key'):
                self.assertTrue(rx.match(server + 'browser_' + t), server + t)
            for t in ('navigate', 'snapshot', 'fill_form', 'take_screenshot'):
                self.assertFalse(rx.match(server + 'browser_' + t), server + t)
        for name in ('mcp__other__browser_click', 'Read', 'Bash'):
            self.assertFalse(rx.match(name), name)

    def test_commands(self):
        def cmd(rel):
            return json.loads(_read(os.path.join(ROOT, rel)))['hooks']['PreToolUse'][0]['hooks'][0]['command']
        self.assertEqual(cmd('hooks/claude.json'), 'node "${CLAUDE_PLUGIN_ROOT}/hooks/approval_guard.js" --mode ask')
        self.assertEqual(cmd('hooks/codex.json'), 'node "${PLUGIN_ROOT}/hooks/approval_guard.js" --mode deny')
        if os.path.exists(os.path.join(ROOT, '.claude', 'settings.json')):
            self.assertEqual(cmd('.claude/settings.json'), 'node "$CLAUDE_PROJECT_DIR/hooks/approval_guard.js" --mode ask')

    def test_old_guard_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'hooks', 'approval_guard.py')))
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'hooks', 'hooks.json')))
        self.assertEqual(json.loads(_read(os.path.join(ROOT, '.claude-plugin', 'plugin.json')))['hooks'], './hooks/claude.json')


if __name__ == '__main__':
    unittest.main()
