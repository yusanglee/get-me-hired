"""Run record, review page and picks (engine/runrecord.py), on the fictional Chief of Staff fixture run
from test_discover_score (Acme Robotics, Globex, Initech). No network."""
import csv, json, os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from engine import discover, runrecord, score  # noqa: E402
import test_discover_score as T  # noqa: E402

DATE = T.TODAY.isoformat()


class Fixture(unittest.TestCase):
    """The fixture workspace and fake network of test_discover_score, without re-running its tests."""
    setUp, tearDown, searcher, discover = (T.CosEndToEnd.setUp, T.CosEndToEnd.tearDown, T.CosEndToEnd.searcher,
                                           T.CosEndToEnd.discover)


class RunRecordTest(Fixture):
    def run_all(self, cfg_change=None):
        if cfg_change:
            p = os.path.join(self.ws, 'config.json')
            cfg = json.load(open(p, encoding='utf-8'))
            cfg_change(cfg)
            json.dump(cfg, open(p, 'w', encoding='utf-8', newline='\n'))
        ctx, _ = self.discover()
        lines = []
        score.run(ctx, out=lines.append)
        rec = json.load(open(runrecord.path_for(ctx.queue, DATE), encoding='utf-8'))
        return ctx, rec, lines

    def test_discover_records_every_drop_with_reason(self):
        ctx, _ = self.discover()
        rec = json.load(open(runrecord.path_for(ctx.queue, DATE), encoding='utf-8'))
        drops = {d['title']: d for d in rec['dropped']}
        self.assertNotIn('Executive Assistant to the Chief of Staff', drops)  # title misses are not kept, not even counted
        self.assertNotIn('title', rec['discover']['counts'])
        self.assertNotIn('title', json.dumps({k: v for k, v in rec['discover'].items() if k != 'boards'}))
        # each job board's report is kept (a board's title_matches is a count of kept titles, not of misses)
        self.assertEqual([b['source'] for b in rec['discover']['boards']], list(discover.DEFAULT_SOURCES))
        self.assertTrue(os.path.exists(os.path.join(ctx.state, 'jd', drops['Chief of Staff, Engineering']['id'] + '.txt')))
        self.assertEqual(drops['Chief of Staff, Engineering']['reason'], 'location')
        self.assertEqual(drops['Chief of Staff, Engineering']['location'], 'London, UK')
        pay = drops['Strategy & Operations Manager']
        self.assertEqual((pay['reason'], pay['salary_max'], pay['stage']), ('salary', 150000, 'discover'))
        self.assertTrue(pay['url'].startswith('https://'))
        counts = rec['discover']['counts']
        for reason in ('location', 'salary'):
            self.assertEqual(counts[reason], sum(d['reason'] == reason for d in rec['dropped']), reason)
        self.assertEqual(rec['discover']['kept'], 6)
        self.assertEqual(rec['roles'], [])

    def test_applied_role_dropped_by_a_filter_is_tagged_already_applied(self):
        """A role in the tracker that discover's own filters drop (here: location) is still recorded as already applied,
        matched by company + title; the filter that would have dropped it is in the detail."""
        rows = T.tracker.read(T.tracker.path_of(self.ws))
        T.tracker.upsert(rows, {'company': 'Acme Robotics', 'title': 'Chief of Staff, Engineering', 'date_applied': '2026-10-01',
                                'status': 'applied'})
        T.tracker.write(T.tracker.path_of(self.ws), rows)
        ctx, _ = self.discover()
        rec = json.load(open(runrecord.path_for(ctx.queue, DATE), encoding='utf-8'))
        d = next(d for d in rec['dropped'] if d['title'] == 'Chief of Staff, Engineering')
        self.assertEqual((d['stage'], d['reason'], d['detail']), ('discover', 'already_applied', 'would be dropped for: location'))

    def test_prepared_folder_is_in_workflow_not_applied(self):
        """A folder in 02-Ready to Apply means prepared, not applied: score drops it as in_workflow. The tracker row
        and the 03-Applied folder still count as applied."""
        os.makedirs(os.path.join(self.ws, 'Workflow', '02-Ready to Apply', '2026-10-11 Globex - Head of Strategy'))
        ctx, rec, lines = self.run_all()
        drops = sorted((d['reason'], d['id']) for d in rec['dropped'] if d['stage'] == 'score')
        self.assertEqual(drops, [('already_applied', 'ab-globex-2'), ('in_workflow', 'ab-globex-1')])
        self.assertIn(discover.make_key('Acme Robotics', 'Chief of Staff, Finance'), ctx.applied()[0])
        self.assertNotIn(discover.make_key('Globex', 'Head of Strategy'), ctx.applied()[0])
        self.assertIn(discover.make_key('Globex', 'Head of Strategy'), ctx.known()[0])

    def test_score_records_roles_why_and_score_drops(self):
        ctx, rec, lines = self.run_all()
        by = {r['id']: r for r in rec['roles']}
        self.assertEqual([r['ref'] for r in rec['roles']], list(range(1, len(rec['roles']) + 1)))
        b = by['gh-acme-1']
        self.assertEqual(b['tier'], 'B')
        self.assertIn('B band', b['why'])
        p = b['parts']
        self.assertEqual(max(0, min(100, p['base'] + p['strengths'] + p['gaps'] + p['level'] + p['ats'])), b['fit'])
        self.assertIn('consulting or banking background', by['ab-globex-1']['gaps'])
        self.assertIn('On-site veto', by['gh-acme-7']['why'])
        applied = [d for d in rec['dropped'] if d['stage'] == 'score']
        self.assertEqual([(d['reason'], d['id']) for d in applied], [('already_applied', 'ab-globex-2')])
        self.assertTrue(any(d['stage'] == 'discover' for d in rec['dropped']))  # discover half kept
        self.assertTrue(lines[-1].startswith('Review page: '))
        self.assertIn('To review: 2 B', '\n'.join(lines))
        self.assertIn('1 already applied', '\n'.join(lines))
        self.assertEqual(next(x for x in lines if x.startswith('Dropped')),
                         'Dropped before scoring: 1 already applied, 1 location, 1 pay below floor.')
        # dropped roles are numbered and carry the fit they would have scored
        d = next(d for d in rec['dropped'] if d['id'] == 'ab-globex-2')
        self.assertTrue(d['ref'].startswith('d'))
        self.assertIsInstance(d['fit'], int)
        self.assertIn(d['would_be'], ('A', 'B', 'C+', 'C'))
        # scored CSV is unchanged by the hook: same columns, no 'parts'
        self.assertEqual(next(csv.reader(open(os.path.join(ctx.queue, f'scored-{DATE}.csv'), encoding='utf-8', newline=''))), score.COLUMNS)

    def test_cap_explains_would_be_tier(self):
        _, rec, lines = self.run_all(lambda c: c['per_company'].update(max_applications=1))
        cap = next(r for r in rec['roles'] if r['id'] == 'gh-acme-1')
        self.assertEqual((cap['tier'], cap['base_tier']), ('cap', 'B'))
        self.assertIn('company cap', cap['why'])
        self.assertIn('Acme Robotics already has 1 recent application', cap['why'])
        self.assertIn('Held back by a company cap: Acme Robotics x2 (would be 1 B, 1 C+)', '\n'.join(lines))

    def test_page_embeds_run_and_is_self_contained(self):
        ctx, rec, _ = self.run_all()
        html = open(os.path.join(ctx.queue, f'review-{DATE}.html'), encoding='utf-8').read()
        self.assertIn(f'<title>Run Review {DATE}</title>', html)
        self.assertNotIn('/*__RUN_DATA__*/null', html)
        m = re.search(r'const DATA = (.*?);\nconst CALLS', html, re.S)
        self.assertEqual(json.loads(m.group(1))['date'], DATE)
        scripts = re.findall(r'<script[^>]*src="([^"]+)"', html)
        self.assertEqual(scripts, [])  # no external scripts; fonts are the only outside load

    def test_page_escapes_closing_tags_in_data(self):
        rec = dict(date=DATE, roles=[], dropped=[dict(stage='discover', reason='title', company='Acme </script><b>', title='x',
                                                      location='', locations='', salary_max=None, url='', id='x', source='', detail='')],
                   picks={})
        d = os.path.join(self.ws, 'q')
        os.makedirs(d)
        html = open(runrecord.build_page(rec, d), encoding='utf-8').read()
        self.assertEqual(html.count('</script>'), 1)


class DropsTest(unittest.TestCase):
    def test_same_role_in_several_locations_is_one_entry(self):
        d = runrecord.Drops()
        for loc, i in (('New York, NY', 1), ('Austin, TX', 2), ('New York, NY', 3)):
            d.add('score', 'already_applied', 'Brightwater', dict(title='Chief of Staff', location_raw=loc, id=f'gh-b-{i}'))
        d.add('score', 'already_applied', 'Brightwater', dict(title='Head of Strategy', location_raw='Remote', id='gh-b-4'))
        d.add('discover', 'title', 'Brightwater', dict(title='Recruiter', location='Remote', id='gh-b-5'))
        self.assertEqual([(r['title'], r['location'], r['postings']) for r in d.rows],
                         [('Chief of Staff', 'New York, NY / Austin, TX', 3), ('Head of Strategy', 'Remote', 1)])


class TitlesTest(unittest.TestCase):
    def test_add_titles(self):
        from engine import packs
        base = packs.load('chief-of-staff')
        p, notes = packs.set_titles(base, ['Strategy & Operations', 'Program Manager', 'Revenue Operations Lead'])
        self.assertEqual(p['titles']['targets'], ['Strategy & Operations', 'Program Manager', 'Revenue Operations Lead'])
        for t in ('Senior Program Manager, Growth', 'Revenue Operations Lead', 'Chief of Staff to the CEO'):
            self.assertTrue(packs.title_ok(p, t), t)
        self.assertFalse(packs.title_ok(p, 'Software Engineer'))
        self.assertNotIn('revenue operations', p['titles']['exclude'])
        self.assertIn("removed 'revenue operations'", ' '.join(notes))
        q = p['titles']['board_queries']
        self.assertEqual(q.count('strategy and operations'), 1)
        self.assertIn('program manager', q)
        p2, _ = packs.set_titles(p, ['program manager', 'Data Analyst'])
        self.assertEqual(p2['titles']['targets'][-1], 'Data Analyst')
        self.assertEqual(len(p2['titles']['targets']), 4)  # no duplicate for a different case
        self.assertTrue(packs.title_ok(p2, 'Data Analyst II'))  # past the other-family rule

    def test_replace_titles(self):
        from engine import packs
        p, _ = packs.set_titles(packs.load('chief-of-staff'), ['Program Manager'], replace=True)
        self.assertTrue(packs.title_ok(p, 'Technical Program Manager'))
        self.assertFalse(packs.title_ok(p, 'Chief of Staff'))
        self.assertEqual(p['titles']['board_queries'], ['program manager'])

    def test_setup_titles_command(self):
        import tempfile
        from io import StringIO
        from unittest import mock
        from engine import packs, setup
        ws = tempfile.mkdtemp()
        pack = packs.draft(packs.load('chief-of-staff'), T.RESUME)
        pack['approved'] = True
        json.dump(pack, open(os.path.join(ws, 'pack.json'), 'w', encoding='utf-8', newline='\n'))
        with mock.patch('sys.stdout', new=StringIO()) as so:
            setup.main(['titles', ws, 'Chief of Staff', 'Program Manager'])
        self.assertIn('Program Manager: matches', so.getvalue())
        saved = json.load(open(os.path.join(ws, 'pack.json'), encoding='utf-8'))
        self.assertTrue(saved['approved'])
        self.assertEqual(saved['titles']['targets'], ['Chief of Staff', 'Program Manager'])
        with mock.patch('sys.stdout', new=StringIO()) as so:
            setup.main(['titles', ws, '--list'])
        self.assertIn('Target titles: Chief of Staff, Program Manager', so.getvalue())


class PicksTest(Fixture):
    def setUp(self):
        super().setUp()
        self.ctx, _ = self.discover()
        score.run(self.ctx, out=lambda *a: None)
        self.rec = json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))
        self.ref = {r['id']: r['ref'] for r in self.rec['roles']}
        self.reviewed = os.path.join(self.ctx.queue, f'reviewed-{DATE}.csv')

    def read(self):
        return {r['id']: r for r in csv.DictReader(open(self.reviewed, encoding='utf-8', newline=''))}

    def test_parse(self):
        P = runrecord.parse_picks
        self.assertEqual(P('apply 1 4; hold 7 waiting on referral'),
                         [dict(ref=1, call='apply', note=''), dict(ref=4, call='apply', note=''),
                          dict(ref=7, call='hold', note='waiting on referral')])
        self.assertEqual(P('pass 2-4, #9'), [dict(ref=r, call='pass', note='') for r in (2, 3, 4, 9)])
        self.assertEqual(P('hold 7: 3 days left'), [dict(ref=7, call='hold', note='3 days left')])
        self.assertEqual(P('apply d3-5 2'), [dict(ref=r, call='apply', note='') for r in ('d3', 'd4', 'd5', 2)])
        self.assertEqual(P('hold D7: maybe'), [dict(ref='d7', call='hold', note='maybe')])
        self.assertEqual(P('Manual 3\nclear 5'), [dict(ref=3, call='manual', note=''), dict(ref=5, call='clear', note='')])
        with self.assertRaises(runrecord.PickError):
            P('maybe 3')
        with self.assertRaises(runrecord.PickError):
            P('apply soon')

    def test_picks_write_reviewed_csv(self):
        c, b = self.ref['ab-globex-1'], self.ref['gh-acme-1']  # a C promoted, a B
        lines, warn, path = runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(f'apply {c} {b}; hold {self.ref["hm-initech-cos"]}: recruiter call first'))
        self.assertEqual(path, self.reviewed)
        rows = self.read()
        self.assertEqual(list(next(csv.reader(open(path, encoding='utf-8', newline='')))), runrecord.REVIEWED_COLUMNS)
        self.assertEqual(rows['ab-globex-1']['call'], 'apply')
        self.assertEqual(rows['ab-globex-1']['top_gap'], 'consulting or banking background')
        self.assertIn('tier C', rows['ab-globex-1']['notes'])
        self.assertEqual(rows['hm-initech-cos']['call'], 'hold')
        self.assertIn('recruiter call first', rows['hm-initech-cos']['notes'])
        self.assertEqual(rows['gh-acme-1']['salary_max'], '260000')
        rec = json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))
        self.assertEqual(rec['picks']['gh-acme-1']['call'], 'apply')
        self.assertEqual(warn, [])
        page = open(os.path.join(self.ctx.queue, f'review-{DATE}.html'), encoding='utf-8').read()
        self.assertIn('"picks":{"ab-globex-1"', page)  # page rebuilt with the picks in it

    def test_existing_stage_2b_rows_are_updated_not_replaced(self):
        cols = runrecord.REVIEWED_COLUMNS
        with open(self.reviewed, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerow({**{c: '' for c in cols}, 'call': 'apply', 'id': 'gh-acme-1', 'company': 'Acme Robotics',
                        'template_script': 'Brightwater-Ops', 'notes': 'Hybrid NYC.'})
            w.writerow({**{c: '' for c in cols}, 'call': 'pass', 'id': 'zz-other-1', 'company': 'Hooli'})
        b = self.ref['gh-acme-1']
        lines, _, _ = runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(f'pass {b}: comp too low'))
        rows = self.read()
        self.assertEqual(list(rows), ['gh-acme-1', 'zz-other-1'])
        self.assertEqual(rows['gh-acme-1']['call'], 'pass')
        self.assertEqual(rows['gh-acme-1']['template_script'], 'Brightwater-Ops')
        self.assertEqual(rows['gh-acme-1']['notes'], 'Hybrid NYC.; Review page pick: comp too low')
        self.assertIn('(was apply)', lines[0])
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(f'pass {b}: comp too low'))
        self.assertEqual(self.read()['gh-acme-1']['notes'], 'Hybrid NYC.; Review page pick: comp too low')  # idempotent
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(f'clear {b}'))
        self.assertIn('gh-acme-1', self.read())  # a stage 2b row is never removed by clear

    def test_clear_removes_page_row_and_json_picks(self):
        c = self.ref['ab-globex-1']
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(f'apply {c}'))
        runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=c, call='clear')])
        self.assertNotIn('ab-globex-1', self.read())
        self.assertNotIn('ab-globex-1', json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))['picks'])

    def test_bad_ref_and_dry_run(self):
        with self.assertRaises(runrecord.PickError):
            runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=99, call='apply')])
        with self.assertRaises(runrecord.PickError):
            runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=1, id='gh-gone-9', call='apply')])  # unknown id: no ref fallback
        lines, _, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=1, id='hm-initech-cos', call='hold')], dry_run=True)
        self.assertIn('Initech', lines[0])  # the id wins over a stale ref
        runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=1, call='apply')], dry_run=True)
        self.assertFalse(os.path.exists(self.reviewed))

    def test_rediscover_keeps_picks_and_resets_roles(self):
        runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=1, call='apply')])
        self.discover()
        rec = json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))
        self.assertEqual(rec['roles'], [])
        self.assertEqual(len(rec['picks']), 1)

    def test_rescue_dropped_role(self):
        rec = runrecord.load(self.ctx.queue, DATE)
        loc = next(d for d in rec['dropped'] if d['reason'] == 'location')
        applied = next(d for d in rec['dropped'] if d['reason'] == 'already_applied')
        lines, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(
            f"apply {loc['ref']}: open to relocating; hold {applied['ref']}"))
        rows = self.read()
        self.assertEqual(rows[loc['id']]['call'], 'apply')
        self.assertIn('rescued, dropped for: location outside your metros', rows[loc['id']]['notes'])
        self.assertIn('open to relocating', rows[loc['id']]['notes'])
        self.assertEqual(rows[loc['id']]['fit'], str(loc['fit']))
        self.assertEqual(warn, [])  # hold on an applied role: no warning
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=applied['ref'], call='apply')])
        self.assertIn('applying twice', warn[0])

    def test_pick_of_applied_role_warns_by_id_and_by_title(self):
        """A rescued role that the tracker has, even when its drop reason says something else, warns at pick time."""
        rec = runrecord.load(self.ctx.queue, DATE)
        loc = next(d for d in rec['dropped'] if d['reason'] == 'location')
        index = ({discover.make_key(loc['company'], loc['title'])}, set())
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=loc['ref'], call='apply')], True, applied=index)
        self.assertTrue(any('duplicate' in w for w in warn), warn)
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=loc['ref'], call='apply')], True,
                                           applied=(set(), {loc['id']}))
        self.assertTrue(any('duplicate' in w for w in warn), warn)
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=loc['ref'], call='apply')], True, applied=(set(), set()))
        self.assertFalse(any('duplicate' in w for w in warn), warn)

    def test_applied_check_lists_queued_roles_already_applied(self):
        rec = runrecord.load(self.ctx.queue, DATE)
        loc = next(d for d in rec['dropped'] if d['reason'] == 'location')
        runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=loc['ref'], call='apply')])
        self.assertEqual(runrecord.queued_applied(self.ctx.queue, DATE, (set(), set())), [])
        hits = runrecord.queued_applied(self.ctx.queue, DATE, (set(), {loc['id']}))
        self.assertEqual([h['id'] for h in hits], [loc['id']])
        hits = runrecord.queued_applied(self.ctx.queue, DATE, ({discover.make_key(loc['company'], loc['title'])}, set()))
        self.assertEqual([h['id'] for h in hits], [loc['id']])

    def test_stage_2b_todo_and_fill(self):
        c, b = self.ref['ab-globex-1'], self.ref['gh-acme-1']
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks(f'apply {c}; hold {b}'))
        left = runrecord.todo(self.ctx.queue, DATE)
        self.assertEqual([t['id'] for t in left], ['ab-globex-1'])  # hold rows need no stage 2b
        self.assertTrue(left[0]['jd'].endswith('ab-globex-1.txt'))
        warn = runrecord.fill(self.ctx.queue, DATE, 'ab-globex-1', dict(
            gap_type='major', top_gap='JD or law degree required', summary_variant='Operator', template_script='Brightwater-Ops',
            lead_material='OKR cycle; board materials'))
        self.assertEqual(warn, [])
        row = self.read()['ab-globex-1']
        self.assertEqual((row['call'], row['gap_type'], row['template_script']), ('apply', 'major', 'Brightwater-Ops'))
        self.assertEqual(runrecord.todo(self.ctx.queue, DATE), [])
        warn = runrecord.fill(self.ctx.queue, DATE, 'ab-globex-1', dict(gap_type='critical'))
        self.assertIn('critical gap', warn[0])
        self.assertEqual(self.read()['ab-globex-1']['call'], 'apply')  # the call is the user's
        for bad in (dict(call='pass'), dict(gap_type='huge')):
            with self.assertRaises(runrecord.PickError):
                runrecord.fill(self.ctx.queue, DATE, 'ab-globex-1', bad)
        with self.assertRaises(runrecord.PickError):
            runrecord.fill(self.ctx.queue, DATE, 'zz-none', dict(gap_type='minor'))

    def test_gate_pick_warns(self):
        rec = runrecord.load(self.ctx.queue, DATE)
        rec['roles'][0].update(tier='gate', flags=['gate FAIL: citizenship required'])
        runrecord.save(self.ctx.queue, rec)
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(ref=1, call='apply')])
        self.assertIn('hard gate', warn[0])

    def test_cli_summary_and_picks(self):
        from io import StringIO
        from unittest import mock
        with mock.patch('sys.stdout', new=StringIO()) as so:
            runrecord.main(['summary', '--workspace', self.ws])
        self.assertIn(f'Run {DATE}: 5 roles scored', so.getvalue())
        with mock.patch('sys.stdout', new=StringIO()) as so:
            runrecord.main(['picks', 'hold 2', '--workspace', self.ws])
        self.assertIn('Wrote ', so.getvalue())
        self.assertNotIn('Stage 2b to fill', so.getvalue())  # hold: nothing to fill
        self.assertEqual(len(self.read()), 1)
        with mock.patch('sys.stdout', new=StringIO()) as so:
            runrecord.main(['picks', 'apply 1', '--workspace', self.ws])
        self.assertIn('Stage 2b to fill now', so.getvalue())
        with mock.patch('sys.stdout', new=StringIO()) as so:
            runrecord.main(['fill', 'gh-acme-1', '--set', 'gap_type=none', '--set', 'top_gap=', '--workspace', self.ws])
        self.assertIn('Filled gap_type, top_gap for gh-acme-1', so.getvalue())


if __name__ == '__main__':
    unittest.main()
