"""v1.0 E5: tracker find / prep / sheet-rows / statuses and `gmh check-text`. Fictional people and companies only."""
import io, os, sys, tempfile, unittest, zipfile
from contextlib import redirect_stderr, redirect_stdout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import checktext, tracker

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def docx(path, lines):
    body = ''.join(f'<w:p><w:r><w:t>{l}</w:t></w:r></w:p>' for l in lines)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', f'<w:document><w:body>{body}</w:body></w:document>')


ROWS = [
    {'company': 'Brightwater', 'title': 'Senior Product Manager, Payments', 'id': 'gh-brightwater-1', 'job_key': 'brightwater|spm',
     'status': 'applied', 'status_date': '2026-10-01', 'date_applied': '2026-10-01'},
    {'company': 'Harbor Labs', 'title': 'Staff Product Manager', 'id': 'ab-harbor-9', 'job_key': 'harbor|spm',
     'status': 'interviewing', 'status_date': '2026-11-02', 'date_applied': '2026-10-10', 'folder': 'Workflow/04-Interviewing/Harbor'},
]


def run(fn, argv):
    out, err, code = io.StringIO(), io.StringIO(), 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            fn(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
    return code, out.getvalue(), err.getvalue()


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = self.tmp.name
        tracker.write(tracker.path_of(self.ws), [dict(r) for r in ROWS])
        self.folder = os.path.join(self.ws, 'Workflow', '04-Interviewing', 'Harbor')
        os.makedirs(self.folder)
        docx(os.path.join(self.folder, 'Jordan Rivera Resume.docx'),
             ['Jordan Rivera', 'Grew weekly active users 40% across 3 launches', 'Led a team of 12 engineers', 'Shipped on time'])
        docx(os.path.join(self.folder, 'Jordan Rivera Cover Letter.docx'), ['Dear team'])
        with open(os.path.join(self.folder, 'posting.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('Staff PM at Harbor Labs')
        with open(os.path.join(self.ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('Grew weekly active users 40% across 3 launches. Led 12 engineers. Founded in 2019.')

    def tearDown(self):
        self.tmp.cleanup()


class Find(unittest.TestCase):
    def test_ranking_and_none(self):
        self.assertEqual(tracker.fuzzy(ROWS, 'harbor staff')[0]['company'], 'Harbor Labs')
        self.assertEqual(tracker.fuzzy(ROWS, 'brightln payments')[0]['company'], 'Brightwater')  # typo, difflib
        self.assertEqual(tracker.fuzzy(ROWS, 'ab-harbor-9')[0]['id'], 'ab-harbor-9')
        self.assertEqual(tracker.fuzzy(ROWS, 'zzzz qqqq'), [])

    def test_at_most_five(self):
        rows = [{'company': f'Acme {i}', 'title': 'Product Manager', 'id': f'x{i}'} for i in range(9)]
        self.assertEqual(len(tracker.fuzzy(rows, 'acme product manager')), 5)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            tracker.write(tracker.path_of(d), [dict(r) for r in ROWS])
            code, out, _ = run(tracker.main, ['find', 'harbor', '--workspace', d])
            self.assertEqual(code, 0)
            self.assertIn('ab-harbor-9\tHarbor Labs\tStaff Product Manager\tinterviewing\t2026-11-02', out)
            code, out, err = run(tracker.main, ['find', 'nonexistent', 'thing', '--workspace', d])
            self.assertEqual((code, out), (1, ''))
            self.assertIn('no tracker row', err)


class Statuses(unittest.TestCase):
    def test_lists_vocabulary_marks_closed(self):
        code, out, _ = run(tracker.main, ['statuses'])
        lines = out.splitlines()
        self.assertEqual([l.split()[0] for l in lines], tracker.STATUSES)
        self.assertIn('rejected (closed)', lines)
        self.assertIn('applied', lines)


class SheetRows(Workspace):
    def test_since_and_state(self):
        code, out, _ = run(tracker.main, ['sheet-rows', '--since', '2026-11-01', '--workspace', self.ws])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        cols = out.rstrip('\n').split('\t')
        self.assertEqual(len(cols), len(tracker.COLUMNS))
        self.assertEqual(cols[tracker.COLUMNS.index('id')], 'ab-harbor-9')
        # no state, no --since: every row
        self.assertEqual(len(run(tracker.main, ['sheet-rows', '--workspace', self.ws])[1].strip().splitlines()), 2)
        # --mark records the date; the next run reads it
        before = open(tracker.path_of(self.ws), 'rb').read()
        run(tracker.main, ['sheet-rows', '--mark', '--date', '2026-11-05', '--workspace', self.ws])
        self.assertEqual(tracker.last_mirror(self.ws), '2026-11-05')
        self.assertEqual(run(tracker.main, ['sheet-rows', '--workspace', self.ws])[1].strip(), '')
        self.assertEqual(open(tracker.path_of(self.ws), 'rb').read(), before)  # tracker.csv untouched

    def test_cells_are_one_line(self):
        rows = [{**ROWS[0], 'notes': 'a\nb\tc'}]
        self.assertEqual(len(tracker.tsv(rows).splitlines()), 1)
        self.assertEqual(tracker.tsv(rows).count('\t'), len(tracker.COLUMNS) - 1)


class Prep(Workspace):
    def test_numbers_with_source_lines_and_paths(self):
        code, out, _ = run(tracker.main, ['prep', 'ab-harbor-9', '--workspace', self.ws])
        self.assertEqual(code, 0)
        self.assertIn('# Interview prep: Staff Product Manager at Harbor Labs', out)
        self.assertIn('- 40%: "Grew weekly active users 40% across 3 launches"', out)
        self.assertIn('- 12: "Led a team of 12 engineers"', out)
        self.assertNotIn('Shipped on time"', out)
        self.assertIn(os.path.join(self.folder, 'Jordan Rivera Resume.docx'), out)
        self.assertIn(os.path.join(self.folder, 'Jordan Rivera Cover Letter.docx'), out)
        self.assertIn(os.path.join(self.folder, 'posting.md'), out)

    def test_unknown_key_exits(self):
        self.assertNotEqual(run(tracker.main, ['prep', 'nope', '--workspace', self.ws])[0], 0)


class CheckText(Workspace):
    def check(self, kind, text, id_='ab-harbor-9'):
        p = os.path.join(self.ws, 'draft.txt')
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        argv = [kind, p, '--workspace', self.ws] + (['--id', id_] if id_ else [])
        return run(checktext.main, argv)

    def test_ok(self):
        code, out, _ = self.check('followup', 'Hi Sam,\n\nI led 12 engineers and grew users 40%.\n\nThanks, Jordan')
        self.assertEqual((code, out.strip()), (0, 'ok'))

    def test_problems_one_line_each(self):
        code, out, _ = self.check('thank-you', 'Hi Sam, great talk — I grew revenue 90% and I have not run a P&L.')
        self.assertEqual(code, 1)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(any('dash' in l for l in lines))
        self.assertTrue(any('90%' in l for l in lines))
        self.assertTrue(any('volunteers a gap' in l for l in lines))

    def test_length_limits(self):
        self.assertEqual(self.check('note', 'x' * 301)[0], 1)
        self.assertEqual(self.check('note', 'x' * 300)[0], 0)
        self.assertEqual(self.check('followup', 'word ' * 151)[0], 1)
        self.assertEqual(self.check('thank-you', 'word ' * 200)[0], 0)
        self.assertEqual(self.check('cover', 'word ' * 381)[0], 1)
        self.assertEqual(self.check('answer', 'word ' * 500)[0], 0)

    def test_without_id_uses_master_resume(self):
        self.assertEqual(self.check('note', 'Founded in 2019.', id_=None)[0], 0)
        self.assertEqual(self.check('note', 'Founded in 2015.', id_=None)[0], 1)

    def test_comments_ignored_and_missing_facts_flagged(self):
        self.assertEqual(self.check('followup', 'Hi Sam,\n<!-- — 99% -->\nThanks')[0], 0)
        os.remove(os.path.join(self.ws, 'master-resume.md'))
        code, out, _ = self.check('answer', 'Hello', id_=None)
        self.assertEqual(code, 1)
        self.assertIn('cannot be checked', out)

    def test_templates_exist(self):
        for t in ('interview-prep.md', 'followup-email.md', 'thank-you.md'):
            with open(os.path.join(REPO, 'templates', t), encoding='utf-8') as fh:
                self.assertIn('{', fh.read())


if __name__ == '__main__':
    unittest.main()
