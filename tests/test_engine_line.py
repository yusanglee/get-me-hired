"""The workspace CLAUDE.md must not pin a versioned plugin cache folder (old versions survive an update, so Claude
kept running 0.8 on a machine updated to 0.16). setup init writes a version-free line; setup check repairs old ones."""
import os, tempfile, unittest

from engine import setup

CACHE = '/Users/someone/.claude/plugins/cache/get-me-hired/get-me-hired/0.16.1'
OLD = 'Engine: /Users/someone/.claude/plugins/cache/get-me-hired/get-me-hired/0.8.0  (set GMH_WORKSPACE to this folder)'


class EngineLine(unittest.TestCase):
    def test_installed_plugin_line_has_no_version_folder(self):
        line = setup.engine_line(CACHE)
        self.assertNotIn('0.16.1', line)
        self.assertIn('/.claude/plugins/marketplaces/get-me-hired/bin/gmh', line)
        self.assertIn('${CLAUDE_PLUGIN_ROOT}/bin/gmh', line)
        self.assertIn("plugin's skills", line)

    def test_dev_checkout_keeps_its_path(self):
        self.assertEqual(setup.engine_line('/Users/someone/code/get-me-hired'),
                         'Engine: /Users/someone/code/get-me-hired  (set GMH_WORKSPACE to this folder)')

    def _ws(self, engine):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, 'CLAUDE.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('# Job-search workspace (x)\n\nRules here.\n\n' + engine + '\n')
        return ws

    def test_repair_rewrites_a_versioned_line_only(self):
        ws = self._ws(OLD)
        self.assertEqual(setup.repair_engine_line(ws, CACHE), OLD)
        text = open(os.path.join(ws, 'CLAUDE.md'), encoding='utf-8').read()
        self.assertNotIn('/plugins/cache/', text.split('Rules here.')[1].split('Never a versioned')[0])
        self.assertIn('Rules here.', text)
        self.assertIsNone(setup.repair_engine_line(ws, CACHE))  # already fixed: no change

    def test_repair_leaves_a_dev_line_alone(self):
        dev = 'Engine: /Users/someone/code/get-me-hired  (set GMH_WORKSPACE to this folder)'
        ws = self._ws(dev)
        self.assertIsNone(setup.repair_engine_line(ws, CACHE))
        self.assertIn(dev, open(os.path.join(ws, 'CLAUDE.md'), encoding='utf-8').read())

    def test_no_claude_md_is_fine(self):
        self.assertIsNone(setup.repair_engine_line(tempfile.mkdtemp(), CACHE))

    def test_check_reports_the_repair(self):
        ws = self._ws(OLD)
        orig = setup.REPO
        setup.REPO = CACHE
        try:
            rep = setup.check(ws)
        finally:
            setup.REPO = orig
        self.assertEqual(rep['engine_line_fixed'], OLD)
        self.assertIn('FIXED: CLAUDE.md', setup.format_check(rep))

    def test_init_writes_no_versioned_path(self):
        ws = os.path.join(tempfile.mkdtemp(), 'ws')
        orig = setup.REPO
        setup.REPO = CACHE
        try:
            setup.init(ws, 'chief-of-staff', False, 'Test User')
        finally:
            setup.REPO = orig
        text = open(os.path.join(ws, 'CLAUDE.md'), encoding='utf-8').read()
        self.assertNotIn('0.16.1', text)
        self.assertIn('marketplaces/get-me-hired', text)
        self.assertEqual(text.count(setup.DAILY_HEADING), 1)
        self.assertIn('/get-me-hired:today', text)
        self.assertFalse(setup.add_daily_section(ws))  # a new workspace already has it


class DailySection(unittest.TestCase):
    def test_check_adds_the_daily_start_once_to_an_older_workspace(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, 'CLAUDE.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('# Job-search workspace (x)\n\nRules here.\n\nEngine: /Users/someone/code/get-me-hired\n')
        rep = setup.check(ws)
        self.assertTrue(rep['daily_section_added'])
        self.assertIn('ADDED: CLAUDE.md now says how to start each day', setup.format_check(rep))
        text = open(os.path.join(ws, 'CLAUDE.md'), encoding='utf-8').read()
        self.assertTrue(text.startswith('# Job-search workspace (x)\n\nRules here.'))
        self.assertIn("Run today's job search", text)
        self.assertNotIn('daily_section_added', setup.check(ws))  # second check: nothing to add
        self.assertEqual(open(os.path.join(ws, 'CLAUDE.md'), encoding='utf-8').read().count(setup.DAILY_HEADING), 1)

    def test_check_replaces_the_retired_multi_session_section(self):
        ws = tempfile.mkdtemp()
        old = ('# Job-search workspace (x)\n\n## Starting the day\nWhen the user says "Run today\'s job search", run '
               '/get-me-hired:daily-run: ... then hand applying to a separate session\n(/get-me-hired:apply-all). In the '
               'home session (/get-me-hired:coordinator), the same phrase starts the daily run in its own session instead.\n'
               '\n## Rules\n- Keep this rule.\n')
        with open(os.path.join(ws, 'CLAUDE.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(old)
        rep = setup.check(ws)
        self.assertEqual(rep['daily_section_added'], 'updated')
        self.assertIn('UPDATED:', setup.format_check(rep))
        text = open(os.path.join(ws, 'CLAUDE.md'), encoding='utf-8').read()
        self.assertIn('/get-me-hired:today', text)
        self.assertNotIn('coordinator', text)
        self.assertNotIn('separate session', text)
        self.assertIn('## Rules\n- Keep this rule.', text)
        self.assertEqual(text.count(setup.DAILY_HEADING), 1)
        self.assertNotIn('daily_section_added', setup.check(ws))  # current now: left alone


if __name__ == '__main__':
    unittest.main()
