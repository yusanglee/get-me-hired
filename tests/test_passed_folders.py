"""A pass pick moves the role's built folder from Workflow/02-Ready to Apply to Workflow/Passed, a later
apply/manual/hold moves it back, and `gmh review folders` is the one-way catch-up. Fictional Chief of Staff
fixture run from test_discover_score (Acme Robotics, Globex, Initech). No network."""
import contextlib, csv, io, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from engine import runrecord, score  # noqa: E402
import test_runrecord as TR  # noqa: E402

DATE = TR.DATE
NAME = '2026-10-20 Acme Robotics - Chief of Staff'


class PassedFolders(TR.Fixture):
    def setUp(self):
        super().setUp()
        self.ctx, _ = self.discover()
        score.run(self.ctx, out=lambda *a: None)
        rec = json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))
        self.ref = {r['id']: r['ref'] for r in rec['roles']}
        self.wf = os.path.join(self.ctx.vault, 'Workflow')
        specs = os.path.join(self.ctx.vault, 'Pipeline', 'specs')
        os.makedirs(specs, exist_ok=True)
        with open(os.path.join(specs, 'Acme.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'slug': 'Acme', 'id': 'gh-acme-1', 'company': 'Acme Robotics', 'title': 'Chief of Staff',
                       'folder': NAME}, fh)
        self.make(runrecord.READY)

    def make(self, stage):
        d = os.path.join(self.wf, stage, NAME)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'resume.pdf'), 'w', encoding='utf-8', newline='\n').close()

    def at(self, stage):
        return os.path.isdir(os.path.join(self.wf, stage, NAME))

    def pick(self, text, dry_run=False):
        return runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(text), dry_run)[0]

    def test_pass_moves_to_passed_and_apply_moves_back(self):
        b = self.ref['gh-acme-1']
        lines = self.pick(f'pass {b}: comp too low')
        self.assertTrue(self.at(runrecord.PASSED))
        self.assertFalse(self.at(runrecord.READY))
        self.assertIn(f'moved: Acme Robotics: Chief of Staff to the CEO [pass]  02-Ready to Apply -> Passed/{NAME}', lines)
        self.assertEqual(self.pick(f'pass {b}')[1:], [])  # repeat: nothing left to move
        for call in ('hold', 'pass', 'manual', 'pass', 'apply'):
            self.pick(f'{call} {b}')
            self.assertTrue(self.at(runrecord.PASSED if call == 'pass' else runrecord.READY), call)
        self.assertTrue(os.path.exists(os.path.join(self.wf, runrecord.READY, NAME, 'resume.pdf')))

    def test_dry_run_and_clear_move_nothing(self):
        b = self.ref['gh-acme-1']
        lines = self.pick(f'pass {b}', dry_run=True)
        self.assertTrue(any(l.startswith('would move: Acme Robotics') for l in lines))
        self.assertTrue(self.at(runrecord.READY))
        self.pick(f'clear {b}')
        self.assertTrue(self.at(runrecord.READY))

    def test_existing_destination_is_left_alone(self):
        self.make(runrecord.PASSED)
        lines = self.pick(f'pass {self.ref["gh-acme-1"]}')
        self.assertTrue(self.at(runrecord.READY) and self.at(runrecord.PASSED))
        self.assertIn('left alone (Passed already has it)', lines[-1])

    def test_roles_without_a_ready_folder_are_skipped(self):
        os.rename(os.path.join(self.wf, runrecord.READY, NAME), os.path.join(self.wf, '03-Applied', NAME))
        self.assertEqual(self.pick(f'pass {self.ref["gh-acme-1"]}')[1:], [])  # an applied folder never moves
        self.assertTrue(self.at('03-Applied'))
        self.assertEqual(self.pick(f'pass {self.ref["ab-globex-1"]}')[1:], [])  # no spec, no folder

    def folders(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runrecord.main(['folders', '--workspace', self.ctx.ws, *argv])
        return out.getvalue()

    def write_reviewed(self, date, call):
        cols = runrecord.REVIEWED_COLUMNS
        with open(os.path.join(self.ctx.queue, f'reviewed-{date}.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerow({**{c: '' for c in cols}, 'call': call, 'id': 'gh-acme-1', 'company': 'Acme Robotics',
                        'title': 'Chief of Staff'})

    def test_catch_up_uses_the_latest_call_and_only_moves_to_passed(self):
        self.write_reviewed('2026-10-01', 'pass')
        self.write_reviewed('2026-10-02', 'apply')  # newer call: stays in Ready
        self.assertIn('0 passed role folder(s) to move', self.folders('--dry-run'))
        self.write_reviewed('2026-10-03', 'pass')
        out = self.folders('--dry-run')
        self.assertIn('would move: Acme Robotics: Chief of Staff [pass]', out)
        self.assertIn('1 passed role folder(s) to move to Workflow/Passed, 0 left alone (dry run, nothing moved)', out)
        self.assertTrue(self.at(runrecord.READY))
        self.assertIn('1 passed role folder(s) moved', self.folders())
        self.assertTrue(self.at(runrecord.PASSED))
        self.write_reviewed('2026-10-04', 'apply')  # a stale apply never pulls a folder back out of Passed
        self.folders()
        self.assertTrue(self.at(runrecord.PASSED))
        self.assertFalse(self.at(runrecord.READY))


if __name__ == '__main__':
    unittest.main()
