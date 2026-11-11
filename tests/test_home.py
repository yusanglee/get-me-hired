"""gmh home: the HOME.md brief and the summaries skills leave (gmh home log, --auto), on a fictional workspace
(Jordan Rivera). No network."""
import datetime, io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from engine import home, setup  # noqa: E402

TODAY = datetime.date(2026, 10, 31)
REPO = os.path.dirname(HERE)


class Home(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.join(tempfile.mkdtemp(prefix='gmh-home-'), 'Jordan Rivera search')
        self.addCleanup(shutil.rmtree, os.path.dirname(self.ws), True)
        setup.init(self.ws, name='Jordan Rivera')

    def test_init_writes_home(self):
        with open(os.path.join(self.ws, 'HOME.md'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('## How to start each day', text)
        self.assertIn('/get-me-hired:today', text)

    def test_models_come_from_skill_frontmatter(self):
        tasks = {t['task']: t for t in home.tasks()}
        self.assertEqual(set(tasks), {name for name, _ in home.TASKS})
        for name, t in tasks.items():
            self.assertEqual(t['model'], home.frontmatter(name)['model'])
        self.assertTrue(home.source('today').endswith(os.path.join('skills', 'today', 'SKILL.md')))
        self.assertEqual(home.frontmatter('today')['model'], 'opus')
        self.assertIsNone(home.source('coordinator'))  # retired
        self.assertNotIn('coordinator', {name for name, _ in home.TASKS})

    def test_frontmatter_falls_back_to_a_command_file(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cmds, skills = os.path.join(d, 'commands'), os.path.join(d, 'skills')
        os.makedirs(os.path.join(skills, 'outcome'))
        os.makedirs(cmds)
        with open(os.path.join(cmds, 'outcome.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('---\ndescription: old\nmodel: haiku\n---\n')
        self.assertEqual(home.frontmatter('outcome', cmds, skills)['model'], 'haiku')
        with open(os.path.join(skills, 'outcome', 'SKILL.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('---\nname: outcome\ndescription: new\nmodel: sonnet\neffort: low\n---\n')
        self.assertEqual(home.frontmatter('outcome', cmds, skills), {'description': 'new', 'model': 'sonnet', 'effort': 'low'})
        self.assertEqual(home.frontmatter('nothing', cmds, skills), {})

    def test_every_task_leaves_a_summary(self):
        from test_skills_structure import bundle
        for name, _ in home.TASKS:
            self.assertIn(f'gmh home log {name}', bundle(name), name)

    def test_links_are_clickable_and_only_existing(self):
        d = home.data(self.ws, TODAY)
        labels = [x['label'] for x in d['links']]
        self.assertIn('Tracker', labels)
        self.assertIn('Dashboard (your applications, filters and tiles)', labels)
        self.assertIn('Resume design editor', labels)
        self.assertNotIn('Tracker in Google Sheets', labels)
        self.assertFalse(any(l.startswith('Review page') for l in labels))
        md = home.markdown(d)
        self.assertIn('(<file://', md)
        self.assertIn('Jordan%20Rivera%20search/tracker.csv>)', md)

    def test_sheet_artifact_and_review_page_links(self):
        cfg_p = os.path.join(self.ws, 'config.json')
        with open(cfg_p, encoding='utf-8') as fh:
            cfg = json.load(fh)
        cfg['tracker']['sheet_id'] = 'abc123'
        cfg['review'] = {'artifact_url': 'https://claude.ai/code/artifact/0000'}
        with open(cfg_p, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(cfg, fh)
        q = os.path.join(self.ws, 'Pipeline', 'queue')
        os.makedirs(q, exist_ok=True)
        for day in ('2026-10-30', '2026-10-31'):
            open(os.path.join(q, f'review-{day}.html'), 'w', encoding='utf-8', newline='\n').close()
        links = {x['label']: x['target'] for x in home.data(self.ws, TODAY)['links']}
        self.assertEqual(links['Tracker in Google Sheets'], 'https://docs.google.com/spreadsheets/d/abc123')
        self.assertEqual(links['Run Review page in Claude (private)'], 'https://claude.ai/code/artifact/0000')
        self.assertTrue(links['Review page (today)'].endswith('review-2026-10-31.html'))

    def test_log_waiting_and_supersede(self):
        at = datetime.datetime(2026, 10, 31, 9, 0)
        home.log(self.ws, 'daily-run', 'Scored 41 roles; 6 A, 9 B.', ['Pick on the review page'], '/get-me-hired:apply-all',
                 date='2026-10-31', now=at)
        d = home.data(self.ws, TODAY)
        self.assertTrue(d['daily_run_today'])
        self.assertEqual([w['item'] for w in d['waiting']], ['Pick on the review page'])
        home.log(self.ws, 'apply-all', 'Applied 5 (Brightwater, Northwind).', ['Two manual applies'], date='2026-10-31',
                 now=at + datetime.timedelta(hours=2))
        d = home.data(self.ws, TODAY)
        self.assertEqual([w['item'] for w in d['waiting']], ['Two manual applies'])
        self.assertEqual([r['task'] for r in d['recent']], ['apply-all', 'daily-run'])
        # a new day's daily run is not settled by yesterday's apply session
        home.log(self.ws, 'daily-run', 'Scored 12.', ['Pick'], date='2026-11-01', now=at + datetime.timedelta(days=1))
        d = home.data(self.ws, datetime.date(2026, 11, 1))
        self.assertEqual([w['item'] for w in d['waiting']], ['Pick', 'Two manual applies'])

    def _queue(self):
        q = os.path.join(self.ws, 'Pipeline', 'queue')
        os.makedirs(q, exist_ok=True)
        return q

    def _reviewed(self, date, calls):
        with open(os.path.join(self._queue(), f'reviewed-{date}.csv'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('id,company,call\n' + ''.join(f'{i},Brightwater,{c}\n' for i, c in calls))

    def test_unconfirmed_picks_wait_without_a_summary(self):
        with open(os.path.join(self._queue(), 'run-2026-10-31.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'date': '2026-10-31', 'roles': [{'id': 'gh-a'}], 'picks': {}}, fh)
        self.assertEqual([w['item'] for w in home.data(self.ws, TODAY)['waiting']],
                         ['Confirm your picks for the 2026-10-31 run on the review page'])
        self._reviewed('2026-10-31', [('gh-a', 'pass')])  # picks confirmed: nothing queued, nothing waiting
        self.assertEqual(home.data(self.ws, TODAY)['waiting'], [])

    def test_queued_roles_not_in_tracker_wait(self):
        self._reviewed('2026-10-30', [('gh-a', 'apply'), ('gh-b', 'manual'), ('gh-c', 'pass')])
        self._reviewed('2026-10-20', [('gh-old', 'apply')])  # older than the recent window
        self.assertEqual([w['item'] for w in home.data(self.ws, TODAY)['waiting']],
                         ['2 of 2 roles queued on 2026-10-30 not applied yet'])
        from engine import tracker
        p = tracker.path_of(self.ws)
        tracker.write(p, tracker.read(p) + [{'id': 'gh-a'}, {'id': 'gh-b'}])
        self.assertEqual(home.data(self.ws, TODAY)['waiting'], [])

    def test_old_summaries_drop_off(self):
        home.log(self.ws, 'gmail-sync', 'Two rejections.', date='2026-10-20')
        self.assertEqual(home.data(self.ws, TODAY)['recent'], [])

    def test_log_validates(self):
        with self.assertRaises(SystemExit):
            home.log(self.ws, '../x', 'x')
        with self.assertRaises(SystemExit):
            home.log(self.ws, 'daily-run', '  ')

    def test_auto_summary_counts_the_day(self):
        from engine import tracker
        day = '2026-10-31'
        self._reviewed(day, [('gh-a', 'apply'), ('gh-b', 'apply'), ('gh-c', 'pass'), ('gh-d', 'hold')])
        p = tracker.path_of(self.ws)
        tracker.write(p, tracker.read(p) + [
            {'id': 'gh-a', 'company': 'Brightwater', 'title': 'Chief of Staff', 'date_applied': day, 'status': 'applied',
             'source': 'pipeline', 'linkedin_interest': f'done {day}',
             'linkedin_connect': f'{day} sent: Sam (https://www.linkedin.com/in/sam)'},
            {'company': 'Northwind', 'title': 'Ops Lead', 'date_applied': '2026-10-01', 'status': 'rejected',
             'status_date': day, 'source': 'gmail', 'gmail_ids': 'm1'}])
        g = os.path.join(self.ws, 'state', 'gmail')
        os.makedirs(g, exist_ok=True)
        with open(os.path.join(g, f'proposed-{day}.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'created': day, 'rows': [{'n': 1, 'action': 'update', 'status': 'rejected', 'gmail_ids': 'm1'},
                                                {'n': 2, 'action': 'add', 'status': 'applied', 'gmail_ids': 'm9'}]}, fh)
        s = home.auto_summary(self.ws, day)
        self.assertIn('Gmail: 1 update(s) (1 rejected), 0 added', s)
        self.assertIn('Picks: 2 apply, 1 hold, 1 pass', s)
        self.assertIn('Queue: 1 applied, 1 to prepare', s)
        self.assertIn('Applied: 1 (Brightwater)', s)
        self.assertIn('LinkedIn: 1 company done (Brightwater), 1 note(s) sent', s)
        self.assertNotIn('Northwind', s.split('Applied:')[1])  # a Gmail-imported row is not an application made today
        out = io.StringIO()
        with redirect_stdout(out):
            home.main(['log', 'today', '--auto', '--summary', 'Good day.', '--waiting', 'One captcha', '--date', day,
                       '--workspace', self.ws])
        with open(os.path.join(home.sessions_dir(self.ws), f'{day}-today.json'), encoding='utf-8') as fh:
            rec = json.load(fh)
        self.assertTrue(rec['summary'].startswith('Gmail: 1 update(s)'))
        self.assertTrue(rec['summary'].endswith('Good day.'))
        self.assertEqual(rec['waiting'], ['One captcha'])

    def test_auto_summary_on_an_empty_day(self):
        s = home.auto_summary(self.ws, '2026-10-31')
        self.assertEqual(s, 'Gmail: not synced that day. Run: none.')

    def test_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            home.main(['log', 'outcome', '--summary', 'Brightwater: interviewing.', '--workspace', self.ws])
        self.assertTrue(os.path.exists(os.path.join(home.sessions_dir(self.ws),
                                                    f'{datetime.date.today().isoformat()}-outcome.json')))
        out = io.StringIO()
        with redirect_stdout(out):
            home.main(['--json', '--workspace', self.ws])
        self.assertEqual(json.loads(out.getvalue())['recent'][0]['task'], 'outcome')


if __name__ == '__main__':
    unittest.main()
