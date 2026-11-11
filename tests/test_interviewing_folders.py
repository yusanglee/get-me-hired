"""A row that reaches interviewing (or offer) moves its Workflow folder from 03-Applied to 04-Interviewing:
tracker.move_folders, `tracker set`, `tracker folders` (the catch-up) and the Gmail import. Fictional data only."""
import contextlib, io, json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import gmail_import as gi, tracker  # noqa: E402

APPLIED = 'Workflow/03-Applied/2026-10-19 Brightwater - Senior PM Growth'
MOVED = 'Workflow/04-Interviewing/2026-10-19 Brightwater - Senior PM Growth'


class InterviewingFolders(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.vault = os.path.join(self.ws, 'vault')
        for stage in ('03-Applied', '04-Interviewing'):
            os.makedirs(os.path.join(self.vault, 'Workflow', stage))
        self.make(APPLIED)
        with open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'paths': {'vault': self.vault}}, fh)
        self.rows = []
        for co, title, folder in (('Brightwater', 'Senior PM, Growth', APPLIED),
                                  ('Northwind', 'Staff PM', 'Workflow/03-Applied/2026-10-20 Northwind - Staff PM')):
            tracker.upsert(self.rows, {'company': co, 'title': title, 'id': co.lower(), 'date_applied': '2026-10-20',
                                       'status': 'applied', 'status_date': '2026-10-20', 'folder': folder})
        self.make(self.rows[1]['folder'])
        tracker.write(tracker.path_of(self.ws), self.rows)

    def tearDown(self):
        shutil.rmtree(self.ws)

    def make(self, folder):
        d = os.path.join(self.vault, folder)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'resume.pdf'), 'w', encoding='utf-8', newline='\n').close()

    def at(self, folder):
        return os.path.isdir(os.path.join(self.vault, folder))

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tracker.main(list(argv) + ['--workspace', self.ws])
        return out.getvalue()

    def test_interviewing_moves_folder_and_cell(self):
        r = self.rows[0]
        r['status'] = 'interviewing'
        moves = tracker.move_folders(self.rows, self.vault)
        self.assertEqual([m['action'] for m in moves], ['move'])
        self.assertEqual(r['folder'], MOVED)
        self.assertTrue(self.at(MOVED))
        self.assertFalse(self.at(APPLIED))
        self.assertEqual(self.rows[1]['folder'], 'Workflow/03-Applied/2026-10-20 Northwind - Staff PM')  # still applied
        d, files = tracker.materials(r, self.vault)  # readers follow the new cell
        self.assertEqual(d, os.path.join(self.vault, MOVED))
        self.assertEqual([os.path.basename(f) for f in files], ['resume.pdf'])

    def test_repeat_is_a_no_op_and_relink_fixes_a_lagging_cell(self):
        r = self.rows[0]
        r['status'] = 'offer'
        tracker.move_folders(self.rows, self.vault)
        self.assertEqual(tracker.move_folders(self.rows, self.vault), [])  # already in 04-Interviewing
        r['folder'] = APPLIED  # folder moved by hand, cell not updated
        self.assertEqual([m['action'] for m in tracker.move_folders(self.rows, self.vault)], ['relink'])
        self.assertEqual(r['folder'], MOVED)

    def test_existing_destination_is_left_alone(self):
        self.make(MOVED)
        r = self.rows[0]
        r['status'] = 'interviewing'
        self.assertEqual([m['action'] for m in tracker.move_folders(self.rows, self.vault)], ['conflict'])
        self.assertEqual(r['folder'], APPLIED)
        self.assertTrue(self.at(APPLIED) and self.at(MOVED))

    def test_missing_folder_and_other_statuses(self):
        r = self.rows[0]
        shutil.rmtree(os.path.join(self.vault, APPLIED))
        r['status'] = 'interviewing'
        self.assertEqual([m['action'] for m in tracker.move_folders(self.rows, self.vault)], ['missing'])
        self.assertEqual(r['folder'], APPLIED)
        for st in ('applied', 'assessment', 'rejected', 'withdrawn'):
            r['status'] = st
            self.assertEqual(tracker.move_folders(self.rows, self.vault), [], st)

    def test_dry_run_changes_nothing(self):
        self.rows[0]['status'] = 'interviewing'
        moves = tracker.move_folders(self.rows, self.vault, dry_run=True)
        self.assertEqual([m['action'] for m in moves], ['move'])
        self.assertEqual(self.rows[0]['folder'], APPLIED)
        self.assertTrue(self.at(APPLIED))
        self.assertIn('would move: Brightwater', tracker.describe_move(moves[0], dry_run=True))

    def test_absolute_folder_cell(self):
        r = self.rows[0]
        r['folder'], r['status'] = os.path.join(self.vault, APPLIED), 'interviewing'
        tracker.move_folders(self.rows, self.vault)
        self.assertEqual(r['folder'], os.path.join(self.vault, MOVED))
        self.assertTrue(self.at(MOVED))

    def test_set_moves_only_that_row(self):
        tracker.set_status(self.rows, 'northwind', 'interviewing', '2026-10-21')  # another row lags, untouched by set
        tracker.write(tracker.path_of(self.ws), self.rows)
        out = self.cli('set', 'brightwater', 'interviewing', '--date', '2026-10-26')
        self.assertIn('moved: Brightwater', out)
        self.assertIn(f'    {APPLIED}\n -> {MOVED}', out)  # from the old path, after the cell changed
        rows = {r['id']: r for r in tracker.read(tracker.path_of(self.ws))}
        self.assertEqual(rows['brightwater']['folder'], MOVED)
        self.assertTrue(rows['northwind']['folder'].startswith('Workflow/03-Applied/'))
        self.assertIn(MOVED, self.cli('materials', 'brightwater'))

    def test_folders_catch_up_dry_run_then_apply(self):
        for r in self.rows:
            r['status'] = 'interviewing'
        tracker.write(tracker.path_of(self.ws), self.rows)
        before = open(tracker.path_of(self.ws), encoding='utf-8').read()
        out = self.cli('folders', '--dry-run')
        self.assertIn('2 row(s) whose folder lags their status (dry run', out)
        self.assertEqual(open(tracker.path_of(self.ws), encoding='utf-8').read(), before)
        self.assertTrue(self.at(APPLIED))
        self.assertIn('moved: Northwind', self.cli('folders'))
        self.assertEqual([r['folder'].split('/')[1] for r in tracker.read(tracker.path_of(self.ws))], ['04-Interviewing'] * 2)
        self.assertIn('0 row(s)', self.cli('folders'))

    def test_gmail_import_moves_rows_it_advances(self):
        tracker.set_status(self.rows, 'northwind', 'interviewing', '2026-10-21')  # lagging, not in this approval
        tracker.write(tracker.path_of(self.ws), self.rows)
        prop = {'rows': [{'n': 1, 'company': 'Brightwater', 'title': 'Senior PM, Growth', 'status': 'interviewing',
                          'status_date': '2026-10-26', 'date_applied': '2026-10-20', 'gmail_ids': 'm01',
                          'job_key': self.rows[0]['job_key']}], 'dismissed': [], 'created': '2026-10-26'}
        res = gi.apply(prop, self.ws, '1')
        self.assertEqual([m['action'] for m in res['moves']], ['move'])
        rows = {r['id']: r for r in tracker.read(tracker.path_of(self.ws))}
        self.assertEqual(rows['brightwater']['folder'], MOVED)
        self.assertTrue(rows['northwind']['folder'].startswith('Workflow/03-Applied/'))


if __name__ == '__main__':
    unittest.main()
