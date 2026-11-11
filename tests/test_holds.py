"""Roles on hold come from the reviewed CSVs, never from tracker rows (tracker.holds), and the dashboard lists them
in an On hold section. Fictional companies only (Brightwater, Northwind, Acme Robotics, Globex)."""
import contextlib, csv, datetime, io, json, os, re, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import dashboard, runrecord, tracker  # noqa: E402

TODAY = datetime.date(2026, 11, 10)


class Holds(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.vault = os.path.join(self.ws, 'vault')
        self.queue = os.path.join(self.vault, 'Pipeline', 'queue')
        os.makedirs(self.queue)
        os.makedirs(os.path.join(self.vault, 'Pipeline', 'specs'))
        with open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'paths': {'vault': self.vault}}, fh)
        self.reviewed('2026-10-20', [('gh-bright-1', 'Brightwater', 'Staff PM, Growth', 'hold', 'waiting on referral'),
                                     ('gh-north-1', 'Northwind', 'Senior PM', 'hold', ''),
                                     ('gh-acme-1', 'Acme Robotics', 'Lead PM', 'hold', ''),
                                     ('gh-globex-1', 'Globex', 'Principal PM', 'apply', '')])
        self.reviewed('2026-11-01', [('gh-bright-1', 'Brightwater', 'Staff PM, Growth', 'hold', 'still waiting'),
                                     ('gh-north-1', 'Northwind', 'Senior PM', 'pass', ''),        # passed later: gone
                                     ('gh-globex-1', 'Globex', 'Principal PM', 'hold', 'recruiter call first')])
        self.rows = []
        tracker.upsert(self.rows, {'company': 'Acme Robotics', 'title': 'Lead PM', 'date_applied': '2026-10-25',
                                   'status': 'applied', 'status_date': '2026-10-25'})  # applied since: gone (by job_key)
        with open(os.path.join(self.vault, 'Pipeline', 'specs', 'Globex.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'id': 'gh-globex-1', 'folder': '2026-11-01 Globex - Principal PM'}, fh)
        os.makedirs(os.path.join(self.vault, 'Workflow', runrecord.READY, '2026-11-01 Globex - Principal PM'))

    def tearDown(self):
        shutil.rmtree(self.ws)

    def reviewed(self, date, items):
        cols = runrecord.REVIEWED_COLUMNS
        with open(os.path.join(self.queue, f'reviewed-{date}.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for rid, co, title, call, note in items:
                w.writerow({**{c: '' for c in cols}, 'id': rid, 'company': co, 'title': title, 'call': call, 'notes': note,
                            'fit': '71', 'locations': 'NYC', 'url': f'https://jobs.example.com/{rid}'})

    def test_latest_hold_not_applied_or_passed(self):
        held = tracker.holds(self.rows, self.vault, TODAY)
        self.assertEqual([h['company'] for h in held], ['Globex', 'Brightwater'])  # newest hold first
        g, b = held
        self.assertEqual((g['since'], g['days'], g['old']), ('2026-11-01', 9, False))
        self.assertEqual((b['since'], b['days'], b['old']), ('2026-10-20', 21, True))  # unbroken holds keep the first date
        self.assertEqual(b['note'], 'still waiting')
        self.assertTrue(g['folder'].endswith(os.path.join('02-Ready to Apply', '2026-11-01 Globex - Principal PM')))
        self.assertEqual(b['folder'], '')  # no folder built
        self.assertEqual(tracker.holds(self.rows, self.vault, TODAY, held_days=30)[1]['old'], False)

    def test_a_break_in_the_holds_restarts_since(self):
        self.reviewed('2026-11-05', [('gh-globex-1', 'Globex', 'Principal PM', 'apply', '')])
        self.reviewed('2026-11-08', [('gh-globex-1', 'Globex', 'Principal PM', 'hold', '')])
        self.assertEqual(tracker.holds(self.rows, self.vault, TODAY)[0]['since'], '2026-11-08')

    def test_tracker_is_never_written(self):
        tracker.write(tracker.path_of(self.ws), self.rows)
        before = open(tracker.path_of(self.ws), encoding='utf-8').read()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tracker.main(['holds', '--workspace', self.ws, '--date', TODAY.isoformat()])
        self.assertIn('2 role(s) on hold (1 held 14+ days)', out.getvalue())
        self.assertIn('Brightwater | Staff PM, Growth | held since 2026-10-20 (21 days) | HELD A WHILE', out.getvalue())
        self.assertIn('no folder built', out.getvalue())
        self.assertEqual(open(tracker.path_of(self.ws), encoding='utf-8').read(), before)

    def test_dashboard_section(self):
        held = tracker.holds(self.rows, self.vault, TODAY)
        page = dashboard.render(self.rows, today=TODAY.isoformat(), vault=self.vault, holds=held)
        data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(len(data['rows']), 1)  # holds are not applications
        self.assertEqual([h['c'] for h in data['holds']], ['Globex', 'Brightwater'])
        self.assertEqual(data['holds'][0]['fit'], 71)
        self.assertTrue(data['holds'][0]['f'].startswith('file://'))
        self.assertTrue(data['holds'][1]['old'])
        self.assertIn('<h2>On hold</h2>', page)
        self.assertIn("tile('on hold'", page)
        empty = dashboard.render(self.rows, today=TODAY.isoformat())
        self.assertIn('"holds":[]', empty)  # section hides itself when there are none

    def test_report_includes_holds(self):
        tracker.write(tracker.path_of(self.ws), self.rows)
        with contextlib.redirect_stdout(io.StringIO()):
            tracker.main(['report', '--workspace', self.ws, '--date', TODAY.isoformat()])
        page = open(os.path.join(self.ws, 'report.html'), encoding='utf-8').read()
        self.assertIn('still waiting', page)


if __name__ == '__main__':
    unittest.main()
