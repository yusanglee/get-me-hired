"""gmh specs brief / check-entry: the resume tailor's packet (never a gap field) and the role-entry check."""
import contextlib, io, json, os, shutil, tempfile, unittest

from engine import specs, stages

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'workspace')
GAPS = {'gap_type': 'GAPTYPE-zq', 'top_gap': 'TOPGAP-zq', 'gap_quote': 'GAPQUOTE-zq', 'gap_note': 'GAPNOTE-zq'}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.ws, self.vault = os.path.join(self.d, 'ws'), os.path.join(self.d, 'vault')
        shutil.copytree(os.path.join(FIX, 'resume'), os.path.join(self.ws, 'resume'))
        json.dump({'paths': {'vault': self.vault}}, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(self.ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write('identity:\n  first_name: Jordan\n  last_name: Rivera\n  email: jordan@example.com\n')
        self.P = os.path.join(self.vault, 'Pipeline')
        for sub in ('queue', 'state/jd', 'state/reads'):
            os.makedirs(os.path.join(self.P, sub))
        cols = ['id', 'company', 'title', 'call', 'summary_variant', 'template_script', 'lead_material', *GAPS]
        for day, lead in (('2026-10-20', 'old lead'), ('2026-10-21', 'Board prep story')):
            with open(os.path.join(self.P, 'queue', f'reviewed-{day}.csv'), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(','.join(cols) + '\n')
                fh.write(','.join(['gh-brightwater-123', 'Brightwater', 'Chief of Staff ', 'apply', 'ops', 'Ops', lead,
                                   *GAPS.values()]) + '\n')
        open(os.path.join(self.P, 'state', 'jd', 'gh-brightwater-123.txt'), 'w', encoding='utf-8', newline='\n').write('posting')
        json.dump({'id': 'gh-brightwater-123', 'needs': ['board prep'], 'concerns': 'CONCERN-zq',
                   'strengths': [{'label': 'planning', 'level': 'strong', 'resume': 'r', 'posting': 'p'}], **GAPS},
                  open(os.path.join(self.P, 'state', 'reads', 'gh-brightwater-123.json'), 'w', encoding='utf-8', newline='\n'))

    def brief(self, **kw):
        return specs.brief(self.ws, self.P, 'gh-brightwater-123', **kw)


class Brief(Fixture):
    def test_packet(self):
        b = self.brief()
        self.assertEqual(b['role'], {'id': 'gh-brightwater-123', 'company': 'Brightwater', 'title': 'Chief of Staff'})
        self.assertTrue(b['posting_path'].replace(os.sep, '/').endswith('state/jd/gh-brightwater-123.txt'))
        self.assertEqual(b['read']['needs'], ['board prep'])
        self.assertEqual(b['read']['strengths'][0]['label'], 'planning')
        ops = b['templates']['Ops']
        self.assertEqual(ops['experience'][1]['id'], 'acme')
        self.assertEqual(ops['experience'][1]['bullets'], ['Led the annual planning process across **6 business units**'])
        self.assertIn('MNA', b['bank']['bullets'])
        self.assertEqual(b['bank']['skill_sets'], {'core': ['Operating Cadence', 'OKRs']})
        self.assertEqual(b['bank']['bio_prefix'], 'Chief of Staff  ·  ')
        self.assertEqual(b['materials'], {'summary_variant': 'ops', 'template_script': 'Ops', 'lead_material': 'Board prep story'})
        self.assertEqual(set(b['return_format']), {'spec', 'notes', 'missing', 'material_feedback'})
        self.assertEqual(b['bios'], ['Operating Cadence & Strategy'])
        self.assertIn('template:Ops', b['summaries'])
        self.assertTrue(any('at most 1' in r for r in b['rules']))

    def test_date_picks_the_file(self):
        self.assertEqual(self.brief()['materials']['lead_material'], 'Board prep story')
        self.assertEqual(self.brief(date='2026-10-20')['materials']['lead_material'], 'old lead')
        with self.assertRaises(specs.SpecError):
            self.brief(date='2026-10-19')

    def test_no_read_and_unknown_id(self):
        os.remove(os.path.join(self.P, 'state', 'reads', 'gh-brightwater-123.json'))
        self.assertEqual(self.brief()['read'], {'needs': [], 'strengths': []})
        with self.assertRaises(specs.SpecError):
            specs.brief(self.ws, self.P, 'nope')
        self.assertEqual(specs.safe_id('a/b c:1'), 'a_b_c_1')

    def test_no_gap_text_anywhere(self):
        text = json.dumps(self.brief())
        for v in [*GAPS.values(), 'CONCERN-zq']:
            self.assertNotIn(v, text)
        for k in ('gap_type', 'top_gap', 'gap_quote', 'concerns'):
            self.assertNotIn(k, text)

    def test_example_is_a_valid_entry(self):
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        self.assertEqual(specs.check_entry(specs.ROLE_ENTRY['example'], t, bank), [])
        for k in specs.ROLE_ENTRY['example']:
            self.assertIn(k + ':', specs.__doc__)


class Check(Fixture):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                stages.main(['--workspace', self.ws, *args])
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def test_problems(self):
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        ok = dict(id='x', slug='X', template='Ops')
        self.assertEqual(specs.check_entry(ok, t, bank), [])
        self.assertIn('missing', specs.check_entry({'id': 'x'}, t, bank)[0])
        self.assertIn('unknown bullet', specs.check_entry({**ok, 'experience': {'acme': ['NOPE']}}, t, bank)[0])
        self.assertIn('not approved', specs.check_entry({**ok, 'skills': ['Juggling']}, t, bank)[0])
        self.assertEqual(specs.check_entry([], t, bank), ['entry must be an object'])

    def test_cli(self):
        code, out = self.run_cli('specs', 'brief', 'gh-brightwater-123')
        self.assertEqual(code, 0)
        with open(out.strip(), encoding='utf-8') as fh:  # v1.0: the packet goes to a file; the path is printed
            self.assertEqual(json.load(fh)['role']['company'], 'Brightwater')
        code, out = self.run_cli('specs', 'brief', 'gh-brightwater-123', '--out', '-')
        self.assertEqual(json.loads(out)['role']['company'], 'Brightwater')
        p = os.path.join(self.d, 'e.json')
        json.dump(specs.ROLE_ENTRY['example'], open(p, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(self.run_cli('specs', 'check-entry', p), (0, 'ok\n'))
        json.dump({'id': 'x', 'slug': 'X', 'template': 'Nope'}, open(p, 'w', encoding='utf-8', newline='\n'))
        code, out = self.run_cli('specs', 'check-entry', p)
        self.assertEqual(code, 1)
        self.assertIn('unknown template', out)

    def test_batch_form_still_runs(self):
        os.makedirs(os.path.join(self.P, 'specs'))  # the one-time snapshot needs a stage folder to copy
        batch = os.path.join(self.d, 'b.json')
        json.dump({'date': '2026-10-21', 'roles': [{**specs.ROLE_ENTRY['example'], 'company': 'Brightwater', 'title': 'CoS'}]},
                  open(batch, 'w', encoding='utf-8', newline='\n'))
        code, out = self.run_cli('specs', batch)
        self.assertEqual(code, 0)
        self.assertIn('1 specs', out)
        self.assertTrue(os.path.exists(os.path.join(self.P, 'specs', 'Brightwater-Ops.json')))


if __name__ == '__main__':
    unittest.main()
