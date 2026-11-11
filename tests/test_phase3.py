"""Phase 3: profile/config, answer rules, resume schema, specs, pay bands, dedup and tiers.
All fixtures are fictional (templates/*.example.*, tests/fixtures/workspace)."""
import datetime, json, os, shutil, tempfile, unittest

from engine import yamlish
from engine.profile import Profile, load_profile, load_config, filename_prefix, home_display, salary_ask, find_soffice
from engine.answers import Answerer, load_answer_bank, load_stage5_answers, choose_option
from engine.locations import location_match, office_answer, preference_order
from engine.resume import apply_overrides, exp_index, page_break_failures, stale_failures, to_legacy, from_build_script, render_payload
from engine.specs import make_spec, run, SpecError, load_templates, load_bank, legacy
from engine.pay import salary, text_bands, ashby_bands, pick_band, lookup_pay, slug_guesses
from engine.triage import applied_index, already_applied, tier, assign_tiers
from engine.job_key import job_key
from engine.sources.base import posting

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WS = os.path.join(HERE, 'fixtures', 'workspace')
PROFILE = os.path.join(ROOT, 'templates', 'profile.example.yaml')
CONFIG = os.path.join(ROOT, 'templates', 'config.example.json')
BANK = os.path.join(ROOT, 'templates', 'answer-bank.example.md')


class TestYamlish(unittest.TestCase):
    def test_subset(self):
        d = yamlish.loads('a:\n  b: 1  # note\n  c: "x # y"\n  d: [1, two]\nlist:\n  - k: v\n    k2: "No"\n  - plain\nyes_no: No\nblock: |\n  one\n  two\n')
        self.assertEqual(d['a'], {'b': 1, 'c': 'x # y', 'd': [1, 'two']})
        self.assertEqual(d['list'], [{'k': 'v', 'k2': 'No'}, 'plain'])
        self.assertEqual(d['yes_no'], 'No')  # never coerced to False: it's a form answer
        self.assertEqual(d['block'], 'one\ntwo\n')

    def test_bad_indent_raises(self):
        with self.assertRaises(ValueError):
            yamlish.loads('a: 1\n   b: 2\n')


class TestProfileConfig(unittest.TestCase):
    def setUp(self):
        self.prof = load_profile(PROFILE)
        self.cfg = load_config(CONFIG)

    def test_profile(self):
        self.assertEqual(self.prof.get('identity.email'), 'jordan.rivera@example.com')
        self.assertEqual(self.prof.get('education.0.school'), 'Northwestern University')
        self.assertIsNone(self.prof.get('identity.website'))
        self.assertEqual(filename_prefix(self.prof), 'Jordan_Rivera_')
        self.assertEqual(home_display(self.prof), 'Chicago, IL')

    def test_required_fields(self):
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as fh:
            fh.write('identity:\n  first_name: A\n')
        with self.assertRaises(ValueError):
            load_profile(fh.name)
        os.remove(fh.name)

    def test_salary_rule(self):
        self.assertEqual(salary_ask(self.prof, 300000, 200000), '225000')  # 300K x 0.75
        self.assertEqual(salary_ask(self.prof, 200000, 190000), '190000')  # range bottom wins
        self.assertEqual(salary_ask(self.prof, None), '180000')            # no range: floor

    def test_config_defaults_and_metros(self):
        self.assertEqual(self.cfg['scoring']['near_miss_margin'], 5)
        self.assertEqual(self.cfg['locations']['home'], 'Chicago')
        self.assertIn('chicago', self.cfg['locations']['metros'][0]['pattern'])

    def test_legacy_location_shape(self):
        cfg = load_config({'locations': {'remote_us': True, 'los_angeles': 'any', 'san_francisco': 'hybrid_ok', 'sf_max_office_days': 3, 'new_york_city': 'any'}})
        names = [m['name'] for m in cfg['locations']['metros']]
        self.assertEqual(names, ['LA', 'SF', 'NYC'])
        self.assertEqual(cfg['locations']['home'], 'LA')
        self.assertEqual(cfg['locations']['metros'][1]['max_office_days'], 3)

    def test_unknown_metro_needs_pattern(self):
        with self.assertRaises(ValueError):
            load_config({'locations': {'metros': [{'name': 'Lisbon'}]}})

    def test_find_soffice_prefers_config(self):
        with tempfile.NamedTemporaryFile() as fh:
            self.assertEqual(find_soffice({'paths': {'soffice': fh.name}}), fh.name)


class TestLocations(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(CONFIG)
        self.prof = load_profile(PROFILE)

    def test_match(self):
        self.assertEqual(location_match('Chicago, IL', '', self.cfg), ['Chicago'])
        self.assertEqual(location_match('Remote - US', '', self.cfg), ['Remote'])
        self.assertEqual(location_match('Remote - Canada', '', self.cfg), [])
        self.assertEqual(preference_order(['SF', 'Remote', 'Chicago'], self.cfg), ['Chicago', 'Remote', 'SF'])

    def test_office_answers(self):
        self.assertEqual(office_answer('Can you work from our office?', 'Chicago', self.prof, self.cfg),
                         'I live in Chicago and can work from the Chicago office.')
        self.assertIn('2 days a week', office_answer('Are you able to be in office 3 days a week?', 'SF', self.prof, self.cfg))
        self.assertIn('relocate to New York', office_answer('Willing to relocate?', 'NYC', self.prof, self.cfg))
        self.assertTrue(office_answer('Do you currently live in the San Francisco area?', 'SF', self.prof, self.cfg).startswith('No, I live in Chicago.'))


class TestAnswers(unittest.TestCase):
    def setUp(self):
        self.prof = load_profile(PROFILE)
        rules, exact = load_answer_bank(BANK)
        self.a = Answerer(self.prof, rules, exact, today=datetime.date(2026, 10, 20))

    def test_profile_backed_rules(self):
        c = self.a.classify
        self.assertEqual(c('Email')['answer'], 'jordan.rivera@example.com')
        self.assertEqual(c('First Name')['answer'], 'Jordan')
        self.assertEqual(c('Gender')['answer'], 'Female')
        self.assertEqual(c('Gender')['kind'], 'eeo')
        self.assertEqual(c('Will you now or in the future require sponsorship?')['answer'], 'No')
        self.assertEqual(c('Are you legally authorized to work in the United States?')['answer'], 'Yes')
        self.assertEqual(c('What is the most recent company you worked for? (current or most recent company)')['answer'], 'Example Health')
        self.assertEqual(c('Current company')['answer'], 'N/A')  # currently_employed: false
        self.assertEqual(c('Location')['answer'], 'Chicago, IL')
        self.assertEqual(c('When can you start?')['answer'], '11/03/2026')  # today + 14 days
        self.assertEqual(c('Desired salary')['answer'], 'SALARY')

    def test_missing_profile_value_asks(self):
        r = self.a.classify('Website')
        self.assertEqual(r['kind'], 'ask')
        self.assertIn('identity.website', r['source'])
        self.assertEqual(self.a.answer('Website', required=False)['kind'], 'skip')

    def test_user_layer_wins(self):
        self.assertEqual(self.a.classify('Do you have a portfolio of work?')['answer'], 'Available on request.')
        self.assertEqual(self.a.classify('Do you live within 50 miles of our office?')['answer'], 'Chicago, IL')
        self.assertEqual(self.a.classify('I have not, and I will not, use AI tools')['kind'], 'ask')
        r = self.a.classify('Are you a current customer of our product?')
        self.assertEqual((r['answer'], r['source']), ('No', 'user: exact label'))

    def test_first_match_and_required_only(self):
        self.assertEqual(self.a.answer('GPA', required=False)['kind'], 'skip')
        self.assertEqual(self.a.answer('Which location are you applying for?', required=True), {'kind': 'fixed', 'answer': 'Chicago', 'source': 'generic rule'})
        self.assertEqual(self.a.classify('Something nobody covers')['kind'], 'ask')

    def test_no_personal_literals_in_generic_rules(self):
        from engine.answers import GENERIC_RULES
        text = json.dumps(GENERIC_RULES).lower()
        # Generic rules point at profile keys; no person's values belong in them (fictional examples here;
        # tests/test_phase7.py checks every tracked file against the real owner's workspace).
        for leaked in ('jordan', 'rivera', 'northwind', 'chicago', '555-'):
            self.assertNotIn(leaked, text)

    def test_stage5_answers(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'stage5-questions-2026-10-20.md'), 'w', encoding='utf-8', newline='\n').write(
                '# Q\n\n1. **Why Acme?** (1 role: Acme: CoS)  \n   ANSWER: Because ops.\n2. **Unanswered?** (1 role: X)  \n   ANSWER:\n')
            self.assertEqual(load_stage5_answers(os.path.join(d, 'stage5-*.md')), {'Why Acme?': 'Because ops.'})

    def test_bad_bank_kind(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as fh:
            fh.write('- `x` -> maybe: y\n')
        with self.assertRaises(ValueError):
            load_answer_bank(fh.name)
        os.remove(fh.name)

    def test_choose_option(self):
        self.assertEqual(choose_option(['Man', 'Woman', 'Decline'], 'Gender', 'Female'), 'Woman')
        self.assertEqual(choose_option(['Black or African American', 'Caribbean', 'White'], 'Race',
                                       'Caribbean (Black or African American)'), 'Caribbean')
        self.assertEqual(choose_option(['Black or African American', 'White'], 'Race',
                                       'Caribbean (Black or African American)'), 'Black or African American')
        self.assertEqual(choose_option(['Illinois', 'California'], 'State', 'Chicago, IL', self.prof), 'Illinois')
        self.assertEqual(choose_option(['I am not a protected veteran', 'I identify as a veteran'], 'Veteran status', 'Not a veteran'),
                         'I am not a protected veteran')
        self.assertIsNone(choose_option(['Red', 'Blue'], 'Favorite color', 'Green'))


class TestResumeSchema(unittest.TestCase):
    def setUp(self):
        self.tpl = load_templates(WS)['Ops']
        self.bank = load_bank(WS)

    def test_overrides_by_index_and_id(self):
        d = apply_overrides(self.tpl, {'experience[1]': ['x'], 'experience.examplehealth': ['y', 'z'], 'bio': 'B'})
        self.assertEqual(d['experience'][1]['bullets'], ['x'])
        self.assertEqual(d['experience'][0]['bullets'], ['y', 'z'])
        self.assertEqual(self.tpl['experience'][1]['bullets'][0][:4], 'Led ')  # template untouched
        with self.assertRaises(KeyError):
            apply_overrides(self.tpl, {'experience[9]': ['x']})
        with self.assertRaises(KeyError):
            apply_overrides(self.tpl, {'acme_typo': ['x']})
        self.assertEqual(exp_index(self.tpl, 'acme'), 1)

    def test_page_rules(self):
        rules = {'pages': 2, 'last_on_page_1': 'experience[0]', 'first_on_page_2': 'experience[1]'}
        good = ['Example Health ...', 'Acme Logistics ...']
        self.assertEqual(page_break_failures(good, self.tpl, rules), [])
        bad = ['Example Health ... Acme Logistics', 'more']
        fails = page_break_failures(bad, self.tpl, rules)
        self.assertTrue(any('rose onto page 1' in f for f in fails))
        self.assertTrue(any('top of page 2' in f for f in fails))

    def test_stale(self):
        self.assertEqual(stale_failures('grew to $7M ARR', [r'\$7M']), [r'stale figure \$7M'])

    def test_render_payload_uses_profile(self):
        p = render_payload(self.tpl, load_profile(PROFILE))
        self.assertEqual(p['name'], 'JORDAN RIVERA')
        self.assertEqual(p['contact'], ['Chicago, IL  ·  555-010-0199  ·  jordan.rivera@example.com', 'linkedin.com/in/jordan-rivera-example'])

    def test_from_build_script(self):
        js = ("const CONTENT = {};\nc.push(sectionHeading('PROFESSIONAL EXPERIENCE'));\n\n"
              "c.push(roleLine('Lead PM', 'Jan 2024 - Apr 2026'));\nc.push(companyLine('Acme', 'Los Angeles, CA'));\n"
              "c.push(scopeLine('Acme\\'s scope.'));\nCONTENT.acme.forEach(t => c.push(bullet(t)));\n"
              "c.push(roleLine('PM', '2013'));\nc.push(companyLine('Daily', 'NY'));\nc.push(bullet(CONTENT.daily));\n"
              "c.push(sectionHeading('SKILLS'));\nc.push(sectionHeading('EDUCATION'));\n"
              "[['State U', 'B.A.', '2010 - 2012']].forEach(([u, d, y], i) =>\n"
              "c.push(sectionHeading('INTERESTS'));\nc.push(new Paragraph({ spacing: { after: 0 }, children: rich('Golf') }));\n")
        doc = from_build_script(js, {'bio': 'b', 'summary': 's', 'skills': 'k', 'acme': ['one', 'two'], 'daily': 'solo'})
        self.assertEqual([x['id'] for x in doc['experience']], ['acme', 'daily'])
        self.assertEqual(doc['experience'][0]['scope'], "Acme's scope.")
        self.assertEqual(doc['education'], [{'school': 'State U', 'degree': 'B.A.', 'years': '2010 - 2012'}])
        self.assertEqual(doc['extra_sections'], [{'heading': 'INTERESTS', 'text': 'Golf'}])
        self.assertEqual(to_legacy(doc)['daily'], 'solo')  # one-string CONTENT entries round-trip


class TestSpecs(unittest.TestCase):
    def setUp(self):
        self.templates, self.bank = load_templates(WS), load_bank(WS)
        self.role = dict(id='gh-acmehealth-1', slug='AcmeHealth-CoS', short='CoS', template='Ops', bio='Scaling Operations',
                         skills=['@core', 'M&A Diligence'], experience={'examplehealth': ['HIRE', 'OPS', 'BRD']})

    def spec(self, **kw):
        return make_spec(dict(self.role, **kw), self.templates, self.bank, {'resume': {'max_extra_bullets': 1}}, '2026-10-21',
                         {'company': 'Acme Health', 'title': 'Chief of Staff '})

    def test_happy_path(self):
        s = self.spec()
        self.assertEqual(s['folder'], '2026-10-21 Acme Health - CoS')
        self.assertEqual(s['title'], 'Chief of Staff')
        self.assertEqual(s['overrides']['bio'], 'Chief of Staff  ·  Scaling Operations')
        self.assertEqual(s['overrides']['skills'], 'Operating Cadence  |  OKRs  |  M&A Diligence')
        self.assertEqual(s['overrides']['experience[0]'][0], 'Hired and onboarded **9 executives** in 18 months')

    def test_rejections(self):
        for kw, msg in [(dict(experience={'examplehealth': ['NOPE', 'OPS']}), 'unknown bullet'),
                        (dict(experience={'examplehealth': ['PLAN', 'OPS']}), 'belongs to acme'),
                        (dict(experience={'examplehealth': ['OPS', 'OPS']}), 'duplicate'),
                        (dict(experience={'examplehealth': ['OPS']}), 'template Ops has 2'),
                        (dict(experience={'acme': ['PLAN', 'MNA', 'MNA']}), 'duplicate'),
                        (dict(skills=['Juggling']), 'not approved'),
                        (dict(summary='Freshly written summary'), 'approved text only'),
                        (dict(template='Nope'), 'unknown template')]:
            with self.assertRaises(SpecError) as e:
                self.spec(**kw)
            self.assertIn(msg, str(e.exception), kw)

    def test_batch_run_and_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            batch = os.path.join(d, 'b.yaml')
            open(batch, 'w', encoding='utf-8', newline='\n').write('date: 2026-10-21\nreviewed: reviewed.csv\nroles:\n  - id: gh-acmehealth-1\n    slug: AH\n'
                                   '    template: Ops\n    experience:\n      acme: [MNA, PLAN]\n')
            specs = run(batch, WS, out_dir=os.path.join(d, 'out'), legacy_shape=True)
            self.assertEqual(specs[0]['overrides'], {'acme': ['Ran diligence on **3 acquisitions**', 'Led the annual planning process across **6 business units**']})
            self.assertTrue(os.path.exists(os.path.join(d, 'out', 'AH.json')))
            open(batch, 'w', encoding='utf-8', newline='\n').write('date: 2026-10-21\nreviewed: reviewed.csv\nroles:\n  - id: gh-other-2\n    slug: O\n    template: Ops\n')
            skipped = []
            self.assertEqual(run(batch, WS, skipped=skipped), [])  # call=pass in the reviewed CSV: skipped, with a note
            self.assertEqual(skipped, ['skipped gh-other-2: call=pass in the reviewed CSV (no spec written)'])
            open(batch, 'w', encoding='utf-8', newline='\n').write('date: 2026-10-21\nreviewed: reviewed.csv\nroles:\n  - id: gh-nope-3\n    slug: N\n    template: Ops\n')
            with self.assertRaises(SpecError):
                run(batch, WS)  # not in the reviewed CSV at all


class TestPay(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config({'locations': {'los_angeles': 'any', 'san_francisco': 'hybrid_ok', 'new_york_city': 'any', 'remote_us': True}})

    COBALT = {'compensationTiers': [
        {'title': 'Bay Area Base Pay Range', 'components': [{'compensationType': 'Salary', 'interval': '1 YEAR', 'minValue': 160000, 'maxValue': 215000}]},
        {'title': 'New York Base Pay Range', 'components': [{'compensationType': 'Salary', 'interval': '1 YEAR', 'minValue': 160000, 'maxValue': 215000}]},
        {'title': 'Los Angeles Base Pay Range', 'components': [{'compensationType': 'Salary', 'interval': '1 YEAR', 'minValue': 150000, 'maxValue': 195000}]},
    ]}

    def test_ashby_band_for_home_metro(self):
        bands = ashby_bands(self.COBALT)
        self.assertEqual(len(bands), 3)
        lo, hi, src = salary('$150K – $215K • Multiple Ranges', 150000, 215000, bands, ['LA', 'SF', 'NYC'], self.cfg)
        self.assertEqual((hi, src), (195000, 'band:LA'))  # under a $200K floor, though the overall top is $215K
        self.assertEqual(salary('', 150000, 215000, bands, ['NYC'], self.cfg)[1], 215000)

    def test_note_between_the_figures(self):
        """Oct 24: "$X (entry level qualifications) to $Y (highly experienced)" read as no range, so the pay floor
        never applied. A short parenthetical note between the figures is skipped."""
        jd = ('Brightwater Bank: the pay range for this position is below. $135,000 (entry level qualifications) to '
              '$160,000 (highly experienced).')
        self.assertEqual(salary(jd), (135000, 160000, 'jd_text'))
        self.assertEqual(salary('$140K (base) - $175K (plus bonus)')[:2], (140000, 175000))
        self.assertEqual(salary('$150,000 (see note below, which explains how pay is set for this role in detail) to $180,000'),
                         (None, None, 'none'))  # a long note is not a range note

    def test_text_bands(self):
        jd = ('Pay: Zone A (San Francisco, New York): $180,000 - $220,000\n'
              'Zone B (Los Angeles, Seattle): $165,000 - $198,000\nAll other US locations: $150,000 - $180,000')
        self.assertEqual(len(text_bands(jd)), 3)
        self.assertEqual(salary(jd, hits=['LA'], cfg=self.cfg)[:2], (165000, 198000))
        self.assertEqual(salary(jd, hits=['Remote'], cfg=self.cfg)[:2], (150000, 180000))
        self.assertEqual(salary('Base $150K - $190K', hits=['LA'], cfg=self.cfg), (150000, 190000, 'jd_text'))  # one range: no bands
        self.assertEqual(salary('no pay here'), (None, None, 'none'))

    def test_home_state_bands(self):
        state_bands = ('USA base pay range (CA, CT, NJ, NY, WA) per year $340,000 - $375,000\n'
                  'USA base pay range (all other U.S. states) per year $305,000 - $340,000')
        self.assertEqual(salary(state_bands, hits=['Remote'], cfg=self.cfg), (340000, 375000, 'band:Remote'))  # lives in CA
        remote_first = ('Remote (Regardless of Location): $250,000 - $279,800\nNew York, NY: $300,000 - $335,700\n'
                  'San Francisco, CA: $300,000 - $335,700\nSan Jose, CA: $300,000 - $335,700')
        self.assertEqual(salary(remote_first, hits=['SF', 'NYC', 'Remote'], cfg=self.cfg)[1], 279800)  # explicit remote band; city bands aren't LA's

    def test_unmatched_bands_fall_back(self):
        jd = 'Denver: $100,000 - $120,000. Austin: $110,000 - $130,000.'
        self.assertEqual(salary(jd, hits=['LA'], cfg=self.cfg), (100000, 130000, 'jd_text'))

    def test_lookup_pay_on_company_board(self):
        calls = []

        def fake_gh(slug, company=''):
            calls.append(('greenhouse', slug))
            if slug == 'lumendata':
                return [posting(id='gh-lumendata-1', source='greenhouse', company=company, title='Senior Product Manager',
                                url='u', description='The range is $149,400 - $182,700 per year.')]
            return None
        adapters = {'greenhouse': fake_gh, 'lever': lambda s, c='': None, 'ashby': lambda s, c='': None}
        hit = lookup_pay('Lumen Data', 'Sr. Product Manager (Remote)', {}, adapters)
        self.assertEqual((hit['salary_max'], hit['ats'], hit['slug']), (182700, 'greenhouse', 'lumendata'))
        self.assertIsNone(lookup_pay('Nobody Inc.', 'Senior Product Manager', {}, adapters))
        self.assertEqual(slug_guesses('Acme Health, Inc.'), ['acmehealth', 'acme-health'])

    def test_lookup_uses_watchlist_board_first(self):
        seen = []

        def fake(slug, company=''):
            seen.append(slug)
            return [posting(id='ab-x-1', source='ashby', company=company, title='Staff Product Manager, Core', url='u',
                            salary_min=150000, salary_max=215000, pay_bands=ashby_bands(self.COBALT))]
        hit = lookup_pay('Cobalt Farms', 'Staff Product Manager, Core', {'Cobalt Farms': ['ashby', 'Cobalt Farms LLC']}, {'ashby': fake}, guess=False)
        self.assertEqual(seen, ['Cobalt Farms LLC'])
        self.assertEqual(len(hit['pay_bands']), 3)


class TestTriage(unittest.TestCase):
    def test_dedup_by_job_key_across_ids(self):
        idx = applied_index(os.path.join(WS, 'applied.csv'))
        # found on LinkedIn under a li- id; applied under the Ashby id
        self.assertTrue(already_applied('Cobalt Farms', 'Staff Product Manager, Core', 'li-4384374758', idx))
        self.assertTrue(already_applied('Quillstone', 'Principal Product Manager - Engagement (Remote, US)', 'li-4477843805', idx))
        self.assertTrue(already_applied('X', 'Y', 'gh-quillstone-8267770', idx))
        self.assertFalse(already_applied('Cobalt Farms', 'Staff Product Manager, Monetization', 'li-1', idx))
        self.assertEqual(job_key('Cobalt Farms', 'Staff PM Core'), job_key('Cobalt Farms LLC', 'Staff Product Manager, Core'))

    def test_near_miss_band(self):
        s = {'tier_a': 70, 'tier_b': 55, 'near_miss_margin': 5}
        self.assertEqual([tier(f, s) for f in (70, 55, 54, 50, 49)], ['A', 'B', 'C+', 'C+', 'C'])
        self.assertEqual(tier(52, dict(s, near_miss_margin=0)), 'C')

    def test_assign_tiers_cap_counts_near_miss(self):
        rows = [dict(company='Acme', fit=80, flags=''), dict(company='Acme', fit=60, flags=''),
                dict(company='Acme', fit=52, flags=''), dict(company='Beta', fit=51, flags='x'), dict(company='Beta', fit=30, flags='')]
        assign_tiers(rows, {'tier_a': 70, 'tier_b': 55, 'near_miss_margin': 5}, cap=3, prior={'acme': 1})
        self.assertEqual([r['tier'] for r in rows], ['A', 'B', 'cap', 'C+', 'C'])
        self.assertEqual([r['review'] for r in rows], ['yes', 'yes', 'no', 'yes', 'no'])
        self.assertIn('near-miss C', rows[3]['flags'])


if __name__ == '__main__':
    unittest.main()


class TestStages(unittest.TestCase):
    """engine/stages.py on a fictional vault: answers -> fill plan, and filler substitution."""

    def setUp(self):
        from engine import stages
        self.stages = stages
        self.tmp = tempfile.mkdtemp()
        self.vault = os.path.join(self.tmp, 'vault')
        shutil.copytree(os.path.join(HERE, 'fixtures', 'vault'), self.vault)
        ws = os.path.join(self.tmp, 'ws')
        os.makedirs(ws)
        shutil.copy(PROFILE, os.path.join(ws, 'profile.yaml'))
        cfg = json.load(open(CONFIG, encoding='utf-8'))
        cfg['paths'] = {'vault': self.vault}
        json.dump(cfg, open(os.path.join(ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        self.ctx = stages.Ctx(ws, today=datetime.date(2026, 10, 20))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_answers_stage(self):
        asks, _ = self.stages.stage_answers(self.ctx)
        out = json.load(open(os.path.join(self.vault, 'Pipeline', 'state', 'answers', 'gh-acmehealth-1.json'), encoding='utf-8'))
        got = {q['label']: (q['kind'], q['answer']) for q in out['questions']}
        self.assertEqual(got['First Name'], ('fixed', 'Jordan'))
        self.assertEqual(got['Website'][0], 'skip')            # optional and no profile value
        self.assertEqual(got['Tell us about a hard call you made'][0], 'draft')
        self.assertEqual(got['Are you a member of our book club?'][0], 'ask')
        self.assertIn('Are you a member of our book club?', asks)
        md = open(os.path.join(self.vault, 'Pipeline', 'queue', 'stage5-questions-2026-10-20-open.md'), encoding='utf-8').read()
        self.assertIn('questions for Jordan', md)

    def test_snapshot_copies_once(self):
        os.makedirs(os.path.join(self.vault, 'Pipeline', 'specs'))
        open(os.path.join(self.vault, 'Pipeline', 'specs', 'x.json'), 'w', encoding='utf-8', newline='\n').write('{}')
        self.ctx.snapshot()
        snap = os.path.join(self.vault, 'Pipeline', 'state', 'pre-v2-snapshot')
        self.assertTrue(os.path.exists(os.path.join(snap, 'specs', 'x.json')))
        open(os.path.join(self.vault, 'Pipeline', 'specs', 'y.json'), 'w', encoding='utf-8', newline='\n').write('{}')
        self.ctx.snapshot()  # never refreshed: the snapshot is the old pipeline's last state
        self.assertFalse(os.path.exists(os.path.join(snap, 'specs', 'y.json')))

    def test_snapshot_on_fresh_vault(self):
        # A new user's first stage: none of the snapshot folders exist yet.
        fresh = os.path.join(self.tmp, 'fresh')
        os.makedirs(fresh)
        ws = os.path.join(self.tmp, 'ws-fresh')
        os.makedirs(ws)
        shutil.copy(PROFILE, os.path.join(ws, 'profile.yaml'))
        cfg = json.load(open(CONFIG, encoding='utf-8'))
        cfg['paths'] = {'vault': fresh}
        json.dump(cfg, open(os.path.join(ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        self.stages.main(['--workspace', ws, 'answers'])
        snap = os.path.join(fresh, 'Pipeline', 'state', 'pre-v2-snapshot')
        self.assertIn('nothing to copy', open(os.path.join(snap, 'README.txt'), encoding='utf-8').read())
        self.assertEqual(os.listdir(snap), ['README.txt'])
        # The marker stops a later run from snapshotting v2's own answers as the old pipeline's.
        self.stages.main(['--workspace', ws, 'answers'])
        self.assertEqual(os.listdir(snap), ['README.txt'])

    def test_fillplan_from_notes(self):
        self.stages.stage_answers(self.ctx)
        form = json.load(open(os.path.join(self.vault, 'Pipeline', 'state', 'answers', 'gh-acmehealth-1.json'), encoding='utf-8'))
        rows = [dict(label=q['label'], required=q['required'], answer=q['answer'] or '', source=q['kind']) for q in form['questions']]
        rows[3]['answer'] = 'Company careers page'
        notes = dict(id='gh-acmehealth-1', resume='/r.pdf', cover=None, rows=rows)
        os.makedirs(os.path.join(self.vault, 'Pipeline', 'state', 'notes'))
        json.dump(notes, open(os.path.join(self.vault, 'Pipeline', 'state', 'notes', 'gh-acmehealth-1.json'), 'w', encoding='utf-8', newline='\n'))
        out, plan, review = self.stages.build_fillplan(self.ctx, 'gh-acmehealth-1')
        by = {p['label']: p for p in plan}
        self.assertEqual(by['Gender']['value'], ['Woman'])
        self.assertEqual(by['How did you hear about this job?']['value'], ['LinkedIn'])  # no careers option: profile fallback
        self.assertEqual(by['Will you require visa sponsorship?']['value'], ['No'])
        self.assertNotIn('Are you a member of our book club?', by)  # unanswered: listed in the stage-5 questions file, never filled
        src = open(out, encoding='utf-8').read()
        self.assertNotRegex(src, r'__[A-Z_]+__')
        self.assertIn("pick(school, 'Northwestern', /^Northwestern University/i)", src)

    def test_every_filler_fully_substituted(self):
        for ats in ('greenhouse', 'lever', 'ashby'):
            src = self.stages.filler_source(self.ctx, ats)
            self.assertNotRegex(src.replace('__PLAN__', ''), r'__[A-Z_]+__', ats)
        self.assertEqual(self.stages._js(["it's", 'b']), "['it\\'s', 'b']")

    def test_filler_skips_blocks_without_profile_values(self):
        self.ctx.prof['forms'] = {}
        src = self.stages.filler_source(self.ctx, 'greenhouse')
        self.assertIn('if (false && await school.count())', src)
        self.assertIn("if (false && await page.locator('#company-name-0').count())", src)
