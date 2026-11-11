"""Fill-plan bugs found while applying on Oct 22, 2026, each reproduced on fictional data
(Jordan Rivera applying to Brightwater)."""
import datetime, json, os, shutil, subprocess, tempfile, unittest

from engine.answers import Answerer, choose_option
from engine.profile import load_profile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROFILE = os.path.join(ROOT, 'templates', 'profile.example.yaml')
CONFIG = os.path.join(ROOT, 'templates', 'config.example.json')
FAKE_PAGE = os.path.join(HERE, 'fixtures', 'fake_greenhouse_page.js')
HAVE_NODE = shutil.which('node') is not None


class _Vault(unittest.TestCase):
    def setUp(self):
        from engine import stages
        self.stages = stages
        self.tmp = tempfile.mkdtemp()
        self.vault = os.path.join(self.tmp, 'vault')
        ws = os.path.join(self.tmp, 'ws')
        os.makedirs(ws)
        shutil.copy(PROFILE, os.path.join(ws, 'profile.yaml'))
        cfg = json.load(open(CONFIG, encoding='utf-8'))
        cfg['paths'] = {'vault': self.vault}
        json.dump(cfg, open(os.path.join(ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        self.ctx = stages.Ctx(ws, today=datetime.date(2026, 10, 22))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_state(self, qid, questions, rows):
        for sub, data in (('answers', dict(id=qid, questions=questions)),
                          ('notes', dict(id=qid, resume='/r.pdf', cover=None, rows=rows))):
            os.makedirs(os.path.join(self.ctx.P, 'state', sub), exist_ok=True)
            json.dump(data, open(os.path.join(self.ctx.P, 'state', sub, qid + '.json'), 'w', encoding='utf-8', newline='\n'))


class TestApprovedDraftsArePlanned(_Vault):
    """Bug 1: a Greenhouse essay no answer rule covers (kind 'ask', or 'skip' when optional) kept its
    approved draft out of the notes, so the fill plan left the textarea empty."""

    def test_draft_for_uncovered_textarea_reaches_the_plan(self):
        essay = 'At Northwind I owned the savings product end to end.'
        side = 'I wrote the onboarding checklist for new hosts.'
        form = dict(questions=[
            dict(label='What savings product have you owned as a PM (e.g. deposits)?', required=True, type='textarea',
                 options=[], kind='ask', answer=''),
            dict(label='Anything about onboarding you want to share?', required=False, type='textarea',
                 options=[], kind='skip', answer=''),
            dict(label='Is there anything we should know about accessibility?', required=False, type='textarea',
                 options=[], kind='skip', answer='')])
        drafts = {'answers': {'What savings product have you owned as a PM (e.g. deposits)?': essay,
                              'Anything about onboarding you want to share?': side}}
        rows, _ = self.stages.note_rows(self.ctx, form, dict(slug='Brightwater-PM'), dict(locations=''), drafts, None, None, None)
        by = {r[0]: r for r in rows}
        self.assertEqual(by['What savings product have you owned as a PM (e.g. deposits)?'][2:], (essay, 'draft'))
        self.assertEqual(by['Anything about onboarding you want to share?'][2:], (side, 'draft'))
        self.assertEqual(by['Is there anything we should know about accessibility?'][3], 'skip')  # no draft: still blank

        self.write_state('gh-brightwater-1', form['questions'],
                         [dict(label=l, required=r, answer=a, source=s) for l, r, a, s in rows])
        _, plan, review = self.stages.build_fillplan(self.ctx, 'gh-brightwater-1')
        got = {p['label']: (p['kind'], p['value']) for p in plan}
        self.assertEqual(got['What savings product have you owned as a PM (e.g. deposits)?'], ('text', essay))
        self.assertEqual(got['Anything about onboarding you want to share?'], ('text', side))
        self.assertNotIn('Is there anything we should know about accessibility?', got)


class TestWorkAuthorizationExamples(unittest.TestCase):
    """Bug 2: "(e.g. ... you have a visa)" sent an authorization question to the sponsorship rule (No)."""

    def setUp(self):
        self.a = Answerer(load_profile(PROFILE), today=datetime.date(2026, 10, 22))

    def test_visa_example_does_not_flip_authorization(self):
        r = self.a.classify('Are you currently legally authorized to work in the country in which this job is based '
                            '(e.g. you are a citizen, you have a visa, etc.)?')
        self.assertEqual((r['kind'], r['answer']), ('fixed', 'Yes'))

    def test_real_sponsorship_question_still_answers_sponsorship(self):
        r = self.a.classify('Will you now or in the future require visa sponsorship to work at Brightwater?')
        self.assertEqual(r['answer'], 'No')

    def test_other_examples_still_count(self):  # parity, Oct 22: the example is what these questions ask about
        r = self.a.classify('Are you subject to any post-employment restrictions at Brightwater? (e.g., non-compete)?')
        self.assertEqual((r['kind'], r['answer']), ('fixed', 'No'))
        r = self.a.classify('Will you now, or in the future, require sponsorship (i.e. H-1B visa, etc.) to work at Brightwater?')
        self.assertEqual(r['answer'], 'No / N/A (U.S. citizen)')  # visa_detail, as before


class TestRaceOptionMatching(unittest.TestCase):
    """Bug 3: "East Asian" matched "East Asian - Chinese" by prefix; a parent category must not pick a subgroup."""

    SUBGROUPS = ['Asian - Indian ', 'East Asian - Chinese', 'East Asian - Japanese ', 'East Asian - Korean ',
                 'East Asian - Other (Please Specify) ', 'White - US', "I don't wish to answer"]

    def test_parent_category_among_subgroups_asks(self):
        self.assertIsNone(choose_option(self.SUBGROUPS, 'Race & Ethnicity', 'East Asian (Asian)'))

    def test_decline_still_matches(self):
        self.assertEqual(choose_option(['Decline To Self Identify', 'Asian'], 'Race', 'Decline to self-identify'),
                         'Decline To Self Identify')

    def test_full_option_still_matches(self):
        self.assertEqual(choose_option(self.SUBGROUPS, 'Race & Ethnicity', 'East Asian - Japanese'), 'East Asian - Japanese ')

    def test_explanatory_parenthetical_still_matches(self):
        opts = ['East Asian (inclusive of Chinese, Japanese, Korean)', 'Southeast Asian (inclusive of Filipino, Thai)',
                'White ', "I don't wish to answer"]
        self.assertEqual(choose_option(opts, 'How do you identify? (race/ethnicity)', 'East Asian (Asian)'), opts[0])
        self.assertEqual(choose_option(['Asian (Not Hispanic or Latino)', 'White (Not Hispanic or Latino)'], 'Race',
                                       'East Asian (Asian)'), 'Asian (Not Hispanic or Latino)')


@unittest.skipUnless(HAVE_NODE, 'node not installed')
class TestGreenhouseRaceDropdown(_Vault):
    """Bug 4: Greenhouse's EEO block lists "Race" in the API, but the page asks "Are you Hispanic/Latino?" first
    and shows the race dropdown only after that is answered, so the filler found no "Race" box to set."""

    RACE_OPTS = ['Decline To Self Identify', 'Two or More Races', 'White', 'Hispanic or Latino', 'Black or African American', 'Asian']
    PAGE = [dict(id='gender', label='Gender', options=['Male', 'Female', 'Decline To Self Identify']),
            dict(id='hispanic_ethnicity', label='Are you Hispanic/Latino?', options=['Yes', 'No', 'Decline To Self Identify']),
            dict(id='race', label='Please identify your race', showIf=dict(id='hispanic_ethnicity', value='No'),
                 options=['Decline To Self Identify', 'Two or More Races', 'White', 'Black or African American', 'Asian'])]

    def fill(self, race, hispanic):
        self.ctx.prof['eeo'] = dict(self.ctx.prof['eeo'], race=race, hispanic=hispanic)
        qs = [dict(label='Gender', required=False, type='multi_value_single_select', section='eeo',
                   options=['Decline To Self Identify', 'Female', 'Male'], kind='eeo', answer='Female'),
              dict(label='Race', required=False, type='multi_value_single_select', section='eeo',
                   options=self.RACE_OPTS, kind='eeo', answer=race)]
        self.write_state('gh-brightwater-2', qs, [dict(label=q['label'], required=False, answer=q['answer'], source='eeo') for q in qs])
        out, plan, review = self.stages.build_fillplan(self.ctx, 'gh-brightwater-2')
        page = os.path.join(self.tmp, 'page.json')
        json.dump(self.PAGE, open(page, 'w', encoding='utf-8', newline='\n'))
        res = subprocess.run(['node', FAKE_PAGE, out, page], capture_output=True, text=True, check=True, encoding='utf-8')
        return json.loads(res.stdout), review

    def test_hispanic_answered_first_then_race(self):
        got, review = self.fill('Asian', 'No')
        self.assertEqual(got['values'], {'gender': 'Female', 'hispanic_ethnicity': 'No', 'race': 'Asian'}, got['report'])
        self.assertNotIn('FAIL', got['report'])

    def test_race_box_found_by_its_label(self):
        self.PAGE = [dict(f, name='') if f['id'] == 'race' else f for f in self.PAGE]  # no accessible name: <label for> only
        got, review = self.fill('Asian', 'No')
        self.assertEqual(got['values'].get('race'), 'Asian', got['report'])

    def test_hispanic_yes_needs_no_race_box(self):
        got, review = self.fill('Hispanic or Latino', 'Yes')
        self.assertEqual(got['values'], {'gender': 'Female', 'hispanic_ethnicity': 'Yes'}, got['report'])
        self.assertNotIn('FAIL', got['report'])


if __name__ == '__main__':
    unittest.main()
