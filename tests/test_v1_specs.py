"""v1.0 E4a: specs accept / coverage / drop_oldest / max_bullets / no_extra / layout rules in the brief,
materials bios paging and fit, the resume-choice approval. Fictional workspace (Jordan Rivera, Brightwater, Acme)."""
import contextlib, csv, io, json, os, shutil, tempfile, unittest

from engine import materials as M, specs

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'workspace')
RID = 'gh-brightwater-123'
POSTING = 'Chief of Staff. You will own the operating cadence, OKRs, board prep and executive hiring for the CEO.'
COLS = ['id', 'company', 'title', 'call', 'summary_variant', 'template_script', 'lead_material']


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.ws = os.path.join(self.d, 'ws')
        shutil.copytree(os.path.join(FIX, 'resume'), os.path.join(self.ws, 'resume'))
        self.cfg = {'resume': {'max_bullet_lines': 2, 'max_extra_bullets': 1}}
        json.dump({}, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        self.P = os.path.join(self.ws, 'Pipeline')
        for sub in ('queue', 'state/jd', 'state/reads', 'specs'):
            os.makedirs(os.path.join(self.P, sub))
        with open(os.path.join(self.P, 'queue', 'reviewed-2026-11-03.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(COLS)
            w.writerow([RID, 'Brightwater', 'Chief of Staff', 'apply', '', '', ''])
            w.writerow(['gh-other-9', 'Other', 'Analyst', 'pass', '', '', ''])
        open(os.path.join(self.P, 'state', 'jd', RID + '.txt'), 'w', encoding='utf-8', newline='\n').write(POSTING)
        open(os.path.join(self.ws, 'terms.txt'), 'w', encoding='utf-8', newline='\n').write(
            'operating cadence\nokrs\nboard prep\nexecutive hiring\n')
        self.reply = os.path.join(self.d, 'reply.json')

    def entry(self, **kw):
        return dict({'id': RID, 'slug': 'Brightwater-CoS', 'short': 'Chief of Staff', 'template': 'Ops',
                     'skills': ['Operating Cadence', 'OKRs', 'Board Prep', 'Executive Hiring']}, **kw)

    def write_reply(self, entry=None, **kw):
        body = {'spec': entry or self.entry(), 'summary_variant': 'ops', 'template_script': 'Ops',
                'lead_material': 'Board prep story', 'notes': 'covers all four terms',
                'missing': [{'experience': 'acme', 'fact': 'pricing', 'resume_line': 'Built the pricing model'}],
                'material_feedback': []}
        body.update(kw)
        json.dump(body, open(self.reply, 'w', encoding='utf-8', newline='\n'))
        return self.reply

    def csv_row(self):
        with open(os.path.join(self.P, 'queue', 'reviewed-2026-11-03.csv'), encoding='utf-8', newline='') as fh:
            return next(r for r in csv.DictReader(fh) if r['id'] == RID)

    def edit_template(self, fn):
        p = os.path.join(self.ws, 'resume', 'templates', 'Ops.json')
        doc = json.load(open(p, encoding='utf-8'))
        fn(doc)
        json.dump(doc, open(p, 'w', encoding='utf-8', newline='\n'))

    def checks(self, entry):
        return specs.check_entry(entry, specs.load_templates(self.ws), specs.load_bank(self.ws), self.cfg)


class Accept(Base):
    def test_accept_writes_everything(self):
        code, out = specs.run_command(self.ws, ['accept', RID, self.write_reply()])
        self.assertEqual((code, out), (0, f'accepted {RID}'))
        row = self.csv_row()
        self.assertEqual((row['summary_variant'], row['template_script'], row['lead_material']),
                         ('ops', 'Ops', 'Board prep story'))
        batch = json.load(open(specs.batch_path(self.ws, '2026-11-03', {}), encoding='utf-8'))
        self.assertEqual([r['id'] for r in batch['roles']], [RID])
        self.assertEqual(batch['date'], '2026-11-03')
        rec = json.load(open(os.path.join(self.P, 'state', 'tailor', RID + '.json'), encoding='utf-8'))
        self.assertEqual(rec['missing'][0]['resume_line'], 'Built the pricing model')
        # the batch file builds
        out = specs.run(specs.batch_path(self.ws, '2026-11-03', {}), self.ws, cfg={})
        self.assertEqual(out[0]['company'], 'Brightwater')

    def test_accept_again_replaces_the_entry(self):
        specs.run_command(self.ws, ['accept', RID, self.write_reply()])
        specs.run_command(self.ws, ['accept', RID, self.write_reply(self.entry(short='CoS'))])
        batch = json.load(open(specs.batch_path(self.ws, '2026-11-03', {}), encoding='utf-8'))
        self.assertEqual([r['short'] for r in batch['roles']], ['CoS'])

    def test_failure_writes_nothing(self):
        before = open(os.path.join(self.P, 'queue', 'reviewed-2026-11-03.csv'), encoding='utf-8').read()
        code, out = specs.run_command(self.ws, ['accept', RID, self.write_reply(self.entry(experience={'acme': ['NOPE']}))])
        self.assertEqual(code, 1)
        self.assertIn('unknown bullet', out)
        self.assertEqual(open(os.path.join(self.P, 'queue', 'reviewed-2026-11-03.csv'), encoding='utf-8').read(), before)
        self.assertFalse(os.path.exists(specs.batch_path(self.ws, '2026-11-03', {})))
        self.assertFalse(os.path.exists(os.path.join(self.P, 'state', 'tailor')))

    def test_labels_default_from_the_entry(self):
        # the tailor is read-only and no longer fills the labels: accept derives them from the spec entry
        body = {'spec': self.entry(experience={'acme': ['MNA', 'PLAN']}), 'notes': ''}
        json.dump(body, open(self.reply, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(specs.run_command(self.ws, ['accept', RID, self.reply])[0], 0)
        row = self.csv_row()
        self.assertEqual((row['summary_variant'], row['template_script'], row['lead_material']),
                         ('template:Ops', 'Ops', 'MNA'))
        # no bullets picked: the template's first bullet, by its bank id; another summary is kept as given
        json.dump({'spec': self.entry(summary='template:Ops'), 'lead_material': ' '}, open(self.reply, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(specs.run_command(self.ws, ['accept', RID, self.reply])[0], 0)
        self.assertEqual(self.csv_row()['lead_material'], 'OPS')

    def test_wrong_id_and_pass_row(self):
        code, out = specs.run_command(self.ws, ['accept', 'gh-other-9', self.write_reply()])
        self.assertEqual(code, 1)
        self.assertIn("not 'gh-other-9'", out)
        self.assertIn("call='pass'", out)
        self.assertEqual(specs.run_command(self.ws, ['accept', 'nope', self.write_reply()])[0], 1)
        self.assertFalse(os.path.exists(os.path.join(self.P, 'scratch')))

    def test_batch_skips_a_role_passed_after_accept(self):
        specs.run_command(self.ws, ['accept', RID, self.write_reply()])
        rp = os.path.join(self.P, 'queue', 'reviewed-2026-11-03.csv')
        text = open(rp, encoding='utf-8', newline='').read()
        open(rp, 'w', encoding='utf-8', newline='').write(text.replace(',Chief of Staff,apply,', ',Chief of Staff,pass,'))
        skipped = []
        self.assertEqual(specs.run(specs.batch_path(self.ws, '2026-11-03', {}), self.ws, cfg={}, skipped=skipped), [])
        self.assertEqual(skipped, [f'skipped {RID}: call=pass in the reviewed CSV (no spec written)'])

    def test_date_picks_the_reviewed_file(self):
        code, out = specs.run_command(self.ws, ['accept', RID, self.write_reply()], date='2026-10-01')
        self.assertEqual(code, 1)
        self.assertIn('reviewed-2026-10-01.csv', out)

    def test_slug_clash_in_the_batch(self):
        with open(os.path.join(self.P, 'queue', 'reviewed-2026-11-03.csv'), 'a', encoding='utf-8', newline='') as fh:
            csv.writer(fh).writerow(['gh-two-2', 'Two', 'COS', 'apply', '', '', ''])
        specs.run_command(self.ws, ['accept', RID, self.write_reply()])
        code, out = specs.run_command(self.ws, ['accept', 'gh-two-2', self.write_reply(self.entry(id='gh-two-2'))])
        self.assertEqual(code, 1)
        self.assertIn('already used', out)


class Coverage(Base):
    def test_before_after(self):
        spec = os.path.join(self.d, 'spec.json')
        json.dump(self.entry(), open(spec, 'w', encoding='utf-8', newline='\n'))
        code, out = specs.run_command(self.ws, ['coverage', RID], spec=spec)
        self.assertEqual((code, out), (0, 'before 3/4, after 4/4; missed: none'))
        json.dump(self.entry(skills=['Operating Cadence', 'OKRs']), open(spec, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(specs.run_command(self.ws, ['coverage', RID], spec=spec)[1],
                         'before 3/4, after 2/4; missed: board prep, executive hiring')

    def test_reads_a_tailor_reply_and_a_built_spec(self):
        self.assertEqual(specs.run_command(self.ws, ['coverage', RID], spec=self.write_reply())[1],
                         'before 3/4, after 4/4; missed: none')
        built = specs.make_spec(self.entry(), specs.load_templates(self.ws), specs.load_bank(self.ws), None, 'd',
                                {'company': 'x', 'title': 'x'})
        p = os.path.join(self.d, 'built.json')
        json.dump(built, open(p, 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(specs.run_command(self.ws, ['coverage', RID], spec=p)[1], 'before 3/4, after 4/4; missed: none')

    def test_default_spec_path_and_errors(self):
        code, out = specs.run_command(self.ws, ['coverage', RID])
        self.assertEqual(code, 1)
        self.assertIn('no spec file', out)
        from engine import layout
        json.dump(self.entry(), open(layout.scratch(self.ws, 'spec', RID), 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(specs.run_command(self.ws, ['coverage', RID])[0], 0)
        os.remove(os.path.join(self.ws, 'terms.txt'))
        self.assertIn('no keyword vocabulary', specs.run_command(self.ws, ['coverage', RID])[1])


class DropOldest(Base):
    def test_drops_the_last_job(self):
        e = self.entry(drop_oldest=1)
        self.assertEqual(self.checks(e), [])
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        spec = specs.make_spec(e, t, bank, self.cfg, 'd', {'company': 'x', 'title': 'x'})
        self.assertEqual(spec['overrides']['drop_oldest'], 1)
        doc = specs.apply_spec(t['Ops'], spec['overrides'])
        self.assertEqual([x['id'] for x in doc['experience']], ['examplehealth'])
        self.assertEqual(len(t['Ops']['experience']), 2)  # the template itself is untouched
        self.assertEqual(specs.legacy(spec, t)['overrides']['drop_oldest'], 1)

    def test_other_drops_fail(self):
        for n in (2, 3, -1, 'one', True, 1.5):
            self.assertIn('drop_oldest', self.checks(self.entry(drop_oldest=n))[0], n)
        self.assertIn('is dropped', self.checks(self.entry(drop_oldest=1, experience={'acme': ['PLAN']}))[0])
        self.assertIn('unknown field', self.checks(self.entry(drop=['examplehealth']))[0])
        self.assertIn('unknown field', self.checks(self.entry(drop_newest=1))[0])
        self.assertIn('bullets', self.checks(self.entry(experience={'examplehealth': []}))[0])

    def test_zero_is_no_drop(self):
        t, bank = specs.load_templates(self.ws), specs.load_bank(self.ws)
        spec = specs.make_spec(self.entry(drop_oldest=0), t, bank, self.cfg, 'd', {'company': 'x', 'title': 'x'})
        self.assertNotIn('drop_oldest', spec['overrides'])


class BulletCaps(Base):
    def test_max_bullets_and_no_extra(self):
        def setup(doc):
            doc['experience'][0]['max_bullets'] = 2
            doc['experience'][1]['no_extra'] = True
        self.edit_template(setup)
        # examplehealth: 3 bullets would be one extra (allowed by max_extra_bullets) but the cap is 2
        e = self.entry(experience={'examplehealth': ['OPS', 'BRD', 'HIRE']})
        self.assertIn('at most 2', self.checks(e)[0])
        self.assertEqual(self.checks(self.entry(experience={'examplehealth': ['OPS', 'BRD']})), [])
        # acme: no_extra blocks the second bullet; the template's own count is fine
        self.assertIn('no_extra', self.checks(self.entry(experience={'acme': ['PLAN', 'MNA']}))[0])
        self.assertEqual(self.checks(self.entry(experience={'acme': ['PLAN']})), [])

    def test_extra_still_allowed_without_the_flags(self):
        self.assertEqual(self.checks(self.entry(experience={'acme': ['PLAN', 'MNA']})), [])

    def test_brief_lists_them(self):
        self.edit_template(lambda d: d['experience'][0].update(max_bullets=2, no_extra=True))
        os.makedirs(os.path.join(self.P, 'state', 'jd'), exist_ok=True)
        b = specs.brief(self.ws, self.P, RID, cfg=self.cfg)
        exp = b['templates']['Ops']['experience']
        self.assertEqual((exp[0]['max_bullets'], exp[0]['no_extra']), (2, True))
        self.assertNotIn('max_bullets', exp[1])
        self.assertTrue(any('max_bullets' in r for r in b['rules']))


class BriefRules(Base):
    def test_layout_rules_only_for_present_keys(self):
        cfg = {'resume': {'max_bullet_lines': 2, 'max_summary_lines': 4, 'max_scope_lines': 1, 'min_last_line_words': 3,
                          'skills_lines': 2, 'max_pages': 2, 'max_page1_free_pt': 30,
                          'page_breaks': {'last_on_page_1': 'experience.examplehealth', 'first_on_page_2': 'experience.acme'}}}
        rules = specs.brief(self.ws, self.P, RID, cfg=cfg)['rules']
        lay = [r for r in rules if r.startswith('Layout: ') and 'each experience keeps' not in r]
        self.assertEqual(len(lay), 8)
        text = '\n'.join(lay)
        for frag in ('every bullet fits on 2 lines', 'summary fits on 4 lines', 'scope line fits on 1 line ',
                     'at least 3 words', 'skills section fits on 2 lines', 'resume is 2 pages',
                     'last on page 1 = experience.examplehealth', 'at most 30 pt'):
            self.assertIn(frag, text)
        one = specs.brief(self.ws, self.P, RID, cfg={'resume': {'max_pages': 1}})['rules']
        self.assertEqual(sum('page' in r and r.startswith('Layout: the resume') for r in one), 1)
        self.assertFalse(any('summary fits' in r for r in one))
        self.assertTrue(any('cover the most posting key terms' in r for r in rules))
        self.assertTrue(any('drop_oldest' in r for r in rules))

    def test_write_brief_default_path(self):
        path = specs.write_brief(self.ws, RID)
        self.assertTrue(os.path.isabs(path))
        self.assertIn(os.path.join('Pipeline', 'scratch'), path)
        self.assertTrue(path.endswith(f'tailor-brief-{RID}.json'))
        self.assertEqual(json.load(open(path, encoding='utf-8'))['role']['company'], 'Brightwater')
        out = os.path.join(self.d, 'x', 'b.json')
        self.assertEqual(specs.run_command(self.ws, ['brief', RID], out=out), (0, out))
        self.assertTrue(os.path.exists(out))


class ResumeChoice(Base):
    def test_render(self):
        text = specs.render_choice(self.ws, RID, self.write_reply(self.entry(drop_oldest=1)), cfg=self.cfg)
        self.assertNotRegex(text, r'\{[a-z_]+\}')
        for frag in ('Brightwater: Chief of Staff', 'Template: Ops', 'Chief of staff with 14 years', 'before 3/4, after 4/4',
                     'Dropped the oldest job(s): Acme Logistics', 'Tailor: covers all four terms',
                     'Operating Cadence  |  OKRs  |  Board Prep  |  Executive Hiring', 'every bullet fits on 2 lines'):
            self.assertIn(frag, text)
        self.assertIn('  - template  Ran the weekly operating review for 12 executives', text.replace('OPS', 'template'))

    def test_bullets_by_id(self):
        text = specs.render_choice(self.ws, RID, self.write_reply(self.entry(experience={'acme': ['PLAN', 'MNA']})))
        self.assertIn('  - MNA  Ran diligence on 3 acquisitions', text)
        self.assertIn('  - PLAN  Led the annual planning process', text)


class Bios(Base):
    def make_sent(self, n):
        for i in range(n):
            json.dump({'overrides': {'bio': f'Chief of Staff  ·  Domain {i:02d} & Strategy'}},
                      open(os.path.join(self.P, 'specs', f's{i:02d}.json'), 'w', encoding='utf-8', newline='\n'))

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                M.main(['--workspace', self.ws, *args])
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def test_pages(self):
        self.make_sent(45)
        code, out = self.cli('bios')
        self.assertEqual(code, 0)
        self.assertIn('  1. Domain 00 & Strategy', out)
        self.assertIn(' 20. Domain 19 & Strategy', out)
        self.assertNotIn('Domain 20', out)
        self.assertIn('page 1 of 3', out)
        code, out = self.cli('bios', '--page', '3')
        self.assertIn(' 41. Domain 40 & Strategy', out)
        self.assertIn(' 45. Domain 44 & Strategy', out)
        self.assertTrue(out.rstrip().endswith('page 3 of 3'))
        out = self.cli('bios', '--page', '2', '--per', '10')[1]
        self.assertIn(' 11. Domain 10', out)
        self.assertIn('page 2 of 5', out)
        code, out = self.cli('bios', '--page', '4')
        self.assertEqual(code, 1 if isinstance(code, int) and code else code)
        self.assertNotEqual(code, 0)

    def test_empty(self):
        code, out = self.cli('bios')
        self.assertEqual(out.strip(), 'No unapproved bios on built resumes.')

    def test_numbering_stays_global_for_approve(self):
        self.make_sent(25)
        self.assertEqual(M.sent_bio_list(self.ws)[22], (23, 'Domain 22 & Strategy'))


class Fit(Base):
    def bank(self):
        return json.load(open(os.path.join(self.ws, 'resume', 'bank.json'), encoding='utf-8'))

    def test_reword_keeps_numbers(self):
        before, after = M.fit(self.ws, 'OPS', 'Ran the weekly operating review with **12 executives**')
        self.assertEqual(before, 'Ran the weekly operating review for **12 executives**')
        self.assertEqual(self.bank()['bullets']['OPS']['text'], after)
        self.assertEqual(self.bank()['bullets']['OPS']['experience'], 'examplehealth')
        log = json.load(open(os.path.join(self.ws, 'resume', 'changes.json'), encoding='utf-8'))
        self.assertEqual((log[-1]['kind'], log[-1]['before'], log[-1]['after']), ('fit', before, after))
        self.assertTrue(os.listdir(os.path.join(self.ws, 'resume', '.history')))

    def test_number_changes_fail_and_change_nothing(self):
        raw = open(os.path.join(self.ws, 'resume', 'bank.json'), encoding='utf-8').read()
        for text in ('Ran the weekly operating review for **13 executives**',   # changed
                     'Ran the weekly operating review',                          # dropped
                     'Ran the weekly operating review for **12 executives** in 2024',  # added
                     'Built the board deck process, cutting prep **from 3 weeks to 2**'):
            bid = 'BRD' if 'board deck' in text else 'OPS'
            with self.assertRaises(M.MaterialError, msg=text) as cm:
                M.fit(self.ws, bid, text)
            self.assertIn('numbers changed', str(cm.exception))
        self.assertEqual(open(os.path.join(self.ws, 'resume', 'bank.json'), encoding='utf-8').read(), raw)
        self.assertFalse(os.path.exists(os.path.join(self.ws, 'resume', 'changes.json')))

    def test_other_refusals(self):
        with self.assertRaises(M.MaterialError):
            M.fit(self.ws, 'NOPE', 'x')
        with self.assertRaises(M.MaterialError):
            M.fit(self.ws, 'OPS', 'Ran the weekly operating review for **12 executives**')  # unchanged
        with self.assertRaises(M.MaterialError):
            M.fit(self.ws, 'OPS', 'Ran the weekly review for **12 executives**, never late')  # gap word
        with self.assertRaises(M.MaterialError):
            M.fit(self.ws, 'OPS', 'Ran the weekly review — **12 executives**')  # dash

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            M.main(['--workspace', self.ws, 'fit', 'OPS', 'Ran the weekly operating review with **12 executives**'])
        self.assertIn('before: Ran the weekly operating review for', out.getvalue())
        self.assertIn('after:  Ran the weekly operating review with', out.getvalue())
        with self.assertRaises(SystemExit) as cm:
            M.main(['--workspace', self.ws, 'fit', 'OPS', 'Ran it for **99 executives**'])
        self.assertIn('numbers changed', str(cm.exception))


class MaterialsBriefOut(Base):
    def test_default_path_is_scratch_and_dash_prints(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            M.main(['--workspace', self.ws, 'brief'])
        path = out.getvalue().strip()
        self.assertTrue(os.path.isabs(path))
        self.assertIn('materials-brief-all.json', path)
        self.assertIn('candidates', json.load(open(path, encoding='utf-8')))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            M.main(['--workspace', self.ws, 'brief', '--out', '-'])
        self.assertIn('candidates', json.loads(out.getvalue()))


if __name__ == '__main__':
    unittest.main()
