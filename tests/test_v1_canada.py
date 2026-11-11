"""E6a: full US + Canada coverage. A US config (no new keys) must behave exactly as before."""
import re
import unittest
from unittest import mock

from engine import answers, gates, locations, locfmt, pay
from engine.locations import location_match, countries_in
from engine.profile import Profile, load_config, KNOWN_METROS
from engine.sources import linkedin, remote_apis


def cfg(remote=None, metros=('Toronto',), **loc):
    d = {'metros': [{'name': m} for m in metros], **loc}
    if remote is not None:
        d['remote_countries'] = remote
    return load_config({'locations': d})


REMOTE_LABELS = ['Remote', 'Remote - US', 'Remote - Canada', 'Remote, North America', 'Remote - UK', 'Canada',
                 'United States', 'Remote (US or Canada)', 'Remote - EMEA']


def remote_hits(c):
    return {l: location_match(l, '', c) == ['Remote'] for l in REMOTE_LABELS}


class RemoteCountries(unittest.TestCase):
    def test_legacy_forms_mean_us(self):
        self.assertEqual(cfg()['locations']['remote_countries'], ['US'])
        self.assertEqual(load_config({'locations': {'remote_us': True}})['locations']['remote_countries'], ['US'])
        off = load_config({'locations': {'remote_us': False}})['locations']
        self.assertEqual((off['remote_countries'], off['remote_us']), ([], False))

    def test_us_only_matches_the_original_rules(self):
        self.assertEqual(remote_hits(cfg()), remote_hits(cfg(['US'])))
        self.assertEqual(remote_hits(cfg(['US'])), {
            'Remote': True, 'Remote - US': True, 'Remote - Canada': False, 'Remote, North America': True,
            'Remote - UK': False, 'Canada': False, 'United States': True, 'Remote (US or Canada)': True,
            'Remote - EMEA': False})

    def test_canada_only_and_both(self):
        self.assertEqual(remote_hits(cfg(['CA'])), {
            'Remote': True, 'Remote - US': False, 'Remote - Canada': True, 'Remote, North America': True,
            'Remote - UK': False, 'Canada': True, 'United States': False, 'Remote (US or Canada)': True,
            'Remote - EMEA': False})
        self.assertEqual(remote_hits(cfg(['US', 'CA'])), {
            'Remote': True, 'Remote - US': True, 'Remote - Canada': True, 'Remote, North America': True,
            'Remote - UK': False, 'Canada': True, 'United States': True, 'Remote (US or Canada)': True,
            'Remote - EMEA': False})

    def test_remote_can_be_top_with_canada_only(self):
        c = cfg(['CA'], top=['Remote'])
        self.assertEqual(c['locations']['top'], ['Remote'])

    def test_bad_country(self):
        with self.assertRaisesRegex(ValueError, 'remote_countries'):
            cfg(['GB'])


class Metros(unittest.TestCase):
    def hits(self, text, metros=('Toronto', 'Vancouver', 'Montreal', 'Ottawa', 'Calgary', 'Edmonton', 'Waterloo')):
        return location_match(text, '', cfg(['CA'], metros=metros))

    def test_metros(self):
        for text, want in [('Toronto, ON', 'Toronto'), ('Mississauga, ON, Canada', 'Toronto'), ('Greater Toronto Area (GTA)', 'Toronto'),
                           ('Vancouver, BC', 'Vancouver'), ('Burnaby, British Columbia', 'Vancouver'),
                           ('Montréal, QC', 'Montreal'), ('Montreal', 'Montreal'), ('Ottawa, Ontario', 'Ottawa'),
                           ('Calgary, AB', 'Calgary'), ('Edmonton, AB', 'Edmonton'), ('Kitchener-Waterloo, ON', 'Waterloo'),
                           ('Waterloo, Ontario', 'Waterloo')]:
            self.assertIn(want, self.hits(text), text)

    def test_one_city_one_metro(self):
        self.assertEqual(self.hits('Ottawa, ON'), ['Ottawa'])
        self.assertEqual(self.hits('Waterloo, ON'), ['Waterloo'])
        self.assertEqual(self.hits('Edmonton, AB'), ['Edmonton'])

    def test_us_lookalikes_and_bare_words(self):
        for text in ['Vancouver, WA', 'Waterloo, IA', 'Ottawa, IL', 'Hybrid, on-site', 'Austin, TX']:
            self.assertEqual(self.hits(text), [], text)

    def test_known_names_have_patterns_and_provinces(self):
        for name in ('Toronto', 'Vancouver', 'Montreal', 'Ottawa', 'Calgary', 'Edmonton', 'Waterloo'):
            self.assertIn(name, KNOWN_METROS)
            self.assertTrue(cfg(['CA'], metros=(name,))['locations']['home_state'])
        self.assertEqual(cfg(['CA'])['locations']['home_state'], ['ON', 'Ontario'])

    def test_countries_in(self):
        for text, want in [('Toronto, ON', {'CA'}), ('Vancouver, WA', {'US'}), ('Vancouver, British Columbia', {'CA'}),
                           ('Remote - North America', {'US', 'CA'}), ('Remote', set()), ('Austin, TX; Toronto, ON', {'US', 'CA'}),
                           ('Kitchener, ON', {'CA'}), ('Hybrid, on-site', set()), ('Remote - Canada', {'CA'})]:
            self.assertEqual(countries_in(text), want, text)

    def test_province_abbreviations_are_not_us_states(self):
        for ab in ('ON', 'BC', 'QC', 'AB', 'MB', 'SK', 'NS', 'NB', 'NL', 'PE'):
            self.assertEqual(countries_in(f'Somewhere, {ab}'), {'CA'}, ab)
            self.assertNotIn(ab.lower(), locations.US_STATES)


class Format(unittest.TestCase):
    def test_canadian_cities(self):
        f = locfmt.format_location
        self.assertEqual(f('Toronto, ON'), 'Toronto')
        self.assertEqual(f('Mississauga, ON · Hybrid'), 'Toronto · Hybrid')
        self.assertEqual(f('Montréal, QC; Ottawa, ON'), 'Montreal; Ottawa')
        self.assertEqual(f('Calgary, AB'), 'Calgary')
        self.assertEqual(f('Kitchener-Waterloo, ON'), 'Waterloo')
        self.assertEqual(f('Remote - Canada'), 'Remote (Canada)')
        self.assertEqual(f('Remote - US or Canada'), 'Remote (US/Canada)')

    def test_us_formatting_unchanged(self):
        f = locfmt.format_location
        self.assertEqual(f('San Francisco, CA · Hybrid'), 'SF · Hybrid')
        self.assertEqual(f('Remote - US'), 'Remote (US)')
        self.assertEqual(f('Remote', remote=True), 'Remote (US)')
        self.assertEqual(f('Remote'), 'Remote')
        self.assertEqual(f('Vancouver, WA'), 'Vancouver')
        self.assertEqual(f('Ottawa, IL'), '')


CA_CFG = load_config({'salary': {'floor_usd': 150000, 'floor_cad': 130000},
                      'locations': {'metros': [{'name': 'Toronto'}], 'remote_countries': ['US', 'CA']}})
US_CFG = load_config({'salary': {'floor_usd': 150000}, 'locations': {'metros': [{'name': 'SF'}]}})


class Pay(unittest.TestCase):
    def full(self, text, hits=('Toronto',), **kw):
        return pay.salary_full(text, hits=list(hits), cfg=kw.get('cfg', CA_CFG))

    def test_cad_forms(self):
        for text in ['CA$120,000 - CA$150,000', 'C$120,000 to C$150,000', 'CAD $120,000 - $150,000', '$120k-$150k CAD',
                     '$120,000 - $150,000 CAD per year', '$120,000 - $150,000 Canadian dollars']:
            lo, hi, _, cur = self.full(text, hits=('Remote',))
            self.assertEqual((lo, hi, cur), (120000, 150000, 'CAD'), text)

    def test_usd_forms(self):
        for text in ['US$150,000 - US$180,000', '$150,000 - $180,000 USD', 'USD $150k to $180k']:
            lo, hi, _, cur = self.full(text)
            self.assertEqual((lo, hi, cur), (150000, 180000, 'USD'), text)

    def test_plain_dollar_default(self):
        self.assertEqual(self.full('$120,000 - $150,000', hits=('Remote',))[3], 'USD')
        self.assertEqual(self.full('$120,000 - $150,000', hits=('Toronto', 'Remote'))[3], 'USD')
        self.assertEqual(self.full('$120,000 - $150,000', hits=('Toronto',))[3], 'CAD')
        self.assertEqual(self.full('$120,000 - $150,000 (we also pay in USD)', hits=('Toronto',))[3], 'USD')

    def test_both_currencies_pick_the_users(self):
        text = 'C$100k - C$130k or US$90k-US$110k'
        self.assertEqual(self.full(text, hits=('Toronto',))[:2], (100000, 130000))
        self.assertEqual(self.full(text, hits=('Remote',))[:2], (90000, 110000))

    def test_board_numbers(self):
        self.assertEqual(pay.salary_full('', 100000, 150000, hits=['Toronto'], cfg=CA_CFG)[3], 'CAD')
        self.assertEqual(pay.salary_full('', 100000, 150000, hits=['Remote'], cfg=CA_CFG)[3], 'USD')

    def test_salary_triple_marks_cad(self):
        self.assertEqual(pay.salary('CA$120,000 - CA$150,000', hits=['Toronto'], cfg=CA_CFG), (120000, 150000, 'jd_text CAD'))
        self.assertEqual(pay.salary('$120,000 - $150,000', hits=['Remote'], cfg=CA_CFG), (120000, 150000, 'jd_text'))

    def test_floors_per_currency(self):
        self.assertTrue(pay.below_floor(120000, 'CAD', CA_CFG))
        self.assertFalse(pay.below_floor(140000, 'CAD', CA_CFG))
        self.assertTrue(pay.below_floor(140000, 'USD', CA_CFG))
        self.assertFalse(pay.below_floor(1000, 'CAD', US_CFG), 'no floor_cad: CAD is never dropped for pay')

    def test_us_config_reads_text_exactly_as_before(self):
        for text in ['CA$120,000 - CA$150,000', '$120k-$150k CAD', '$120,000 - $150,000', 'US$150,000 - US$180,000',
                     '$135,000 (entry) to $160,000 (senior)']:
            old = pay.pairs(text)
            self.assertEqual(old, [(to_lo, to_hi, s, e) for to_lo, to_hi, s, e, _ in pay._pairs_cur(text)])
            self.assertEqual(pay.salary(text, hits=['SF'], cfg=US_CFG), pay.salary(text, hits=['SF']))
        self.assertEqual(pay.salary('CA$120,000 - CA$150,000', hits=['SF'], cfg=US_CFG), (None, None, 'none'))
        self.assertEqual(pay.salary('$120k-$150k CAD', hits=['SF'], cfg=US_CFG), (120000, 150000, 'jd_text'))
        self.assertEqual(pay.salary_full('$120k-$150k CAD', hits=['SF'], cfg=US_CFG)[3], 'USD')

    def test_us_only_remote_countries_is_not_canada_mode(self):
        c = load_config({'locations': {'remote_countries': ['US'], 'metros': [{'name': 'SF'}]}})
        self.assertFalse(pay.canada_on(c))
        self.assertTrue(pay.canada_on(CA_CFG))


class Himalayas(unittest.TestCase):
    JOBS = {'jobs': [
        {'guid': 'https://h/jobs/usd', 'title': 'PM', 'companyName': 'Brightwater', 'pubDate': 4102444800, 'minSalary': 150000,
         'maxSalary': 180000, 'currency': 'USD', 'locationRestrictions': ['United States'], 'description': 'x'},
        {'guid': 'https://h/jobs/cad', 'title': 'PM', 'companyName': 'Northwind', 'pubDate': 4102444800, 'minSalary': 120000,
         'maxSalary': 150000, 'currency': 'CAD', 'locationRestrictions': ['Canada'], 'description': 'y'}]}

    def run_it(self, opts):
        with mock.patch.object(remote_apis, 'fetch_json', return_value=self.JOBS), mock.patch.object(remote_apis.time, 'sleep'):
            return {p['company']: p for p in remote_apis.himalayas(['pm'], 14, dict(opts, pages=1))}

    def test_default_keeps_usd_pay_only(self):
        out = self.run_it({})
        self.assertEqual(out['Brightwater']['salary_max'], 180000)
        self.assertIsNone(out['Northwind']['salary_max'])
        self.assertNotIn('Compensation', out['Northwind']['description'])

    def test_cad_kept_with_ca(self):
        out = self.run_it({'remote_countries': ['US', 'CA']})
        self.assertEqual(out['Brightwater']['salary_max'], 180000)
        self.assertTrue(out['Northwind']['description'].startswith('Compensation: C$120,000 - C$150,000 CAD'))
        lo, hi, src, cur = pay.salary_full(out['Northwind']['description'], hits=['Remote'], cfg=CA_CFG)
        self.assertEqual((lo, hi, cur), (120000, 150000, 'CAD'))


class LinkedinPlaces(unittest.TestCase):
    def test_places(self):
        self.assertEqual(linkedin.places_from_config({}), ['United States'])
        self.assertEqual(linkedin.places_from_config(US_CFG), ['United States'])
        self.assertEqual(linkedin.places_from_config(cfg(['CA'])), ['Canada', 'Toronto, Ontario, Canada'])
        self.assertEqual(linkedin.places_from_config(cfg(['US', 'CA'], metros=('Chicago',))), ['United States', 'Canada'])

    def test_explicit_locations_win(self):
        c = dict(cfg(['CA']), sources={'linkedin': {'locations': ['Boston']}})
        self.assertEqual(linkedin.config_opts(c)['locations'], ['Boston'])
        c = dict(cfg(['CA']), sources={'linkedin': {'opts': {'locations': ['Denver'], 'pages': 2}}})
        self.assertEqual(linkedin.config_opts(c), {'locations': ['Denver'], 'pages': 2})


def prof(**wa):
    return Profile({'identity': {'first_name': 'Jordan', 'last_name': 'Rivera', 'email': 'j@example.com'},
                    'work_authorization': {'authorized_us': 'Yes', 'needs_sponsorship': 'No', 'citizenship': 'United States of America',
                                           **wa}})


SILENT = 'We are hiring a product manager to own the roadmap.'
NO_SPONSOR = 'We are unable to provide visa sponsorship for this role.'


class Gates(unittest.TestCase):
    def test_no_location_is_unchanged(self):
        p = prof(authorized_canada='Yes', needs_sponsorship_canada='No')
        for jd in (SILENT, NO_SPONSOR, 'Must be a U.S. citizen. Active security clearance required.'):
            self.assertEqual(gates.check(jd, p), gates.check(jd, prof()))
            self.assertEqual(gates.check(jd, prof(), 'Toronto, ON'), gates.check(jd, prof()))  # no Canada answers: legacy

    def test_us_location_is_unchanged(self):
        p = prof(authorized_canada='Yes', needs_sponsorship_canada='No')
        jd = 'Must be a U.S. citizen. Active security clearance required.'
        self.assertEqual(gates.check(jd, p, 'Austin, TX'), gates.check(jd, p))

    def test_us_only_gates_skip_canadian_postings(self):
        p = prof(authorized_canada='Yes', needs_sponsorship_canada='No')
        jd = 'Must be a U.S. citizen. Active security clearance required.'
        self.assertEqual(gates.check(jd, p, 'Austin, TX'), gates.check(jd, prof()))
        self.assertEqual(gates.check(jd, p, 'Toronto, ON'), [])
        jd2 = 'Active security clearance required.'
        legacy = gates.check(jd2, prof())
        self.assertTrue(legacy)
        self.assertEqual(gates.check(jd2, prof(authorized_canada='Yes'), 'Toronto, ON'), [])

    def test_sponsorship_uses_canada_field(self):
        need = prof(needs_sponsorship_canada='Yes', authorized_canada='No')
        self.assertEqual(gates.verdict(gates.check(NO_SPONSOR, need, 'Toronto, ON')), gates.FAIL)
        self.assertEqual(gates.verdict(gates.check(SILENT, need, 'Toronto, ON')), gates.UNVERIFIED)
        # US needs sponsorship, Canada doesn't: a Toronto posting that refuses sponsorship is fine
        mixed = prof(needs_sponsorship='Yes', needs_sponsorship_canada='No', authorized_canada='Yes')
        self.assertEqual(gates.verdict(gates.check(NO_SPONSOR, mixed, 'Toronto, ON')), gates.PASS)
        self.assertEqual(gates.verdict(gates.check(NO_SPONSOR, mixed, 'Austin, TX')), gates.FAIL)
        # in both countries the better result wins
        self.assertEqual(gates.verdict(gates.check(NO_SPONSOR, mixed, 'Remote - North America')), gates.PASS)

    def test_unauthorized_without_sponsorship_answer_needs_it(self):
        self.assertEqual(gates.verdict(gates.check(NO_SPONSOR, prof(authorized_canada='No'), 'Toronto, ON')), gates.FAIL)

    def test_canadian_citizenship(self):
        jd = 'Must be a Canadian citizen or permanent resident only.'
        self.assertEqual(gates.verdict(gates.check(jd, prof(authorized_canada='Yes'), 'Ottawa, ON')), gates.FAIL)
        pr = prof(authorized_canada='Yes', permanent_resident_canada='Yes')
        self.assertEqual(gates.verdict(gates.check(jd, pr, 'Ottawa, ON')), gates.PASS)

    def test_french_gate(self):
        p = prof(authorized_canada='Yes', needs_sponsorship_canada='No')
        for jd in ['Bilingual (French/English) required.', 'Français requis pour ce poste.', "Maîtrise du français et de l'anglais.",
                   'Bilingual French and English required']:
            self.assertEqual(gates.verdict(gates.check(jd, p, 'Montréal, QC')), gates.FAIL, jd)
        self.assertEqual(gates.verdict(gates.check('Nous cherchons un candidat bilingue.', p, 'Montréal, QC')), gates.FLAG)
        self.assertEqual(gates.check('Bilingual (French/English) is a plus.', p, 'Montréal, QC'), [])
        fr = Profile(dict(p, languages=[{'language': 'English', 'level': 'native'}, {'language': 'French', 'level': 'professional'}]))
        self.assertEqual(gates.check('Bilingual (French/English) required.', fr, 'Montréal, QC'), [])

    def test_french_gate_off_for_us_config(self):
        self.assertEqual(gates.check('Bilingual (French/English) required.', prof()), [])
        self.assertEqual(gates.check('Bilingual (French/English) required.', prof(), 'Austin, TX'), [])


def classify(label, p=None, **extra):
    base = prof(**extra) if p is None else p
    return answers.Answerer(base).classify(label)


class Answers(unittest.TestCase):
    def test_authorized_canada(self):
        for label in ['Are you legally entitled to work in Canada?', 'Are you legally eligible to work in Canada?',
                      'Are you authorized to work in Canada?']:
            r = classify(label, authorized_canada='Yes')
            self.assertEqual((r['kind'], r['answer']), ('fixed', 'Yes'), label)
            self.assertEqual(classify(label)['kind'], 'ask', label)

    def test_legacy_canada_field_still_answers(self):
        r = classify('Are you legally entitled to work in Canada?', canada='Yes')
        self.assertEqual(r['answer'], 'Yes')

    def test_canada_or_us_exists(self):
        self.assertEqual(classify('Are you eligible to work in Canada or the United States?')['answer'], 'Yes')
        self.assertEqual(classify('Eligible to work in the United States or Canada?', authorized_canada='No')['answer'], 'Yes')

    def test_sponsorship_canada(self):
        label = 'Will you now or in the future require sponsorship to work in Canada?'
        self.assertEqual(classify(label, needs_sponsorship_canada='Yes')['answer'], 'Yes')
        self.assertEqual(classify(label, needs_sponsorship_canada='No')['answer'], 'No')
        self.assertEqual(classify(label)['kind'], 'ask')  # never the U.S. answer

    def test_sponsorship_both_countries(self):
        label = 'Do you require visa sponsorship to work in the United States or Canada?'
        self.assertEqual(classify(label, needs_sponsorship_canada='No')['answer'], 'No')
        self.assertEqual(classify(label, needs_sponsorship_canada='Yes')['answer'], 'Yes')
        self.assertEqual(classify(label)['answer'], 'No')  # no Canada answers: the U.S. answer, as before
        self.assertEqual(classify(label, p=prof(needs_sponsorship_canada='No', needs_sponsorship=''))['kind'], 'ask')

    def test_us_sponsorship_unchanged(self):
        self.assertEqual(classify('Will you require sponsorship now or in the future?')['answer'], 'No')
        self.assertEqual(classify('Do you require visa sponsorship?', needs_sponsorship_canada='Yes')['answer'], 'No')

    def test_employment_equity_defaults_to_decline(self):
        for label in ['Do you identify as a member of a visible minority?', 'Are you Indigenous (First Nations, Métis or Inuit)?',
                      'Do you identify as a woman? (Employment Equity Act)',
                      'Do you identify as a person with a disability? (Employment Equity Act)',
                      'Do you wish to self-identify under the Employment Equity Act?']:
            r = classify(label)
            self.assertEqual((r['kind'], r['answer']), ('eeo', 'I prefer not to answer'), label)

    def test_employment_equity_from_profile(self):
        p = prof()
        p['eeo'] = {'employment_equity': {'visible_minority': 'No', 'women': 'Yes'}, 'disability': 'Decline to self-identify'}
        self.assertEqual(classify('Are you a member of a visible minority?', p=p)['answer'], 'No')
        self.assertEqual(classify('Employment equity: do you identify as a woman?', p=p)['answer'], 'Yes')

    def test_decline_option_matching(self):
        opts = ['Yes', 'No', 'Prefer not to answer']
        self.assertEqual(answers.choose_option(opts, 'visible minority?', answers.EE_DECLINE), 'Prefer not to answer')
        self.assertEqual(answers.choose_option(['Yes', 'No', 'I do not wish to self-identify'], 'x', answers.EE_DECLINE),
                         'I do not wish to self-identify')
        self.assertEqual(answers.choose_option(['Yes', 'No'], 'x', answers.EE_DECLINE), None)

    def test_us_eeo_unchanged(self):
        p = prof()
        p['eeo'] = {'disability': 'Decline to self-identify', 'race': 'Asian'}
        self.assertEqual(classify('Disability status', p=p)['answer'], 'Decline to self-identify')
        self.assertEqual(classify('Race / ethnicity', p=p)['answer'], 'Asian')


if __name__ == '__main__':
    unittest.main()
