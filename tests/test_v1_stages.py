"""E4b: redline brief questions + ai_policy, default --out paths, fillplan apply_url/submit_script/verify gate,
the /tmp fallback, and the manual-apply table. Fictional data, no network."""
import contextlib, datetime, io, json, os, sys, tempfile, unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import linkedin, redline, stages  # noqa: E402

FACTS = 'Jordan Rivera. Product manager at Northwind. Launched a wallet that grew repeat purchases 40%.'


class AiPolicy(unittest.TestCase):
    def test_bans(self):
        for t in ('Please do not use AI tools to write your application.',
                  'Applications written by ChatGPT will not be accepted.',
                  "We don't accept AI-generated cover letters.",
                  'Candidates must not use generative AI to draft their answers.',
                  'Applicants may not use an LLM to write responses.'):
            self.assertTrue(redline.posting_bans_ai(t), t)

    def test_not_bans(self):
        for t in ('We do not use AI to screen applications.', 'You will build AI features for our product.',
                  'We use AI across the company and encourage you to apply.', 'Do not apply twice.',
                  'Tell us how you use AI in your work.', 'Remain available for the interview process.'):
            self.assertFalse(redline.posting_bans_ai(t), t)

    def test_policy_levels(self):
        attest = {'questions': [{'label': 'I have not used AI tools to complete this application'}]}
        self.assertEqual(redline.ai_policy('A normal posting.', {'questions': [{'label': 'Why us?'}]}), 'ok')
        self.assertEqual(redline.ai_policy('A normal posting.', None), 'ok')
        self.assertEqual(redline.ai_policy('A normal posting.', attest), 'ask')
        self.assertEqual(redline.ai_policy('Do not use AI to write your answers.', attest), 'banned')
        banned_form = {'questions': [{'label': 'Why us?', 'description': 'Please do not use AI to write this answer.'}]}
        self.assertEqual(redline.ai_policy('', banned_form), 'banned')


class RoleWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, 'ws')
        self.P = os.path.join(self.ws, 'Pipeline')
        for d in ('specs', 'state/jd', 'state/answers', 'queue'):
            os.makedirs(os.path.join(self.P, d))
        json.dump({'paths': {'vault': self.ws}}, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(self.ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n').write(FACTS)
        json.dump({'id': 'gh-brightwater-1', 'company': 'Brightwater', 'title': 'Senior PM'},
                  open(os.path.join(self.P, 'specs', 'brightwater.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(self.P, 'state', 'jd', 'gh-brightwater-1.txt'), 'w', encoding='utf-8', newline='\n').write('Grow a rewards product.')
        qs = [{'label': 'Why Brightwater?', 'required': True, 'type': 'textarea', 'kind': 'draft', 'answer': 'DRAFT', 'options': []},
              {'label': 'Resume', 'required': True, 'type': 'input_file', 'kind': 'draft', 'answer': 'FILE: tailored', 'options': []},
              {'label': 'Have 5+ years?', 'required': True, 'type': 'ValueSelect', 'kind': 'draft', 'answer': 'YEARS', 'options': ['Yes', 'No']},
              {'label': 'Email', 'required': True, 'type': 'input_text', 'kind': 'fixed', 'answer': 'j@example.com', 'options': []}]
        json.dump({'id': 'gh-brightwater-1', 'company': 'Brightwater', 'title': 'Senior PM', 'url': 'https://x.example/1',
                   'questions': qs}, open(os.path.join(self.P, 'state', 'answers', 'gh-brightwater-1.json'), 'w', encoding='utf-8', newline='\n'))
        self.drafts = os.path.join(self.tmp.name, 'drafts.json')

    def run_redline(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            redline.main([*args, '--workspace', self.ws])
        return out.getvalue().strip()

    def test_brief_reads_questions_from_answers_stage(self):
        path = self.run_redline('brief', self.drafts, 'brightwater')
        self.assertTrue(os.path.isabs(path))
        self.assertEqual(path, os.path.join(self.P, 'scratch', datetime.date.today().isoformat(), 'draft-brief-brightwater.json'))
        b = json.load(open(path, encoding='utf-8'))
        self.assertEqual(b['questions'], ['Why Brightwater?'])  # not the file upload, not the option question
        self.assertEqual(b['ai_policy'], 'ok')

    def test_question_flag_wins_and_out_is_honoured(self):
        out = os.path.join(self.tmp.name, 'sub', 'b.json')
        path = self.run_redline('brief', self.drafts, 'brightwater', '--question', 'Mine?', '--out', out)
        self.assertEqual(path, os.path.abspath(out))
        self.assertEqual(json.load(open(out, encoding='utf-8'))['questions'], ['Mine?'])

    def test_brief_without_answers_file_has_no_questions(self):
        os.remove(os.path.join(self.P, 'state', 'answers', 'gh-brightwater-1.json'))
        b = json.load(open(self.run_redline('brief', self.drafts, 'brightwater'), encoding='utf-8'))
        self.assertEqual((b['questions'], b['ai_policy']), ([], 'ok'))

    def test_ai_attestation_and_ban_reach_brief_and_packet(self):
        p = os.path.join(self.P, 'state', 'answers', 'gh-brightwater-1.json')
        form = json.load(open(p, encoding='utf-8'))
        form['questions'].append({'label': 'I have not used AI tools to write this application', 'required': True,
                                  'type': 'Boolean', 'kind': 'ask', 'answer': '', 'options': []})
        json.dump(form, open(p, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(json.load(open(self.run_redline('brief', self.drafts, 'brightwater'), encoding='utf-8'))['ai_policy'], 'ask')
        open(os.path.join(self.P, 'state', 'jd', 'gh-brightwater-1.txt'), 'w', encoding='utf-8', newline='\n').write('Please do not use AI to write your answers.')
        json.dump({'brightwater': {'cover': ['Dear team,'], 'answers': {}}}, open(self.drafts, 'w', encoding='utf-8', newline='\n'))
        path = self.run_redline('packet', self.drafts, 'brightwater')
        self.assertIn('review-packet-brightwater.json', path)
        self.assertEqual(json.load(open(path, encoding='utf-8'))['ai_policy'], 'banned')


class FillplanLines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.P = os.path.join(self.tmp.name, 'Pipeline')
        os.makedirs(os.path.join(self.P, 'state', 'notes'))
        os.makedirs(os.path.join(self.P, 'specs'))
        self.folder = os.path.join(self.tmp.name, 'ready', 'brightwater')
        os.makedirs(self.folder)
        self.pdf = os.path.join(self.folder, 'Jordan_Rivera_Resume_brightwater.pdf')
        self.ctx = SimpleNamespace(P=self.P, ws=self.tmp.name, vault=self.tmp.name, cfg={}, prof={}, design=None)

    def notes(self, qid, url):
        json.dump({'id': qid, 'url': url, 'folder': self.folder, 'resume': self.pdf}, open(os.path.join(self.P, 'state', 'notes', qid + '.json'), 'w', encoding='utf-8', newline='\n'))

    def test_apply_url_per_ats(self):
        self.notes('ab-acme-1', 'https://jobs.ashbyhq.com/acme/1111?utm=x')
        self.notes('ab-acme-2', 'https://jobs.ashbyhq.com/acme/2222/application')
        self.notes('gh-acme-3', 'https://job-boards.greenhouse.io/acme/jobs/3')
        self.notes('lv-acme-4', 'https://jobs.lever.co/acme/4/apply')
        self.assertEqual(stages.apply_url(self.ctx, 'ab-acme-1'), 'https://jobs.ashbyhq.com/acme/1111/application')
        self.assertEqual(stages.apply_url(self.ctx, 'ab-acme-2'), 'https://jobs.ashbyhq.com/acme/2222/application')
        self.assertEqual(stages.apply_url(self.ctx, 'gh-acme-3'), 'https://job-boards.greenhouse.io/acme/jobs/3')
        self.assertEqual(stages.apply_url(self.ctx, 'lv-acme-4'), 'https://jobs.lever.co/acme/4/apply')

    def test_submit_script_is_absolute_and_exists(self):
        for qid, ats in (('gh-a-1', 'greenhouse'), ('ab-a-1', 'ashby'), ('lv-a-1', 'lever')):
            p = stages.submit_script(qid)
            self.assertTrue(os.path.isabs(p) and os.path.exists(p), p)
            self.assertTrue(p.endswith(f'submit_{ats}.js'))

    def test_resume_problems(self):
        self.notes('gh-brightwater-1', 'https://x.example/1')
        self.assertIn('not found', stages.resume_problems(self.ctx, 'gh-brightwater-1')[0])
        open(self.pdf, 'wb').write(b'%PDF')
        self.assertEqual(stages.resume_problems(self.ctx, 'gh-brightwater-1'), [])  # no spec/JSON: nothing to re-check
        json.dump({'id': 'gh-brightwater-1', 'slug': 'brightwater'}, open(os.path.join(self.P, 'specs', 'b.json'), 'w', encoding='utf-8', newline='\n'))
        json.dump({'name': 'X', '_built_from': 'tpl'}, open(os.path.join(self.folder, 'resume_brightwater.json'), 'w', encoding='utf-8', newline='\n'))
        seen = {}

        def fake_verify(pdf, doc, prof, cfg, bank, jd, terms, facts=None, design=None):
            seen.update(pdf=pdf, doc=doc)
            return ['2 pages'], []
        with mock.patch.object(stages, 'verify', fake_verify), mock.patch.object(stages.specs_mod, 'load_bank', lambda ws: {}), \
                mock.patch.object(stages, '_term_re', lambda ctx: None):
            self.assertEqual(stages.resume_problems(self.ctx, 'gh-brightwater-1'), ['2 pages'])
        self.assertEqual((seen['pdf'], seen['doc']), (self.pdf, {'name': 'X'}))

    def test_main_refuses_and_prints_lines(self):
        qid = 'ab-brightwater-9'
        ctx = SimpleNamespace(P=self.P, first='Jordan')
        plan_calls = []

        def fake_plan(c, q):
            plan_calls.append(q)
            return os.path.join(self.P, 'state', 'fillplans', q + '.js'), [1, 2], ['x']
        self.notes(qid, 'https://jobs.ashbyhq.com/brightwater/9')
        for problems, code in (([], 0), (['bad'], 1)):
            out = io.StringIO()
            with mock.patch.object(stages, 'Ctx', lambda ws: self.ctx), mock.patch.object(stages, 'build_fillplan', fake_plan), \
                    mock.patch.object(stages, 'resume_problems', lambda c, q: problems), \
                    mock.patch('engine.setup.stage_problems', lambda ws, st: []), contextlib.redirect_stdout(out):
                self.ctx.snapshot = lambda: None
                with self.assertRaises(SystemExit) as cm:
                    stages.main(['--workspace', self.tmp.name, 'fillplan', qid])
            self.assertEqual(cm.exception.code, code)
            text = out.getvalue()
            if code == 0:
                self.assertIn('apply_url: https://jobs.ashbyhq.com/brightwater/9/application', text)
                self.assertIn('submit_script: ' + stages.submit_script(qid), text)
            else:
                self.assertIn('not planned', text)
                self.assertNotIn('apply_url', text)
        self.assertEqual(plan_calls, [qid])  # the refused run built nothing


class TempDir(unittest.TestCase):
    def test_cover_uses_tempfile_gettempdir(self):
        seen = {}
        class Prof(dict):
            def require(self, k):
                return self[k]
        ctx = SimpleNamespace(prof=Prof({'identity.first_name': 'Jordan', 'identity.last_name': 'Rivera'}), node_path='', design={}, cfg={})

        def stop(cmd, **kw):
            seen['json'] = [c for c in cmd if c.endswith('.json')]
            raise RuntimeError('stop')
        td = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(td, True))
        with mock.patch.object(stages, 'full_name', lambda p: 'Jordan Rivera'), mock.patch.object(stages, 'contact_lines', lambda p: []), \
                mock.patch.object(stages.subprocess, 'run', stop), mock.patch.object(stages.tempfile, 'gettempdir', lambda: td):
            with self.assertRaises(RuntimeError):
                stages._cover(ctx, 'Brightwater', 'Jan 1, 2026', ['Hi'], 'folder', 'brightwater')
        self.assertEqual(seen['json'], [os.path.join(td, 'cl_brightwater.json')])


class ManualTable(unittest.TestCase):
    def test_table_rows_and_links(self):
        with tempfile.TemporaryDirectory() as d:
            notes = os.path.join(d, '02-Ready to Apply', 'brightwater', 'application-notes.md')
            cover = os.path.join(d, '02-Ready to Apply', 'brightwater', 'Jordan_Cover_brightwater.pdf')
            t = stages.manual_apply_table([
                dict(company='Brightwater', title='Senior PM | Rewards', url='https://x.example/1', notes=notes, cover=cover),
                dict(company='Lumen', title='PM', url='https://x.example/2', notes=notes, cover=None)])
        lines = t.splitlines()
        self.assertEqual(lines[0], '| Company | Role | Posting | Application notes | Cover letter |')
        self.assertEqual(len(lines), 4)
        self.assertIn('Senior PM / Rewards', lines[2])
        self.assertIn('[posting](https://x.example/1)', lines[2])
        self.assertIn('file://', lines[2])
        self.assertIn('Ready%20to%20Apply', lines[2])
        self.assertTrue(lines[2].rstrip().endswith('Jordan_Cover_brightwater.pdf](' + lines[2].split('](')[-1]))
        self.assertTrue(lines[3].endswith('| none |'))
        self.assertNotIn('ROW:', t)


class ManualNotesPrintsTable(unittest.TestCase):
    def test_table_printed_at_end(self):
        from tests.test_manual_notes_cover import ManualNotesCover
        case = ManualNotesCover('test_approved_cover_becomes_a_document_and_is_named_in_the_notes')
        case.setUp()
        self.addCleanup(lambda: __import__('shutil').rmtree(case.ws, True))
        case.drafts('2026-01-05', {'brightwater': {'cover': ['Dear Brightwater team,']}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            case.run_stage()
        text = out.getvalue()
        self.assertIn('| Company | Role | Posting | Application notes | Cover letter |', text)
        table = text.split('| Company |', 1)[1].splitlines()
        self.assertEqual(len(table), 4)  # header rest, rule, two manual roles
        self.assertIn('[posting](https://example.com/brightwater)', table[2])
        self.assertIn('Jordan_Rivera_Cover_Letter_brightwater.pdf', table[2])
        self.assertTrue(table[3].endswith('| none |'))


if __name__ == '__main__':
    unittest.main()
