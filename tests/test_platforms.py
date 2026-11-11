"""Per-platform manifests and the Codex/Gemini generators in engine/platforms.py."""
import glob, json, os, re, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import platforms as P  # noqa: E402

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


def _json(rel):
    return json.loads(_read(rel))


def _agents():
    return sorted(glob.glob(os.path.join(ROOT, 'subagents', '*.md')))


class Manifests(unittest.TestCase):
    def test_json_manifests_parse(self):
        for rel in ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', '.codex-plugin/plugin.json',
                    '.codex-plugin/mcp.json', '.agents/plugins/marketplace.json', 'gemini-extension.json',
                    'hooks/claude.json', 'hooks/codex.json', '.mcp.json',
                    '.antigravity-plugin/plugin.json', 'mcp_config.json', 'hooks.json'):
            _json(rel)

    def test_versions_match(self):
        v = _json('.claude-plugin/plugin.json')['version']
        self.assertEqual(_json('.claude-plugin/marketplace.json')['plugins'][0]['version'], v)
        self.assertEqual(_json('.codex-plugin/plugin.json')['version'], v)
        self.assertEqual(_json('gemini-extension.json')['version'], v)
        self.assertEqual(_json('.antigravity-plugin/plugin.json')['version'], v)

    def test_no_root_hooks_json(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'hooks', 'hooks.json')))

    def test_each_platform_points_at_its_own_files(self):
        self.assertEqual(_json('.claude-plugin/plugin.json')['hooks'], './hooks/claude.json')
        cx = _json('.codex-plugin/plugin.json')
        self.assertEqual(cx['hooks'], './hooks/codex.json')
        self.assertTrue(os.path.isfile(os.path.join(ROOT, cx['mcpServers'][2:])))
        self.assertEqual(_json('gemini-extension.json')['contextFileName'], 'platforms/gemini/GEMINI.md')
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'platforms', 'gemini', 'GEMINI.md')))
        src = _json('.agents/plugins/marketplace.json')['plugins'][0]['source']
        self.assertEqual(src['path'], './')

    def test_playwright_pinned_the_same_everywhere(self):
        want = _json('.mcp.json')['playwright']
        self.assertEqual(_json('gemini-extension.json')['mcpServers']['playwright'], want)
        self.assertEqual(_json('.codex-plugin/mcp.json')['mcpServers']['playwright'], want)
        self.assertEqual(_json('mcp_config.json')['mcpServers']['playwright'], want)
        self.assertIn('@playwright/mcp@0.0.83', want['args'])

    def test_antigravity_plugin(self):
        m = _json('.antigravity-plugin/plugin.json')
        self.assertEqual(m['name'], 'get-me-hired')
        self.assertLessEqual(len(m['suggestedPrompts']), 3)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'rules', 'AGENTS.md')))
        group = _json('hooks.json')['get-me-hired-submit-guard']['PreToolUse'][0]
        rx = re.compile(group['matcher'])
        for name in ('browser_click', 'mcp_playwright_browser_run_code_unsafe', 'playwright/browser_press_key',
                     'mcp__plugin_get-me-hired_playwright__browser_type'):
            self.assertTrue(rx.search(name), name)
        for name in ('browser_navigate', 'run_command', 'browser_snapshot'):
            self.assertFalse(rx.search(name), name)
        self.assertEqual(group['hooks'][0]['command'], 'node "${PLUGIN_ROOT}/hooks/approval_guard.js" --mode antigravity')
        # Claude Code reads hooks/claude.json (via plugin.json), Codex/Gemini read hooks/hooks.json: none read the root file
        self.assertNotIn('hooks.json', _read('.claude-plugin/plugin.json'))

    @unittest.skipUnless(tomllib, 'tomllib needs Python 3.11+')
    def test_policy_toml(self):
        d = tomllib.loads(_read('policies/submit-guard.toml'))
        self.assertTrue(d['rule'])
        for r in d['rule']:
            self.assertEqual(r['decision'], 'ask_user')  # extension policies cannot allow
            re.compile(r['argsPattern'].replace('(?i)', ''))

    def test_policy_has_no_allow(self):
        text = _read('policies/submit-guard.toml')
        self.assertNotIn('decision = "allow"', text)
        self.assertGreaterEqual(text.count('decision = "ask_user"'), 4)


FM = '---\nname: demo\ndescription: "Does a \\"thing\\" with `code` and a \\\\ slash."\ntools: Read, WebSearch\nmodel: opus\n---\n\nBody line "quoted" \\ and """triple""".\n'


class Generators(unittest.TestCase):
    def test_frontmatter(self):
        f, body = P.parse_frontmatter(FM)
        self.assertEqual(f['name'], 'demo')
        self.assertEqual(f['description'], 'Does a "thing" with `code` and a \\ slash.')
        self.assertTrue(body.startswith('Body line'))

    @unittest.skipUnless(tomllib, 'tomllib needs Python 3.11+')
    def test_codex_agent_roundtrip(self):
        d = tomllib.loads(P.codex_agent(FM))
        self.assertEqual(d['name'], 'demo')
        self.assertEqual(d['description'], 'Does a "thing" with `code` and a \\ slash.')
        self.assertEqual(d['model_reasoning_effort'], 'high')
        self.assertNotIn('model', d)
        self.assertEqual(d['developer_instructions'], 'Body line "quoted" \\ and """triple""".\n')

    def test_codex_effort_mapping(self):
        for model, eff in (('opus', 'high'), ('sonnet', 'medium'), ('haiku', 'low')):
            self.assertIn('model_reasoning_effort = "%s"' % eff, P.codex_agent(FM.replace('model: opus', 'model: ' + model)))
        self.assertIn('model_reasoning_effort = "low"', P.codex_agent(FM.replace('model: opus', 'model: opus\neffort: low')))

    def test_gemini_agent(self):
        out = P.gemini_agent(FM)
        f, body = P.parse_frontmatter(out)
        self.assertEqual(f['name'], 'demo')
        self.assertEqual(f['model'], 'inherit')
        self.assertIn('  - read_file', out)
        self.assertIn('  - google_web_search', out)
        self.assertIn('Body line', body)

    def test_gemini_playwright_tool_names(self):
        self.assertEqual(P._gemini_tool('mcp__playwright__browser_click'), 'mcp_playwright_browser_click')
        self.assertEqual(P._gemini_tool('mcp__plugin_get-me-hired_playwright__browser_click'), 'mcp_playwright_browser_click')

    @unittest.skipUnless(tomllib, 'tomllib needs Python 3.11+')
    def test_gemini_command(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, 'today'))
            with open(os.path.join(t, 'today', 'SKILL.md'), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('---\nname: today\ndescription: "Run the \\"day\\"."\n---\nbody\n')
            d = tomllib.loads(P.gemini_command(os.path.join(t, 'today')))
            self.assertEqual(d['description'], 'Run the "day".')
            self.assertEqual(d['prompt'], 'Use the get-me-hired today skill. {{args}}')

    def test_every_real_agent_converts(self):
        self.assertTrue(_agents())
        for path in _agents():
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            f, _ = P.parse_frontmatter(text)
            cx = P.codex_agent(text)
            self.assertIn('name = "%s"' % f['name'], cx)
            self.assertIn('description = ', cx)
            self.assertIn('developer_instructions = """', cx)
            if tomllib:
                d = tomllib.loads(cx)
                self.assertEqual((d['name'], d['description']), (f['name'], f['description']), path)
            g = P.gemini_agent(text)
            gf, _ = P.parse_frontmatter(g)
            self.assertEqual(gf['name'], f['name'])
            self.assertTrue(gf['description'])
            self.assertEqual(gf['model'], 'inherit')
            if tomllib:  # description is a JSON string: same text after parsing
                self.assertEqual(json.loads(re.search(r'^description: (.*)$', g, re.M).group(1)), f['description'])

    def test_write_all(self):
        with tempfile.TemporaryDirectory() as t:
            paths = P.write_all(ROOT, t)
            self.assertEqual(len([p for p in paths if p.endswith('.toml') and os.sep + 'agents' + os.sep in p]), len(_agents()))
            self.assertEqual(len([p for p in paths if p.endswith('.md')]), len(_agents()))


if __name__ == '__main__':
    unittest.main()
