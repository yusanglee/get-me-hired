"""The review page lists location drops that would score tier A in the US; the rest stay in the run record and on
the page behind "show all" and search. engine.locations.country tells US from international by the location text."""
import copy, json, os, re, tempfile, unittest

from engine import runrecord
from engine.locations import country


def all_drops(data):
    """The page's drops as its script sees them: listed rows plus the compact hidden rows."""
    rows = lambda t: [{c: v for c, v in zip(t['cols'], r) if v is not None} for r in t['rows']]
    return rows(data['dropped']) + rows(data.get('hidden') or {'cols': [], 'rows': []})


class Country(unittest.TestCase):
    def test_us(self):
        for loc in ('Seattle, WA', 'San Mateo, CA, United States', 'Cary,North Carolina,United States',
                    'US California (Redwood City) - Office', 'US > Arizona > Phoenix', 'Atlanta, Georgia, United States',
                    'Seattle, Washington', 'Lexington, Ky', 'Mercer Island, USA', 'Distributed - US; Jacksonville, Florida',
                    'Ontario, CA', 'Boston, Massachusetts', 'Palo Alto, CA, US; Seattle, WA, US'):
            self.assertEqual(country(loc), 'us', loc)

    def test_international(self):
        for loc in ('London / Stockholm', 'Remote Canada', 'Toronto, Canada', 'ES - Barcelona, Spain', 'Helsinki',
                    'Shanghai, China', 'Seoul, Korea', 'Vancouver, British Columbia', 'Remote UK', 'Mexico City, Mexico',
                    'Canada - Remote (ON, AB, BC, or NS Only)', 'Singapore', 'Tokyo, Japan'):
            self.assertEqual(country(loc), 'intl', loc)

    def test_mixed_counts_as_us(self):
        self.assertEqual(country('Vancouver,British Columbia,Canada / Cary,North Carolina,United States'), 'us')

    def test_unclear(self):
        for loc in ('Greater Houston', 'Hybrid - Denver', 'Seattle, Hybrid', ''):
            self.assertEqual(country(loc), '', loc)


def drop(ref, reason, would_be, location, company='Brightwater'):
    return dict(stage='discover', reason=reason, company=company, title='Senior Product Manager', location=location,
                locations='', salary_max=None, url='', id=f'gh-x-{ref}', source='greenhouse', detail='', postings=1,
                ref=f'd{ref}', fit=80, ats=90, gaps=[], flags=[], top_locations=[], would_be=would_be)


class PageData(unittest.TestCase):
    def rec(self):
        return dict(version=1, date='2026-01-05', roles=[], picks={}, dropped=[
            drop(1, 'location', 'A', 'Austin, TX'), drop(2, 'location', 'A', 'London'),
            drop(3, 'location', 'B', 'Austin, TX'), drop(4, 'location', 'A', 'Greater Houston'),
            drop(5, 'passed', 'A', 'London'), drop(6, 'salary', 'C', 'Remote')])

    def test_listed_only_tier_a_not_international(self):
        rec = self.rec()
        before = copy.deepcopy(rec)
        out = runrecord.page_data(rec)
        loc = {d['ref']: (d['country'], d['listed']) for d in all_drops(out) if d['reason'] == 'location'}
        self.assertEqual(loc, {'d1': ('us', True), 'd2': ('intl', False), 'd3': ('us', False), 'd4': ('', True)})
        self.assertNotIn('listed', next(d for d in all_drops(out) if d['ref'] == 'd5'))  # other reasons are listed in full
        self.assertEqual(sorted(d['ref'] for d in all_drops(out)), sorted(d['ref'] for d in rec['dropped']))  # refs unchanged
        self.assertEqual(rec, before)  # the record itself is not changed

    def test_page_keeps_every_row_and_each_reason_has_a_section(self):
        rec = self.rec()
        q = tempfile.mkdtemp()
        html = open(runrecord.build_page(rec, q), encoding='utf-8').read()
        data = json.loads(re.search(r'const DATA = (.*?);\nconst CALLS', html, re.S).group(1))
        self.assertEqual(len(all_drops(data)), 6)  # hidden rows are still on the page (search, show all)
        self.assertEqual(data['omitted'], {})
        self.assertIn("passed: 'Passed in an earlier review'", html)  # passed drops had no section before
        self.assertIn("id = 'g-drop-' + reason", html)


    def test_page_stays_under_its_budget_and_counts_what_it_leaves_off(self):
        rec = self.rec()
        big = [dict(stage='discover', reason='location', company=f'Corvid{i}', title='Senior Manager, Strategy',
                    location='London / Berlin / Paris / Madrid / Rome / Dublin', locations='', salary_max=None,
                    url=f'https://jobs.ashbyhq.com/corvid/{i:05d}-abcdefghij', id=f'ab-corvid-{i}', source='ashby',
                    detail='', ref=f'd{10 + i}', fit=i % 50, ats=30, would_be='C') for i in range(3000)]
        rec['dropped'] += big
        q = tempfile.mkdtemp()
        page = runrecord.build_page(rec, q)
        self.assertLessEqual(os.path.getsize(page), runrecord.PAGE_BUDGET)
        html = open(page, encoding='utf-8').read()
        data = json.loads(re.search(r'const DATA = (.*?);\nconst CALLS', html, re.S).group(1))
        kept = all_drops(data)
        self.assertGreater(data['omitted']['location'], 0)
        self.assertEqual(data['omitted'].get('passed'), 1)  # look-back reasons go before location drops
        self.assertEqual(len(kept) + sum(data['omitted'].values()), len(rec['dropped']))
        self.assertTrue({'d1', 'd4', 'd6'} <= {d['ref'] for d in kept})  # full rows (pay, A-tier location) always stay
        off_fit = max(r['fit'] for r in big if r['ref'] not in {d['ref'] for d in kept})
        self.assertLessEqual(off_fit, min(d['fit'] for d in kept if d['ref'] in {r['ref'] for r in big}))  # lowest fit go
        self.assertIn('+2 more', next(d for d in kept if d['ref'].startswith('d1')
                                      and d.get('company', '').startswith('Corvid'))['location'])
        self.assertLess(max(map(len, html.splitlines())), 4000)  # one row per line: readable in parts

    def test_config_sets_the_rule(self):
        self.assertEqual(runrecord.location_listing({}), dict(tiers=['A'], us_only=True))
        ls = runrecord.location_listing({'review': {'location_drops': {'tiers': ['A', 'B'], 'us_only': False}}})
        out = runrecord.page_data(self.rec(), ls)
        self.assertEqual([d['ref'] for d in all_drops(out) if d.get('listed')], ['d1', 'd2', 'd3', 'd4'])
        with self.assertRaises(SystemExit):
            runrecord.location_listing({'review': {'location_drops': {'tiers': ['top']}}})

    def test_rule_saved_in_the_record_is_used_on_rebuild(self):
        rec = self.rec()
        rec['score'] = {'settings': {'location_drops': {'tiers': ['B'], 'us_only': True}}}
        self.assertEqual([d['ref'] for d in all_drops(runrecord.page_data(rec)) if d.get('listed')], ['d3'])

    def test_summary_counts_only_listed_tiers(self):
        line = [l for l in runrecord.summary(self.rec()) if l.startswith('Dropped before scoring')][0]
        self.assertIn('these would score A: 2 location drops in the US (the page lists only these; the other 2 are '
                      'under "show all")', line)
        self.assertNotIn('pay or range', line)  # the salary drop is tier C


if __name__ == '__main__':
    unittest.main()
