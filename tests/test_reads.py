"""Posting reads (engine/reads.py): validation, the cache, gap rules in scoring and the run record, `gmh review reads`,
picks and todo, the summary line and the review page. Fictional fixture run from test_discover_score; no network."""
import csv, datetime, json, os, re, sys, unittest
from io import StringIO
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from engine import reads, runrecord, score, triage  # noqa: E402
import test_runrecord as TR  # noqa: E402

DATE = TR.DATE
ROLE_KEYS = ['ref', 'tier', 'base_tier', 'why', 'fit', 'ats', 'parts', 'company', 'title', 'locations', 'location_raw', 'salary_min',
             'salary_max', 'salary_source', 'gaps', 'flags', 'review', 'url', 'id', 'source', 'new', 'first_seen', 'top_locations']


def row(rid, gap='none', top='', quote='', strengths=(), needs=('OKR cadence',), concerns=''):
    return dict(id=rid, gap_type=gap, top_gap=top, gap_quote=quote, strengths=list(strengths), needs=list(needs), concerns=concerns)


def strong(label, level='strong'):
    return dict(label=label, level=level, resume='ran the OKR cycle', posting='own the operating cadence')


class ReadsBase(TR.Fixture):
    def setUp(self):
        super().setUp()
        self.ctx, _ = self.discover()
        score.run(self.ctx, out=lambda *a: None)  # the run record the reads are checked against
        self.reader = reads.Reader(self.ctx)

    def set_config(self, change):
        p = os.path.join(self.ws, 'config.json')
        cfg = json.load(open(p, encoding='utf-8'))
        change(cfg)
        json.dump(cfg, open(p, 'w', encoding='utf-8', newline='\n'))
        self.ctx = type(self.ctx)(self.ws, today=self.ctx.today)
        self.reader = reads.Reader(self.ctx)

    def cache(self, *rows):
        reads.save(self.ctx.state, reads.validate(dict(rows=list(rows)), reads.known_ids(self.ctx.queue, DATE), self.ctx.state),
                   self.reader.resume)

    def score(self, **kw):
        score.run(self.ctx, out=lambda *a: None)
        return {r['id']: r for r in json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))['roles']}

    def cli(self, *args):
        with mock.patch('sys.stdout', new=StringIO()) as so:
            try:
                runrecord.main([*args, '--workspace', self.ws])
            except SystemExit as e:
                return str(e)
        return so.getvalue()

    def reply_file(self, *rows):
        p = os.path.join(self.ws, 'reply.json')
        json.dump(dict(rows=list(rows)), open(p, 'w', encoding='utf-8', newline='\n'))
        return p


class ValidateTest(ReadsBase):
    def check(self, reply, *fragments):
        with self.assertRaises(reads.ReadError) as cm:
            reads.validate(reply, {'gh-acme-1', 'hm-initech-cos'}, self.ctx.state)
        text = str(cm.exception)
        for f in fragments:
            self.assertIn(f, text)
        return cm.exception.problems

    def test_bad_replies_list_every_problem(self):
        good = row('gh-acme-1')
        probs = self.check(dict(rows=[
            good, row('gh-gone-9'), row('hm-initech-cos', gap='huge'),
            row('hm-initech-cos', strengths=[strong('a'), strong('b'), strong('c'), strong('d')]),
            row('gh-acme-1', needs=list('abcdef')),
            row('gh-acme-1', strengths=[strong('a', level='great')])]),
            'nothing saved', 'gh-gone-9', "gap_type 'huge'", 'at most 3', 'at most 5', "level 'great'", 'appears twice')
        self.assertEqual(len(probs), 8)  # gh-acme-1 repeats twice
        self.check([], 'no rows')
        self.check('nope', 'expected')
        self.check(dict(rows=[dict(gap_type='none')]), 'id missing')
        self.check(dict(rows=[row('gh-acme-1', top=5)]), 'top_gap must be text')

    def test_reviewed_csv_row_and_dropped_posting_are_allowed_ids(self):
        d = next(d for d in runrecord.load(self.ctx.queue, DATE)['dropped'] if d['reason'] == 'location')
        score.run(self.ctx, out=lambda *a: None)
        with open(os.path.join(self.ctx.queue, f'reviewed-{DATE}.csv'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('call,company,title,id\napply,Initech,Chief of Staff,hm-initech-cos\n')
        ids = reads.known_ids(self.ctx.queue, DATE)
        self.assertLessEqual({d['id'], 'hm-initech-cos', 'gh-acme-1'}, ids)
        self.assertNotIn('gh-gone-9', ids)

    def test_posting_must_be_saved(self):
        os.remove(os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt'))
        self.check(dict(rows=[row('gh-acme-1')]), 'no saved posting')

    def test_apply_rejects_whole_file_and_writes_nothing(self):
        score.run(self.ctx, out=lambda *a: None)
        before = open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8').read()
        out = self.cli('reads', '--apply', self.reply_file(row('gh-acme-1'), row('gh-acme-1', gap='bogus')))
        self.assertIn('nothing saved', out)
        self.assertIn("gap_type 'bogus'", out)
        self.assertFalse(os.path.exists(os.path.join(self.ctx.state, 'reads')))
        self.assertEqual(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8').read(), before)


class CacheTest(ReadsBase):
    def test_valid_until_posting_or_resume_changes(self):
        self.cache(row('gh-acme-1', gap='minor', top='no SQL', concerns='thin on data'))
        rd = reads.valid(self.ctx.state, 'gh-acme-1', self.reader.resume)
        self.assertEqual((rd['gap_type'], rd['top_gap'], rd['concerns']), ('minor', 'no SQL', 'thin on data'))
        self.assertEqual(set(reads.public(rd)), {'id', 'gap_type', 'top_gap', 'gap_quote', 'strengths', 'needs', 'read_at'})
        self.assertIsNone(reads.valid(self.ctx.state, 'gh-acme-6', self.reader.resume))  # never read
        jd = open(os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt'), encoding='utf-8').read()
        self.assertEqual(reads.valid(self.ctx.state, 'gh-acme-1', self.reader.resume, jd)['id'], 'gh-acme-1')  # JD text given
        self.assertIsNone(reads.valid(self.ctx.state, 'gh-acme-1', self.reader.resume, jd + ' changed'))
        self.assertIsNone(reads.valid(self.ctx.state, 'gh-acme-1', self.reader.resume + '\nNew job'))
        with open(os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\nNow also: travel 50%.')
        self.assertIsNone(self.reader('gh-acme-1'))  # the posting changed: stale

    def test_safe_file_name(self):
        self.assertTrue(reads.path_of('/s', 'gh/odd id:1').endswith(os.path.join('reads', 'gh_odd_id_1.json')))


class ScoringTest(ReadsBase):
    def test_critical_read_gets_own_tier_and_frees_the_company_cap(self):
        before = self.score()
        self.assertEqual((before['gh-acme-1']['tier'], before['gh-acme-6']['tier']), ('B', 'cap'))
        self.cache(row('gh-acme-1', 'critical', 'JD or law degree required', 'Juris Doctor required'))
        after = self.score()
        g = after['gh-acme-1']
        self.assertEqual((g['tier'], g['review'], g['fit'], g['ats']), ('gap', 'no', before['gh-acme-1']['fit'], before['gh-acme-1']['ats']))
        self.assertEqual(g['why'], 'Critical gap: JD or law degree required, so it was taken out of review: "Juris Doctor required"')
        self.assertEqual(g['read']['gap_type'], 'critical')
        self.assertNotIn('concerns', g['read'])
        self.assertEqual(after['gh-acme-6']['tier'], 'C+')  # took the cap slot the gap role no longer uses
        refs = [r['id'] for r in sorted(after.values(), key=lambda r: r['ref'])]
        self.assertEqual(refs[-1], 'gh-acme-1')  # after the reviewable and the C tiers (no gate rows in this run)
        rows = list(csv.DictReader(open(os.path.join(self.ctx.queue, f'scored-{DATE}.csv'), encoding='utf-8', newline='')))
        self.assertEqual(rows[-1]['id'], 'gh-acme-1')
        self.assertEqual(rows[-1]['tier'], 'gap')

    def test_gap_rows_sit_before_gate_rows(self):
        self.cache(row('gh-acme-1', 'critical', 'x'))
        with mock.patch.object(score.hosts, 'check', side_effect=lambda u: ('lookalike', 'greenhouse') if u and 'initech' in u else (None, None)), \
                mock.patch.object(score, 'gates_on', return_value=True), mock.patch.object(score, 'gate_profile', return_value=None):
            by = self.score()
        order = [r['tier'] for r in sorted(by.values(), key=lambda r: r['ref'])]
        self.assertEqual(order[-2:], ['gap', 'gate'])

    def test_major_read_holds_an_a_to_b_with_its_own_why(self):
        self.set_config(lambda c: c.update(scoring={'tier_a': 66, 'tier_b': 55}))
        self.assertEqual(self.score()['gh-acme-1']['tier'], 'A')
        self.cache(row('gh-acme-1', 'major', 'no people management'))
        r = self.score()['gh-acme-1']
        self.assertEqual(r['tier'], 'B')
        self.assertEqual(r['why'], 'Fit 66 is at or above the A line (66), held to B: major gap (no people management).')
        self.assertTrue(r['gap_hold'])
        self.assertEqual(r['review'], 'yes')

    def test_why_names_both_holds(self):
        sc = dict(tier_a=70, tier_b=55, near_miss_margin=5, over_bar_tier='B')
        both = dict(company='Brightwater', fit=80, tier='B', over_bar=True, gap_hold=True, read=dict(top_gap='no SQL'), flags=[])
        over = dict(company='Brightwater', fit=80, tier='B', over_bar=True, flags=[])
        major = dict(company='Brightwater', fit=80, tier='B', gap_hold=True, read=dict(top_gap='no SQL'), flags=[])
        runrecord.explain([both, over, major], sc, 5, 90, {}, {})
        self.assertEqual(both['why'], 'Fit 80 is at or above the A line (70), held to B: it asks for more than your profile shows (see flags); '
                                      'also a major gap (no SQL).')
        self.assertEqual(over['why'], 'Fit 80 is at or above the A line (70), held to B: it asks for more than your profile shows (see flags).')
        self.assertEqual(major['why'], 'Fit 80 is at or above the A line (70), held to B: major gap (no SQL).')

    def test_flag_settings_only_add_a_flag(self):
        base = self.score()
        self.set_config(lambda c: c.update(scoring={'gap_rules': {'critical': 'flag', 'major': 'flag'}}))
        self.cache(row('gh-acme-1', 'critical', 'no JD; law degree'), row('hm-initech-cos', 'major', 'no SQL'))
        by = self.score()
        self.assertEqual((by['gh-acme-1']['tier'], by['hm-initech-cos']['tier']), ('B', 'B'))
        self.assertIn('critical gap: no JD, law degree', by['gh-acme-1']['flags'])  # ';' would split the flag
        self.assertIn('major gap: no SQL', by['hm-initech-cos']['flags'])
        self.assertEqual(by['gh-acme-1']['why'], base['gh-acme-1']['why'])
        self.assertEqual(by['gh-acme-6']['tier'], 'cap')

    def test_minor_and_none_reads_change_nothing_but_the_read_key(self):
        base = self.score()
        self.cache(row('gh-acme-1', 'minor', 'no SQL', strengths=[strong('OKR cadence', 'excellent')]), row('hm-initech-cos'))
        by = self.score()
        for rid in ('gh-acme-1', 'hm-initech-cos'):
            self.assertEqual({k: v for k, v in by[rid].items() if k != 'read'}, base[rid])
            self.assertIn('read', by[rid])
        self.assertEqual(by['gh-acme-1']['read']['strengths'][0]['level'], 'excellent')

    def test_bad_gap_rule_is_named(self):
        with self.assertRaises(SystemExit) as cm:
            triage.gap_rules({'gap_rules': {'major': 'A'}})
        self.assertIn('scoring.gap_rules.major', str(cm.exception))
        self.assertEqual(triage.gap_rules({}), {'critical': 'section', 'major': 'B'})

    def test_no_reads_leaves_the_output_byte_identical(self):
        def snapshot():
            rec = json.load(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8'))
            for k in ('discover', 'score'):
                rec[k].pop('at')
            return open(os.path.join(self.ctx.queue, f'scored-{DATE}.csv'), 'rb').read(), json.dumps(rec, indent=1, ensure_ascii=False)
        self.score()
        plain, rec = snapshot()
        self.assertEqual(list(json.loads(rec)['roles'][0]), ROLE_KEYS)
        self.assertEqual(list(json.loads(rec)['score']['settings']), ['tier_a', 'tier_b', 'near_miss_margin', 'cap', 'window_days', 'location_drops'])
        self.assertNotIn('"read"', rec)
        self.assertNotIn('gap_hold', rec)
        os.makedirs(os.path.join(self.ctx.state, 'reads'))  # an empty reads dir
        self.score()
        self.assertEqual(snapshot(), (plain, rec))
        self.cache(row('gh-acme-1', 'critical', 'x'))
        with open(os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\nChanged after the read.')  # a stale read counts as no read
        self.score()
        csv_bytes, rec2 = snapshot()
        self.assertEqual(rec2.replace('Changed after the read.', ''), rec2)
        self.assertEqual(csv_bytes, plain)


class CommandTest(ReadsBase):
    def setUp(self):
        super().setUp()
        self.by = self.score()
        self.reviewed = os.path.join(self.ctx.queue, f'reviewed-{DATE}.csv')

    def reviewed_rows(self):
        return {r['id']: r for r in csv.DictReader(open(self.reviewed, encoding='utf-8', newline=''))}

    def test_lists_unread_ab_roles_with_hints_and_json(self):
        out = self.cli('reads')
        self.assertIn('gh-acme-1  Acme Robotics: ', out)
        self.assertIn('[B, fit 66]', out)
        self.assertIn('gh-acme-1.txt', out)
        self.assertNotIn('gh-acme-6', out)  # tier cap: not asked for
        self.assertNotIn('ab-globex-1', out)  # tier C
        data = json.loads(self.cli('reads', '--json'))
        r = next(x for x in data['roles'] if x['id'] == 'gh-acme-1')
        self.assertEqual((r['tier'], r['fit']), ('B', 66))
        self.assertTrue(r['jd'].endswith('gh-acme-1.txt'))
        self.assertIsInstance(r['strength_hits'], list)
        self.assertEqual([x['id'] for x in data['roles']], ['gh-acme-1', 'hm-initech-cos'])
        self.cache(row('gh-acme-1'))
        self.assertEqual([x['id'] for x in json.loads(self.cli('reads', '--json'))['roles']], ['hm-initech-cos'])

    def test_critical_gap_roles_are_listed_until_read_again(self):
        self.cache(row('gh-acme-1', 'critical', 'x'))
        self.score()
        self.assertNotIn('gh-acme-1', self.cli('reads'))
        with open(os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\nUpdated.')
        self.assertIn('gh-acme-1', self.cli('reads'))  # the posting changed: the read is stale, so it is asked for again
        self.assertEqual(self.reader('gh-acme-1'), None)

    def test_ids_lists_any_role_dropped_posting_or_reviewed_row(self):
        d = next(d for d in runrecord.load(self.ctx.queue, DATE)['dropped'] if d['reason'] == 'location')
        out = self.cli('reads', '--ids', 'gh-acme-6', d['id'])
        self.assertIn('gh-acme-6  Acme Robotics', out)
        self.assertIn('[cap, fit 50]', out)
        self.assertIn(f"{d['id']}  ", out)
        self.assertIn('[dropped', out)
        self.assertIn('not in the', self.cli('reads', '--ids', 'zz-none'))

    def test_apply_before_picks_scores_again_with_the_reads(self):
        out = self.cli('reads', '--apply', self.reply_file(row('gh-acme-1', 'critical', 'law degree required', 'JD required'), row('hm-initech-cos')))
        self.assertIn('Cached 2 read(s)', out)
        self.assertIn('Tiers:', out)
        self.assertIn('Gap read: 1 critical (own section)', out)
        rec = runrecord.load(self.ctx.queue, DATE)
        by = {r['id']: r for r in rec['roles']}
        self.assertEqual(by['gh-acme-1']['tier'], 'gap')
        self.assertIn('read', by['hm-initech-cos'])
        self.assertTrue(any(d['stage'] == 'discover' for d in rec['dropped']))
        page = open(os.path.join(self.ctx.queue, f'review-{DATE}.html'), encoding='utf-8').read()
        self.assertIn('law degree required', page)
        self.assertNotIn('Gap read:', self.cli('reads', '--ids', 'gh-acme-1'))

    def test_apply_scores_again_as_of_the_run_date(self):
        from unittest import mock
        from engine import score
        seen = []
        with mock.patch.object(score, 'run', lambda ctx, src, out=print: seen.append(ctx.today)):
            self.cli('reads', '--apply', self.reply_file(row('hm-initech-cos')))
        self.assertEqual(seen, [datetime.date.fromisoformat(DATE)])  # cap windows count from the run's day, not today

    def test_apply_after_picks_keeps_refs_and_fills_reviewed_rows(self):
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1; hold 2'))
        self.assertEqual(self.reviewed_rows()['gh-acme-1']['gap_type'], '')
        before = open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8').read()
        out = self.cli('reads', '--apply', self.reply_file(row('gh-acme-1', 'major', 'no SQL'), row('hm-initech-cos', 'minor', 'x')))
        self.assertIn('not scored again', out.replace('was not scored again', 'not scored again'))
        self.assertIn('Filled gap_type/top_gap (and pay with no posted range) on 2 reviewed row(s)', out)
        self.assertNotIn('Tiers:', out)
        self.assertEqual(open(runrecord.path_for(self.ctx.queue, DATE), encoding='utf-8').read(), before)
        rows = self.reviewed_rows()
        self.assertEqual((rows['gh-acme-1']['gap_type'], rows['gh-acme-1']['top_gap']), ('major', 'no SQL'))
        self.assertEqual(rows['gh-acme-1']['call'], 'apply')
        self.assertEqual(rows['hm-initech-cos']['gap_type'], 'minor')

    def test_apply_after_picks_leaves_filled_fields_alone(self):
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1'))
        runrecord.fill(self.ctx.queue, DATE, 'gh-acme-1', dict(gap_type='none', top_gap='by hand'))
        self.cli('reads', '--apply', self.reply_file(row('gh-acme-1', 'major', 'no SQL')))
        r = self.reviewed_rows()['gh-acme-1']
        self.assertEqual((r['gap_type'], r['top_gap']), ('none', 'by hand'))


class PicksTest(ReadsBase):
    def setUp(self):
        super().setUp()
        self.score()
        self.reviewed = os.path.join(self.ctx.queue, f'reviewed-{DATE}.csv')

    def rows(self):
        return {r['id']: r for r in csv.DictReader(open(self.reviewed, encoding='utf-8', newline=''))}

    def test_new_row_takes_gap_fields_from_the_read(self):
        self.cache(row('gh-acme-1', 'major', 'no SQL'), row('hm-initech-cos'))
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1 2'), reader=self.reader)
        rows = self.rows()
        self.assertEqual((rows['gh-acme-1']['gap_type'], rows['gh-acme-1']['top_gap']), ('major', 'no SQL'))
        self.assertEqual((rows['hm-initech-cos']['gap_type'], rows['hm-initech-cos']['top_gap']), ('none', ''))

    def test_no_read_keeps_the_old_behaviour(self):
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1'), reader=self.reader)
        self.assertEqual(self.rows()['gh-acme-1']['gap_type'], '')

    def test_stale_read_is_not_copied(self):
        self.cache(row('gh-acme-1', 'major', 'no SQL'))
        with open(os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\nChanged.')
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1'), reader=self.reader)
        self.assertEqual(self.rows()['gh-acme-1']['gap_type'], '')

    def test_existing_row_with_empty_gap_fields_gets_them(self):
        with open(self.reviewed, 'w', newline='', encoding='utf-8') as fh:
            fh.write('call,gap_type,top_gap,company,title,summary_variant,id\nhold,,,Acme Robotics,Chief of Staff to the CEO,Operator,gh-acme-1\n'
                     'hold,minor,kept,Initech,Chief of Staff,,hm-initech-cos\n')
        self.cache(row('gh-acme-1', 'major', 'no SQL'), row('hm-initech-cos', 'critical', 'other'))
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1 2'), reader=self.reader)
        rows = self.rows()
        self.assertEqual((rows['gh-acme-1']['gap_type'], rows['gh-acme-1']['top_gap'], rows['gh-acme-1']['summary_variant']), ('major', 'no SQL', 'Operator'))
        self.assertEqual((rows['hm-initech-cos']['gap_type'], rows['hm-initech-cos']['top_gap']), ('minor', 'kept'))

    def test_picking_a_gap_tier_role_warns(self):
        self.cache(row('gh-acme-1', 'critical', 'law degree required', 'JD required'))
        self.score()
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(id='gh-acme-1', call='apply')], reader=self.reader)
        self.assertEqual(warn, [f"#{self.ref_of('gh-acme-1')} Acme Robotics: critical gap (law degree required); check before applying"])
        row_ = self.rows()['gh-acme-1']
        self.assertEqual((row_['gap_type'], row_['top_gap']), ('critical', 'law degree required'))
        _, warn, _ = runrecord.apply_picks(self.ctx.queue, DATE, [dict(id='gh-acme-1', call='hold')], reader=self.reader)
        self.assertEqual(warn, [])  # only apply and manual warn

    def ref_of(self, rid):
        return next(r['ref'] for r in runrecord.load(self.ctx.queue, DATE)['roles'] if r['id'] == rid)

    def test_cli_picks_uses_the_cache(self):
        self.cache(row('gh-acme-1', 'minor', 'no SQL'))
        out = self.cli('picks', 'apply 1')
        self.assertEqual(self.rows()['gh-acme-1']['gap_type'], 'minor')
        self.assertIn('gh-acme-1', out)
        self.assertIn('missing: materials', out)
        self.assertNotIn('missing: read', out)


class TodoTest(ReadsBase):
    def setUp(self):
        super().setUp()
        self.score()

    def test_todo_names_what_is_missing(self):
        self.cache(row('gh-acme-1', 'minor', 'x'))
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1 2; hold 3'), reader=self.reader)
        left = {t['id']: t for t in runrecord.todo(self.ctx.queue, DATE)}
        self.assertEqual(set(left), {'gh-acme-1', 'hm-initech-cos'})  # hold rows need nothing
        self.assertEqual(left['gh-acme-1']['missing'], ['materials'])
        self.assertEqual(left['hm-initech-cos']['missing'], ['read', 'materials'])
        runrecord.fill(self.ctx.queue, DATE, 'hm-initech-cos', dict(gap_type='none'))
        self.assertEqual(runrecord.todo(self.ctx.queue, DATE)[1]['missing'], ['materials'])
        for rid in ('gh-acme-1', 'hm-initech-cos'):
            runrecord.fill(self.ctx.queue, DATE, rid, dict(summary_variant='Operator', template_script='Brightwater-Ops'))
        self.assertEqual(len(runrecord.todo(self.ctx.queue, DATE)), 2)  # lead_material still empty
        for rid in ('gh-acme-1', 'hm-initech-cos'):
            runrecord.fill(self.ctx.queue, DATE, rid, dict(lead_material='OKR cycle'))
        self.assertEqual(runrecord.todo(self.ctx.queue, DATE), [])

    def test_cli_todo_wording(self):
        runrecord.apply_picks(self.ctx.queue, DATE, runrecord.parse_picks('apply 1'))
        out = self.cli('todo')
        self.assertIn('missing: read and materials', out)
        self.assertIn('gh-acme-1.txt', out)
        for rid in ('gh-acme-1',):
            runrecord.fill(self.ctx.queue, DATE, rid, dict(gap_type='none', summary_variant='a', template_script='b', lead_material='c'))
        self.assertIn('Nothing to fill', self.cli('todo'))


class SummaryAndPageTest(ReadsBase):
    def test_summary_line(self):
        self.set_config(lambda c: c.update(scoring={'tier_a': 66, 'tier_b': 55}))
        by = self.score()
        rec = runrecord.load(self.ctx.queue, DATE)
        self.assertIn('Gap read: 2 A/B roles not read yet (gmh review reads).', runrecord.summary(rec))
        self.cache(row('gh-acme-1', 'major', 'no SQL'), row('hm-initech-cos', 'critical', 'law degree required'))
        self.score()
        lines = runrecord.summary(runrecord.load(self.ctx.queue, DATE))
        self.assertIn('Gap read: 1 critical (own section), 1 A held to B for a major gap.', lines)
        self.assertIn('1 gap', [l for l in lines if l.startswith('Run ')][0])
        self.assertEqual(by['gh-acme-1']['tier'], 'A')

    def test_no_line_when_nothing_to_say(self):
        rec = dict(date=DATE, roles=[dict(tier='C', new=True, ref=1)], dropped=[], picks={})
        self.assertFalse([l for l in runrecord.summary(rec) if l.startswith('Gap read')])

    def test_cli_summary_counts_the_cache_not_the_record(self):
        self.score()
        self.assertIn('2 A/B roles not read yet', self.cli('summary'))
        self.cache(row('gh-acme-1'), row('hm-initech-cos'))
        self.assertNotIn('Gap read', self.cli('summary'))

    def test_page_has_the_critical_gap_section_and_badges(self):
        self.cache(row('gh-acme-1', 'critical', 'law degree required', 'JD required'),
                   row('hm-initech-cos', 'minor', 'no SQL', strengths=[strong('OKR cadence', 'excellent'), strong('board decks')]))
        self.score()
        html = open(os.path.join(self.ctx.queue, f'review-{DATE}.html'), encoding='utf-8').read()
        self.assertIn("['gap', 'Critical gap'", html)
        self.assertIn('--t-gap', html)
        self.assertEqual(re.findall(r'<script[^>]*src="([^"]+)"', html), [])
        data = json.loads(re.search(r'const DATA = (.*?);\nconst CALLS', html, re.S).group(1))
        by = {r['id']: r for r in runrecord.page_roles(data)}
        self.assertEqual(by['gh-acme-1']['tier'], 'gap')
        self.assertEqual(by['gh-acme-1']['read']['gap_quote'], 'JD required')
        self.assertEqual([s['level'] for s in by['hm-initech-cos']['read']['strengths']], ['excellent', 'strong'])


if __name__ == '__main__':
    unittest.main()
