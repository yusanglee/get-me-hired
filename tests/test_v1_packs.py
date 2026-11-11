"""E6b: discovery and scoring for any field. The recorded decisions below were captured from the code BEFORE the
no-range policy, pack triage regex and pack board paths existed; they pin every keep/drop decision, reason and
parsed pay for the shipped packs under old-default settings. Fictional postings only."""
import copy, os, sys, types, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import discover, packs, triage  # noqa: E402
from engine.profile import load_config  # noqa: E402

CFG = {'salary': {'floor_usd': 150000},
       'locations': {'home': 'LA', 'remote_us': True, 'metros': [{'name': 'LA'}, {'name': 'NYC', 'policy': 'hybrid_ok'}]}}


def posting(title, loc='Remote, US', wp='Remote', text='', smin=None, smax=None):
    return dict(id='x', title=title, location=loc, workplace=wp, text=text, smin=smin, smax=smax, bands=[], company='Brightwater')


def ctx_for(pack, cfg=None):
    return types.SimpleNamespace(pack=pack, cfg=load_config(copy.deepcopy(cfg or CFG)))


def decide(ctx, p):
    info, why = discover.keep(ctx, dict(p))
    return why, None if info is None else (info['locations'], info['smin'], info['smax'])


PM_CASES = [
    ('Senior Product Manager', posting('Senior Product Manager')),
    ('Staff Product Manager, Growth', posting('Staff Product Manager, Growth')),
    ('Product Manager', posting('Product Manager')),
    ('Product Manager w range', posting('Product Manager', smin=150000, smax=190000)),
    ('Product Manager low range', posting('Product Manager', smin=60000, smax=80000)),
    ('Senior PM low range', posting('Senior Product Manager', smin=60000, smax=80000)),
    ('Principal PM', posting('Principal Product Manager')),
    ('Director of Product', posting('Director of Product')),
    ('Head of Product', posting('Head of Product')),
    ('Product Manager II', posting('Product Manager II')),
    ('Associate Product Manager', posting('Associate Product Manager', smin=150000, smax=190000)),
    ('Product Designer', posting('Senior Product Designer')),
    ('Marketing', posting('Senior Product Marketing Manager')),
    ('Registered Nurse', posting('Registered Nurse')),
    ('Senior Engineer', posting('Senior Software Engineer')),
    ('Lead PM onsite far', posting('Lead Product Manager', loc='Berlin, Germany', wp='')),
    ('Sr PM text pay', posting('Sr. Product Manager', text='Pay range $170,000 - $210,000 per year')),
    ('PM text pay', posting('Product Manager', text='Pay range $170,000 - $210,000 per year')),
    ('Technical PM', posting('Senior Technical Product Manager')),
    ('Group PM', posting('Group Product Manager')),
    ('VP Product', posting('VP of Product')),
    ('Product Owner', posting('Senior Product Owner')),
    ('PM LA', posting('Product Manager', loc='Los Angeles, CA', wp='')),
    ('PM NYC onsite', posting('Product Manager', loc='New York, NY', wp='')),
]
PM_RECORDED = [
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('no_range_level', None),
    ('kept', ('Remote', 150000, 190000)),
    ('salary', None),
    ('salary', None),
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('title', None),
    ('title', None),
    ('title', None),
    ('title', None),
    ('title', None),
    ('location', None),
    ('kept', ('Remote', 170000.0, 210000.0)),
    ('kept', ('Remote', 170000.0, 210000.0)),
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('title', None),
    ('title', None),
    ('no_range_level', None),
    ('no_range_level', None),
]
COS_CASES = [
    (t, posting(t, smin=lo, smax=hi)) for t, lo, hi in [
        ('Chief of Staff', None, None), ('Senior Chief of Staff', None, None), ('Chief of Staff to the CEO', None, None),
        ('Chief of Staff', 160000, 200000), ('Chief of Staff', 90000, 120000), ('Head of Operations', None, None),
        ('Product Manager', None, None)]]
COS_RECORDED = [
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', None, None)),
    ('kept', ('Remote', 160000, 200000)),
    ('salary', None),
    ('kept', ('Remote', None, None)),
    ('title', None),
]

NURSE = {
    'name': 'nursing', 'label': 'Nursing',
    'titles': {'include': r'\bnurse\b|\brn\b|teacher', 'exclude': [], 'senior': r'senior|lead|charge', 'no_range': 'include'},
}
MOM_JD = 'You will manage charge nurses and lead a team of nurse managers who manage nurses.'


class RecordedDecisions(unittest.TestCase):
    """Shipped packs, config without the new keys: decisions identical to the recorded ones."""

    def test_product_management(self):
        ctx = ctx_for(packs.load('product-management'))
        got = [decide(ctx, p) for _, p in PM_CASES]
        self.assertEqual(got, PM_RECORDED)

    def test_chief_of_staff(self):
        ctx = ctx_for(packs.load('chief-of-staff'))
        self.assertEqual([decide(ctx, p) for _, p in COS_CASES], COS_RECORDED)

    def test_explicit_default_policy_changes_nothing(self):
        cfg = copy.deepcopy(CFG)
        cfg['salary'] = dict(cfg['salary'], no_range_policy='include_if_level_fits')
        ctx = ctx_for(packs.load('product-management'), cfg)
        self.assertEqual([decide(ctx, p) for _, p in PM_CASES], PM_RECORDED)

    def test_shipped_packs_set_no_new_keys(self):
        for name in packs.base_packs():
            pack = packs.load(name)
            self.assertNotIn('no_range', pack['titles'], name)
            self.assertNotIn('triage', pack, name)
            self.assertNotIn('sources', pack, name)


class NoRangePolicy(unittest.TestCase):
    def test_nursing_pack_include_keeps_titles_without_level_word(self):
        ctx = ctx_for(packs.validate(copy.deepcopy(NURSE)))
        for t in ('Registered Nurse', 'Math Teacher'):
            self.assertEqual(decide(ctx, posting(t)), ('kept', ('Remote', None, None)), t)
        # a posted range below the floor still drops
        self.assertEqual(decide(ctx, posting('Registered Nurse', smin=60000, smax=80000))[0], 'salary')

    def test_same_nursing_pack_under_default_policy_drops_them(self):
        pack = copy.deepcopy(NURSE)
        del pack['titles']['no_range']
        ctx = ctx_for(packs.validate(pack))
        self.assertEqual(decide(ctx, posting('Registered Nurse'))[0], 'no_range_level')
        self.assertEqual(decide(ctx, posting('Lead Nurse'))[0], 'kept')

    def test_config_policy(self):
        pm = packs.load('product-management')
        for policy, plain, senior in (('include', 'kept', 'kept'), ('exclude', 'no_range', 'no_range'),
                                      ('include_if_level_fits', 'no_range_level', 'kept')):
            cfg = copy.deepcopy(CFG)
            cfg['salary'] = dict(cfg['salary'], no_range_policy=policy)
            ctx = ctx_for(pm, cfg)
            self.assertEqual(decide(ctx, posting('Product Manager'))[0], plain, policy)
            self.assertEqual(decide(ctx, posting('Senior Product Manager'))[0], senior, policy)

    def test_exclude_still_keeps_ranged_postings(self):
        cfg = copy.deepcopy(CFG)
        cfg['salary'] = dict(cfg['salary'], no_range_policy='exclude')
        ctx = ctx_for(packs.load('product-management'), cfg)
        self.assertEqual(decide(ctx, posting('Product Manager', smin=150000, smax=190000))[0], 'kept')

    def test_pack_overrides_config(self):
        cfg = copy.deepcopy(CFG)
        cfg['salary'] = dict(cfg['salary'], no_range_policy='exclude')
        ctx = ctx_for(packs.validate(copy.deepcopy(NURSE)), cfg)
        self.assertEqual(decide(ctx, posting('Registered Nurse'))[0], 'kept')
        pack = copy.deepcopy(NURSE)
        pack['titles']['no_range'] = 'exclude'
        cfg['salary']['no_range_policy'] = 'include'
        self.assertEqual(decide(ctx_for(packs.validate(pack), cfg), posting('Lead Nurse'))[0], 'no_range')

    def test_bad_values(self):
        pack = copy.deepcopy(NURSE)
        pack['titles']['no_range'] = 'sometimes'
        with self.assertRaises(packs.PackError):
            packs.validate(pack)
        cfg = copy.deepcopy(CFG)
        cfg['salary'] = dict(cfg['salary'], no_range_policy='sometimes')
        with self.assertRaises(packs.PackError):
            decide(ctx_for(packs.load('product-management'), cfg), posting('Senior Product Manager'))


class ManagerOfManagers(unittest.TestCase):
    PROF = {'employment.managed_managers': 'No'}

    def test_default_pattern_unchanged_without_pack(self):
        self.assertIs(triage.managers_re(None), triage.MANAGERS_RE)
        self.assertIs(triage.managers_re(packs.load('product-management')), triage.MANAGERS_RE)

    def test_pack_pattern(self):
        flags, hold = triage.over_bar(MOM_JD, self.PROF)
        self.assertEqual((flags, hold), ([], False))  # default is PM-worded, no match
        pack = packs.validate(dict(copy.deepcopy(NURSE), triage={'manager_of_managers': r'nurse managers who manage'}))
        flags, hold = triage.over_bar(MOM_JD, self.PROF, pack)
        self.assertTrue(hold)
        self.assertIn('asks to manage managers', flags[0])

    def test_bad_regex_rejected(self):
        with self.assertRaises(packs.PackError):
            packs.validate(dict(copy.deepcopy(NURSE), triage={'manager_of_managers': '('}))


class BoardCategories(unittest.TestCase):
    CFG = {'sources': {'builtin': {'enabled': True}, 'remote100k': {'enabled': True}, 'nodesk': {'enabled': True}}}

    def test_pm_pack_keeps_searcher_defaults(self):
        notes = []
        src = discover.board_sources(self.CFG, packs.load('product-management'), notes=notes)
        self.assertEqual(set(src), {'builtin', 'remote100k', 'nodesk'})
        self.assertNotIn('opts', src['builtin'])
        self.assertNotIn('opts', src['remote100k'])
        self.assertEqual(notes, [])

    def test_other_pack_with_nothing_set_skips_both_with_a_note(self):
        notes = []
        src = discover.board_sources(self.CFG, packs.validate(copy.deepcopy(NURSE)), notes=notes)
        self.assertEqual(set(src), {'nodesk'})
        self.assertEqual({n for n, _ in notes}, {'builtin', 'remote100k'})
        self.assertIn('sources.builtin_path', dict(notes)['builtin'])

    def test_pack_settings_fill_opts(self):
        pack = packs.validate(dict(copy.deepcopy(NURSE), sources={'builtin_path': '/jobs/remote/nursing',
                                                                  'remote100k_category': 'healthcare'}))
        src = discover.board_sources(self.CFG, pack, notes=[])
        self.assertEqual(src['builtin']['opts']['paths'], ['/jobs/remote/nursing'])
        self.assertEqual(src['remote100k']['opts']['categories'], ['healthcare'])

    def test_config_opts_win_over_pack(self):
        cfg = {'sources': {'builtin': {'enabled': True, 'opts': {'paths': ['/jobs/remote/other'], 'pages': 1}}}}
        pack = packs.validate(dict(copy.deepcopy(NURSE), sources={'builtin_path': '/jobs/remote/nursing'}))
        src = discover.board_sources(cfg, pack, notes=[])
        self.assertEqual(src['builtin']['opts'], {'paths': ['/jobs/remote/other'], 'pages': 1})

    def test_config_opts_rescue_a_pack_with_no_setting(self):
        cfg = {'sources': {'remote100k': {'enabled': True, 'opts': {'categories': ['operations']}}}}
        notes = []
        src = discover.board_sources(cfg, packs.load('chief-of-staff'), notes=notes)
        self.assertEqual(src['remote100k']['opts']['categories'], ['operations'])
        self.assertEqual(notes, [])

    def test_disabled_board_gets_no_note(self):
        notes = []
        cfg = {'sources': {'builtin': {'enabled': False}}}
        discover.board_sources(cfg, packs.validate(copy.deepcopy(NURSE)), notes=notes)
        self.assertEqual(notes, [])

    def test_default_sources_unchanged_and_boards_default_on_removed(self):
        self.assertEqual(discover.DEFAULT_SOURCES, ('himalayas', 'remotive', 'nodesk', 'linkedin'))
        src = discover.board_sources({}, packs.validate(copy.deepcopy(NURSE)))
        self.assertEqual(set(src), set(discover.DEFAULT_SOURCES))
        from engine import boards
        self.assertFalse(hasattr(boards, 'DEFAULT_ON'))

    def test_bad_builtin_path_rejected(self):
        with self.assertRaises(packs.PackError):
            packs.validate(dict(copy.deepcopy(NURSE), sources={'builtin_path': 'jobs/nursing'}))


class Template(unittest.TestCase):
    def test_template_validates_with_new_fields(self):
        import json
        with open(os.path.join(packs.PACK_DIR, '_template.json'), encoding='utf-8') as fh:
            t = json.load(fh)
        t['titles']['include'] = 'nurse'
        packs.validate(t)
        self.assertIn('no_range', t['titles'])
        self.assertIn('manager_of_managers', t['triage'])
        self.assertIn('builtin_path', t['sources'])


if __name__ == '__main__':
    unittest.main()
