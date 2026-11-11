"""v1.0 cross-platform setup: agents per tool, context file per tool, engine line per tool, generated Gemini commands,
permissions merge. Fictional data only."""
import json, os, subprocess, sys, tempfile, unittest

from engine import setup

REPO = setup.REPO


def run(*args, env=None):
    e = dict(os.environ)
    e.pop('GMH_TOOL', None)
    e.pop('GMH_WORKSPACE', None)
    e.update(env or {})
    return subprocess.run([sys.executable, '-m', 'engine.setup'] + list(args), cwd=REPO, capture_output=True,
                          text=True, encoding='utf-8', env=e)


class AgentsPerTool(unittest.TestCase):
    def test_codex_and_gemini_write_their_formats_and_are_idempotent(self):
        for tool, sub, ext in (('codex', '.codex', '.toml'), ('gemini', '.gemini', '.md')):
            ws = tempfile.mkdtemp()
            r = run('agents', '--tool', tool, '--workspace', ws)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = os.path.join(ws, sub, 'agents')
            files = sorted(os.listdir(d))
            self.assertTrue(files and all(f.endswith(ext) for f in files))
            self.assertIn('posting-reader' + ext, files)
            self.assertIn('added', r.stdout)
            self.assertIn('already current', run('agents', '--tool', tool, ws).stdout)
            self.assertEqual(run('agents', '--tool', tool, '--check', '--workspace', ws).returncode, 0)
            with open(os.path.join(d, 'posting-reader' + ext), 'a', encoding='utf-8', newline='\n') as fh:
                fh.write('\n# edited\n')
            self.assertEqual(run('agents', '--tool', tool, '--check', '--workspace', ws).returncode, 1)
            self.assertIn('posting-reader: updated', run('agents', '--tool', tool, '--workspace', ws).stdout)

    def test_codex_toml_parses(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest('tomllib needs Python 3.11')
        ws = tempfile.mkdtemp()
        run('agents', '--tool', 'codex', '--workspace', ws)
        p = os.path.join(ws, '.codex', 'agents', 'posting-reader.toml')
        with open(p, 'rb') as fh:
            self.assertEqual(tomllib.load(fh)['name'], 'posting-reader')

    def test_claude_default_unchanged(self):
        ws = tempfile.mkdtemp()
        self.assertEqual(run('agents', ws).returncode, 0)
        self.assertEqual(set(setup.agents_status(ws).values()), {'ok'})
        self.assertTrue(os.path.isdir(os.path.join(ws, '.claude', 'agents')))
        self.assertFalse(os.path.exists(os.path.join(ws, '.codex')))

    def test_non_claude_without_a_workspace_does_not_write_into_the_checkout(self):
        r = run('agents', '--tool', 'codex', '--check', env={'GMH_WORKSPACE': tempfile.mkdtemp()})
        self.assertEqual(r.returncode, 1)  # nothing written there yet
        self.assertIn('missing', r.stdout)


class ContextFilePerTool(unittest.TestCase):
    def _init(self, tool):
        ws = os.path.join(tempfile.mkdtemp(), 'ws')
        setup.init(ws, 'chief-of-staff', False, 'Test User', tool)
        return ws

    def test_each_tool_writes_only_its_file(self):
        for tool, fn, other in (('claude', 'CLAUDE.md', 'AGENTS.md'), ('codex', 'AGENTS.md', 'CLAUDE.md'),
                                ('gemini', 'GEMINI.md', 'CLAUDE.md')):
            ws = self._init(tool)
            self.assertTrue(os.path.exists(os.path.join(ws, fn)))
            self.assertFalse(os.path.exists(os.path.join(ws, other)))
            with open(os.path.join(ws, fn), encoding='utf-8') as fh:
                text = fh.read()
            self.assertEqual(text.count(setup.DAILY_HEADING), 1)
            self.assertIn('get-me-hired today skill', text)
            self.assertIn('Engine:', text)
            if tool == 'claude':
                self.assertIn('/get-me-hired:today', text)
            else:
                self.assertNotIn('/get-me-hired:today', text)
                self.assertIn('use the get-me-hired today skill', text)

    def test_default_tool_is_claude_and_env_picks_another(self):
        old = os.environ.pop('GMH_TOOL', None)
        try:
            self.assertEqual(setup.resolve_tool(), 'claude')
            os.environ['GMH_TOOL'] = 'gemini'
            self.assertEqual(setup.resolve_tool(), 'gemini')
            self.assertEqual(setup.resolve_tool('codex'), 'codex')
            with self.assertRaises(SystemExit):
                setup.resolve_tool('vim')
        finally:
            os.environ.pop('GMH_TOOL', None)
            if old:
                os.environ['GMH_TOOL'] = old

    def test_check_repairs_whichever_file_exists(self):
        old_line = 'Engine: /Users/someone/.claude/plugins/cache/get-me-hired/get-me-hired/0.8.0  (set GMH_WORKSPACE to this folder)'
        for fn in ('AGENTS.md', 'GEMINI.md'):
            ws = tempfile.mkdtemp()
            with open(os.path.join(ws, fn), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('# Job-search workspace (x)\n\nRules here.\n\n' + old_line + '\n')
            rep = setup.check(ws)
            self.assertEqual(rep['daily_section_added'], 'added')
            self.assertEqual(rep['context_file'], fn)
            self.assertIn(fn, setup.format_check(rep))
            with open(os.path.join(ws, fn), encoding='utf-8') as fh:
                text = fh.read()
            self.assertEqual(text.count(setup.DAILY_HEADING), 1)
            self.assertFalse(os.path.exists(os.path.join(ws, 'CLAUDE.md')))

    def test_pack_label_updates_every_context_file(self):
        ws = self._init('codex')
        setup._claude_md_pack(ws, 'Brand New Label')
        with open(os.path.join(ws, 'AGENTS.md'), encoding='utf-8') as fh:
            self.assertIn('role-family rules (Brand New Label)', fh.read())


class EngineLinePerTool(unittest.TestCase):
    def test_claude_says_skills_and_mentions_windows(self):
        line = setup.engine_line('/Users/someone/.claude/plugins/cache/get-me-hired/get-me-hired/0.9.0')
        self.assertIn("plugin's skills", line)
        self.assertNotIn('plugin command', line)
        self.assertIn('gmh.cmd', line)

    def test_gemini_names_the_extension_folder(self):
        line = setup.engine_line('/Users/someone/.gemini/extensions/get-me-hired', 'gemini')
        self.assertIn('.gemini/extensions/get-me-hired/bin/gmh', line)
        self.assertIn('gmh.cmd', line)

    def test_antigravity_names_the_staged_plugin_folder(self):
        line = setup.engine_line('/Users/someone/.gemini/config/plugins/get-me-hired', 'antigravity')
        self.assertIn('~/.gemini/config/plugins/get-me-hired/bin/gmh', line.replace('/Users/someone', '~'))
        self.assertIn('gmh.cmd', line)
        self.assertEqual(setup.CONTEXT_FILES['antigravity'], 'AGENTS.md')

    def test_antigravity_agents_command_installs_nothing(self):
        import subprocess
        r = subprocess.run([sys.executable, '-m', 'engine.setup', 'agents', '--tool', 'antigravity'],
                           capture_output=True, text=True, encoding='utf-8', cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('not installed', r.stdout)

    def test_codex_uses_the_running_folder(self):
        self.assertEqual(setup.engine_line('/Users/someone/code/get-me-hired', 'codex'),
                         'Engine: /Users/someone/code/get-me-hired  (set GMH_WORKSPACE to this folder)')
        line = setup.engine_line('/Users/someone/.codex/plugins/cache/mk/get-me-hired/1.0.0', 'codex')
        self.assertIn('/.codex/plugins/cache/mk/get-me-hired/1.0.0/bin/gmh', line)

    def test_dev_checkout_is_the_same_for_every_tool(self):
        for t in setup.TOOLS:
            self.assertEqual(setup.engine_line('/Users/someone/code/gmh', t),
                             'Engine: /Users/someone/code/gmh  (set GMH_WORKSPACE to this folder)')


class GeminiCommands(unittest.TestCase):
    def test_generated_files_are_current(self):
        r = run('platform-files', '--check')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_skill_has_a_command(self):
        skills = [d for d in os.listdir(os.path.join(REPO, 'skills')) if os.path.isfile(os.path.join(REPO, 'skills', d, 'SKILL.md'))]
        self.assertTrue(skills)
        for d in skills:
            self.assertTrue(os.path.isfile(os.path.join(REPO, 'commands', d + '.toml')), d)

    def test_check_detects_missing_and_stale_in_a_copy(self):
        from engine import platforms
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, 'skills', 'demo'))
        with open(os.path.join(repo, 'skills', 'demo', 'SKILL.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('---\nname: demo\ndescription: Demo skill.\n---\nBody\n')
        self.assertEqual(setup.platform_files_status(repo), {'commands/demo.toml': 'missing'})
        self.assertEqual(setup.write_platform_files(repo), {'commands/demo.toml': 'added'})
        self.assertEqual(setup.platform_files_status(repo), {'commands/demo.toml': 'ok'})
        with open(os.path.join(repo, 'commands', 'demo.toml'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('old')
        self.assertEqual(setup.platform_files_status(repo), {'commands/demo.toml': 'stale'})
        self.assertIn('commands/demo.toml', platforms.command_files(repo))


class Permissions(unittest.TestCase):
    def test_merge_keeps_existing_and_is_idempotent(self):
        ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(ws, '.claude'))
        mine = {'permissions': {'allow': ['Bash(ls)'], 'deny': ['Bash(my rule)']}, 'model': 'opus'}
        with open(os.path.join(ws, '.claude', 'settings.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(mine, fh)
        r = run('permissions', '--workspace', ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('rule(s) added', r.stdout)
        with open(os.path.join(ws, '.claude', 'settings.json'), encoding='utf-8') as fh:
            got = json.load(fh)
        self.assertEqual(got['model'], 'opus')
        self.assertEqual(got['permissions']['allow'], ['Bash(ls)'])
        self.assertEqual(got['permissions']['deny'][0], 'Bash(my rule)')
        self.assertIn('Edit(**/tracker.csv)', got['permissions']['deny'])
        self.assertIn('already has every suggested rule', run('permissions', '--workspace', ws).stdout)

    def test_creates_the_file_and_refuses_bad_json(self):
        ws = tempfile.mkdtemp()
        self.assertEqual(run('permissions', '--workspace', ws).returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(ws, '.claude', 'settings.json')))
        bad = tempfile.mkdtemp()
        os.makedirs(os.path.join(bad, '.claude'))
        p = os.path.join(bad, '.claude', 'settings.json')
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('{not json')
        r = run('permissions', '--workspace', bad)
        self.assertEqual(r.returncode, 1)
        with open(p, encoding='utf-8') as fh:
            self.assertEqual(fh.read(), '{not json')


if __name__ == '__main__':
    unittest.main()
