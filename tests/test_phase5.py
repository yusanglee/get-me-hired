"""Phase 5: eligibility and language hard gates (engine/gates.py) and their place in score.run.
Fictional people and postings only."""
import csv, json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import re  # noqa: E402
import datetime  # noqa: E402
from engine import gates, hosts, redline, score, tracker, verify  # noqa: E402
from engine.profile import Profile  # noqa: E402
import test_discover_score as tds  # noqa: E402

CITIZEN = Profile({'work_authorization': {'citizenship': 'United States of America', 'needs_sponsorship': 'No'},
                   'languages': [{'language': 'English', 'level': 'native'}, {'language': 'Spanish', 'level': 'conversational'}]})
VISA = Profile({'work_authorization': {'citizenship': 'Canada', 'needs_sponsorship': 'Yes'},
                'languages': [{'language': 'English', 'level': 'fluent'}]})
NO_LANGS = Profile({'work_authorization': {'citizenship': 'United States of America', 'needs_sponsorship': 'No'}})


def verdicts(jd, prof):
    return [(v, label) for v, label, _ in gates.check(jd, prof)]


class EligibilityGate(unittest.TestCase):
    def test_citizenship_required(self):
        jd = 'About the role. Applicants must be a U.S. citizen due to contract requirements. Benefits include...'
        self.assertEqual(verdicts(jd, CITIZEN), [('PASS', 'citizenship required')])
        res = gates.check(jd, VISA)
        self.assertEqual(gates.verdict(res), 'FAIL')
        self.assertIn('must be a U.S. citizen', res[0][2])  # quoted, never silent

    def test_permanent_resident_passes_citizens_or_pr_only(self):
        jd = 'Open to U.S. citizens or permanent residents only.'
        green_card = Profile({'work_authorization': {'citizenship': 'Mexico', 'permanent_resident': 'Yes', 'needs_sponsorship': 'No'}})
        self.assertEqual(gates.verdict(gates.check(jd, green_card)), 'PASS')
        self.assertEqual(gates.verdict(gates.check(jd, VISA)), 'FAIL')

    def test_clearance(self):
        jd = 'Requirements: Active Top Secret clearance is required. 5+ years in product.'
        self.assertEqual(gates.verdict(gates.check(jd, CITIZEN)), 'FAIL')
        cleared = Profile({**CITIZEN, 'work_authorization': {**CITIZEN['work_authorization'], 'clearance': 'Top Secret (active)'}})
        self.assertEqual(gates.verdict(gates.check(jd, cleared)), 'FLAG')

    def test_clearance_or_ability_to_obtain_is_a_flag_for_a_citizen(self):
        jd = 'Active Secret Security Clearance or the ability to obtain one'
        self.assertEqual(verdicts(jd, CITIZEN), [('FLAG', 'must hold or be able to obtain a security clearance')])
        self.assertEqual(gates.verdict(gates.check(jd, VISA)), 'FAIL')

    def test_clearance_preferred_is_not_required(self):
        jd = 'Nice to have: an active security clearance. Experience with payments.'
        self.assertNotEqual(gates.verdict(gates.check(jd, CITIZEN)), 'FAIL')

    def test_clearance_not_required_is_not_a_gate(self):
        for jd in ('Mission | On Site | Full Time | U.S. Citizenship Required / No Active Clearance Required',
                   'No clearance required.', 'A security clearance is not required for this role.',
                   "An active clearance isn't required.", 'This role does not require an active security clearance.',
                   'You do not need to hold a clearance.', 'No security clearance needed.',
                   'Any active clearance requirement will be listed in the role description.'):
            self.assertFalse([r for r in gates.check(jd, CITIZEN) if 'clearance' in r[1]], jd)
        for jd in ('No relocation. Active Secret clearance required.',
                   'Candidates will not be considered without an active Secret clearance.'):
            self.assertEqual(verdicts(jd, CITIZEN), [('FAIL', 'security clearance required')], jd)

    def test_citizenship_still_gates_when_no_clearance_is_needed(self):
        jd = ('Brightwater Defense | U.S. Citizenship Required / No Active Clearance Required. '
              'Due to government contract requirements, this role is limited to U.S. citizens.')
        self.assertEqual(verdicts(jd, CITIZEN), [('PASS', 'citizenship required')])
        self.assertEqual(verdicts(jd, VISA), [('FAIL', 'citizenship required'), ('UNVERIFIED', 'posting silent on sponsorship')])
        self.assertEqual(verdicts('This role is limited to U.S. citizens.', VISA)[0], ('FAIL', 'citizenship required'))

    def test_sponsorship(self):
        for jd in ('Please note that visa sponsorship is not available for this position.',
                   'Brightwater will not sponsor a new applicant for employment authorization for this position.',
                   'Candidates should not require, now or in the future, sponsorship for employment visa status.',
                   'Sponsorship not available at this time.'):
            self.assertEqual(gates.verdict(gates.check(jd, VISA)), 'FAIL', jd)
            self.assertEqual(gates.verdict(gates.check(jd, CITIZEN)), 'PASS', jd)  # irrelevant to a citizen
        self.assertEqual(verdicts('Visa sponsorship: we do sponsor visas!', VISA), [('PASS', 'sponsorship offered')])

    def test_silence_is_not_permission(self):
        jd = 'Senior Product Manager. You will own the checkout funnel. Hybrid in New York.'
        self.assertEqual(verdicts(jd, VISA), [('UNVERIFIED', 'posting silent on sponsorship')])
        self.assertEqual(verdicts(jd, CITIZEN), [])  # a citizen needing nothing: silence is fine

    def test_ad_sponsorships_are_not_visa_sponsorship(self):
        jd = 'You will lead Sponsorships: help creators earn from sponsorships with brands. We can explain how sponsorships work.'
        self.assertEqual(verdicts(jd, VISA), [('UNVERIFIED', 'posting silent on sponsorship')])


class LanguageGate(unittest.TestCase):
    def test_undeclared_language_fails(self):
        res = gates.check('Requirements: Fluent Japanese and English. 6+ years of product experience.', CITIZEN)
        self.assertEqual(res[0][:2], ('FAIL', 'Japanese required, not in profile'))
        self.assertIn('Fluent Japanese', res[0][2])

    def test_bar_above_declared_level_flags(self):
        self.assertEqual(verdicts('Must be fluent in Spanish to work with our Madrid team.', CITIZEN),
                         [('FLAG', 'Spanish bar may exceed declared level')])
        self.assertEqual(verdicts('Conversational Spanish is required.', CITIZEN), [])

    def test_nice_to_have_and_product_mentions_ignored(self):
        for jd in ('Bonus points: Mandarin proficiency.', 'Desired: professional fluency in English, with a strong benefit to proficiency in Portuguese',
                   'We offer English proficiency testing to millions of learners.', 'Grow our Spanish-language content library.'):
            self.assertNotIn('FAIL', [v for v, _ in verdicts(jd, CITIZEN)], jd)
        self.assertEqual(verdicts('Bonus points: Mandarin proficiency.', CITIZEN), [])

    def test_no_languages_in_profile_means_english_only(self):
        self.assertEqual(verdicts('Fluent English required.', NO_LANGS), [])
        self.assertEqual(verdicts('Fluent Spanish required.', NO_LANGS), [('FAIL', 'Spanish required, not in profile')])

    def test_any_one_of_several_languages(self):
        jd = ('Brightwater is hiring a regional PM. Fluency in English and at least one other local language '
              '(Spanish or Portuguese). Based in Lisbon.')
        self.assertEqual(verdicts(jd, NO_LANGS), [('FAIL', 'Spanish or Portuguese required, neither in profile')])
        self.assertEqual(verdicts(jd, CITIZEN), [('FLAG', 'Spanish or Portuguese bar may exceed declared level')])
        self.assertEqual(verdicts('Must be a fluent Spanish or Portuguese speaker.', NO_LANGS),
                         [('FAIL', 'Spanish or Portuguese required, neither in profile')])
        self.assertEqual(verdicts('Spanish or Portuguese fluency required.', NO_LANGS),
                         [('FAIL', 'Spanish or Portuguese required, neither in profile')])
        self.assertEqual(verdicts('Fluent English, Spanish, or Portuguese.', NO_LANGS), [])
        self.assertEqual(verdicts('Fluent in English, Spanish and Portuguese.', NO_LANGS),
                         [('FAIL', 'Spanish required, not in profile'), ('FAIL', 'Portuguese required, not in profile')])
        self.assertEqual(verdicts('Fluency in Mandarin Chinese.', NO_LANGS), [('FAIL', 'Mandarin required, not in profile')])

    def test_optional_or_unneeded_language_never_fails(self):
        for jd in ('Fluent English required. Spanish a plus.', 'Spanish is a nice to have. Fluent in English.',
                   'Fluent in English; Spanish is not required.', 'Fluent English. No Portuguese needed.',
                   'Mandarin proficiency (spoken and written) is a plus for this team.',
                   'WOULD BE NICE IF YOU ALSO HAVE - Experience in the Korean market - Working proficiency in Korean',
                   'Nice to have:\n- Shipped games in Asia\n- Fluent in Japanese'):
            self.assertEqual(verdicts(jd, NO_LANGS), [], jd)

    def test_required_heading_after_optional_one_requires_again(self):
        jd = 'Nice to have: shipped games in Asia. Requirements: - 8+ years in product - Fluent in Japanese'
        self.assertEqual(verdicts(jd, NO_LANGS), [('FAIL', 'Japanese required, not in profile')])

    def test_quote_is_bounded_on_run_together_text(self):
        jd = 'x ' * 400 + 'Fluent Korean and willingness to travel ' + 'y ' * 400
        q = gates.check(jd, CITIZEN)[0][2]
        self.assertIn('Fluent Korean', q)
        self.assertLess(len(q), 240)

    def test_summary(self):
        res = gates.check('Fluent Japanese required.', CITIZEN)
        self.assertEqual(gates.summary(res), 'gate FAIL: Japanese required, not in profile ("Fluent Japanese required")')


class ScoreWithGates(tds.CosEndToEnd):
    """score.run on the Chief of Staff fixture workspace, with a profile that needs sponsorship."""

    def write_profile(self, needs_sponsorship):
        open(os.path.join(self.ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write(
            'identity:\n  first_name: Pat\n  last_name: Example\n  email: pat@example.com\n'
            f'work_authorization:\n  citizenship: Canada\n  needs_sponsorship: "{needs_sponsorship}"\n'
            'languages:\n  - language: English\n    level: native\n')

    def add_to_jd(self, ctx, rid, text):
        p = os.path.join(ctx.state, 'jd', rid + '.txt')
        open(p, 'a', encoding='utf-8', newline='\n').write('\n' + text)

    def test_gate_fail_is_listed_not_scored(self):
        self.write_profile('Yes')
        ctx, _ = self.discover()
        self.add_to_jd(ctx, 'gh-acme-1', 'Please note that visa sponsorship is not available for this position.')
        self.add_to_jd(ctx, 'hm-initech-cos', 'We do sponsor visas for this role.')
        lines = []
        spath, scored = score.run(ctx, out=lines.append)
        by = {r['id']: r for r in scored}
        self.assertEqual(by['gh-acme-1']['tier'], 'gate')
        self.assertEqual(by['gh-acme-1']['review'], 'no')
        self.assertIn('gate FAIL: no visa sponsorship ("Please note that visa sponsorship is not available', by['gh-acme-1']['flags'])
        self.assertEqual(scored[-1]['id'], 'gh-acme-1')  # listed last, after every scored role
        self.assertEqual(by['hm-initech-cos']['tier'], 'B')  # sponsorship offered: scored as before
        self.assertIn('gate UNVERIFIED: posting silent on sponsorship', by['gh-acme-6']['flags'])
        self.assertTrue(any(l.startswith('Hard gates, not scored (tier "gate"): 1: Acme Robotics') for l in lines))
        self.assertIn('gh-acme-1', {r['id'] for r in csv.DictReader(open(spath, encoding='utf-8', newline=''))})

    def test_lookalike_link_is_gated_even_without_profile(self):
        ctx, (dpath, _) = self.discover()
        rows = list(csv.DictReader(open(dpath, encoding='utf-8', newline='')))
        for r in rows:
            if r['id'] == 'gh-acme-1':
                r['url'] = 'https://job-boards.greenhovse.io/acme/jobs/1'
        with open(dpath, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        _, scored = score.run(ctx, out=lambda *a: None)
        by = {r['id']: r for r in scored}
        self.assertEqual(by['gh-acme-1']['tier'], 'gate')
        self.assertIn('imitates greenhouse.io', by['gh-acme-1']['flags'])

    def test_gates_off_and_no_profile_change_nothing(self):
        ctx, _ = self.discover()
        _, base = score.run(ctx, out=lambda *a: None)  # no profile.yaml: gates skipped
        self.write_profile('Yes')
        self.add_to_jd(ctx, 'gh-acme-1', 'Sponsorship not available at this time.')
        cfg = json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))
        cfg['gates'] = {'enabled': False}
        json.dump(cfg, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        ctx2, _ = self.discover()
        self.add_to_jd(ctx2, 'gh-acme-1', 'Sponsorship not available at this time.')
        _, off = score.run(ctx2, out=lambda *a: None)
        self.assertEqual([(r['id'], r['tier'], r['fit']) for r in off], [(r['id'], r['tier'], r['fit']) for r in base])

    # The parent class's tests run again here unchanged; skip the duplicates.
    test_discover_then_score = test_second_run_marks_seen = test_explicit_config_queries_win = None
    test_company_cap_counts_workflow_and_tracker = test_employer_limit = None


FACTS = """# Jordan Rivera
Senior Product Manager, Brightwater (2021-2026). Grew weekly active users 40% in 2024; led a team of 12;
launched Brightwater Rewards, a loyalty program that reached $3M in annual revenue.
"""
POSTING = 'Staff Product Manager, Loyalty at Northwind. You will grow a program with 10M members.'
ENTRY = {'cover': ['Dear Northwind team,', 'At Brightwater I grew weekly active users 40% and launched Brightwater Rewards.',
                   'I would bring that loyalty experience to your 10M members.'],
         'answers': {'Why Northwind?': 'Your loyalty program is the product I most want to build next.'}}


class RedlineChecks(unittest.TestCase):
    def test_clean_draft_has_no_problems(self):
        self.assertEqual(redline.check(ENTRY, FACTS, POSTING), [])

    def test_unsupported_numbers_and_dashes(self):
        e = {'cover': ['I grew revenue 65% and managed $12M — quickly.'], 'answers': {'Team size?': 'I led 12 people across 3x growth.'}}
        probs = {(p['field'], p['problem'], p['detail']) for p in redline.check(e, FACTS, POSTING)}
        self.assertIn(('cover.0', 'unsupported number', '$12m, 65%'), probs)
        self.assertIn(('cover.0', 'em or en dash', '—'), probs)
        self.assertIn(('answers.Team size?', 'unsupported number', '3x'), probs)  # 12 is in the facts, 3x is not

    def test_number_forms_match(self):
        self.assertEqual(redline.numbers('$3 million and 40 percent'), redline.numbers('$3M and 40%'))

    def test_long_cover_flagged(self):
        e = {'cover': ['word ' * 400]}
        self.assertEqual(redline.check(e, FACTS)[0]['problem'], 'cover letter may run past one page')

    def test_volunteered_gaps_flagged(self):
        e = {'cover': ['I haven\u2019t run a marketplace, but I grew weekly active users 40%.',
                       'I would bring loyalty work rather than payments depth.', 'I have limited experience in B2B.'],
             'answers': {'Why Northwind?': "I'd be learning the loyalty stack, and I don't have fintech experience.",
                         'Do you have fintech experience?': "I haven't worked in fintech; I launched Brightwater Rewards."}}
        probs = {p['field']: p['detail'] for p in redline.check(e, FACTS, POSTING) if p['problem'] == 'volunteers a gap'}
        self.assertEqual(probs, {'cover.0': "I haven't", 'cover.1': 'rather than', 'cover.2': 'limited experience',
                                 'answers.Why Northwind?': "I'd be learning, I don't have"})  # a direct question may get a no

    def test_strength_lines_are_not_gaps(self):
        for t in ["I don't just ship features; I measure them.", 'I led a team of 12.', 'I have shipped loyalty programs.']:
            self.assertEqual(redline.volunteered_gaps(t), [], t)
        self.assertEqual(redline.volunteered_gaps("I'll be direct about the gap. Two honest gaps follow."),
                         ['be direct about', 'honest gaps'])
        self.assertEqual(redline.volunteered_gaps('The 2x activation gap was significant.'), [])

    def test_rules_forbid_volunteering_gaps(self):
        self.assertTrue(any('volunteer a gap' in r for r in redline.RULES))

    def test_packet_holds_only_draft_and_sources(self):
        p = redline.packet(ENTRY, FACTS, POSTING, 'Northwind', 'Staff Product Manager, Loyalty')
        self.assertEqual(set(p), {'role', 'ai_policy', 'rules', 'draft', 'rule_checks', 'facts', 'posting', 'return_format'})
        self.assertEqual(p['draft']['cover.1'], ENTRY['cover'][1])
        self.assertEqual(p['draft']['answers.Why Northwind?'], ENTRY['answers']['Why Northwind?'])


class RedlineApply(unittest.TestCase):
    def test_exact_edits_apply_and_original_untouched(self):
        edits = [{'field': 'cover.2', 'old_string': 'that loyalty experience', 'new_string': 'what I learned launching Brightwater Rewards'},
                 {'field': 'answers.Why Northwind?', 'old_string': 'the product I most want to build next',
                  'new_string': 'closest to Brightwater Rewards, which reached $3M in annual revenue'}]
        new, applied, rejected = redline.apply(ENTRY, edits, FACTS, POSTING)
        self.assertEqual((len(applied), rejected), (2, []))
        self.assertIn('what I learned launching Brightwater Rewards', new['cover'][2])
        self.assertIn('that loyalty experience', ENTRY['cover'][2])  # input not mutated

    def test_rejections(self):
        edits = [{'field': 'cover.1', 'old_string': 'not in the text', 'new_string': 'x'},
                 {'field': 'cover.9', 'old_string': 'a', 'new_string': 'b'},
                 {'field': 'cover.1', 'old_string': 'grew weekly active users 40%', 'new_string': 'grew weekly active users 75%'},
                 {'field': 'cover.1', 'old_string': 'and launched', 'new_string': '— and launched'},
                 {'field': 'cover.1', 'old_string': '', 'new_string': 'x'}]
        new, applied, rejected = redline.apply(ENTRY, edits, FACTS, POSTING)
        self.assertEqual(applied, [])
        self.assertEqual([r['rejected'] for r in rejected], [
            'old_string found 0 times (must be exactly once)', 'no such field',
            'adds a number the facts do not support: 75%', 'adds an em or en dash', 'empty old_string'])
        self.assertEqual(new, ENTRY)

    def test_edit_that_adds_a_gap_rejected(self):
        e = {'cover': ['I launched Brightwater Rewards.'], 'answers': {'Have you led a payments team?': 'I led a team of 12.'}}
        edits = [{'field': 'cover.0', 'old_string': 'I launched', 'new_string': "I haven't run payments, but I launched"},
                 {'field': 'answers.Have you led a payments team?', 'old_string': 'I led',
                  'new_string': "Not payments; I haven't. I led"}]
        _, applied, rejected = redline.apply(e, edits, FACTS)
        self.assertEqual([r['rejected'] for r in rejected], ['adds a sentence that volunteers a gap'])
        self.assertEqual([a['field'] for a in applied], ['answers.Have you led a payments team?'])

    def test_ambiguous_old_string_rejected(self):
        e = {'cover': ['team and team']}
        _, applied, rejected = redline.apply(e, [{'field': 'cover.0', 'old_string': 'team', 'new_string': 'group'}], FACTS)
        self.assertEqual(rejected[0]['rejected'], 'old_string found 2 times (must be exactly once)')

    def test_cli_apply_backs_up_and_reports(self):
        import io, shutil, tempfile
        from contextlib import redirect_stdout
        d = tempfile.mkdtemp()
        try:
            vault = os.path.join(d, 'vault')
            for sub in ('Pipeline/specs', 'Pipeline/state/jd', 'Pipeline/drafts'):
                os.makedirs(os.path.join(vault, sub))
            ws = os.path.join(d, 'ws')
            os.makedirs(ws)
            json.dump({'paths': {'vault': vault}}, open(os.path.join(ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
            open(os.path.join(ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n').write(FACTS)
            json.dump({'slug': 'Northwind-Loyalty', 'id': 'gh-northwind-1', 'company': 'Northwind', 'title': 'Staff PM'},
                      open(os.path.join(vault, 'Pipeline/specs/Northwind-Loyalty.json'), 'w', encoding='utf-8', newline='\n'))
            open(os.path.join(vault, 'Pipeline/state/jd/gh-northwind-1.txt'), 'w', encoding='utf-8', newline='\n').write(POSTING)
            dp = os.path.join(vault, 'Pipeline/drafts/drafts-2026-10-21.json')
            json.dump({'Northwind-Loyalty': ENTRY}, open(dp, 'w', encoding='utf-8', newline='\n'))
            ep = os.path.join(d, 'edits.json')
            json.dump({'verdict': 'ready', 'edits': [{'field': 'cover.0', 'old_string': 'team', 'new_string': 'loyalty team'}]}, open(ep, 'w', encoding='utf-8', newline='\n'))
            buf = io.StringIO()
            with redirect_stdout(buf):
                redline.main(['packet', dp, 'Northwind-Loyalty', '--workspace', ws])
            self.assertEqual(json.load(open(buf.getvalue().strip(), encoding='utf-8'))['posting'], POSTING)
            buf = io.StringIO()
            with redirect_stdout(buf):
                redline.main(['apply', dp, 'Northwind-Loyalty', ep, '--workspace', ws])
            rep = json.loads(buf.getvalue())
            self.assertEqual((len(rep['applied']), rep['rejected'], rep['remaining_checks']), (1, [], []))
            self.assertEqual(json.load(open(dp, encoding='utf-8'))['Northwind-Loyalty']['cover'][0], 'Dear Northwind loyalty team,')
            self.assertEqual(json.load(open(dp.replace('.json', '.pre-review.json'), encoding='utf-8'))['Northwind-Loyalty'], ENTRY)
        finally:
            shutil.rmtree(d)


class SourceHosts(unittest.TestCase):
    def test_known_and_other(self):
        for u in ('https://job-boards.greenhouse.io/brightwater/jobs/1', 'https://jobs.lever.co/northwind/abc',
                  'https://northwind.wd5.myworkdayjobs.com/x', 'https://www.linkedin.com/jobs/view/1'):
            self.assertEqual(hosts.check(u)[0], 'known', u)
        self.assertEqual(hosts.check('https://careers.brightwater.com/jobs/1'), ('other', ''))

    def test_lookalikes(self):
        for u, k in (('https://greenhovse.io/a', 'greenhouse.io'), ('https://greenhouse.com/a', 'greenhouse.io'),
                     ('https://greenhouse-jobs.com/a', 'greenhouse.io'), ('https://ashbyhq.co/a', 'ashbyhq.com'),
                     ('https://linkedln.com/jobs', 'linkedin.com'), ('https://myworkdayjob.com/a', 'myworkdayjobs.com')):
            self.assertEqual(hosts.check(u), ('lookalike', k), u)
        self.assertEqual(hosts.check('https://xn--grnhouse-9wa.io/a')[0], 'lookalike')

    def test_invalid(self):
        for u in ('', 'javascript:alert(1)', 'ftp://greenhouse.io/x', 'https://localhost/x'):
            self.assertEqual(hosts.check(u)[0], 'invalid', u)


class AtsChecks(unittest.TestCase):
    def test_text_layer(self):
        self.assertEqual(verify.text_layer_failures('Jordan Rivera\nSenior Product Manager'), [])
        self.assertIn('2 unreadable glyph', verify.text_layer_failures('Jordan (cid:12)ivera (cid:7)')[0])
        self.assertIn('1 unreadable glyph', verify.text_layer_failures('Product \ufffd Manager')[0])
        self.assertEqual(verify.text_layer_failures('  \n  '), ['no extractable text (image-only PDF?)'])

    def test_date_ranges(self):
        good = 'Brightwater  Jan 2021 - Mar 2024\nNorthwind  2019 - Present\n05/2018-12/2018'
        self.assertEqual(verify.date_range_failures(good), [])
        bad = 'Brightwater  Jan 2021 \u2011 Mar 2024\nNorthwind  2019 \u2212 Present\nAcme 2016 \u2192 2018'
        f = verify.date_range_failures(bad)
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0].startswith('3 date range(s) without a plain hyphen'))

    def test_keyword_coverage_never_invents(self):
        terms = re.compile(r'\b(sql|experimentation|loyalty|kubernetes|roadmap)\b', re.I)
        jd = 'You will own the loyalty roadmap, run experimentation, write SQL. Kubernetes is used by the platform team.'
        resume = 'Jordan Rivera. Launched Brightwater Rewards loyalty program; ran A/B testing on onboarding.'
        facts = resume + ' Built the 2025 product roadmap. Wrote SQL dashboards in BigQuery.'
        cov = verify.keyword_coverage(jd, terms, resume, facts)
        self.assertEqual(cov, {'experimentation': 'synonym', 'kubernetes': 'gap', 'loyalty': 'covered',
                               'roadmap': 'have-it', 'sql': 'have-it'})
        self.assertEqual(verify.coverage_note(cov),
                         'coverage: covered 1; synonym 1; have-it 2 (roadmap, sql); gap 1 (kubernetes)')


class Lifecycle(unittest.TestCase):
    TODAY = datetime.date(2026, 11, 20)

    def rows(self):
        rows = []
        for co, title, st, d in (('Brightwater', 'Staff PM, Growth', 'applied', '2026-11-12'),       # 8 days: not yet
                                 ('Northwind', 'Senior PM, Loyalty', 'applied', '2026-11-05'),      # 15 days: due
                                 ('Acme Robotics', 'Lead PM', 'interviewing', '2026-11-01'),        # due
                                 ('Globex', 'Senior PM', 'rejected', '2026-09-01'),                 # closed
                                 ('Initech', 'Staff PM', 'applied', '2026-09-10'),                  # 71 days: stale
                                 ('Umbrella', 'Senior PM', 'offer', '2026-10-01')):                 # offers left to the user
            tracker.upsert(rows, {'company': co, 'title': title, 'date_applied': d, 'status': st, 'status_date': d})
        return rows

    def test_followups_due_and_cap(self):
        rows = self.rows()
        due = [r['company'] for r in tracker.followups_due(rows, self.TODAY)]
        self.assertEqual(due, ['Initech', 'Acme Robotics', 'Northwind'])
        key = tracker.find(rows, rows[1]['job_key'])['job_key']
        tracker.log_followup(rows, key, '2026-11-18')  # a follow-up resets the quiet clock
        self.assertNotIn('Northwind', [r['company'] for r in tracker.followups_due(rows, self.TODAY)])
        tracker.log_followup(rows, key, '2026-11-19')
        self.assertEqual(tracker.find(rows, key)['followups'], '2026-11-18 2026-11-19')
        later = datetime.date(2026, 12, 31)
        self.assertNotIn('Northwind', [r['company'] for r in tracker.followups_due(rows, later)])  # two sent: stop

    def test_stale_and_set(self):
        rows = self.rows()
        self.assertEqual([r['company'] for r in tracker.stale(rows, self.TODAY)], ['Initech'])
        key = [r for r in rows if r['company'] == 'Initech'][0]['job_key']
        tracker.set_status(rows, key, 'no_response', '2026-11-20', 'closed in stale sweep')
        r = tracker.find(rows, key)
        self.assertEqual((r['status'], r['status_date']), ('no_response', '2026-11-20'))
        self.assertIn('2026-11-20: closed in stale sweep', r['notes'])
        self.assertEqual(tracker.stale(rows, self.TODAY), [])
        with self.assertRaises(ValueError):
            tracker.set_status(rows, key, 'ghosted', '2026-11-20')
        with self.assertRaises(KeyError):
            tracker.find(rows, 'nope')

    def test_closed_statuses_close(self):
        self.assertTrue(tracker.advance('offer', '2026-11-01', 'accepted', '2026-11-05'))
        self.assertFalse(tracker.advance('no_response', '2026-11-05', 'applied', '2026-11-01'))

    def test_new_column_reads_old_files(self):
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'tracker.csv')
        open(p, 'w', encoding='utf-8', newline='\n').write('"date_applied","company","title","id","job_key","status","status_date","source","url","folder","gmail_ids","notes"\n'
                           '"2026-11-01","Brightwater","Staff PM","x1","brightwater_staff-pm","applied","2026-11-01","pipeline","","","",""\n')
        rows = tracker.read(p)
        tracker.log_followup(rows, 'x1', '2026-11-15')
        tracker.write(p, rows)
        self.assertEqual(tracker.read(p)[0]['followups'], '2026-11-15')

    def test_gap_heatmap(self):
        import tempfile
        q = tempfile.mkdtemp()
        cols = ['tier', 'fit', 'ats', 'company', 'title', 'locations', 'salary_max', 'gaps', 'flags', 'review', 'url', 'id']
        for name, rows in (('scored-2026-11-01.csv', [('C', 'infrastructure; B2B/enterprise', 'a1'), ('B', 'infrastructure', 'b1')]),
                           ('scored-2026-11-02.csv', [('A', '', 'b1'), ('C', 'infrastructure', 'c1')])):  # b1 rescored: newest wins
            with open(os.path.join(q, name), 'w', newline='', encoding='utf-8') as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                for tier, gaps, rid in rows:
                    w.writerow([tier, 50, 50, 'Brightwater', 'PM', 'NYC', '', gaps, '', 'no', '', rid])
        gaps = tracker.gap_counts(q)
        self.assertEqual(gaps, {'infrastructure': {'C': 2}, 'B2B/enterprise': {'C': 1}})
        page = tracker.gap_table(gaps)
        self.assertIn('<td>infrastructure</td>', page)
        self.assertLess(page.index('infrastructure'), page.index('B2B/enterprise'))
        self.assertEqual(tracker.gap_table({}), '')

    def test_materials(self):
        import tempfile
        vault = tempfile.mkdtemp()
        folder = os.path.join(vault, 'Workflow', '03-Applied', '2026-11-01 Brightwater - Staff PM')
        os.makedirs(folder)
        for f in ('Jordan_Rivera_Resume_Brightwater.pdf', 'application-notes.md', '.DS_Store'):
            open(os.path.join(folder, f), 'w', encoding='utf-8', newline='\n').close()
        d, files = tracker.materials({'folder': 'Workflow/03-Applied/2026-11-01 Brightwater - Staff PM'}, vault)
        self.assertEqual([os.path.basename(f) for f in files], ['Jordan_Rivera_Resume_Brightwater.pdf', 'application-notes.md'])
        self.assertEqual(tracker.materials({'folder': ''}, vault)[1], [])


if __name__ == '__main__':
    unittest.main()
