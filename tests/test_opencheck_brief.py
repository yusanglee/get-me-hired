"""gmh review open-check (engine/opencheck.py) and gmh redline brief/put (engine/redline.py). Fictional data, no network."""
import contextlib, csv, io, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import opencheck, redline  # noqa: E402

UUID = '3f2a9c10-1b2d-4e5f-8a9b-0c1d2e3f4a5b'


def board(*ids):
    return [{'id': i, 'url': f'https://jobs.example.com/{i}', 'apply_url': ''} for i in ids]


def row(rid, company='Brightwater', title='Product Manager', url=''):
    return dict(id=rid, company=company, title=title, url=url, call='apply')


class OpenCheck(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def fake(self, ats, boards):
        def fn(slug, company=''):
            self.calls.append((ats, slug))
            b = boards.get(slug)
            if isinstance(b, Exception):
                raise b
            return b
        return fn

    def adapters(self, **boards):
        return {a: self.fake(a, boards.get(a, {})) for a in ('greenhouse', 'lever', 'ashby')}

    def test_open_and_closed_with_one_fetch_per_board(self):
        ad = self.adapters(greenhouse={'brightwater': board('gh-brightwater-11', 'gh-brightwater-12')})
        res = opencheck.open_check([row('gh-brightwater-11'), row('gh-brightwater-99'), row('gh-brightwater-12')], ad)
        self.assertEqual([r['status'] for r in res], ['open', 'closed', 'open'])
        self.assertEqual(self.calls, [('greenhouse', 'brightwater')])

    def test_open_by_posting_url_when_id_differs(self):
        ad = self.adapters(greenhouse={'brightwater': [{'id': 'gh-brightwater-5', 'url': 'https://boards.greenhouse.io/brightwater/jobs/7/'}]})
        r = row('gh-brightwater-7', url='https://boards.greenhouse.io/brightwater/jobs/7?gh_src=x')
        self.assertEqual(opencheck.open_check([r], ad)[0]['status'], 'open')

    def test_unknown_when_not_an_ats_posting(self):
        for rid in ('li-12345', 'wd-acme-77', ''):
            res = opencheck.open_check([row(rid)], self.adapters())[0]
            self.assertEqual(res['status'], 'unknown', rid)
            self.assertIn('check by hand', res['reason'])
        self.assertEqual(self.calls, [])

    def test_unknown_when_adapter_raises_or_has_no_board(self):
        ad = self.adapters(greenhouse={'brightwater': RuntimeError('boom')})
        res = opencheck.open_check([row('gh-brightwater-1'), row('lv-gone-' + UUID)], ad)
        self.assertEqual([r['status'] for r in res], ['unknown', 'unknown'])
        self.assertIn("couldn't read", res[0]['reason'])

    def test_hyphenated_slugs_and_uuid_ids(self):
        rid = f'ab-bright-line-labs-{UUID}'
        ad = self.adapters(ashby={'bright-line-labs': board(rid)}, lever={'acme-robotics': board(f'lv-acme-robotics-{UUID}')},
                           greenhouse={'acme-robotics': board('gh-acme-robotics-42')})
        res = opencheck.open_check([row(rid), row(f'lv-acme-robotics-{UUID}'), row('gh-acme-robotics-42')], ad)
        self.assertEqual([r['status'] for r in res], ['open'] * 3)

    def test_slug_from_url_then_cache(self):
        rid = 'gh-oddname-5'  # the id's slug guess is wrong; the url and the cache know better
        ad = self.adapters(greenhouse={'real-slug': board(rid)})
        r = row(rid, url='https://job-boards.greenhouse.io/real-slug/jobs/5')
        self.assertEqual(opencheck.open_check([r], ad)[0]['status'], 'open')
        ad = self.adapters(greenhouse={'real-slug': board(rid)})
        res = opencheck.open_check([row(rid, company='Odd Name')], ad, {'odd name': ['greenhouse', 'real-slug']})
        self.assertEqual(res[0]['status'], 'open')

    def test_picks_line_uses_run_refs(self):
        res = [dict(id='gh-a-1', status='closed'), dict(id='gh-b-2', status='open'), dict(id='gh-c-3', status='closed'),
               dict(id='gh-d-4', status='closed')]
        rec = {'roles': [{'id': 'gh-a-1', 'ref': 3}, {'id': 'gh-b-2', 'ref': 4}], 'dropped': [{'id': 'gh-c-3', 'ref': 'd12'}]}
        self.assertEqual(opencheck.picks_line(res, rec), 'gmh review picks "pass 3 d12: closed"')
        self.assertEqual(opencheck.picks_line([dict(id='gh-b-2', status='open')], rec), '')
        full = [dict(r, company='X', title='T', reason='') for r in res[:3]]
        self.assertEqual(opencheck.lines(full, rec)[-1], 'gmh review picks "pass 3 d12: closed"')


FACTS = 'At Brightwater I grew weekly active users 40% and launched Brightwater Rewards.'


class BriefAndPut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = os.path.join(self.tmp.name, 'ws')
        P = os.path.join(self.ws, 'Pipeline')
        for d in ('specs', 'queue', os.path.join('state', 'jd')):
            os.makedirs(os.path.join(P, d))
        json.dump({'paths': {'vault': self.ws}}, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(self.ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n').write(FACTS)
        json.dump({'id': 'gh-northwind-9', 'company': 'Northwind', 'title': 'Loyalty PM'},
                  open(os.path.join(P, 'specs', 'northwind-pm.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(P, 'state', 'jd', 'gh-northwind-9.txt'), 'w', encoding='utf-8', newline='\n').write('Grow a loyalty program.')
        cols = ['call', 'gap_type', 'top_gap', 'company', 'summary_variant', 'lead_material', 'id']
        for d, lead in (('2026-10-27', 'old lead'), ('2026-10-28', 'Brightwater Rewards launch')):
            with open(os.path.join(P, 'queue', f'reviewed-{d}.csv'), 'w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, cols)
                w.writeheader()
                w.writerow(dict(call='apply', gap_type='major', top_gap='no payments background', company='Northwind',
                                summary_variant='loyalty', lead_material=lead, id='gh-northwind-9'))
        self.drafts = os.path.join(self.tmp.name, 'drafts.json')

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            redline.main([*args, '--workspace', self.ws])
        text = out.getvalue()
        if args[0] in ('brief', 'packet'):  # these print the path of the file they wrote
            self.last_path = text.strip()
            return json.load(open(self.last_path, encoding='utf-8'))
        return json.loads(text)

    def test_brief_has_lead_but_never_a_gap(self):
        b = self.run_cli('brief', self.drafts, 'northwind-pm', '--question', 'Why Northwind?')
        self.assertEqual(b['role'], {'company': 'Northwind', 'title': 'Loyalty PM'})
        self.assertEqual(b['lead'], {'summary_variant': 'loyalty', 'lead_material': 'Brightwater Rewards launch'})
        self.assertEqual(b['questions'], ['Why Northwind?'])
        self.assertEqual(b['facts'], FACTS)
        self.assertIn('Grow a loyalty program.', b['posting'])
        self.assertEqual(set(b), {'role', 'ai_policy', 'rules', 'facts', 'posting', 'questions', 'lead', 'return_format'})
        blob = json.dumps(b)
        for banned in ('gap_type', 'top_gap', 'no payments background'):
            self.assertNotIn(banned, blob)
        self.assertFalse(os.path.exists(self.drafts))

    def test_draft_rules_drop_only_reviewer_rules(self):
        self.assertEqual(len(redline.DRAFT_RULES), len(redline.RULES) - 2)
        self.assertFalse(any('old_string' in r or r.startswith('Flag any claim') for r in redline.DRAFT_RULES))
        self.assertTrue(any('volunteer a gap' in r for r in redline.DRAFT_RULES))

    def test_put_creates_file_keeps_other_slugs_and_shows_checks(self):
        reply = os.path.join(self.tmp.name, 'reply.json')
        json.dump({'cover': ['I grew weekly active users 40% — fast.'], 'answers': {'Why Northwind?': 'Loyalty.'}, 'notes': 'x'},
                  open(reply, 'w', encoding='utf-8', newline='\n'))
        out = self.run_cli('put', self.drafts, 'northwind-pm', reply)
        self.assertEqual([c['problem'] for c in out['rule_checks']], ['em or en dash'])
        self.assertEqual(json.load(open(self.drafts, encoding='utf-8')),
                         {'northwind-pm': {'cover': ['I grew weekly active users 40% — fast.'], 'answers': {'Why Northwind?': 'Loyalty.'}}})
        d = json.load(open(self.drafts, encoding='utf-8'))
        d['other'] = {'cover': ['keep']}
        json.dump(d, open(self.drafts, 'w', encoding='utf-8', newline='\n'))
        json.dump({'cover': ['Clean.'], 'answers': {}}, open(reply, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(self.run_cli('put', self.drafts, 'northwind-pm', reply)['rule_checks'], [])
        d = json.load(open(self.drafts, encoding='utf-8'))
        self.assertEqual((d['other'], d['northwind-pm']['cover']), ({'cover': ['keep']}, ['Clean.']))
        self.assertNotIn('drafts.json.tmp', os.listdir(self.tmp.name))


if __name__ == '__main__':
    unittest.main()
