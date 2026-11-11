"""setup check takes the workspace the way the other stages do (--workspace), and keeps the positional.
commands/daily-run.md said `gmh setup check --workspace <ws>` while check accepted only the positional, so the
day's first step failed with "unrecognized arguments"."""
import contextlib, io, os, re, unittest
from unittest import mock

from engine import setup, profile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SetupCheckCli(unittest.TestCase):
    def _run(self, argv, env=None):
        seen = []
        with mock.patch.object(setup, 'check', side_effect=lambda ws: seen.append(ws) or {}), \
                mock.patch.object(setup, 'format_check', return_value='ok'), \
                mock.patch.dict(os.environ, env or {}, clear=False), contextlib.redirect_stdout(io.StringIO()):
            if env is None:
                os.environ.pop('GMH_WORKSPACE', None)
            setup.main(argv)
        return seen

    def test_positional(self):
        self.assertEqual(self._run(['check', '/tmp/ws-a']), ['/tmp/ws-a'])

    def test_workspace_flag(self):
        self.assertEqual(self._run(['check', '--workspace', '/tmp/ws-a']), ['/tmp/ws-a'])
        self.assertEqual(self._run(['check', '--workspace', '/tmp/ws-a', '--json']), ['/tmp/ws-a'])

    def test_env_fallback(self):
        self.assertEqual(self._run(['check'], env={'GMH_WORKSPACE': '/tmp/ws-env'}), ['/tmp/ws-env'])

    def test_both_same_ok_different_refused(self):
        self.assertEqual(self._run(['check', '/tmp/ws-a', '--workspace', '/tmp/ws-a']), ['/tmp/ws-a'])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self._run(['check', '/tmp/ws-a', '--workspace', '/tmp/ws-b'])

    def test_no_workspace_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self._run(['check'])

    def test_every_documented_setup_check_parses(self):
        """Each `gmh setup check ...` in the shipped skills, references, commands, agents and docs must parse."""
        import glob
        found = 0
        for pattern in ('skills/**/*.md', 'references/*.md', 'commands/*.md', 'subagents/*.md', 'docs/*.md'):
            for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
                name = os.path.relpath(path, ROOT)
                with open(path, encoding='utf-8') as fh:
                    body = fh.read()
                for m in re.finditer(r'gmh setup check([^`\n]*)`', body):
                    args = m.group(1).replace('<ws>', '/tmp/ws').replace('<folder>', '/tmp/ws').split()
                    found += 1
                    self.assertEqual(self._run(['check'] + args, env={'GMH_WORKSPACE': '/tmp/ws'}), ['/tmp/ws'],
                                     f'{name}: gmh setup check{m.group(1)}')
        self.assertGreater(found, 2)


REP = dict(workspace='/w', privacy=[], profile_error='x', config_missing=[], resume_templates=[], resume_drafts=[],
           resume_versions=0, companies=dict(listed=0, resolved=0, unresolved=[], not_probed=[]), tracker_rows=0, sheet_mirror=False)


class ReadyToApply(unittest.TestCase):
    def test_browser_problems(self):
        with mock.patch('shutil.which', return_value=None), mock.patch('os.path.exists', return_value=False):
            got = setup.browser_problems()
        self.assertEqual(len(got), 2)
        self.assertIn('npx', got[0])
        self.assertIn('npx playwright install chrome', got[1])
        with mock.patch('shutil.which', side_effect=lambda c: '/usr/bin/' + c if c in ('npx', 'chromium') else None), \
                mock.patch('os.path.exists', return_value=False):
            self.assertEqual(setup.browser_problems(), [])
        with mock.patch('shutil.which', side_effect=lambda c: '/x/npx' if c == 'npx' else None), \
                mock.patch('os.path.exists', side_effect=lambda p: p == '/Applications/Google Chrome.app'):
            self.assertEqual(setup.browser_problems(), [])

    def test_ready_stays_about_finding_roles(self):
        rep = dict(REP, ready=True, tools=['Node.js not found (https://nodejs.org)'], browser=[], ready_to_apply=False)
        out = setup.format_check(rep)
        self.assertNotIn('READY for discover/tailor', out)
        self.assertIn('Find and score roles: READY', out)
        self.assertIn('Build resumes and fill application forms: NOT ready', out)
        self.assertIn('  - Node.js not found', out)

    def test_both_ready(self):
        out = setup.format_check(dict(REP, ready=True, tools=[], browser=[], ready_to_apply=True))
        self.assertIn('Find and score roles: READY', out)
        self.assertIn('Build resumes and fill application forms: READY', out)

    def test_not_ready_to_find(self):
        out = setup.format_check(dict(REP, ready=False, tools=[], browser=['Google Chrome not found: x'], ready_to_apply=False))
        self.assertIn('Find and score roles: not ready', out)
        self.assertIn('  - Google Chrome not found', out)

    def test_check_report_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ws, mock.patch.object(setup, 'tools_problems', return_value=['t']), \
                mock.patch.object(setup, 'browser_problems', return_value=[]):
            rep = setup.check(ws)
        self.assertEqual((rep['tools'], rep['browser'], rep['ready'], rep['ready_to_apply']), (['t'], [], False, False))


class SofficeTimeout(unittest.TestCase):
    def test_timeout_message(self):
        import subprocess

        def hang(cmd, **kw):
            self.assertEqual(kw['timeout'], 180)
            raise subprocess.TimeoutExpired(cmd, 180)
        with mock.patch('subprocess.run', side_effect=hang), self.assertRaises(RuntimeError) as cm:
            profile.soffice_pdf('/x/soffice', '/out', '/out/Resume_Brightwater.docx')
        self.assertIn("LibreOffice didn't finish converting Resume_Brightwater.docx in 3 minutes", str(cm.exception))
        self.assertIn('close any open LibreOffice windows', str(cm.exception))

    def test_arguments_unchanged(self):
        with mock.patch('subprocess.run') as run:
            profile.soffice_pdf('/x/soffice', '/out', 'a.docx', 'b.docx')
        self.assertEqual(run.call_args[0][0], ['/x/soffice', '--headless', '--convert-to', 'pdf', '--outdir', '/out', 'a.docx', 'b.docx'])


if __name__ == '__main__':
    unittest.main()
