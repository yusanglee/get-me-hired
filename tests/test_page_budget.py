"""The review page stays under its size budget for a large run (100 scored roles, every A, B and gap role with a full
posting read (reads cover those tiers), field lengths about those of a real 90-role run), keeps every role and what the page shows for it, and says when it can't fit."""
import json, os, re, tempfile, unittest

from engine import runrecord

COMPANIES = ('Brightwater', 'Corvid Labs', 'Halcyon Health', 'Meridian Freight', 'Northwind Games', 'Pinecrest Bank',
             'Quillon', 'Redwood Robotics', 'Saltmarsh Media', 'Tidewell')
TIERS = ('A', 'B', 'C+', 'C', 'cap', 'gap', 'gate')


def role(i):
    co = COMPANIES[i % len(COMPANIES)]
    slug = co.lower().replace(' ', '-')
    return dict(
        ref=i + 1, tier=TIERS[i % len(TIERS)], base_tier='B', fit=60 + i % 35, ats=70 + i % 25, company=co,
        title=f'Senior Product Manager, Growth {i}',
        why='strong match on consumer growth, lifecycle and experimentation; level and pay fit; posting is two weeks old',
        parts=dict(base=50, strengths=18, gaps=-4, level=3, ats=4, location=5,
                   strength_hits=['growth', 'lifecycle', 'experimentation', 'consumer', 'retention', 'onboarding',
                                  'monetization', 'payments', r'(?:a/b|ab) test'],
                   gap_hits=[['sql', 'required'], ['healthcare', 'preferred'], ['b2b saas', 'preferred']]),
        locations='Seattle/Remote US/New York', top_locations=['Seattle'], location_raw='Seattle, WA; Remote (US); NYC',
        salary_min=180000, salary_max=240000, gaps=['sql', 'healthcare'], flags=['asks 8+ years', 'on-site 3 days'],
        url=f'https://www.linkedin.com/jobs/view/senior-product-manager-growth-and-lifecycle-at-{slug}-{4400000000 + i}'
            '?refId=abcdefghijklmnop&trackingId=qrstuvwxyz0123456789',
        id=f'li-{4400000000 + i}',
        source='greenhouse (via job board; board "brightwater" found by name, check it is this company)' if i % 7 == 0
        else ('linkedin', 'greenhouse', 'ashby', 'lever')[i % 4],
        new=i % 3 == 0, first_seen='2026-01-02', gap_hold=i % 5 == 0,
        read=None if TIERS[i % len(TIERS)] in ('C+', 'C', 'cap', 'gate') else dict(gap_type=('minor', 'major', 'critical', 'none')[i % 4],
                  top_gap='No stated ownership of an in-product messaging system with segmentation, triggers and capping',
                  gap_quote='Experience shipping in-product messaging, notification or CRM systems, including '
                            'segmentation, triggers and frequency capping',
                  strengths=[dict(label=f'Lifecycle experimentation program {k}', level=('excellent', 'strong')[k % 2],
                                  posting='Design and run experiments to measure the impact of marketing, messaging and '
                                          'rewards on retention across web and mobile',
                                  resume='bank:growth-3', note='ignored by the page')
                             for k in range(4)],
                  extra='not on the page'))


def drop(i, reason, listed=True):
    return dict(stage='discover', reason=reason, company=COMPANIES[i % len(COMPANIES)],
                title=f'Senior Product Manager, Payments {i}', location='London / Berlin / Paris / Madrid / Rome',
                locations='', salary_max=150000 if reason == 'salary' else None, id=f'gh-x-{i}', source='greenhouse',
                url=f'https://job-boards.greenhouse.io/brightwater/jobs/{8000000000 + i}?gh_jid={8000000000 + i}',
                detail='top of range below your floor' if reason == 'salary' else '', postings=1, ref=f'd{i + 1}',
                fit=i % 90, ats=60, gaps=['sql'], flags=['asks 8+ years'], top_locations=[],
                would_be=('A' if listed else 'C'))


def big_run(roles=100):
    dropped = [drop(i, 'salary') for i in range(80)]
    dropped += [drop(80 + i, ('location', 'already_applied', 'passed', 'duplicate')[i % 4], listed=False)
                for i in range(400)]
    return dict(version=1, date='2026-01-05', pack='product', picks={}, roles=[role(i) for i in range(roles)],
                dropped=dropped)


def page_data_of(path):
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    return html, json.loads(re.search(r'const DATA = (.*?);\nconst CALLS', html, re.S).group(1))


class Budget(unittest.TestCase):
    def build(self, rec):
        return runrecord.build_page(rec, tempfile.mkdtemp())

    def test_hundred_roles_with_full_reads_fit(self):
        rec = big_run()
        page = self.build(rec)
        size = os.path.getsize(page)
        self.assertLessEqual(size, runrecord.PAGE_BUDGET)
        self.assertLessEqual(size / runrecord.TOKEN_BYTES, 35_000)
        self.assertNotIn('over the', runrecord.page_size(page))
        html, data = page_data_of(page)
        roles = runrecord.page_roles(data)
        self.assertEqual([r['ref'] for r in roles], list(range(1, 101)))  # every scored role stays
        r, src = roles[1], rec['roles'][1]  # tier B
        for k in ('tier', 'fit', 'ats', 'company', 'title', 'why', 'locations', 'salary_max', 'gaps', 'flags', 'id',
                  'source', 'top_locations'):
            self.assertEqual(r[k], src[k], k)  # what the page shows is kept as is
        self.assertEqual(r['url'], 'https://www.linkedin.com/jobs/view/4400000001/')
        self.assertEqual(r['read']['top_gap'], src['read']['top_gap'])
        self.assertEqual(r['read']['gap_quote'], src['read']['gap_quote'])
        self.assertEqual([s['label'] for s in r['read']['strengths']], [s['label'] for s in src['read']['strengths'][:3]])
        self.assertEqual(r['parts']['gap_hits'], ['sql', 'healthcare', 'b2b saas'])
        self.assertEqual(r['parts']['strength_n'], 9)
        self.assertNotIn('extra', r['read'])
        drops = runrecord.page_drops(data)
        self.assertEqual(len(drops) + sum(data['omitted'].values()), len(rec['dropped']))  # left off, but counted
        if data['omitted'].get('salary'):  # listed drops go only after every compact row and hover quote
            self.assertEqual(data['hidden']['rows'], [])
            self.assertNotIn('posting', r['read']['strengths'][0])
        kept = sorted(d['fit'] for d in drops if d['reason'] == 'salary')
        cut = [d['fit'] for d in rec['dropped'] if d['reason'] == 'salary' and d['ref'] not in {x['ref'] for x in drops}]
        self.assertLessEqual(max(cut or [-1]), min(kept or [100]))  # lowest fit go first
        self.assertLess(max(map(len, html.splitlines())), 4000)  # one row per line: readable in parts

    def test_roles_alone_over_budget_cut_hover_quotes_then_warn(self):
        rec = big_run(roles=400)
        page = self.build(rec)
        _, data = page_data_of(page)
        roles = runrecord.page_roles(data)
        self.assertEqual(len(roles), 400)  # roles are never left off: picks need them
        self.assertEqual(runrecord.page_drops(data), [])
        self.assertNotIn('posting', roles[0]['read']['strengths'][0])
        self.assertEqual(roles[0]['read']['strengths'][0]['label'], 'Lifecycle experimentation program 0')
        msg = runrecord.page_size(page)
        self.assertIn('over the 120 KB budget', msg)
        self.assertIn('read it in parts', msg)

    def test_page_and_standing_copy_begin_with_the_doctype(self):
        """The artifact server sniffs index.html and refuses a page that doesn't start with <!DOCTYPE html>."""
        page = self.build(big_run(roles=3))
        ws = tempfile.mkdtemp()
        for p in (page, runrecord.standing_copy(page, ws)):
            with open(p, encoding='utf-8') as fh:
                self.assertTrue(fh.read().startswith('<!DOCTYPE html>\n'), p)

    def test_short_url(self):
        self.assertEqual(runrecord.short_url('https://www.linkedin.com/jobs/view/senior-pm-at-brightwater-4487427675'),
                         'https://www.linkedin.com/jobs/view/4487427675/')
        self.assertEqual(runrecord.short_url('https://www.linkedin.com/jobs/view/4487427675/?trk=x'),
                         'https://www.linkedin.com/jobs/view/4487427675/')
        for u in ('https://job-boards.greenhouse.io/brightwater/jobs/8044715003', '', None):
            self.assertEqual(runrecord.short_url(u), u)


if __name__ == '__main__':
    unittest.main()
