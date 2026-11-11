"""gmh materials: tailor notes -> candidates -> drafter proposals -> one-by-one approval into the bank and templates.
Fictional workspace (Jordan Rivera at Example Health and Acme Logistics). No network."""
import datetime, json, os, shutil, tempfile, unittest

from engine import materials as M, setup, specs

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'workspace')
NOW = datetime.datetime(2026, 11, 3, 18, 0)
MASTER = """# Jordan Rivera

## Example Health, Chief of Staff to the CEO (2021-2026)
- Ran the weekly operating review for 12 executives
- Managed a team of 4 analysts and coached one into a director role
- Launched the company OKR program across 9 departments in one quarter

## Acme Logistics, Strategy Manager (2016-2021)
- Led the annual planning process across 6 business units
- Built the pricing model adopted for every new enterprise contract
"""
LINE_TEAM = 'Managed a team of 4 analysts and coached one into a director role'
LINE_OKR = 'Launched the company OKR program across 9 departments in one quarter'
LINE_PRICE = 'Built the pricing model adopted for every new enterprise contract'


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix='gmh-materials-')
        self.addCleanup(shutil.rmtree, self.ws, True)
        shutil.copytree(os.path.join(FIX, 'resume'), os.path.join(self.ws, 'resume'))
        json.dump({}, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        open(os.path.join(self.ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n').write(MASTER)
        self.P = os.path.join(self.ws, 'Pipeline')
        for sub in ('state/reads', 'specs', 'queue'):
            os.makedirs(os.path.join(self.P, sub))
        self.tmp = os.path.join(self.ws, 'scratch')
        os.makedirs(self.tmp)

    def write(self, name, obj):
        p = os.path.join(self.tmp, name)
        json.dump(obj, open(p, 'w', encoding='utf-8', newline='\n'))
        return p

    def tailor(self, rid, missing=(), feedback=()):
        return M.save(self.ws, rid, self.write(f'tailor-{rid}.json', {
            'spec': {'id': rid, 'slug': rid, 'template': 'Ops'}, 'notes': 'n',
            'missing': list(missing), 'material_feedback': list(feedback)}), now=NOW)

    def cands(self):
        cs, ignored = M.candidates(self.ws, now=NOW)
        return {c.get('resume_line') or c.get('text') or c['key']: c for c in cs}, ignored

    def propose(self, *props):
        return M.propose(self.ws, self.write('reply.json', {'proposals': list(props), 'notes': ''}), now=NOW)

    def bank(self):
        return json.load(open(os.path.join(self.ws, 'resume', 'bank.json'), encoding='utf-8'))


class Candidates(Base):
    def test_sources_grouped_and_filtered(self):
        self.tailor('gh-brightwater-1', missing=[
            {'experience': 'examplehealth', 'fact': 'team', 'resume_line': LINE_TEAM},
            {'experience': 'examplehealth', 'fact': 'invented', 'resume_line': 'Ran a 200-person sales org'},
            {'experience': 'examplehealth', 'fact': 'covered', 'resume_line': 'Ran the weekly operating review for 12 executives'}],
            feedback=[{'kind': 'bio', 'template': 'Ops', 'issue': 'too ops-heavy for a platform role'}])
        self.tailor('gh-northwind-2', missing=[{'experience': 'examplehealth', 'resume_line': LINE_TEAM}],
                    feedback=[{'kind': 'bio', 'template': 'Ops', 'issue': 'no product angle'}])
        json.dump({'id': 'ab-corvid-3', 'read_at': NOW.isoformat(), 'strengths': [{'label': 'pricing', 'resume': LINE_PRICE}]},
                  open(os.path.join(self.P, 'state', 'reads', 'ab-corvid-3.json'), 'w', encoding='utf-8', newline='\n'))
        json.dump({'slug': 'Old', 'overrides': {'bio': 'Chief of Staff  ·  Strategy & Finance'}},
                  open(os.path.join(self.P, 'specs', 'Old.json'), 'w', encoding='utf-8', newline='\n'))
        cs, ignored = self.cands()
        self.assertEqual(cs[LINE_TEAM]['roles'], ['gh-brightwater-1', 'gh-northwind-2'])
        self.assertEqual(cs[LINE_TEAM]['kind'], 'bullet')
        self.assertEqual(cs[LINE_PRICE]['roles'], ['ab-corvid-3'])
        self.assertEqual(cs['bio:Ops']['issues'], ['too ops-heavy for a platform role', 'no product angle'])
        self.assertNotIn('Strategy & Finance', cs)  # sent bios are a list of their own, not drafter candidates
        self.assertEqual(M.sent_bio_list(self.ws), [(1, 'Strategy & Finance')])
        self.assertIn('1 bios already used', M.candidate_lines([], [], sent=1)[0])
        self.assertNotIn('Ran the weekly operating review for 12 executives', cs)  # a bullet already says it
        self.assertEqual(ignored, ['Ran a 200-person sales org'])
        self.assertEqual(list(cs.values())[0]['cid'], 'c1')  # most-asked first
        self.assertIn('bullets', M.candidate_lines(*M.candidates(self.ws, now=NOW))[0])

    def test_focus_on_a_days_picks(self):
        json.dump({'id': 'gh-picked-1', 'read_at': NOW.isoformat(), 'strengths': [{'label': 'pricing', 'resume': LINE_PRICE}]},
                  open(os.path.join(self.P, 'state', 'reads', 'gh-picked-1.json'), 'w', encoding='utf-8', newline='\n'))
        self.tailor('gh-other-2', missing=[{'experience': 'examplehealth', 'resume_line': LINE_TEAM}])
        with open(os.path.join(self.P, 'queue', 'reviewed-2026-11-04.csv'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('id,company,call\ngh-picked-1,Corvid,apply\ngh-other-2,Brightwater,pass\n')
        focus = M.queued_ids(self.ws, '2026-11-04')
        self.assertEqual(focus, {'gh-picked-1'})
        cs, _ = M.candidates(self.ws, now=NOW, focus=focus)
        self.assertEqual([c['resume_line'] for c in cs], [LINE_PRICE])  # only what today's picks asked for
        self.assertEqual(json.load(open(os.path.join(self.P, 'state', 'materials', 'candidates.json'), encoding='utf-8'))['focus'], ['gh-picked-1'])
        self.assertEqual(len(M.candidates(self.ws, now=NOW)[0]), 2)  # without focus, everything recent
        with self.assertRaises(M.MaterialError):
            M.queued_ids(self.ws, '2026-11-05')

    def test_old_notes_drop_out(self):
        M.save(self.ws, 'gh-old-1', self.write('t.json', {'spec': {'template': 'Ops'},
               'missing': [{'experience': 'acme', 'resume_line': LINE_PRICE}]}), now=NOW - datetime.timedelta(days=40))
        self.assertEqual(self.cands()[0], {})


class Proposals(Base):
    def setUp(self):
        super().setUp()
        self.tailor('gh-brightwater-1', missing=[{'experience': 'examplehealth', 'resume_line': LINE_TEAM},
                                                {'experience': 'examplehealth', 'resume_line': LINE_OKR}],
                    feedback=[{'kind': 'template', 'template': 'Ops', 'issue': 'lead with OKRs'}])
        self.cs = self.cands()[0]

    def cid(self, key):
        return self.cs[key]['cid']

    def test_checks_reject_invented_numbers_gaps_and_bad_sources(self):
        added, rejected = self.propose(
            {'candidate': self.cid(LINE_TEAM), 'kind': 'bullet', 'experience': 'examplehealth',
             'text': 'Managed **6 analysts**, coaching one into a director role', 'source': [LINE_TEAM]},
            {'candidate': self.cid(LINE_OKR), 'kind': 'bullet', 'experience': 'examplehealth',
             'text': 'Launched OKRs across **9 departments**, despite limited prior experience', 'source': [LINE_OKR]},
            {'candidate': 'c99', 'kind': 'bullet', 'experience': 'examplehealth', 'text': 'x', 'source': [LINE_OKR]},
            {'candidate': self.cid(LINE_OKR), 'kind': 'bullet', 'experience': 'nowhere',
             'text': 'Launched OKRs across **9 departments**', 'source': ['Not a line in the master resume at all']})
        self.assertEqual(added, [])
        probs = {i: ' '.join(p) for i, _, p in rejected}
        self.assertIn('numbers not in the source lines: 6', probs[0])
        self.assertIn('names a gap', probs[1])
        self.assertIn('unknown candidate', probs[2])
        self.assertIn('source not in the master resume', probs[3])
        self.assertIn('unknown experience', probs[3])

    def test_bullet_approved_with_edit_then_usable_by_the_tailor(self):
        added, rejected = self.propose({'candidate': self.cid(LINE_TEAM), 'kind': 'bullet', 'experience': 'examplehealth',
                                        'text': 'Managed **4 analysts** and coached one into a director role',
                                        'source': [LINE_TEAM]})
        self.assertEqual((added, rejected), (['p1'], []))
        self.assertIn('Managed **4 analysts**', '\n'.join(M.show_lines(self.ws)))
        with self.assertRaises(M.MaterialError):  # an edit that adds a number is checked again
            M.approve(self.ws, 'p1', text='Managed **5 analysts** and coached one into a director role', now=NOW)
        out = M.approve(self.ws, 'p1', text='Led **4 analysts** and coached one into a director role', now=NOW)
        self.assertIn('bullet examplehealth-m01', out)
        b = self.bank()['bullets']['examplehealth-m01']
        self.assertEqual((b['text'], b['proposal'], b['added']), ('Led **4 analysts** and coached one into a director role', 'p1', '2026-11-03'))
        self.assertTrue(os.listdir(os.path.join(self.ws, 'resume', '.history')))
        self.assertEqual(json.load(open(os.path.join(self.ws, 'resume', 'changes.json'), encoding='utf-8'))[0]['pid'], 'p1')
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        entry = {'id': 'x', 'slug': 'X', 'template': 'Ops', 'experience': {'examplehealth': ['OPS', 'examplehealth-m01']}}
        self.assertEqual(specs.check_entry(entry, t, bank), [])
        with self.assertRaises(M.MaterialError):
            M.approve(self.ws, 'p1', now=NOW)  # no longer pending
        self.assertNotIn(LINE_TEAM, self.cands()[0])  # proposed once, never again

    def test_reject_is_remembered(self):
        self.propose({'candidate': self.cid(LINE_OKR), 'kind': 'bullet', 'experience': 'examplehealth',
                      'text': 'Launched the OKR program across **9 departments** in one quarter', 'source': [LINE_OKR]})
        M.reject(self.ws, 'p1', 'not a story I tell', now=NOW)
        self.assertNotIn(LINE_OKR, self.cands()[0])
        self.assertEqual(M.pending_count(self.ws), 0)

    def test_bio_and_summary_become_approved_options(self):
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        entry = {'id': 'x', 'slug': 'X', 'template': 'Ops', 'bio': 'Operating Cadence & People Leadership'}
        self.assertIn('not an approved bio', specs.check_entry(entry, t, bank)[0])
        # bios and summaries need candidates: a sent bio and the template feedback
        json.dump({'slug': 'Old', 'overrides': {'bio': 'Chief of Staff  ·  Operating Cadence & People Leadership'}},
                  open(os.path.join(self.P, 'specs', 'Old.json'), 'w', encoding='utf-8', newline='\n'))
        json.dump({'slug': 'Old2', 'overrides': {'bio': 'Chief of Staff  ·  0-to-1 Programs & Strategy'}},
                  open(os.path.join(self.P, 'specs', 'Old2.json'), 'w', encoding='utf-8', newline='\n'))
        self.assertEqual([t for _, t in M.sent_bio_list(self.ws)],
                         ['0-to-1 Programs & Strategy', 'Operating Cadence & People Leadership'])
        with self.assertRaises(M.MaterialError):
            M.approve_bios(self.ws, '3')
        self.assertEqual(M.approve_bios(self.ws, 'all', reject_refs='1', now=NOW),
                         (['Operating Cadence & People Leadership'], ['0-to-1 Programs & Strategy']))
        self.assertEqual(M.sent_bio_list(self.ws), [])  # approved and turned down: neither comes back
        cs = self.cands()[0]
        added, rejected = self.propose(
            {'candidate': cs['template:Ops']['cid'], 'kind': 'summary', 'name': 'okr-builder',
             'text': 'Chief of staff who launched an OKR program across 9 departments in one quarter and ran the '
                     'weekly operating review for 12 executives.', 'source': [LINE_OKR, 'Ran the weekly operating review for 12 executives']})
        self.assertEqual(rejected, [])
        for pid in added:
            M.approve(self.ws, pid, now=NOW)
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        self.assertEqual(specs.check_entry(dict(entry, summary='bank:okr-builder'), t, bank), [])
        self.assertIn('Operating Cadence & People Leadership', bank['bios'])
        self.assertEqual(specs.check_entry(entry, t, bank), [])

    def test_reopen_undoes_a_rejection(self):
        self.propose({'candidate': self.cid(LINE_OKR), 'kind': 'bullet', 'experience': 'examplehealth',
                      'text': 'Launched the OKR program across **9 departments** in one quarter', 'source': [LINE_OKR]})
        with self.assertRaises(M.MaterialError):
            M.reopen(self.ws, 'p1')  # still pending
        M.reject(self.ws, 'p1', 'misclick', now=NOW)
        self.assertEqual(M.reopen(self.ws, 'p1', now=NOW), 'p1 is pending again')
        p = M.Ctx(self.ws).load_proposals()[0]
        self.assertEqual((p['status'], 'reason' in p), ('pending', False))
        self.assertEqual(M.pending_count(self.ws), 1)
        self.assertNotIn(LINE_OKR, self.cands()[0])  # still one proposal for that candidate
        M.approve(self.ws, 'p1', now=NOW)
        with self.assertRaises(M.MaterialError):
            M.reopen(self.ws, 'p1')  # approved: already in the bank
        with self.assertRaises(M.MaterialError):
            M.reopen(self.ws, 'p9')

    def test_reopen_fails_when_the_checks_no_longer_pass(self):
        self.propose({'candidate': self.cid(LINE_OKR), 'kind': 'bullet', 'experience': 'examplehealth',
                      'text': 'Launched the OKR program across **9 departments** in one quarter', 'source': [LINE_OKR]})
        M.reject(self.ws, 'p1', now=NOW)
        open(os.path.join(self.ws, 'master-resume.md'), 'w', encoding='utf-8', newline='\n').write('# Jordan Rivera\n- Something else entirely here\n')
        with self.assertRaises(M.MaterialError) as e:
            M.reopen(self.ws, 'p1')
        self.assertIn('no longer passes', str(e.exception))

    def test_reopen_bios(self):
        for i, bio in enumerate(('Strategy & Finance', 'Growth & Retention')):
            json.dump({'slug': f'S{i}', 'overrides': {'bio': 'Chief of Staff  ·  ' + bio}},
                      open(os.path.join(self.P, 'specs', f'S{i}.json'), 'w', encoding='utf-8', newline='\n'))
        M.reject_bios(self.ws, 'all')
        self.assertEqual(M.sent_bio_list(self.ws), [])
        self.assertEqual(M.rejected_bio_list(self.ws), ['Growth & Retention', 'Strategy & Finance'])
        self.assertEqual(M.reopen_bios(self.ws, 'growth & retention'), 1)
        self.assertEqual([t for _, t in M.sent_bio_list(self.ws)], ['Growth & Retention'])
        with self.assertRaises(M.MaterialError):
            M.reopen_bios(self.ws, 'Not A Bio')
        self.assertEqual(M.reopen_bios(self.ws, 'all'), 1)
        self.assertEqual(len(M.sent_bio_list(self.ws)), 2)

    def test_drafted_bio_may_say_0_to_1_but_no_other_numbers(self):
        c = M.Ctx(self.ws)
        ok = {'kind': 'bio', 'text': '0-to-1 Programs & Operating Cadence', 'source': [LINE_OKR]}
        self.assertEqual(M.check(ok, c), [])
        self.assertTrue(M.check(dict(ok, text='9 Departments & Operating Cadence'), c))
        self.assertEqual(M._refs('1,3-4', 5), [1, 3, 4])
        with self.assertRaises(M.MaterialError):
            M._refs('2-9', 5)

    def test_template_version(self):
        old_v = specs.template_version(specs.load_templates(self.ws)['Ops'])
        bad, _ = self.propose({'candidate': self.cid('template:Ops'), 'kind': 'template', 'base': 'Ops',
                               'changes': {'experience': {'examplehealth': ['OPS']}}})
        self.assertEqual(bad, [])  # must keep 2 bullets
        added, rejected = self.propose({'candidate': self.cid('template:Ops'), 'kind': 'template', 'base': 'Ops',
                                        'changes': {'experience': {'examplehealth': ['HIRE', 'OPS']},
                                                    'skills': ['OKRs', 'Operating Cadence']}, 'why': 'lead with OKRs'})
        self.assertEqual((added, rejected), (['p1'], []))
        with self.assertRaises(M.MaterialError):
            M.approve(self.ws, 'p1', text='anything', now=NOW)
        self.assertIn('v2', M.approve(self.ws, 'p1', now=NOW))
        doc = specs.load_templates(self.ws)['Ops']
        self.assertEqual(doc['version'], 2)
        self.assertEqual(doc['experience'][0]['bullets'][0], 'Hired and onboarded **9 executives** in 18 months')
        self.assertTrue(os.path.exists(os.path.join(self.ws, 'resume', 'templates', '.history', 'Ops@v1.json')))
        new_v = specs.template_version(doc)
        self.assertNotEqual(new_v, old_v)
        self.assertTrue(new_v.startswith('v2-'))
        spec = specs.make_spec({'id': 'x', 'slug': 'X', 'template': 'Ops'}, specs.load_templates(self.ws),
                               specs.load_bank(self.ws), date='2026-11-03', row={'company': 'Brightwater', 'title': 'CoS'})
        self.assertEqual(spec['template_version'], new_v)
        self.assertEqual(sorted(specs.load_templates(self.ws)), ['Ops'])  # .history isn't a template

    def test_brief_packet(self):
        b = M.brief(self.ws, now=NOW)
        self.assertEqual(b['facts_path'], os.path.join(self.ws, 'master-resume.md'))
        self.assertEqual({c['cid'] for c in b['candidates']}, set(self.cs[k]['cid'] for k in self.cs))
        self.assertEqual(b['templates']['Ops']['experience']['examplehealth'], ['OPS', 'BRD'])
        self.assertEqual(b['bios'], ['Operating Cadence & Strategy'])
        self.assertIn('proposals', b['return_format'])


class ResumeApproveKeepsMaterials(unittest.TestCase):
    def test_bank_rebuild_keeps_approved_additions(self):
        ws = tempfile.mkdtemp(prefix='gmh-mat-setup-')
        self.addCleanup(shutil.rmtree, ws, True)
        shutil.copytree(os.path.join(FIX, 'resume'), os.path.join(ws, 'resume'))
        open(os.path.join(ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write('identity:\n  first_name: Jordan\n  last_name: Rivera\n')
        bank = json.load(open(os.path.join(ws, 'resume', 'bank.json'), encoding='utf-8'))
        bank['bullets']['acme-m01'] = {'text': 'Built the pricing model', 'experience': 'acme', 'proposal': 'p1'}
        bank['bios'], bank['summaries'] = ['Strategy & Finance'], {'okr': 'A summary.'}
        json.dump(bank, open(os.path.join(ws, 'resume', 'bank.json'), 'w', encoding='utf-8', newline='\n'))
        os.makedirs(os.path.join(ws, 'resume', 'draft'))
        shutil.copy(os.path.join(ws, 'resume', 'templates', 'Ops.json'), os.path.join(ws, 'resume', 'draft', 'Ops.json'))
        setup.resume_approve(ws, 'Ops')
        after = json.load(open(os.path.join(ws, 'resume', 'bank.json'), encoding='utf-8'))
        self.assertEqual(after['bullets']['acme-m01']['text'], 'Built the pricing model')
        self.assertEqual((after['bios'], after['summaries']), (['Strategy & Finance'], {'okr': 'A summary.'}))


if __name__ == '__main__':
    unittest.main()
