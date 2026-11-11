"""E1 (dev/v1-cli.md): profile/config/companies/tools edits, resume titles, pack and check changes."""
import json, os, subprocess, sys, tempfile, unittest
from unittest import mock

from engine import setup, setup_edit, yamlish

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gmh(*args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, '-m', 'engine', *args], cwd=REPO, capture_output=True, text=True,
                          encoding='utf-8', env=e)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = os.path.join(self.tmp.name, 'ws')
        setup.init(self.ws, setup.LATER, name='Jordan Rivera')

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, name):
        with open(os.path.join(self.ws, name), encoding='utf-8') as fh:
            return fh.read()

    def write(self, name, text):
        with open(os.path.join(self.ws, name), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)

    def cfg(self):
        return json.loads(self.read('config.json'))


class ProfileEdit(Base):
    def test_set_scalar_keeps_comments_and_order(self):
        before = self.read('profile.yaml')
        setup_edit.profile_set(self.ws, 'identity.first_name', 'Jordan')
        setup_edit.profile_set(self.ws, 'identity.email', 'jordan@example.com')
        after = self.read('profile.yaml')
        self.assertEqual(yamlish.loads(after)['identity']['first_name'], 'Jordan')
        self.assertEqual(yamlish.loads(after)['identity']['email'], 'jordan@example.com')
        self.assertEqual(before.count('#'), after.count('#'))
        self.assertEqual(list(yamlish.loads(before)), list(yamlish.loads(after)))

    def test_leading_zero_stays_string(self):
        setup_edit.profile_set(self.ws, 'home.zip', '02134')
        self.assertEqual(yamlish.loads(self.read('profile.yaml'))['home']['zip'], '02134')

    def test_bool(self):
        setup_edit.profile_set(self.ws, 'work_authorization.authorized_us', 'true')
        self.assertIs(yamlish.loads(self.read('profile.yaml'))['work_authorization']['authorized_us'], True)

    def test_add_to_list_and_json_value(self):
        setup_edit.profile_set(self.ws, 'languages', '{"language": "French", "level": "fluent"}', add=True, as_json=True)
        setup_edit.profile_set(self.ws, 'languages', '{"language": "Spanish", "level": "basic"}', add=True, as_json=True)
        langs = yamlish.loads(self.read('profile.yaml'))['languages']
        self.assertEqual([x['language'] for x in langs], ['French', 'Spanish'])

    def test_add_to_existing_block_list_touches_nothing_else(self):
        self.write('profile.yaml', 'identity:\n  first_name: Jordan   # keep me\n  last_name: Rivera\n'
                                   'languages:\n  # note\n  - English\n  - French\neeo:\n  gender: x\n')
        setup_edit.profile_set(self.ws, 'languages', 'Spanish', add=True)
        text = self.read('profile.yaml')
        self.assertIn('# keep me', text)
        self.assertIn('# note', text)
        self.assertEqual(yamlish.loads(text)['languages'], ['English', 'French', 'Spanish'])
        self.assertEqual(yamlish.loads(text)['eeo'], {'gender': 'x'})

    def test_new_nested_keys_and_list_item_fields(self):
        self.write('profile.yaml', 'identity:\n  first_name: Jordan\neducation:\n  - school: Acme U\n    degree: BA\n')
        setup_edit.profile_set(self.ws, 'education.0.year', '2010')
        setup_edit.profile_set(self.ws, 'education.1.school', 'Brightwater College')
        setup_edit.profile_set(self.ws, 'home.city', 'Chicago')
        d = yamlish.loads(self.read('profile.yaml'))
        self.assertEqual(d['education'][0], {'school': 'Acme U', 'degree': 'BA', 'year': 2010})
        self.assertEqual(d['education'][1], {'school': 'Brightwater College'})
        self.assertEqual(d['home'], {'city': 'Chicago'})

    def test_unknown_top_level_key_is_usage_error(self):
        with self.assertRaises(setup_edit.Usage):
            setup_edit.profile_set(self.ws, 'banana.split', '1')

    def test_cli_exit_codes_and_show(self):
        env = {'GMH_WORKSPACE': self.ws}
        self.assertEqual(gmh('setup', 'profile', 'set', 'banana.x', '1', env=env).returncode, 2)
        r = gmh('setup', 'profile', 'set', 'identity.last_name', "O'Neil: Jr", env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "set identity.last_name = O'Neil: Jr"))
        r = gmh('setup', 'profile', 'show', 'identity.last_name', env=env)
        self.assertEqual(r.stdout.strip(), "O'Neil: Jr")
        self.assertIn('last_name:', gmh('setup', 'profile', 'show', 'identity', env=env).stdout)
        self.assertEqual(gmh('setup', 'profile', 'show', 'identity.nope', env=env).returncode, 1)

    def test_yamlish_dumps_round_trip(self):
        d = {'a': {'b': [1, 'x y', {'k': '02134', 'z': True, 'n': None}], 'c': 'multi\nline\n', 'e': [],
                   'f': 'a: b', 'h': "it's"}, 't': 'true'}
        self.assertEqual(yamlish.loads(yamlish.dumps(d)), d)


class ConfigEdit(Base):
    def test_locations_and_order_kept(self):
        self.write('config.json', json.dumps({'zeta': 1, 'locations': {'home': None, 'remote_us': True, 'metros': []},
                                              'alpha': {'x': 1}}))
        setup_edit.config_locations(self.ws, home='NYC', remote_countries='us, ca', metros=['NYC', 'Portland:portland|pdx'])
        cfg = self.cfg()
        self.assertEqual(list(cfg), ['zeta', 'locations', 'alpha'])
        self.assertEqual(cfg['locations']['remote_countries'], ['US', 'CA'])
        self.assertEqual([m['name'] for m in cfg['locations']['metros']], ['NYC', 'Portland'])
        self.assertEqual(cfg['locations']['metros'][1]['pattern'], 'portland|pdx')
        self.assertIn('\n  "zeta"', self.read('config.json'))

    def test_unknown_metro_without_pattern_refused(self):
        with self.assertRaises(setup_edit.Usage):
            setup_edit.config_locations(self.ws, metros=['Nowhereville'])

    def test_top(self):
        setup_edit.config_locations(self.ws, home='Chicago', remote_countries='US', metros=['Chicago', 'NYC'])
        setup_edit.config_top(self.ws, ['Chicago', 'Remote'], bonus=4)
        self.assertEqual(self.cfg()['locations']['top'], ['Chicago', 'Remote'])
        self.assertEqual(self.cfg()['locations']['top_bonus'], 4)
        with self.assertRaises(setup_edit.Usage):
            setup_edit.config_top(self.ws, ['Atlantis'])

    def test_salary(self):
        setup_edit.config_salary(self.ws, 200000, 'USD', 'exclude')
        setup_edit.config_salary(self.ws, 250000, 'CAD')
        s = self.cfg()['salary']
        self.assertEqual((s['floor_usd'], s['floor_cad'], s['no_range_policy']), (200000, 250000, 'exclude'))
        with self.assertRaises(setup_edit.Usage):
            setup_edit.config_salary(self.ws, 1, 'USD', 'maybe')

    def test_resume_keys(self):
        setup_edit.config_resume(self.ws, 'max_pages', '2')
        setup_edit.config_resume(self.ws, 'font', 'Calibri')
        setup_edit.config_resume(self.ws, 'page_breaks', '{"first_on_page_2": "experience[2]"}')
        r = self.cfg()['resume']
        self.assertEqual((r['max_pages'], r['font'], r['page_breaks']), (2, 'Calibri', {'first_on_page_2': 'experience[2]'}))
        with self.assertRaises(setup_edit.Usage):
            setup_edit.config_resume(self.ws, 'max_pages', 'two')
        with self.assertRaises(setup_edit.Usage):
            setup_edit.config_resume(self.ws, 'bogus', '1')

    def test_cli(self):
        r = gmh('setup', 'config', 'salary', '--floor', '190000', '--workspace', self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cfg()['salary']['floor_usd'], 190000)
        self.assertEqual(gmh('setup', 'config', 'salary', '--workspace', self.ws).returncode, 2)


class Companies(Base):
    def test_add_dedup(self):
        self.assertEqual(setup_edit.companies_add(self.ws, 'Acme Robotics'), 'added')
        self.assertEqual(setup_edit.companies_add(self.ws, 'acme robotics', slug='x'), 'already there')
        self.assertEqual(setup_edit.companies_add(self.ws, 'Brightwater', slug='brightwater-hq', ats='lever'), 'added')
        self.assertIn('Acme Robotics | acmerobotics\n', self.read('companies.txt'))
        self.assertIn('Brightwater | brightwater-hq\n', self.read('companies.txt'))
        self.assertEqual([n for n, _ in setup._companies(self.ws)], ['Acme Robotics', 'Brightwater'])
        cache = json.loads(self.read('Pipeline/state/ats_cache.json'))
        self.assertEqual(cache['Brightwater'], ['lever', 'brightwater-hq'])


class Tools(Base):
    def test_missing_node(self):
        with self.assertRaises(setup_edit.Nothing) as c:
            setup_edit.tools_install(self.ws, which=lambda n: None)
        self.assertIn('nodejs.org', str(c.exception))

    def test_install_records_path(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            os.makedirs(os.path.join(self.ws, '.gmh', 'node_modules', 'docx'))
            return subprocess.CompletedProcess(cmd, 0, '', '')
        mods = setup_edit.tools_install(self.ws, run=fake_run, which=lambda n: '/x/' + n)
        self.assertEqual(mods, os.path.join(self.ws, '.gmh', 'node_modules'))
        self.assertEqual(self.cfg()['paths']['node_modules'], mods)
        self.assertIn('--prefix', calls[0])
        with open(os.path.join(self.ws, '.gmh', 'package.json'), encoding='utf-8') as fh:
            self.assertIn('docx', json.load(fh)['dependencies'])

    def test_npm_failure(self):
        with self.assertRaises(setup_edit.Nothing):
            setup_edit.tools_install(self.ws, which=lambda n: '/x/' + n,
                                     run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, '', 'boom'))


RESUME_A = """Jordan Rivera
Senior Product Manager | Acme Robotics | Jan 2020 - Present
- Led a team of 5 managers and shipped the thing
Product Manager, Brightwater    2016 - 2019
Skills: Python
"""
RESUME_B = """Jordan Rivera
Senior Product Manager, Acme Robotics (2020 - 2023)
Associate Product Manager | Globex | 2014 - 2016
"""


class Resumes(Base):
    def test_titles_across_versions(self):
        d = os.path.join(self.tmp.name, 'resumes')
        os.makedirs(d)
        for n, t in (('a.txt', RESUME_A), ('b.md', RESUME_B)):
            with open(os.path.join(d, n), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(t)
        done = setup.add_resume_versions(self.ws, [d])
        self.assertEqual([w for _, w in done], ['added', 'added'])
        rows = setup_edit.title_table(setup.resume_versions(self.ws))
        self.assertEqual(rows[0][:2], (2, 'Senior Product Manager'))
        titles = [r[1] for r in rows]
        self.assertIn('Product Manager', titles)
        self.assertIn('Associate Product Manager', titles)
        self.assertNotIn('Acme Robotics', titles)
        r = gmh('setup', 'resumes', '--titles', '--workspace', self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Senior Product Manager', r.stdout)

    def test_pdf_uses_pdftotext(self):
        pdf = os.path.join(self.tmp.name, 'r.pdf')
        with open(pdf, 'wb') as fh:
            fh.write(b'%PDF-')
        fake = subprocess.CompletedProcess([], 0, RESUME_A.encode('utf-8'), b'')
        with mock.patch('shutil.which', return_value='/usr/bin/pdftotext'), \
                mock.patch('subprocess.run', return_value=fake) as run:
            out = setup.add_resume_versions(self.ws, [pdf])
        self.assertEqual(out[0][1], 'added')
        self.assertEqual(run.call_args[0][0], ['/usr/bin/pdftotext', '-layout', pdf, '-'])

    def test_pdf_without_pdftotext(self):
        pdf = os.path.join(self.tmp.name, 'r.pdf')
        with open(pdf, 'wb') as fh:
            fh.write(b'%PDF-')
        with mock.patch('shutil.which', return_value=None), self.assertRaises(SystemExit) as c:
            setup.add_resume_versions(self.ws, [pdf])
        self.assertIn('pdftotext', str(c.exception))

    def test_workspace_still_first_positional(self):
        self.assertEqual(setup_edit.resolve_resume_args([self.ws, 'a.txt']), (self.ws, ['a.txt']))
        self.assertEqual(setup_edit.resolve_resume_args(['a.txt'], self.ws), (self.ws, ['a.txt']))


class InitPackCheck(Base):
    def test_init_requires_pack(self):
        r = gmh('setup', 'init', os.path.join(self.tmp.name, 'w2'))
        self.assertEqual(r.returncode, 2)
        self.assertIn('--pack', r.stderr)

    def test_no_fallback_pack(self):
        with self.assertRaises(SystemExit) as c:
            setup._no_pack()
        self.assertIn('pick one', str(c.exception))

    def test_check_resume_keys_and_tools_hint(self):
        cfg = self.cfg()
        cfg['resume'] = {'_layout_note': 'x', 'pages': 2, 'weird': 1}
        self.write('config.json', json.dumps(cfg))
        rep = setup.check(self.ws)
        self.assertEqual(rep['resume_keys']['unknown'], ['weird'])
        self.assertIn('max_pages', rep['resume_keys']['missing'])
        self.assertNotIn('pages', rep['resume_keys']['missing'])
        text = setup.format_check(rep)
        self.assertIn('unknown key(s)', text)
        self.assertIn('layout rules not set', text)
        cfg['paths'] = {'node_modules': os.path.join(self.tmp.name, 'none')}
        from engine import resume  # the plugin's own tools/node_modules may be installed on this machine
        with mock.patch.object(resume, 'TOOLS_MODULES', os.path.join(self.tmp.name, 'none2')):
            self.assertTrue(any('gmh setup tools' in p for p in setup.tools_problems(cfg, self.ws)))


class TermCount(unittest.TestCase):
    def test_range_enforced_before_writing(self):
        from engine import packs
        base = {'terms': ['a'] * 5}
        with mock.patch.object(setup, '_unapproved_pack', return_value=('p', {'name': 'x', 'titles': {}})), \
                mock.patch.object(setup, '_read_json', return_value={}), \
                mock.patch.object(setup, 'resume_text', return_value='resume'), \
                mock.patch.object(packs, 'check_catalog', return_value=(base, {'strengths': [], 'gaps': [], 'terms': []})), \
                mock.patch.object(packs, 'validate', side_effect=lambda x: x), \
                mock.patch.object(setup, '_dump') as dump:
            with self.assertRaises(SystemExit) as c:
                setup.pack_catalog('/nonexistent', '/p.json', term_range=setup.TERM_RANGE)
            self.assertIn('5 terms', str(c.exception))
            dump.assert_not_called()


if __name__ == '__main__':
    unittest.main()
