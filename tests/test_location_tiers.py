"""Two-tier target locations: config locations.top (first choice) adds top_bonus fit points and is shown in green."""
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from engine import locations, runrecord, score  # noqa: E402
from engine.profile import load_config  # noqa: E402
import test_discover_score as tds  # noqa: E402  (module import: its own tests don't run twice)

BASE = {'locations': {'home': 'LA', 'remote_us': True, 'metros': [{'name': 'LA'}, {'name': 'NYC'}, {'name': 'SF'}]}}


def cfg(**loc):
    c = json.loads(json.dumps(BASE))
    c['locations'].update(loc)
    return load_config(c)


class TopTierConfig(unittest.TestCase):
    def test_off_by_default(self):
        c = cfg()
        self.assertEqual(c['locations']['top'], [])
        self.assertEqual(locations.top_bonus('LA/Remote', c), (0, []))

    def test_top_match(self):
        c = cfg(top=['LA', 'Remote'], top_bonus=7)
        self.assertEqual(locations.top_bonus('SF/Remote', c), (7, ['Remote']))
        self.assertEqual(locations.top_bonus(['NYC'], c), (0, []))

    def test_unknown_top_name_refused(self):
        with self.assertRaisesRegex(ValueError, "'Boston'"):
            cfg(top=['Boston'])
        with self.assertRaisesRegex(ValueError, 'remote_us is off'):
            cfg(top=['Remote'], remote_us=False)

    def test_bonus_clamped_and_shown_in_parts(self):
        c = cfg(top=['LA'])
        r = dict(fit=98, locations='LA', parts={})
        score.add_location_bonus(c, r)
        self.assertEqual((r['fit'], r['top_locations'], r['parts']['location']), (100, ['LA'], 5))
        r = dict(fit=60, locations='NYC', parts={})
        score.add_location_bonus(c, r)
        self.assertEqual((r['fit'], r['top_locations'], r['parts']), (60, [], {}))


class TopTierEndToEnd(tds.CosEndToEnd):
    """The Chief of Staff fixture run, once with one tier and once with NYC as first choice."""

    def run_once(self, top):
        conf = json.loads(json.dumps(tds.CONFIG))
        if top:
            conf['locations']['top'] = top
        json.dump(conf, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        ctx, _ = self.discover()
        _, rows = score.run(ctx, out=lambda *a: None)
        return ctx, {r['id']: r for r in rows}

    def test_bonus_and_record(self):
        _, plain = self.run_once(None)
        ctx, tiered = self.run_once(['NYC'])
        self.assertEqual(tiered['gh-acme-1']['fit'], plain['gh-acme-1']['fit'] + 5)  # New York, NY
        self.assertEqual(tiered['gh-acme-1']['top_locations'], ['NYC'])
        self.assertEqual(tiered['gh-acme-7']['fit'], 0)  # SF on-site veto still wins
        rec = runrecord.load(ctx.queue, '2026-10-20')
        role = next(r for r in rec['roles'] if r['id'] == 'gh-acme-1')
        self.assertEqual((role['top_locations'], role['parts']['location']), (['NYC'], 5))
        self.assertTrue(all(r['top_locations'] == [] for r in rec['roles'] if 'NYC' not in r['locations'].split('/')))
        html = open(runrecord.build_page(rec, ctx.queue), encoding='utf-8').read()
        self.assertIn('loc-top', html)

    def test_discover_then_score(self):  # covered by the parent class
        pass

    test_earlier_pass_is_dropped_and_hold_is_labeled = test_second_run_marks_seen = test_discover_then_score
    test_explicit_config_queries_win = test_company_cap_counts_workflow_and_tracker = test_employer_limit = test_discover_then_score


class CompanyRules(unittest.TestCase):
    RULE = {'company': 'brightwater', 'when': 'multiple locations', 'as': 'LA'}

    def test_rule_matches_company_and_text(self):
        c = cfg(company_rules=[self.RULE])
        loc = 'Multiple Locations / Austin, Texas, United States'
        self.assertEqual(locations.location_match(loc, '', c, 'Brightwater Games'), ['LA'])
        self.assertEqual(locations.location_match(loc, '', c, 'Other Co'), [])
        self.assertEqual(locations.location_match('Austin, Texas', '', c, 'Brightwater'), [])
        self.assertEqual(locations.location_match(loc, '', c), [])

    def test_no_duplicate_when_already_matched(self):
        c = cfg(company_rules=[self.RULE])
        self.assertEqual(locations.location_match('Los Angeles / Multiple Locations', '', c, 'Brightwater'), ['LA'])

    def test_bad_rule_refused(self):
        with self.assertRaisesRegex(ValueError, "'Boston'"):
            cfg(company_rules=[dict(self.RULE, **{'as': 'Boston'})])
        with self.assertRaisesRegex(ValueError, 'needs when'):
            cfg(company_rules=[{'company': 'brightwater', 'as': 'LA'}])
        with self.assertRaisesRegex(ValueError, "'when' 'multiple \\(locations' is not a valid regex"):
            cfg(company_rules=[dict(self.RULE, when='multiple (locations')])


if __name__ == '__main__':
    unittest.main()
