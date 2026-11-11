"""gmh today (where the day stands, next step), gmh fills (form status), the applied check on unfinished forms, and
gmh setup agents, on a fictional workspace (Jordan Rivera, Brightwater). No network."""
import datetime, io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import applied, fills, runrecord, setup, today, tracker  # noqa: E402

DAY = datetime.date(2026, 11, 3)
D = DAY.isoformat()
MATS = {'summary_variant': 'v1', 'template_script': 'build_a.js', 'lead_material': 'cover letter'}


class Today(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.join(tempfile.mkdtemp(prefix='gmh-today-'), 'Jordan Rivera search')
        self.addCleanup(shutil.rmtree, os.path.dirname(self.ws), True)
        setup.init(self.ws, name='Jordan Rivera')
        self.q = os.path.join(self.ws, 'Pipeline', 'queue')
        os.makedirs(self.q, exist_ok=True)

    def touch(self, name, text=''):
        with open(os.path.join(self.q, name), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)

    def reviewed(self, date, rows):
        cols = ['id', 'company', 'title', 'call', 'gap_type', 'top_gap'] + list(MATS)
        with open(os.path.join(self.q, f'reviewed-{date}.csv'), 'w', encoding='utf-8', newline='') as fh:
            import csv
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

    def step(self):
        return today.data(self.ws, DAY)['next']['step']

    def test_the_day_moves_through_its_steps(self):
        self.assertEqual(self.step(), 'find')
        self.touch(f'discovered-{D}.csv', 'id\n')
        self.assertEqual(self.step(), 'score')
        self.touch(f'scored-{D}.csv', 'id\n')
        runrecord.save(self.q, {'version': 1, 'date': D, 'roles': [{'id': 'gh-brightwater-9', 'tier': 'C'}],
                                'dropped': [], 'picks': {}})
        self.assertEqual(self.step(), 'pick')
        prepared = dict(MATS, gap_type='minor', top_gap='')
        self.reviewed(D, [dict(id='gh-brightwater-1', company='Brightwater', title='Chief of Staff', call='apply'),
                          dict(prepared, id='gh-brightwater-2', company='Brightwater', title='Ops Lead', call='apply'),
                          dict(prepared, id='ab-corvid-3', company='Corvid', title='PM', call='manual'),
                          dict(id='gh-larkspur-4', company='Larkspur', title='PM', call='pass')])
        d = today.data(self.ws, DAY)
        self.assertEqual(d['queue']['to_prepare'], ['gh-brightwater-1'])
        self.assertEqual(d['queue']['to_fill'], ['gh-brightwater-2'])
        self.assertEqual(d['queue']['manual'], ['ab-corvid-3'])
        self.assertEqual(d['next']['step'], 'prepare')
        self.reviewed(D, [dict(prepared, id='gh-brightwater-2', company='Brightwater', title='Ops Lead', call='apply')])
        self.assertEqual(self.step(), 'fill')
        fills.record(self.ws, 'gh-brightwater-2', 'needs_user', ['captcha'])
        d = today.data(self.ws, DAY)
        self.assertEqual((d['queue']['needs_user'], d['next']['step']), (['gh-brightwater-2'], 'submit'))
        self.assertTrue(any('captcha' in l for l in today.lines(d)))
        fills.record(self.ws, 'gh-brightwater-2', 'ready')
        self.assertEqual(today.data(self.ws, DAY)['queue']['ready'], ['gh-brightwater-2'])
        p = tracker.path_of(self.ws)
        tracker.write(p, tracker.read(p) + [{'id': 'gh-brightwater-2', 'company': 'Brightwater', 'title': 'Ops Lead',
                                             'status': 'applied', 'date_applied': D, 'source': 'pipeline'}])
        d = today.data(self.ws, DAY)
        self.assertEqual(d['queue']['applied'], ['gh-brightwater-2'])
        self.assertIn(d['next']['step'], ('linkedin', 'wrap'))

    def test_earlier_queue_and_partial_discover(self):
        self.touch(f'discovered-{D}.csv.part', 'id\n')
        d = today.data(self.ws, DAY)
        self.assertTrue(d['run']['discover_partial'])
        self.assertIn('stopped mid-write', '\n'.join(today.lines(d)))
        self.touch(f'discovered-{D}.csv', 'id\n')
        self.touch(f'scored-{D}.csv', 'id\n')
        runrecord.save(self.q, {'version': 1, 'date': D, 'roles': [], 'dropped': [], 'picks': {}})
        self.reviewed(D, [])
        self.reviewed('2026-11-01', [dict(id='gh-old-1', company='Brightwater', title='PM', call='apply')])
        d = today.data(self.ws, DAY)
        self.assertEqual(d['earlier'], [{'date': '2026-11-01', 'left': 1, 'queued': 1}])
        self.assertEqual(d['next']['step'], 'earlier')

    def test_gmail_status(self):
        self.assertEqual(today.gmail_status(self.ws, DAY), {'last': None, 'today': False})
        self.assertIn('Gmail sync: not yet today (never run', '\n'.join(today.lines(today.data(self.ws, DAY))))
        d = os.path.join(self.ws, 'state', 'gmail')
        os.makedirs(d, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        with open(os.path.join(d, 'sync.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'last_run': now.isoformat(), 'updated': now.isoformat()}, fh)
        local_day = now.astimezone().date()
        self.assertTrue(today.gmail_status(self.ws, local_day)['today'])
        self.assertFalse(today.gmail_status(self.ws, local_day + datetime.timedelta(days=1))['today'])

    def test_cli_json_and_home(self):
        out = io.StringIO()
        with redirect_stdout(out):
            today.main(['--workspace', self.ws, '--json', '--date', D])
        self.assertEqual(json.loads(out.getvalue())['next']['step'], 'find')
        self.assertTrue(os.path.exists(os.path.join(self.ws, 'HOME.md')))


class Fills(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix='gmh-fills-')
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_record_and_unfinished(self):
        self.assertIsNone(fills.unfinished(self.ws, 'gh-brightwater-1'))  # no record: filled by hand, or manual
        with self.assertRaises(ValueError):
            fills.record(self.ws, 'gh-brightwater-1', 'needs_user')  # must say what is left
        with self.assertRaises(ValueError):
            fills.record(self.ws, '../escape', 'ready')
        fills.record(self.ws, 'gh-brightwater-1', 'needs_user', ['captcha', ' '])
        self.assertEqual(fills.load(self.ws, 'gh-brightwater-1')['left'], ['captcha'])
        self.assertIn('captcha', fills.unfinished(self.ws, 'gh-brightwater-1'))
        fills.record(self.ws, 'gh-brightwater-1', 'ready', ['ignored'])
        self.assertEqual(fills.load(self.ws, 'gh-brightwater-1')['left'], [])
        self.assertIsNone(fills.unfinished(self.ws, 'gh-brightwater-1'))

    def test_applied_refuses_an_unfinished_form(self):
        P = os.path.join(self.ws, 'Pipeline')
        os.makedirs(os.path.join(P, 'specs'))
        os.makedirs(os.path.join(P, 'queue'))
        with open(os.path.join(P, 'specs', 'Brightwater-CoS.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'id': 'gh-brightwater-1', 'company': 'Brightwater', 'title': 'Chief of Staff',
                       'folder': '2026-11-03 Brightwater - Chief of Staff'}, fh)
        fills.record(self.ws, 'gh-brightwater-1', 'blocked', note='needs an account')
        out = applied.mark(self.ws, ['gh-brightwater-1'], D)
        self.assertEqual(len(out), 1)
        self.assertIn("form isn't finished", out[0])
        self.assertEqual(tracker.read(tracker.path_of(self.ws)), [])
        fills.record(self.ws, 'gh-brightwater-1', 'ready')
        self.assertEqual(applied.mark(self.ws, ['gh-brightwater-1'], D), ['applied: Brightwater | Chief of Staff'])


class Agents(unittest.TestCase):
    def test_install_and_check(self):
        folder = tempfile.mkdtemp(prefix='gmh-agents-')
        self.addCleanup(shutil.rmtree, folder, True)
        names = {f[:-3] for f in os.listdir(setup.AGENTS_DIR) if f.endswith('.md')}
        self.assertTrue({'posting-reader', 'form-filler', 'linkedin-note-drafter'} <= names)
        self.assertEqual(set(setup.agents_status(folder).values()), {'missing'})
        self.assertEqual(set(setup.install_agents(folder).values()), {'added'})
        self.assertEqual(set(setup.agents_status(folder).values()), {'ok'})
        with open(os.path.join(folder, '.claude', 'agents', 'form-filler.md'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\nlocal edit\n')
        self.assertEqual(setup.agents_status(folder)['form-filler'], 'stale')
        self.assertEqual(setup.install_agents(folder)['form-filler'], 'updated')


if __name__ == '__main__':
    unittest.main()
