"""Discover and score from a workspace's pack, end to end for a Chief of Staff workspace. No network:
the ATS adapters and job-board searchers are replaced by fixture postings (tests/fixtures/discover)."""
import csv, datetime, json, os, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import boards, discover, packs, score, tracker  # noqa: E402
from engine.sources import ats  # noqa: E402
from engine.sources.base import posting  # noqa: E402

FIX = json.load(open(os.path.join(HERE, 'fixtures', 'discover', 'cos_postings.json'), encoding='utf-8'))
TODAY = datetime.date(2026, 10, 20)
RESUME = """# Pat Example
Chief of Staff to the CEO at Example Health (2021-2026). Ran the OKR and annual planning cycle for 400 people;
prepared quarterly board materials; led fundraising diligence for a $60M Series C; built financial models;
ran the operating cadence and executive communication across 9 teams.
"""
CONFIG = {
    'salary': {'floor_usd': 180000},
    'locations': {'home': 'NYC', 'remote_us': True,
                  'metros': [{'name': 'NYC'}, {'name': 'SF', 'policy': 'hybrid_ok', 'max_office_days': 2}]},
    'per_company': {'max_applications': 2, 'window_days': 90},
}


def fake_adapter(kind):
    def fetch(slug, company=''):
        raw = FIX['ats'].get(kind, {}).get(slug)
        if raw is None:
            return None
        return [posting(source=kind, company=company or slug, ats=kind, remote=r.pop('remote', False) or 'remote' in r['location'].lower(), **r)
                for r in (dict(x) for x in raw)]
    return fetch


ADAPTERS = {k: fake_adapter(k) for k in ('greenhouse', 'lever', 'ashby')}


def fake_resolve(slugs, company=''):
    for s in slugs:
        for kind, fn in ADAPTERS.items():
            if fn(s, company):
                return [kind, s]
    return None


class CosEndToEnd(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        json.dump(CONFIG, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(self.ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n').write(RESUME)
        open(os.path.join(self.ws, 'companies.txt'), 'w', encoding='utf-8', newline='\n').write(FIX['companies_txt'])
        pack = packs.draft(packs.load('chief-of-staff'), RESUME)
        pack['approved'] = True
        json.dump(pack, open(os.path.join(self.ws, 'pack.json'), 'w', encoding='utf-8', newline='\n'))
        rows = []
        tracker.upsert(rows, {'company': 'Globex', 'title': 'Chief of Staff, Operations', 'date_applied': '2026-10-01',
                              'status': 'applied', 'status_date': '2026-10-01'})
        tracker.write(tracker.path_of(self.ws), rows)
        os.makedirs(os.path.join(self.ws, 'Workflow', '03-Applied', '2026-10-05 Acme Robotics - Chief of Staff, Finance'))
        self.queries = {}

    def tearDown(self):
        shutil.rmtree(self.ws)

    def searcher(self, name):
        def search(queries, since_days, opts):
            self.queries[name] = list(queries)
            return [posting(**p) for p in FIX['boards'].get(name, [])]
        return search

    def discover(self):
        ctx = discover.Ctx(self.ws, today=TODAY)
        searchers = {n: self.searcher(n) for n in discover.DEFAULT_SOURCES}
        lookup = lambda company, title, cache, memo=None: (
            {'salary_min': 200000, 'salary_max': 250000, 'pay_bands': [], 'ats': 'lever', 'slug': 'initech'} if company == 'Initech' else None)
        with mock.patch.dict(boards.SEARCHERS, searchers), mock.patch.dict(ats.ADAPTERS, ADAPTERS):
            return ctx, discover.run(ctx, ats_adapters=ADAPTERS, resolver=fake_resolve, pay_lookup=lookup, out=lambda *a: None)

    def test_discover_then_score(self):
        ctx, (path, _) = self.discover()
        self.assertTrue(path.endswith('discovered-2026-10-20.csv'))
        self.assertFalse(os.path.exists(path + '.part'))  # written beside it, then renamed into place
        rows = {r['id']: r for r in csv.DictReader(open(path, encoding='utf-8', newline=''))}
        self.assertEqual(list(next(csv.reader(open(path, encoding='utf-8', newline='')))), discover.COLUMNS)
        # title, location and pay filters
        self.assertEqual(set(rows), {'gh-acme-1', 'gh-acme-6', 'gh-acme-7', 'ab-globex-1', 'ab-globex-2', 'hm-initech-cos'})
        self.assertEqual(rows['gh-acme-1']['salary_max'], '260000')
        self.assertEqual(rows['gh-acme-6']['salary_max'], '')  # no range, kept because "lead" is senior
        self.assertEqual(rows['gh-acme-7']['locations'], 'SF')
        self.assertIn('pay from lever/initech', rows['hm-initech-cos']['salary_source'])
        self.assertEqual(rows['hm-initech-cos']['source'], 'himalayas')
        # applied in tracker.csv -> already in workflow
        self.assertEqual(rows['ab-globex-2']['already_in_workflow'], 'yes')
        self.assertEqual(rows['gh-acme-1']['already_in_workflow'], 'no')
        self.assertTrue(all(r['new'] == 'yes' for r in rows.values()))
        # job boards searched with the pack's queries (config has no sources section)
        self.assertEqual(self.queries['himalayas'], ctx.pack['titles']['board_queries'])
        # JD files in the original format
        jd = open(os.path.join(ctx.state, 'jd', 'gh-acme-1.txt'), encoding='utf-8').read().split('\n')
        self.assertEqual(jd[:4], ['Chief of Staff to the CEO', 'Acme Robotics', 'New York, NY', 'https://boards.greenhouse.io/acme/jobs/1'])
        self.assertNotIn('\n', jd[5])  # description on one line, like the original
        cache = json.load(open(os.path.join(ctx.state, 'ats_cache.json'), encoding='utf-8'))
        self.assertEqual(cache, {'Acme Robotics': ['greenhouse', 'acme'], 'Globex': ['ashby', 'globex'], 'Nowhere Corp': None})

        spath, scored = score.run(ctx, out=lambda *a: None)
        self.assertTrue(spath.endswith('scored-2026-10-20.csv'))
        by = {r['id']: r for r in scored}
        self.assertNotIn('ab-globex-2', by)  # already applied
        self.assertEqual(by['gh-acme-1']['tier'], 'B')
        self.assertEqual(by['hm-initech-cos']['tier'], 'B')
        self.assertEqual(by['gh-acme-7']['fit'], 0)  # SF, 4 office days over the 2-day limit
        self.assertIn('SF on-site, over office-day limit', by['gh-acme-7']['flags'])
        self.assertIn('consulting or banking background', by['ab-globex-1']['gaps'])
        self.assertLess(by['ab-globex-1']['fit'], by['gh-acme-1']['fit'])
        self.assertIn('no posted range', by['gh-acme-6']['flags'])
        self.assertEqual([r['tier'] for r in scored].count('C'), 2)
        self.assertEqual(by['gh-acme-6']['tier'], 'cap')  # a near-miss C+, held: Acme is at its 2-application cap
        self.assertEqual(scored, sorted(scored, key=lambda r: (-r['fit'], -r['ats'])))
        self.assertEqual(list(next(csv.reader(open(spath, encoding='utf-8', newline='')))), score.COLUMNS)

    def test_earlier_pass_is_dropped_and_hold_is_labeled(self):
        ctx, _ = self.discover()
        with open(os.path.join(ctx.queue, 'reviewed-2026-10-18.csv'), 'w', newline='', encoding='utf-8') as fh:
            fh.write('call,company,title,id\npass,Acme Robotics,Chief of Staff to the CEO,gh-acme-1\n'
                     'hold,Initech,Chief of Staff,hm-initech-cos\n')
        with open(os.path.join(ctx.queue, 'reviewed-2026-10-20.csv'), 'w', newline='', encoding='utf-8') as fh:  # today's picks: ignored
            fh.write('call,company,title,id\npass,Acme Robotics,x,gh-acme-6\n')
        _, scored = score.run(ctx, out=lambda *a: None)
        by = {r['id']: r for r in scored}
        self.assertNotIn('gh-acme-1', by)
        self.assertIn('gh-acme-6', by)
        self.assertIn('held 2026-10-18', by['hm-initech-cos']['flags'])
        run = json.load(open(os.path.join(ctx.queue, 'run-2026-10-20.json'), encoding='utf-8'))
        drop = [d for d in run['dropped'] if d.get('reason') == 'passed']
        self.assertEqual([d['title'] for d in drop], ['Chief of Staff to the CEO'])

    def test_earlier_apply_pick_is_dropped_and_counts_toward_cap(self):
        ctx, _ = self.discover()
        with open(os.path.join(ctx.queue, 'reviewed-2026-10-18.csv'), 'w', newline='', encoding='utf-8') as fh:
            fh.write('call,company,title,id\nhold,Initech,Chief of Staff,hm-initech-cos\n'
                     'pass,Acme Robotics,Chief of Staff to the CEO,gh-acme-1\n')
        with open(os.path.join(ctx.queue, 'reviewed-2026-10-19.csv'), 'w', newline='', encoding='utf-8') as fh:
            fh.write('call,company,title,id\napply,Initech,Chief of Staff,hm-initech-cos\n'  # latest call wins
                     'manual,Acme Robotics,Chief of Staff to the CEO,gh-acme-1\n')
        _, scored = score.run(ctx, out=lambda *a: None)
        by = {r['id']: r for r in scored}
        self.assertNotIn('hm-initech-cos', by)
        self.assertNotIn('gh-acme-1', by)
        run = json.load(open(os.path.join(ctx.queue, 'run-2026-10-20.json'), encoding='utf-8'))
        drop = {d['id']: d for d in run['dropped'] if d.get('reason') == 'already_picked'}
        self.assertEqual(drop['hm-initech-cos']['detail'], 'picked apply 2026-10-19')
        self.assertEqual(drop['gh-acme-1']['detail'], 'picked manual 2026-10-19')
        # the picked Acme role still counts toward Acme's cap (1 in Workflow + 1 picked = 2 = cap)
        self.assertEqual(by['gh-acme-6']['tier'], 'cap')
        page = open(os.path.join(ctx.queue, 'review-2026-10-20.html'), encoding='utf-8').read()
        self.assertIn("already_picked: 'Picked in an earlier review'", page)

    def test_second_run_marks_seen(self):
        self.discover()
        _, (path, _) = self.discover()
        self.assertTrue(all(r['new'] == 'no' for r in csv.DictReader(open(path, encoding='utf-8', newline=''))))

    def test_explicit_config_queries_win(self):
        cfg = {'sources': {'himalayas': {'enabled': True, 'queries': ['chief of staff']}, 'remotive': {'enabled': True}}}
        src = discover.board_sources(cfg, packs.load('chief-of-staff'), skip={'nodesk'})
        self.assertEqual(src['himalayas']['queries'], ['chief of staff'])
        self.assertEqual(src['remotive']['queries'], packs.load('chief-of-staff')['titles']['board_queries'])
        self.assertEqual(set(discover.board_sources({'sources': {'linkedin': {'enabled': True}}}, packs.load('chief-of-staff'),
                                                    skip={'linkedin'})), set())

    def test_company_cap_counts_workflow_and_tracker(self):
        ctx, _ = self.discover()
        self.assertEqual(score.prior_applications(ctx), {'acme robotics': 1, 'globex': 1})
        cfg = json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))
        cfg['per_company']['max_applications'] = 1  # Acme already has one application in the window
        json.dump(cfg, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        _, scored = score.run(discover.Ctx(self.ws, today=TODAY), out=lambda *a: None)
        self.assertEqual(next(r for r in scored if r['id'] == 'gh-acme-1')['tier'], 'cap')
        self.assertEqual(next(r for r in scored if r['id'] == 'hm-initech-cos')['tier'], 'B')

    def test_company_cap_window_is_rolling_by_date_applied(self):
        ctx, _ = self.discover()
        rows = tracker.read(tracker.path_of(self.ws))
        for title, date in (('Chief of Staff, Strategy', '2026-07-01'), ('Chief of Staff, Product', '2026-07-30')):
            tracker.upsert(rows, {'company': 'Globex', 'title': title, 'date_applied': date, 'status': 'applied'})
        tracker.write(tracker.path_of(self.ws), rows)
        # Oct 20 minus 90 days is Jul 22: the Jul 1 application is outside the window, Jul 30 and Oct 1 inside
        self.assertEqual(score.prior_applications(ctx)['globex'], 2)
        cfg = json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))
        cfg['per_company']['window_days'] = 365
        json.dump(cfg, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(score.prior_applications(discover.Ctx(self.ws, today=TODAY))['globex'], 3)

    def test_old_application_with_new_folder_counts_by_date_applied(self):
        ctx, _ = self.discover()
        rows = tracker.read(tracker.path_of(self.ws))
        tracker.upsert(rows, {'company': 'Initech', 'title': 'Chief of Staff', 'date_applied': '2026-05-01', 'status': 'applied'})
        tracker.write(tracker.path_of(self.ws), rows)
        os.makedirs(os.path.join(self.ws, 'Workflow', '04-Interviewing', '2026-10-10 Initech - Chief of Staff'))
        self.assertNotIn('initech', score.prior_applications(ctx))

    def test_default_cap_is_five_per_90_days(self):
        from engine.profile import load_config
        self.assertEqual(load_config({})['per_company'], {'max_applications': 5, 'window_days': 90})

    def test_employer_limit(self):
        ctx, _ = self.discover()
        cfg = json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))
        cfg['company_limits'] = {'globex': {'max_applications': 1, 'window_days': 180}}
        json.dump(cfg, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        ctx = discover.Ctx(self.ws, today=TODAY)
        _, scored = score.run(ctx, out=lambda *a: None)
        g = next(r for r in scored if r['id'] == 'ab-globex-1')
        self.assertIn('Globex limit: 1 of 1 used in 180 days', g['flags'])
        if g['fit'] >= 50:
            self.assertEqual(g['tier'], 'cap')


if __name__ == '__main__':
    unittest.main()
