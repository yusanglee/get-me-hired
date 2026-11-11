"""Each application stage checks what it needs before it writes anything (setup.stage_problems), and the stages
use the workspace when config has no paths.vault, as discover and the other commands already did."""
import contextlib, io, json, os, tempfile, unittest
from unittest import mock

from engine import setup, stages


def workspace(root, profile=True, config=True, template=False, vault=None):
    ws = os.path.join(root, 'ws')
    os.makedirs(ws)
    if profile:
        open(os.path.join(ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write(
            'identity:\n  first_name: Jordan\n  last_name: Rivera\n  email: jordan@example.com\n')
    if config:
        json.dump({'paths': {'vault': vault}} if vault else {}, open(os.path.join(ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
    if template:
        os.makedirs(os.path.join(ws, 'resume', 'templates'))
        open(os.path.join(ws, 'resume', 'templates', 'base.json'), 'w', encoding='utf-8', newline='\n').write('{}')
    return ws


class StageProblems(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ready_workspace_has_none(self):
        ws = workspace(self.tmp.name)
        for stage in ('answers', 'manual-notes', 'fillplan'):
            self.assertEqual(setup.stage_problems(ws, stage), [], stage)

    def test_missing_profile_and_config(self):
        probs = setup.stage_problems(workspace(self.tmp.name, profile=False, config=False), 'answers')
        self.assertTrue(any('profile.yaml' in p for p in probs))
        self.assertTrue(any('config.json' in p for p in probs))

    def test_profile_without_required_fields(self):
        ws = workspace(self.tmp.name)
        open(os.path.join(ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write('identity:\n  first_name: Jordan\n')
        self.assertTrue(any('identity.last_name' in p for p in setup.stage_problems(ws, 'fillplan')))

    def test_specs_and_tailor_need_a_template(self):
        ws = workspace(self.tmp.name)
        with mock.patch.object(setup, 'tools_problems', return_value=[]):
            self.assertTrue(any('resume template' in p for p in setup.stage_problems(ws, 'specs')))
            self.assertTrue(any('resume template' in p for p in setup.stage_problems(ws, 'tailor')))
            self.assertEqual(setup.stage_problems(ws, 'answers'), [])

    def test_builds_need_the_tools(self):
        ws = workspace(self.tmp.name, template=True)
        with mock.patch.object(setup, 'tools_problems', return_value=['LibreOffice not found']):
            self.assertEqual(setup.stage_problems(ws, 'tailor'), ['LibreOffice not found'])
            self.assertEqual(setup.stage_problems(ws, 'notes'), ['LibreOffice not found'])
            self.assertEqual(setup.stage_problems(ws, 'specs'), [])

    def test_pdf_tools_are_checked(self):
        found = {'node': '/bin/node'}
        with mock.patch('shutil.which', side_effect=found.get):
            probs = setup.tools_problems({}, self.tmp.name)
        self.assertTrue(any('pdftotext' in p for p in probs))


class StagesMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_stops_before_writing(self):
        ws = workspace(self.tmp.name, template=True)
        err = io.StringIO()
        with mock.patch.object(setup, 'tools_problems', return_value=['Node.js not found']), \
                mock.patch.object(stages, 'stage_tailor') as tailor, contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                stages.main(['--workspace', ws, 'tailor', 'spec.json'])
        self.assertIn('Node.js not found', str(cm.exception.code))
        tailor.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(ws, 'Pipeline')))  # no snapshot either

    def test_vault_defaults_to_workspace(self):
        ws = workspace(self.tmp.name)
        self.assertEqual(stages.Ctx(ws).vault, ws)
        vault = os.path.join(self.tmp.name, 'vault')
        ws2 = workspace(os.path.join(self.tmp.name, 'other'), vault=vault)
        self.assertEqual(stages.Ctx(ws2).vault, vault)


if __name__ == '__main__':
    unittest.main()
