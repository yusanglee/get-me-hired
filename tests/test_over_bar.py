"""Critical-gap Tier A false positives: seniority asks the fit score doesn't read (engine/triage.py over_bar),
earlier review calls carried onto "passed before" drops, hard gates on dropped roles, and the picks warnings.
Fictional people and postings only (the Chief of Staff fixture run: Acme Robotics, Globex, Initech)."""
import csv, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from engine import runrecord, score, triage  # noqa: E402
from engine.profile import Profile  # noqa: E402
import test_runrecord as TR  # noqa: E402

PM = Profile({'employment': {'years_experience': '12 years (2014 to 2026)', 'managed_managers': 'No'}})
SILENT = Profile({'employment': {'years_experience': '12 years'}})


class OverBar(unittest.TestCase):
    def test_years_above_profile_hold(self):
        flags, hold = triage.over_bar('What we look for: 15+ years in product management, leading multi-team areas.', PM)
        self.assertEqual((flags, hold), (['asks 15+ years (profile: 12)'], True))
        self.assertEqual(triage.over_bar('Requirements: 10+ years of product experience.', PM), ([], False))
        self.assertEqual(triage.over_bar('Requirements: 12+ years of product experience.', PM), ([], False))
        self.assertEqual(triage.over_bar('Required: 10\u201314 years in product management.', PM), ([], False))
        self.assertEqual(triage.over_bar('Required: 14-18 years in product management.', PM), (['asks 14+ years (profile: 12)'], True))

    def test_years_nice_to_have_or_not_experience_ignored(self):
        for jd in ('Nice to have: 15+ years of experience in fintech.', 'Brightwater has 20 years serving customers.',
                   '8+ years of product experience; 15+ years of experience is a plus.'):
            self.assertEqual(triage.over_bar(jd, PM), ([], False), jd)

    def test_profile_years_parse(self):
        self.assertEqual(triage.profile_years(Profile({'employment': {'years_experience': 'from master: 13 years PM, 2013 to 2026'}})), 13)
        self.assertIsNone(triage.profile_years(Profile({})))
        self.assertIsNone(triage.profile_years(None))
        self.assertEqual(triage.over_bar('15+ years of product experience required.', Profile({})), ([], False))

    def test_manages_managers(self):
        for jd in ('Build, mentor, and manage a team of product managers, including people managers.',
                   'People Leadership: Experience operating through layers of leadership, delegating ownership.',
                   'You will lead a team of product leaders across three groups.',
                   'Experience managing managers in a high-growth company.'):
            flags, hold = triage.over_bar(jd, PM)
            self.assertTrue(hold, jd)
            self.assertTrue(flags[0].startswith('asks to manage managers (profile: not done)'), jd)
        flags, hold = triage.over_bar('Experience managing managers in a high-growth company.', SILENT)
        self.assertFalse(hold)
        self.assertIn('profile employment.managed_managers not set', flags[0])
        yes = Profile({'employment': {'managed_managers': 'Yes'}})
        self.assertEqual(triage.over_bar('Experience managing managers.', yes), ([], False))

    def test_people_management_alone_is_not_managers_of_managers(self):
        for jd in ('Manage a team of 4 product managers.', 'Partner with product leaders and engineering managers.',
                   'Nice to have: experience managing managers.'):
            self.assertEqual(triage.over_bar(jd, PM), ([], False), jd)

    def test_held_tier(self):
        sc = {'tier_a': 70, 'tier_b': 55}
        self.assertEqual(triage.held_tier('A', True, sc), 'B')
        self.assertEqual(triage.held_tier('B', True, sc), 'B')
        self.assertEqual(triage.held_tier('A', False, sc), 'A')
        self.assertEqual(triage.held_tier('A', True, dict(sc, over_bar_tier='A')), 'A')


class EndToEnd(TR.Fixture):
    def write_profile(self, years='3 years'):
        open(os.path.join(self.ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write(
            'identity:\n  first_name: Jordan\n  last_name: Rivera\n  email: jordan@example.com\n'
            'work_authorization:\n  citizenship: United States of America\n  needs_sponsorship: "No"\n'
            f'employment:\n  years_experience: {years}\n')

    def add_to_jd(self, ctx, rid, text):
        with open(os.path.join(ctx.state, 'jd', rid + '.txt'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\n' + text)

    def write_reviewed(self, ctx, date, rows):
        with open(os.path.join(ctx.queue, f'reviewed-{date}.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=runrecord.REVIEWED_COLUMNS, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

    def rescore(self, ctx):
        lines = []
        score.run(ctx, out=lines.append)
        return json.load(open(runrecord.path_for(ctx.queue, TR.DATE), encoding='utf-8')), lines

    def test_held_to_b_with_why(self):
        p = os.path.join(self.ws, 'config.json')
        cfg = json.load(open(p, encoding='utf-8'))
        cfg.setdefault('scoring', {}).update(tier_a=40, tier_b=30)
        json.dump(cfg, open(p, 'w', encoding='utf-8', newline='\n'))
        self.write_profile('3 years')
        ctx, _ = self.discover()
        self.add_to_jd(ctx, 'gh-acme-1', 'Requirements: 10+ years of experience in operations.')
        rec, _ = self.rescore(ctx)
        r = next(r for r in rec['roles'] if r['id'] == 'gh-acme-1')
        self.assertEqual((r['tier'], r['base_tier']), ('B', 'B'))
        self.assertIn('held to B', r['why'])
        self.assertIn('asks 10+ years (profile: 3)', r['flags'])

    def test_passed_drop_carries_worst_gap_and_picks_warn(self):
        ctx, _ = self.discover()
        base = dict(company='Initech', title='Chief of Staff', id='hm-initech-cos', url='https://example.com/initech')
        self.write_reviewed(ctx, '2026-10-10', [dict(base, call='pass', gap_type='critical',
                                                      top_gap='operating through layers of leadership')])
        self.write_reviewed(ctx, '2026-10-15', [dict(base, call='pass', notes='company cap')])
        rec, _ = self.rescore(ctx)
        d = next(d for d in rec['dropped'] if d['id'] == 'hm-initech-cos')
        self.assertEqual(d['reason'], 'passed')
        self.assertEqual(d['prior'], dict(date='2026-10-15', gap_type='critical', top_gap='operating through layers of leadership',
                                          notes='company cap', gap_date='2026-10-10'))
        _, warn, _ = runrecord.apply_picks(ctx.queue, TR.DATE, [dict(ref=d['ref'], call='apply')], dry_run=True)
        self.assertTrue(any('passed 2026-10-10 with a critical gap (operating through layers of leadership)' in w for w in warn), warn)
        html = open(os.path.join(ctx.queue, f'review-{TR.DATE}.html'), encoding='utf-8').read()
        self.assertIn('Earlier review', html)

    def test_dropped_role_that_fails_a_gate_is_not_would_be_a(self):
        self.write_profile()
        ctx, _ = self.discover()
        rec = json.load(open(runrecord.path_for(ctx.queue, TR.DATE), encoding='utf-8'))
        loc = next(d for d in rec['dropped'] if d['reason'] == 'location')
        self.add_to_jd(ctx, loc['id'], 'Requirements: Fluent Spanish or Portuguese.')
        rec, lines = self.rescore(ctx)
        d = next(d for d in rec['dropped'] if d['id'] == loc['id'])
        self.assertEqual(d['would_be'], 'gate')
        self.assertIn('Spanish or Portuguese required, neither in profile', d['gate'])
        _, warn, _ = runrecord.apply_picks(ctx.queue, TR.DATE, [dict(ref=d['ref'], call='apply')], dry_run=True)
        self.assertTrue(any('would fail a hard gate' in w for w in warn), warn)

    def test_employer_limit_zero_still_excludes(self):
        p = os.path.join(self.ws, 'config.json')
        cfg = json.load(open(p, encoding='utf-8'))
        cfg['company_limits'] = {'acme robotics': {'max_applications': 0, 'window_days': 3650}}
        json.dump(cfg, open(p, 'w', encoding='utf-8', newline='\n'))
        ctx, _ = self.discover()
        rec, _ = self.rescore(ctx)
        acme = [r for r in rec['roles'] if r['company'] == 'Acme Robotics' and r['base_tier'] != 'C']
        self.assertTrue(acme)
        self.assertEqual({r['tier'] for r in acme}, {'cap'})


if __name__ == '__main__':
    unittest.main()
