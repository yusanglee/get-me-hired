"""G1: integration glue for the E6a/E6b features. The RECORDED_* tables were captured from the code BEFORE this
package (a US-only config: no remote_countries with CA, no floor_cad, a profile without Canada fields) and pin every
keep/drop decision, reason, parsed pay, gate result and searcher opts. Fictional postings only."""
import copy, os, sys, tempfile, types, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import boards, discover, gates, packs, runrecord, score, setup, triage  # noqa: E402
from engine.profile import Profile, load_config  # noqa: E402


def P(title, loc='Remote, US', wp='Remote', text='', smin=None, smax=None, bands=None):
    return dict(id='x', title=title, location=loc, workplace=wp, text=text, smin=smin, smax=smax, bands=bands or [],
                company='Brightwater')


CASES = [P('Senior Product Manager'), P('Product Manager'), P('Product Manager', smin=140000, smax=149999),
         P('Product Manager', smin=150000, smax=150000), P('Staff Product Manager', text='Pay $120,000 - $149,000'),
         P('Staff Product Manager', text='Pay $120,000 - $190,000'), P('Product Manager', loc='Los Angeles, CA', wp=''),
         P('Product Manager', loc='New York, NY', wp='', bands=[{'label': 'New York', 'min': 130000, 'max': 140000}]),
         P('Product Manager', loc='Los Angeles, CA', wp='', text='Los Angeles: $160,000 - $200,000 Remote: $120,000 - $140,000'),
         P('Senior Product Manager', loc='Toronto, ON', wp=''), P('Senior Product Manager', loc='Remote - Canada', wp='Remote'),
         P('Senior Product Manager', text='CA$90,000 - CA$100,000'), P('Registered Nurse')]
CFG = {'salary': {'floor_usd': 150000},
       'locations': {'home': 'LA', 'remote_us': True, 'metros': [{'name': 'LA'}, {'name': 'NYC', 'policy': 'hybrid_ok'}]}}
CFG_REMOTE_OFF = {'salary': {}, 'locations': {'home': 'LA', 'remote_us': False, 'metros': [{'name': 'LA'}]}}
JDS = ['We are hiring a product manager.', 'Must be a U.S. citizen. Active security clearance required.',
       'We cannot provide visa sponsorship.', 'Fluent Spanish required.', 'French required for this role. Bilingue.']
US_PROFILE = Profile({'work_authorization': {'authorized_us': 'Yes', 'needs_sponsorship': 'Yes',
                                             'citizenship': 'United States of America'}})


def decisions(cfg, policy=None):
    c = copy.deepcopy(cfg)
    if policy:
        c.setdefault('salary', {})['no_range_policy'] = policy
    ctx = types.SimpleNamespace(pack=packs.load('product-management'), cfg=load_config(c))
    out = []
    for p in CASES:
        info, why = discover.keep(ctx, dict(p))
        out.append([why, None if info is None else [info['locations'], info['smin'], info['smax'], info['salary_source']]])
    return out


RECORDED_DEFAULT = [['kept', ['Remote', None, None, 'none']], ['no_range_level', None], ['salary', None],
 ['kept', ['Remote', 150000, 150000, 'board']], ['salary', None], ['kept', ['Remote', 120000.0, 190000.0, 'jd_text']],
 ['no_range_level', None], ['salary', None], ['kept', ['LA', 160000.0, 200000.0, 'band:LA']], ['location', None],
 ['location', None], ['kept', ['Remote', None, None, 'none']], ['title', None]]
RECORDED_INCLUDE = [['kept', ['Remote', None, None, 'none']], ['kept', ['Remote', None, None, 'none']], ['salary', None],
 ['kept', ['Remote', 150000, 150000, 'board']], ['salary', None], ['kept', ['Remote', 120000.0, 190000.0, 'jd_text']],
 ['kept', ['LA', None, None, 'none']], ['salary', None], ['kept', ['LA', 160000.0, 200000.0, 'band:LA']],
 ['location', None], ['location', None], ['kept', ['Remote', None, None, 'none']], ['title', None]]
RECORDED_REMOTE_OFF = [['location', None], ['location', None], ['location', None], ['location', None], ['location', None],
 ['location', None], ['no_range_level', None], ['location', None], ['kept', ['LA', 160000.0, 200000.0, 'band:LA']],
 ['location', None], ['location', None], ['location', None], ['title', None]]
RECORDED_EXCLUDE = [['no_range_level', None], ['no_range_level', None], ['salary', None], ['kept', ['Remote', 150000, 150000, 'board']],
 ['salary', None], ['kept', ['Remote', 120000.0, 190000.0, 'jd_text']], ['no_range_level', None], ['salary', None],
 ['kept', ['LA', 160000.0, 200000.0, 'band:LA']], ['location', None], ['location', None], ['no_range_level', None],
 ['title', None]]
RECORDED_GATES = [[['UNVERIFIED', 'posting silent on sponsorship', "check the employer's careers page before drafting"]],
 [['FAIL', 'security clearance required', 'Active security clearance required'],
  ['UNVERIFIED', 'posting silent on sponsorship', "check the employer's careers page before drafting"],
  ['PASS', 'citizenship required', 'Must be a U.S. citizen']],
 [['FAIL', 'no visa sponsorship', 'We cannot provide visa sponsorship']],
 [['FAIL', 'Spanish required, not in profile', 'Fluent Spanish required'],
  ['UNVERIFIED', 'posting silent on sponsorship', "check the employer's careers page before drafting"]],
 [['UNVERIFIED', 'posting silent on sponsorship', "check the employer's careers page before drafting"]]]
RECORDED_OPTS = [{'pages': 2}, {'pages': 2}, {'pages': 2}]


class UsOnlyParity(unittest.TestCase):
    def test_keep_default_policy(self):
        self.assertEqual(decisions(CFG), RECORDED_DEFAULT)

    def test_keep_include_policy(self):
        self.assertEqual(decisions(CFG, 'include'), RECORDED_INCLUDE)

    def test_keep_remote_off_no_floor(self):
        self.assertEqual(decisions(CFG_REMOTE_OFF), RECORDED_REMOTE_OFF)

    def test_exclude_only_changes_the_no_range_reason(self):
        got = decisions(CFG, 'exclude')
        want = [['no_range' if r[0] == 'no_range_level' else r[0], r[1]] for r in RECORDED_EXCLUDE]
        self.assertEqual(got, want)
        self.assertIn('no_range', [r[0] for r in got])
        self.assertNotIn('no_range_level', [r[0] for r in got])

    def test_gates_unchanged_and_location_not_passed(self):
        ctx = types.SimpleNamespace(cfg=load_config(copy.deepcopy(CFG)))
        for jd, want in zip(JDS, RECORDED_GATES):
            loc = score.gate_location(ctx, US_PROFILE, 'Remote - US or Canada')
            self.assertIsNone(loc)
            self.assertEqual([list(r) for r in gates.check(jd, US_PROFILE, location=loc)], want)

    def test_searcher_opts_unchanged(self):
        spec = {'enabled': True, 'queries': ['pm'], 'opts': {'pages': 2}}
        cfg = load_config({'sources': {'linkedin': spec, 'himalayas': spec}})
        got = [boards.source_opts('linkedin', cfg['sources']['linkedin'], cfg),
               boards.source_opts('himalayas', cfg['sources']['himalayas'], cfg), boards.source_opts('nodesk', spec, cfg)]
        self.assertEqual(got, RECORDED_OPTS)
        self.assertEqual(boards.source_opts('linkedin', {'enabled': True}, load_config({})), {})


CA_CFG = {'salary': {'floor_usd': 150000, 'floor_cad': 180000},
          'locations': {'home': 'Toronto', 'remote_countries': ['US', 'CA'], 'metros': [{'name': 'Toronto'}]}}


class CadPay(unittest.TestCase):
    def keep(self, cfg, text):
        ctx = types.SimpleNamespace(pack=packs.load('product-management'), cfg=load_config(copy.deepcopy(cfg)))
        return discover.keep(ctx, P('Senior Product Manager', loc='Toronto, ON', wp='', text=text))

    def test_cad_range_uses_cad_floor(self):
        info, why = self.keep(CA_CFG, 'Pay CA$120,000 - CA$150,000')
        self.assertEqual((info, why), (None, 'salary'))
        info, why = self.keep(CA_CFG, 'Pay CA$150,000 - CA$200,000')
        self.assertEqual(why, 'kept')
        self.assertTrue(info['salary_source'].endswith(' CAD'))

    def test_cad_range_without_cad_floor_is_kept(self):
        cfg = copy.deepcopy(CA_CFG)
        cfg['salary']['floor_cad'] = None
        info, why = self.keep(cfg, 'Pay CA$90,000 - CA$100,000')
        self.assertEqual(why, 'kept')

    def test_usd_range_still_uses_usd_floor(self):
        cfg = copy.deepcopy(CA_CFG)
        info, why = self.keep(cfg, 'Pay US$120,000 - US$140,000 USD')
        self.assertEqual(why, 'salary')


class BoardOpts(unittest.TestCase):
    def test_linkedin_places_from_config(self):
        cfg = load_config({'locations': {'remote_countries': ['US', 'CA'], 'metros': []}, 'sources': {'linkedin': {'enabled': True}}})
        opts = boards.source_opts('linkedin', cfg['sources']['linkedin'], cfg)
        self.assertEqual(opts['locations'], ['United States', 'Canada'])

    def test_explicit_linkedin_locations_win(self):
        cfg = load_config({'locations': {'remote_countries': ['US', 'CA'], 'metros': []},
                           'sources': {'linkedin': {'enabled': True, 'opts': {'locations': ['Denver'], 'pages': 1}}}})
        self.assertEqual(boards.source_opts('linkedin', cfg['sources']['linkedin'], cfg), {'locations': ['Denver'], 'pages': 1})

    def test_himalayas_gets_remote_countries(self):
        cfg = load_config({'locations': {'remote_countries': ['CA'], 'metros': []}, 'sources': {'himalayas': {'enabled': True}}})
        self.assertEqual(boards.source_opts('himalayas', cfg['sources']['himalayas'], cfg), {'remote_countries': ['CA']})
        cfg['sources']['himalayas']['opts'] = {'remote_countries': ['US']}
        self.assertEqual(boards.source_opts('himalayas', cfg['sources']['himalayas'], cfg), {'remote_countries': ['US']})

    def test_search_receives_merged_opts(self):
        seen = {}
        cfg = load_config({'locations': {'remote_countries': ['US', 'CA'], 'metros': []},
                           'sources': {'linkedin': {'enabled': True, 'queries': ['pm']}}})
        orig = boards.SEARCHERS['linkedin']
        boards.SEARCHERS['linkedin'] = lambda q, d, o: seen.update(o) or []
        try:
            boards._search('linkedin', cfg['sources']['linkedin'], 14, cfg)
        finally:
            boards.SEARCHERS['linkedin'] = orig
        self.assertEqual(seen['locations'], ['United States', 'Canada'])


class GateLocation(unittest.TestCase):
    def test_passed_only_when_canada_is_in_play(self):
        us = types.SimpleNamespace(cfg=load_config(copy.deepcopy(CFG)))
        ca = types.SimpleNamespace(cfg=load_config(copy.deepcopy(CA_CFG)))
        self.assertIsNone(score.gate_location(us, US_PROFILE, 'Toronto, ON'))
        self.assertEqual(score.gate_location(ca, US_PROFILE, 'Toronto, ON'), 'Toronto, ON')
        has_ca = Profile({'work_authorization': {'authorized_canada': 'Yes', 'needs_sponsorship_canada': 'No'}})
        self.assertEqual(score.gate_location(us, has_ca, 'Toronto, ON'), 'Toronto, ON')
        self.assertIsNone(score.gate_location(ca, None, 'Toronto, ON'))


class NoRangeReason(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(runrecord.REASONS['no_range'], 'No posted pay range')
        self.assertIn('not senior', runrecord.REASONS['no_range_level'])
        page = open(os.path.join(os.path.dirname(runrecord.__file__), 'review_page.html'), encoding='utf-8').read()
        self.assertIn("no_range: 'No posted pay range'", page)
        self.assertIn("'no_range_level', 'no_range']", page)


class ConfigValidation(unittest.TestCase):
    def test_bad_policy_is_a_clear_error(self):
        with self.assertRaises(packs.PackError) as cm:
            load_config({'salary': {'no_range_policy': 'sometimes'}})
        self.assertIn('salary.no_range_policy', str(cm.exception))
        for ok in ('include', 'exclude', 'include_if_level_fits'):
            load_config({'salary': {'no_range_policy': ok}})
        load_config({})

    def test_example_config_resume_keys(self):
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = json.load(open(os.path.join(root, 'templates', 'config.example.json'), encoding='utf-8'))['resume']
        self.assertEqual((r['max_pages'], r['max_scope_lines'], r['min_last_line_words'], r['max_page1_free_pt']), (2, 2, 3, 40))
        self.assertIn('skills_lines', r['_layout_note'])
        self.assertNotIn('skills_lines', [k for k in r if not k.startswith('_')])

    def test_new_workspace_writes_remote_countries(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            ws = os.path.join(d, 'ws')
            setup.init(ws, pack='product-management') if 'pack' in setup.init.__code__.co_varnames else setup.init(ws)
            loc = json.load(open(os.path.join(ws, 'config.json'), encoding='utf-8'))['locations']
        self.assertEqual(loc['remote_countries'], ['US'])
        self.assertNotIn('remote_us', loc)
        self.assertTrue(load_config({'locations': loc})['locations']['remote_us'])


class YearsRe(unittest.TestCase):
    JD = 'We want 8+ years of nursing practice and 3 years in a hospital.'
    PROF = Profile({'employment': {'years_experience': '5 years'}})

    def test_default_is_unchanged(self):
        self.assertIs(triage.years_re(None), triage.YEARS_RE)
        self.assertIs(triage.years_re({'triage': {}}), triage.YEARS_RE)
        self.assertEqual(triage.over_bar(self.JD, self.PROF), ([], False))  # default pattern does not read "nursing practice"

    def test_pack_pattern(self):
        pack = {'triage': {'years_re': r'(?:(\d{1,2})\s*-\s*)?(\d{1,2})\s*\+?\s*years?\s+of\s+nursing'}}
        self.assertEqual(triage.over_bar(self.JD, self.PROF, pack), (['asks 8+ years (profile: 5)'], True))

    def test_bad_pattern_is_a_clear_error(self):
        with self.assertRaises(ValueError):
            triage.years_re({'triage': {'years_re': '('}})


if __name__ == '__main__':
    unittest.main()
