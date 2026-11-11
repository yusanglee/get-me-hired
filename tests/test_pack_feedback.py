"""pack-feedback (proposals from past reviews and reads) and pack-sample --from-stored, on a fictional workspace
(Jordan Rivera, UX research). No network."""
import csv, datetime, hashlib, io, json, os, re, shutil, sys, tempfile, time, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import pack_feedback, packs, setup  # noqa: E402
from engine.runrecord import PICK_MARK, REVIEWED_COLUMNS  # noqa: E402

TODAY = datetime.date(2026, 10, 29)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def reviewed(ws, date, rows):
    p = os.path.join(ws, 'Pipeline', 'queue', f'reviewed-{date}.csv')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEWED_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in REVIEWED_COLUMNS})


def read(ws, rid, **kw):
    row = dict(id=rid, gap_type='none', top_gap='', gap_quote='', strengths=[], needs=[], read_at='2026-10-28T09:00:00')
    row.update(kw)
    write(os.path.join(ws, 'Pipeline', 'state', 'reads', rid + '.json'), json.dumps(row))


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix='gmh-fb-')
        self.addCleanup(shutil.rmtree, self.ws, True)
        pack, _ = packs.new_pack('ux-research', 'UX Research', ['UX Researcher'])
        pack['strengths'] = [{'label': 'usability testing', 'pattern': 'usability testing', 'weight': 4}]
        pack['gaps'] = [{'label': 'statistics', 'pattern': 'statistic', 'weight': 6}]
        setup._dump(os.path.join(self.ws, 'pack.json'), pack)
        self.pack = pack

    def digest(self):
        return {f: hashlib.sha1(open(os.path.join(self.ws, f), 'rb').read()).hexdigest()
                for f in ('pack.json', 'pack-base.json') if os.path.exists(os.path.join(self.ws, f))}


class Feedback(Base):
    def seed(self):
        rows = lambda *xs: [dict(call='apply', company=c, title='UX Researcher', id=i, gap_type=g, top_gap=t) for i, c, g, t in xs]
        reviewed(self.ws, '2026-10-20', rows(('gh-brightwater-1', 'Brightwater', 'major', 'Healthcare research experience'),
                                             ('gh-northwind-2', 'Northwind', 'critical', 'healthcare research experience'),
                                             ('gh-fieldnote-3', 'Fieldnote', 'minor', 'Statistics')))
        reviewed(self.ws, '2026-10-21', rows(('gh-brightwater-1', 'Brightwater', 'minor', 'Healthcare research experiences'),  # same role again
                                             ('gh-lakeside-4', 'Lakeside', 'major', 'Experience with eye tracking'),
                                             ('gh-lakeside-5', 'Lakeside', 'none', 'ignored')))
        read(self.ws, 'gh-harbor-6', gap_type='major', top_gap='eye tracking experience', gap_quote='Experience with eye tracking required',
             strengths=[{'label': 'Diary studies', 'level': 'excellent', 'resume': 'r', 'posting': 'Run diary studies'},
                        {'label': 'usability testing', 'level': 'strong', 'resume': 'r', 'posting': 'usability testing'}])
        read(self.ws, 'gh-brightwater-1', strengths=[{'label': 'diary study', 'level': 'strong', 'resume': 'r', 'posting': 'diary studies'}])
        read(self.ws, 'gh-northwind-2', strengths=[{'label': 'diary studies', 'level': 'strong', 'resume': 'r', 'posting': 'diary'}])
        write(os.path.join(self.ws, 'Pipeline', 'state', 'jd', 'gh-harbor-6.txt'), 'UX Researcher\nHarbor Labs\nRemote\nhttp://x\n\ntext')

    def test_groups_drops_covered_and_proposes(self):
        self.seed()
        prop, stats = pack_feedback.propose(self.ws, today=TODAY)
        gaps = {e['label']: e for e in prop['gaps']}
        hc = next(e for k, e in gaps.items() if k.startswith('healthcare'))
        self.assertEqual(hc['weight'], 10)  # one role critical
        self.assertIn('in 2 roles: 1 critical, 1 major', hc['_evidence'])  # Brightwater counted once (worst of its two rows)
        self.assertTrue(re.search(hc['pattern'], 'healthcare research experience'))
        eye = next(e for k, e in gaps.items() if 'eye' in k)
        self.assertEqual((eye['weight'], len(eye['_examples'])), (6, 2))
        self.assertIn('Harbor Labs: UX Researcher', ' '.join(eye['_examples']))
        self.assertIn('Experience with eye tracking required', ' '.join(eye['_examples']))
        self.assertFalse([k for k in gaps if 'statistic' in k])  # pack.json already has it (and only 1 role anyway)
        self.assertEqual([s['label'] for s in prop['strengths']], ['diary studies'])  # usability testing is covered
        self.assertEqual(prop['strengths'][0]['weight'], 3)  # one excellent of three roles
        self.assertEqual((prop['title_gaps'], prop['terms'], prop['exclude']), ([], [], []))

    def test_excellent_strength_weight(self):
        for i in (1, 2, 3):
            read(self.ws, f'r-{i}', strengths=[{'label': 'survey design', 'level': 'excellent' if i < 3 else 'strong',
                                                'resume': 'r', 'posting': 'survey design'}])
        prop, _ = pack_feedback.propose(self.ws, today=TODAY)
        self.assertEqual((prop['strengths'][0]['weight'], prop['strengths'][0]['_evidence'][:33]),
                         (4, 'in 3 roles: 2 excellent, 1 strong'))

    def test_covered_gap_and_minimum(self):
        self.seed()
        pack = dict(self.pack, gaps=self.pack['gaps'] + [{'label': 'eye', 'pattern': 'eye tracking', 'weight': 6}])
        setup._dump(os.path.join(self.ws, 'pack.json'), pack)
        prop, stats = pack_feedback.propose(self.ws, today=TODAY)
        self.assertFalse([e for e in prop['gaps'] if 'eye' in e['label']])
        self.assertTrue([r for r in stats['repeats_covered'] if 'eye' in r[1]])
        prop, _ = pack_feedback.propose(self.ws, min_roles=3, today=TODAY)
        self.assertEqual(prop['gaps'], [])
        setup._dump(os.path.join(self.ws, 'pack-base.json'),  # pack-base.json counts too
                    dict(self.pack, gap_catalog=[{'label': 'hc', 'pattern': 'healthcare', 'weight': 8}]))
        prop, _ = pack_feedback.propose(self.ws, today=TODAY)
        self.assertFalse([e for e in prop['gaps'] if 'healthcare' in e['label']])

    def test_pass_notes_and_days(self):
        pick = lambda i, note: dict(call='pass', company='Brightwater', title='UX Researcher', id=i,
                                    notes=f'stage 2b text; {PICK_MARK} (tier A): {note}')
        reviewed(self.ws, '2026-10-01', [pick('a-1', 'wants a PhD'), dict(call='apply', id='a-9', notes=f'{PICK_MARK} (tier A): wants a PhD')])
        reviewed(self.ws, '2026-10-27', [pick('a-2', 'wants a PhD'), pick('a-3', 'on-site only')])
        prop, _ = pack_feedback.propose(self.ws, today=TODAY)
        self.assertEqual([e['label'] for e in prop['gaps']], ['wants a phd'])
        self.assertIn('in 2 roles', prop['gaps'][0]['_evidence'])
        prop, _ = pack_feedback.propose(self.ws, days=7, today=TODAY)  # the October 1 file is out
        self.assertEqual(prop['gaps'], [])

    def test_days_uses_read_at(self):
        read(self.ws, 'r-1', gap_type='major', top_gap='eye tracking', read_at='2026-09-01T00:00:00')
        read(self.ws, 'r-2', gap_type='major', top_gap='eye tracking', read_at='2026-10-28T00:00:00')
        self.assertEqual(len(pack_feedback.propose(self.ws, min_roles=1, today=TODAY)[0]['gaps']), 1)
        self.assertEqual(len(pack_feedback.propose(self.ws, today=TODAY)[0]['gaps']), 1)  # both roles, one group
        self.assertEqual(pack_feedback.propose(self.ws, days=14, today=TODAY)[0]['gaps'], [])  # one role left: under the minimum

    def test_nothing_stored(self):
        prop, stats = pack_feedback.propose(self.ws, today=TODAY)
        self.assertEqual((prop['gaps'], prop['strengths'], stats['roles']), ([], [], 0))
        self.assertIn('Nothing new', pack_feedback.describe(prop, stats))

    def test_cli_leaves_pack_files_alone_and_proposal_passes_catalog(self):
        self.seed()
        setup._dump(os.path.join(self.ws, 'pack-base.json'), self.pack)
        before = self.digest()
        out = io.StringIO()
        with redirect_stdout(out):
            setup.main(['pack-feedback', self.ws])
        self.assertEqual(self.digest(), before)
        self.assertIn('pack.json is unchanged', out.getvalue())
        self.assertIn('healthcare', out.getvalue())
        prop = json.load(open(os.path.join(self.ws, 'pack-sample', 'proposal-feedback.json'), encoding='utf-8'))
        prop['gaps'] = [e for e in prop['gaps'] if 'healthcare' in e['label']]  # keep what the sample shows
        prop['strengths'] = [e for e in prop['strengths'] if 'diary' in e['label']]
        sample = [{'title': 'UX Researcher', 'text': 'Requirements\n- Healthcare research experience\n- diary studies\n\nBenefits'}]
        base, report = packs.check_catalog(packs.validate(dict(self.pack)), prop, sample, 'diary studies')
        self.assertEqual((len(base['gap_catalog']), len(base['strength_catalog'])), (1, 1))


class FromStored(Base):
    def jd(self, name, title, company, age_days, text='Requirements\n- usability testing'):
        p = os.path.join(self.ws, 'Pipeline', 'state', 'jd', name + '.txt')
        write(p, f'{title}\n{company}\nRemote\nhttps://example.com/{name}\n\n{text}')
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))

    def test_stored_sample(self):
        self.jd('gh-a-1', 'Senior UX Researcher', 'Brightwater', 1)
        self.jd('gh-a-2', 'UX Researcher II', 'Brightwater', 5)
        self.jd('gh-b-3', 'UX Researcher', 'Northwind', 20)
        self.jd('gh-b-4', 'UX Designer', 'Northwind', 2)  # not the user's title
        self.jd('gh-c-5', 'User Experience Research Lead', 'Harbor', 2)  # shares the "research" stem; the pack rejects it
        found = setup.stored_postings(self.ws)
        self.assertEqual([p['id'] for p in found['sample']], ['gh-a-1', 'gh-a-2', 'gh-b-3'])  # newest first
        self.assertEqual(found['sample'][0]['company'], 'Brightwater')
        self.assertEqual(found['per_title'], [('UX Researcher', 3)])
        self.assertEqual([t for t, _ in found['near']], ['User Experience Research Lead'])
        self.assertEqual([p['id'] for p in setup.stored_postings(self.ws, days=7)['sample']], ['gh-a-1', 'gh-a-2'])
        self.assertEqual(len(setup.stored_postings(self.ws, max_n=2)['sample']), 2)

    def test_vault_outside_the_workspace(self):
        vault = tempfile.mkdtemp(prefix='gmh-vault-')
        self.addCleanup(shutil.rmtree, vault, True)
        write(os.path.join(self.ws, 'config.json'), json.dumps({'paths': {'vault': vault}}))
        p = os.path.join(vault, 'Pipeline', 'state', 'jd', 'gh-a-1.txt')
        write(p, 'UX Researcher\nBrightwater\nRemote\nhttps://example.com/a\n\nRequirements\n- usability testing')
        self.assertEqual([x['id'] for x in setup.stored_postings(self.ws)['sample']], ['gh-a-1'])
        reviewed(vault, '2026-10-27', [dict(id='gh-a-1', company='Brightwater', title='UX Researcher', call='pass',
                                            gap_type='critical', top_gap='healthcare domain')])
        gaps, _, _ = pack_feedback.collect(self.ws, today=TODAY)
        self.assertEqual([g['phrase'] for g in gaps], ['healthcare domain'])

    def test_pack_sample_from_stored_writes_same_files(self):
        self.jd('gh-a-1', 'UX Researcher', 'Brightwater', 1)
        self.jd('gh-b-2', 'UX Researcher', 'Northwind', 2, 'Requirements\n- diary studies')
        write(os.path.join(self.ws, 'master-resume.md'), 'Diary studies and usability testing.\n')
        setup.pack_sample(self.ws, from_stored=True)
        d = os.path.join(self.ws, 'pack-sample')
        sample = json.load(open(os.path.join(d, 'sample.json'), encoding='utf-8'))
        self.assertEqual([s['source'] for s in sample], ['stored', 'stored'])
        self.assertIn('## Near misses', open(os.path.join(d, 'evidence.md'), encoding='utf-8').read())
        self.assertEqual(setup.pack_seed(self.ws)[2], 2)

    def test_cli_says_near_misses_empty(self):
        self.jd('gh-a-1', 'UX Researcher', 'Brightwater', 1)
        write(os.path.join(self.ws, 'master-resume.md'), 'Usability testing.\n')
        out = io.StringIO()
        with redirect_stdout(out):
            setup.main(['pack-sample', self.ws, '--from-stored', '--days', '30'])
        self.assertIn('1 sample postings', out.getvalue())
        self.assertIn('No near-miss titles', out.getvalue())


if __name__ == '__main__':
    unittest.main()
