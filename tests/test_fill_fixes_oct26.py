"""Fill bugs found while applying on Oct 25-26, 2026 (AI attestations, a "No" that picked a state and a country-only
location field are at the end), each reproduced on fictional data (Jordan Rivera, Brightwater):
a title question answered with the employer, "Canada or the United States" answered by the Canada-only rule,
a Greenhouse degree spelled "Bachelors", and resume uploads set before Greenhouse's upload script was ready."""
import datetime, json, os, re, subprocess, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.answers import Answerer
from engine.profile import load_profile
from test_fillplan_fixes import FAKE_PAGE, HAVE_NODE, PROFILE, _Vault


class Answers(unittest.TestCase):
    def setUp(self):
        self.a = Answerer(load_profile(PROFILE), today=datetime.date(2026, 10, 26))
        self.title = self.a.prof.get('employment.most_recent.title')
        self.company = self.a.prof.get('employment.most_recent.company')

    def ans(self, q):
        return self.a.classify(q)['answer']

    def test_title_questions_get_the_title(self):
        for q in ('What is your current or most recent job title?', 'Current or most recent title',
                  'Title at your current or most recent company', 'Job title at your most recent employer',
                  'What is your most recent job title?'):
            self.assertEqual(self.ans(q), self.title, q)

    def test_company_questions_still_get_the_company(self):
        for q in ('Current or most recent employer', 'Current (or most recent) company', 'Previous employer'):
            self.assertEqual(self.ans(q), self.company, q)

    def test_us_or_canada_is_yes_when_us_authorized(self):
        for q in ('Are you legally eligible to work in Canada or the United States?',
                  'Are you authorized to work in the US or Canada?', 'Can you work in the United States or in Canada?'):
            self.assertEqual(self.ans(q), 'Yes', q)

    def test_either_yes(self):
        from engine.answers import _either_yes
        self.assertEqual(_either_yes('Yes', 'No'), 'Yes')
        self.assertEqual(_either_yes('No', 'No'), 'No')
        self.assertIsNone(_either_yes('No', None))  # Canada unknown: ask rather than say No


class DegreeFallback(unittest.TestCase):
    def test_level_word_spelled_other_ways(self):
        from engine.stages import _degree_loose
        r = _degree_loose("^Bachelor's Degree$")
        for o in ('Bachelors', "Bachelor's", 'Bachelor Degree', 'Bachelor’s Degree'):
            self.assertTrue(re.search(r, o, re.I), o)
        for o in ('Bachelor of Arts', "Master's Degree", 'Associates'):
            self.assertFalse(re.search(r, o, re.I), o)
        self.assertEqual(_degree_loose(''), '(?!)')


@unittest.skipUnless(HAVE_NODE, 'node not installed')
class GreenhouseUpload(_Vault):
    def fill(self, fail_first):
        qs = [dict(label='Resume/CV', required=True, type='input_file', options=[], kind='fixed', answer='FILE')]
        self.write_state('gh-brightwater-3', qs, [dict(label='Resume/CV', required=True, answer='FILE: tailored resume PDF',
                                                      source='fixed')])
        out, plan, review = self.stages.build_fillplan(self.ctx, 'gh-brightwater-3')
        self.assertIn("/^Bachelor'?", open(out, encoding='utf-8').read())  # the degree fallback is substituted into the filler
        page = os.path.join(self.tmp, 'page.json')
        json.dump([dict(id='resume', label='Resume/CV', file=True, failFirst=fail_first)], open(page, 'w', encoding='utf-8', newline='\n'))
        res = subprocess.run(['node', FAKE_PAGE, out, page], capture_output=True, text=True, check=True, encoding='utf-8')
        return json.loads(res.stdout)

    @staticmethod
    def lines(got):
        r = got['report']
        return r.splitlines() if isinstance(r, str) else r

    def test_ready_widget_uploads_once(self):
        got = self.fill(0)
        self.assertEqual(got['uploads'], {'resume': 1})
        self.assertTrue(any(r.startswith('ok    file') for r in self.lines(got)), got['report'])

    def test_not_ready_widget_gets_a_second_try(self):
        got = self.fill(1)
        self.assertEqual(got['uploads'], {'resume': 2})
        self.assertEqual(got['values']['resume'], 'r.pdf Remove')
        self.assertTrue(any(r.startswith('ok    file') for r in self.lines(got)), got['report'])

    def test_still_not_attached_is_reported(self):
        got = self.fill(2)
        self.assertTrue(any(r.startswith('FAIL  file') and 'not shown' in r for r in self.lines(got)), got['report'])


if __name__ == '__main__':
    unittest.main()


class AiAttestation(unittest.TestCase):
    """An AI-use attestation is the user's to answer for each role, even when an earlier form's answer exists."""

    def setUp(self):
        self.a = Answerer(load_profile(PROFILE), exact={'candidate ai usage attestation:': 'I agree'},
                          today=datetime.date(2026, 10, 26))

    def test_attestations_ask(self):
        for q in ('Candidate AI Usage Attestation:', 'AI Policy for Application',
                  'I attest that all materials I submit were completed without the use of AI Tools.',
                  'By submitting your application, you are agreeing not to use AI interview tools during the process.',
                  'Acceptable use of AI may differ by role; we ask all candidates to adhere to these expectations.',
                  'I certify that I did not use generative AI to write my answers.'):
            r = self.a.classify(q)
            self.assertEqual((r['kind'], r['answer']), ('ask', ''), q)

    def test_questions_about_ai_work_are_not_attestations(self):
        for q in ('How has AI changed the way you approach your work?', 'How do you use AI in your day-to-day work?',
                  'Do you have experience using AI tools to synthesize qualitative research?'):
            self.assertNotEqual(self.a.classify(q)['source'], 'AI attestation: the user answers it for each role', q)

    def test_company_use_of_ai_is_a_consent_not_an_attestation(self):
        from engine.answers import ai_attestation
        self.assertFalse(ai_attestation('I understand that Brightwater may use AI tools to assist in the interview process.'))
        self.assertFalse(ai_attestation('With your permission, we may use AI transcription software to summarize your interview.'))


class NoIsAWholeWord(unittest.TestCase):
    def test_no_does_not_pick_a_state(self):
        from engine.answers import choose_option
        opts = ['I have no plans to move at this time', 'California', 'North Carolina', 'Norway']
        self.assertEqual(choose_option(opts, 'Do you plan to move out of the state/country in the next 6-12 months?', 'No'),
                         'I have no plans to move at this time')
        self.assertEqual(choose_option(['Blindness', 'None of these apply'], 'Are you a person living with a disability?', 'No'),
                         'None of these apply')
        self.assertEqual(choose_option(['Yesterday', 'Yes, I can'], 'Can you start soon?', 'Yes'), 'Yes, I can')


class AshbyCountryLocation(_Vault):
    def test_form_keeps_location_types_and_description(self):
        from unittest import mock
        from engine import forms
        field = dict(title='Location', type='Location', locationTypes=['Country'])
        resp = dict(data=dict(jobPosting=dict(applicationForm=dict(sections=[dict(title='', fieldEntries=[
            dict(isRequired=True, field=field, descriptionHtml="<p>Country you're currently residing in</p>")])]),
            surveyForms=[])))
        with mock.patch.object(forms, 'get', return_value=json.dumps(resp)):
            q = forms.ashby('brightwater', 'x')[0]
        self.assertEqual((q['location_types'], q['description']), (['Country'], "Country you're currently residing in"))

    def test_country_location_types_the_country(self):
        q = dict(label='Location', required=True, type='Location', options=[], section='', location_types=['Country'])
        self.write_state('ab-brightwater-4', [q], [dict(label='Location', required=True, answer='Chicago, IL', source='fixed')])
        out, plan, review = self.stages.build_fillplan(self.ctx, 'ab-brightwater-4')
        self.assertEqual(plan, [dict(label='Location', kind='location', value='United States', typed='United States',
                                     re='^United\\ States')])

    def test_city_location_unchanged(self):
        q = dict(label='Location', required=True, type='Location', options=[], section='')
        self.write_state('ab-brightwater-5', [q], [dict(label='Location', required=True, answer='Chicago, IL', source='fixed')])
        out, plan, review = self.stages.build_fillplan(self.ctx, 'ab-brightwater-5')
        self.assertEqual(plan[0]['kind'], 'location')
        self.assertNotIn('typed', plan[0])


class AuthorizationWithSponsorshipNote(unittest.TestCase):
    """Oct 26: "(*NOTE* Visa Sponsorship is not available for this position.)" after an authorization question sent
    it to the sponsorship rule, and "authorized to work?" was answered No."""

    def setUp(self):
        self.a = Answerer(load_profile(PROFILE), today=datetime.date(2026, 10, 26))

    def test_note_does_not_make_it_a_sponsorship_question(self):
        for q in ('Are you authorized to work in the United States for any employer? (*NOTE* Visa Sponsorship is not '
                  'available for this position.)', 'Are you authorized to work in the US? Note: we cannot sponsor visas.'):
            self.assertEqual(self.a.classify(q)['answer'], self.a.prof.get('work_authorization.authorized_us'), q)

    def test_sponsorship_questions_still_answer_sponsorship(self):
        want = self.a.prof.get('work_authorization.needs_sponsorship')
        for q in ('Will you now or in the future require visa sponsorship? (Note: sponsorship is not available)',
                  'Will you require sponsorship?'):
            self.assertEqual(self.a.classify(q)['answer'], want, q)


class RelocationAssistance(_Vault):
    """Oct 26: "We will not provide relocation assistance. Do you require relocation assistance?" got Yes from
    the relocation rule, which answers whether you would move, not whether you need the benefit."""

    LABEL = '[Relocation] Brightwater will not provide relocation assistance for this role. Do you require relocation assistance?'

    def test_routed_to_its_own_rule(self):
        a = self.ctx.answerer()
        self.assertEqual(a.classify(self.LABEL)['answer'], 'RELOCATION_ASSIST')
        self.assertEqual(a.classify('Are you willing to relocate to New York?')['answer'], 'RELOCATION')

    def test_no_when_working_from_home_or_remote(self):
        from engine.locations import relocation_assistance
        home = self.ctx.cfg['locations'].get('home')
        self.assertEqual(relocation_assistance('Remote', self.ctx.prof, self.ctx.cfg), 'No')
        self.assertEqual(relocation_assistance(home, self.ctx.prof, self.ctx.cfg), 'No')

    def test_elsewhere_asks_unless_the_profile_says(self):
        from engine.locations import relocation_assistance
        other = next(m['name'] for m in self.ctx.cfg['locations']['metros'] if m['name'] != self.ctx.cfg['locations'].get('home'))
        self.assertIsNone(relocation_assistance(other, self.ctx.prof, self.ctx.cfg))
        self.ctx.prof['preferences'] = dict(self.ctx.prof.get('preferences') or {}, relocation_assistance='No')
        self.assertEqual(relocation_assistance(other, self.ctx.prof, self.ctx.cfg), 'No')


class OfficeOptionClaims(unittest.TestCase):
    """Oct 26: a hybrid answer for San Francisco picked "Yes, I already live in the San Francisco Bay Area"."""
    OPTS = ['Yes, I already live in the San Francisco Bay Area', 'Yes, I am willing to relocate at my own expense', 'No']
    LAB = 'Will you be able to work on-site in San Francisco at least three days a week?'

    def test_hybrid_answer_does_not_claim_residence_or_a_move(self):
        from engine.answers import choose_option
        ans = 'Yes, I can work from the San Francisco office up to 3 days a week (hybrid); I would not relocate full time.'
        self.assertIsNone(choose_option(self.OPTS, self.LAB, ans))

    def test_answers_that_say_so_still_match(self):
        from engine.answers import choose_option
        self.assertEqual(choose_option(self.OPTS, self.LAB, 'Yes, I would relocate to San Francisco.'), self.OPTS[1])
        self.assertEqual(choose_option(['Yes', 'No'], self.LAB, 'Yes, I can work from the office 3 days a week.'), 'Yes')


class YearsPlaceholder(_Vault):
    """Oct 26: a YEARS placeholder ("13 years ... [pick the matching option]") was typed into a text box."""

    def test_placeholder_goes_to_review(self):
        lab = 'Do you have 5+ years of hands-on product management experience?'
        q = dict(label=lab, required=True, type='input_text', options=[], section='')
        self.write_state('gh-brightwater-6', [q], [dict(label=lab, required=True, answer='13 [pick the matching option]',
                                                       source='draft')])
        out, plan, review = self.stages.build_fillplan(self.ctx, 'gh-brightwater-6')
        self.assertEqual(plan, [])
        self.assertTrue(any(r.startswith(lab[:40]) for r in review), review)


@unittest.skipUnless(HAVE_NODE, 'node not installed')
class RepeatedQuestionBlock(_Vault):
    """Oct 26: a form repeated a block of questions (same labels, other ids); the filler set only the first of each."""

    def test_each_copy_is_filled(self):
        lab = 'Are you legally authorized to work in the country where you are applying?'
        qs = [dict(label=lab, required=True, type='multi_value_single_select', options=['Yes', 'No'], section='')] * 2
        rows = [dict(label=lab, required=True, answer='Yes', source='fixed')] * 2
        self.write_state('gh-brightwater-7', qs, rows)
        out, plan, review = self.stages.build_fillplan(self.ctx, 'gh-brightwater-7')
        page = os.path.join(self.tmp, 'page.json')
        with open(page, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump([dict(id='auth1', label=lab, options=['Yes', 'No']), dict(id='auth2', label=lab, options=['Yes', 'No'])], fh)
        got = json.loads(subprocess.run(['node', FAKE_PAGE, out, page], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
        self.assertEqual(got['values'], {'auth1': 'Yes', 'auth2': 'Yes'}, got['report'])


class PerRoleAiApproval(_Vault):
    """An AI attestation asks (0.20.2); an answer in a stage-5 file that names the role id approves that role only."""
    LABEL = 'Candidate AI Usage Attestation:'

    def form(self, rid, company):
        os.makedirs(os.path.join(self.ctx.P, 'state', 'forms'), exist_ok=True)
        with open(os.path.join(self.ctx.P, 'state', 'forms', rid + '.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(dict(id=rid, company=company, title='Product Lead', url='https://x', questions=[
                dict(label=self.LABEL, required=True, type='multi_value_single_select', options=['I agree'], section='')]), fh)

    def answers(self, rid):
        with open(os.path.join(self.ctx.P, 'state', 'answers', rid + '.json'), encoding='utf-8') as fh:
            return {q['label']: (q['kind'], q['answer']) for q in json.load(fh)['questions']}

    def test_answer_naming_the_role_applies_to_that_role_only(self):
        self.form('gh-brightwater-8', 'Brightwater')
        self.form('gh-northwind-9', 'Northwind')
        with contextlib_quiet():
            self.stages.stage_answers(self.ctx)
        q = os.path.join(self.ctx.P, 'queue')
        md = open(os.path.join(q, 'stage5-questions-2026-10-22-open.md'), encoding='utf-8').read()
        self.assertIn(f'**{self.LABEL}** (1 role: gh-brightwater-8: Brightwater: Product Lead)', md)
        self.assertIn(f'**{self.LABEL}** (1 role: gh-northwind-9: Northwind: Product Lead)', md)
        with open(os.path.join(q, 'stage5-questions-2026-10-22-a.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(f'1. **{self.LABEL}** (gh-brightwater-8; Jordan read it and agrees)\n   ANSWER: I agree\n')
        with contextlib_quiet():
            self.stages.stage_answers(self.ctx)
        self.assertEqual(self.answers('gh-brightwater-8')[self.LABEL], ('user', 'I agree'))
        self.assertEqual(self.answers('gh-northwind-9')[self.LABEL], ('ask', ''))

    def test_answer_without_a_role_id_approves_nothing(self):
        from engine.answers import load_stage5_role_answers
        q = os.path.join(self.tmp, 's5')
        os.makedirs(q)
        with open(os.path.join(q, 'stage5-questions-x.md'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(f'1. **{self.LABEL}** (Brightwater; Jordan agrees)\n   ANSWER: I agree\n'
                     f'2. **{self.LABEL}** (ab-north-wind-1f2e, lv-acme-3: two roles)\n   ANSWER: I agree\n')
        self.assertEqual(sorted(load_stage5_role_answers(os.path.join(q, '*.md'))),
                         [('ab-north-wind-1f2e', 'Candidate AI Usage Attestation:'), ('lv-acme-3', 'Candidate AI Usage Attestation:')])
        a = Answerer(load_profile(PROFILE), exact={'Candidate AI Usage Attestation:': 'I agree'},
                     role_exact=load_stage5_role_answers(os.path.join(q, '*.md')))
        self.assertEqual(a.classify(self.LABEL)['kind'], 'ask')
        self.assertEqual(a.classify(self.LABEL, role='gh-brightwater-8')['kind'], 'ask')
        self.assertEqual(a.classify(self.LABEL, role='lv-acme-3')['answer'], 'I agree')


def contextlib_quiet():
    import contextlib, io
    return contextlib.redirect_stdout(io.StringIO())
