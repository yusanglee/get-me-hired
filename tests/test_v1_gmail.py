"""v1.0 E2: gmail ingest, decide, sectioned propose table, counts after apply, pack role words."""
import contextlib, io, json, os, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import gmail_import as gi, setup, tracker  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'gmail', 'incoming.jsonl')


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            gi.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue(), err.getvalue()


def thread(tid, msgs):
    """A connector-shaped thread built from incoming.jsonl style messages (no bodies)."""
    return {'id': tid, 'viewUrl': f'https://mail.example/#all/{tid}',
            'messages': [{'id': m['id'], 'subject': m['subject'], 'sender': m['sender'], 'date': m['date'],
                          'snippet': m.get('snippet', '')} for m in msgs]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, 'ws')
        setup.init(self.ws, 'chief-of-staff')
        self.msgs = gi.read_incoming(FIX)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(obj, fh, ensure_ascii=False)
        return p

    def pages(self):
        by_thread = {}
        for m in self.msgs:
            by_thread.setdefault(m['thread_id'], []).append(m)
        threads = [thread(t, ms) for t, ms in by_thread.items()]
        return threads[:4], threads[4:]


class IngestTest(Base):
    def test_page_list_and_threads_all_accepted_and_unioned(self):
        a, b = self.pages()
        p1 = self.write('p1.json', {'threads': a, 'nextPageToken': 'x'})
        p2 = self.write('p2.json', [{'threads': b}, {'threads': a[:1]}])  # a list of pages, one thread repeated
        out = os.path.join(self.tmp, 'in.jsonl')
        code, text, _ = run('ingest', p1, p2, '--out', out)
        self.assertEqual(code, 0)
        n = len({m['thread_id'] for m in self.msgs})
        self.assertEqual(text.strip(), f'{n} threads ({n} new) -> {out}')
        got = gi.read_incoming(out)
        self.assertEqual({m['id'] for m in got}, {m['id'] for m in self.msgs})
        p3 = self.write('p3.json', a + b)  # a bare list of threads
        out2 = os.path.join(self.tmp, 'in2.jsonl')
        run('ingest', p3, '--out', out2)
        self.assertEqual(gi.read_incoming(out), gi.read_incoming(out2))

    def test_viewurl_kept_and_second_run_counts_new(self):
        a, b = self.pages()
        out = os.path.join(self.tmp, 'in.jsonl')
        run('ingest', self.write('p1.json', {'threads': a}), '--out', out)
        self.assertTrue(all(m['url'].startswith('https://mail.example/#all/') for m in gi.read_incoming(out)))
        _, text, _ = run('ingest', self.write('p2.json', {'threads': a + b}), '--out', out)
        total = len({m['thread_id'] for m in self.msgs})
        self.assertIn(f'{total} threads ({total - len(a)} new) -> ', text)

    def test_flat_thread_without_messages_and_epoch_dates(self):
        flat = {'id': 'th1', 'subject': 'Thank you for applying to Brightwater', 'sender': 'Brightwater <no-reply@greenhouse.io>',
                'snippet': 'Thanks for applying', 'internalDate': '1783000000000', 'viewUrl': 'https://mail.example/#all/th1'}
        out = os.path.join(self.tmp, 'in.jsonl')
        run('ingest', self.write('p.json', {'threads': [flat]}), '--out', out)
        (m,) = gi.read_incoming(out)
        self.assertEqual((m['id'], m['thread_id']), ('th1', 'th1'))
        self.assertRegex(m['date'], r'^\d{4}-\d\d-\d\d$')

    def test_no_bodies_stored_and_utf8(self):
        t = thread('t1', [{'id': 'a1', 'subject': 'Candidature reçue — Café Co', 'sender': 'Café Co <jobs@cafe.example>',
                           'date': '2026-07-01'}])
        t['messages'][0]['body'] = 'SECRET BODY TEXT'
        out = os.path.join(self.tmp, 'in.jsonl')
        run('ingest', self.write('p.json', [t]), '--out', out)
        raw = open(out, encoding='utf-8').read()
        self.assertNotIn('SECRET BODY TEXT', raw)
        self.assertIn('Café', raw)

    def test_default_path_is_workspace_state(self):
        a, _ = self.pages()
        code, text, _ = run('ingest', self.write('p.json', {'threads': a}), '--workspace', self.ws)
        want = os.path.abspath(os.path.join(self.ws, 'state', 'gmail', 'incoming.jsonl'))
        self.assertTrue(os.path.exists(want))
        self.assertTrue(text.strip().endswith(want))

    def test_ingested_file_gives_the_same_proposal_as_the_original(self):
        a, b = self.pages()
        out = os.path.join(self.tmp, 'in.jsonl')
        run('ingest', self.write('p.json', {'threads': a + b}), '--out', out)
        direct = gi.propose(self.msgs, self.ws)
        via = gi.propose(gi.read_incoming(out), self.ws)

        def shape(p):
            return [(r['company'], r['title'], r['status'], r['action'], r['date_applied']) for r in p['rows']], \
                sorted(u['id'] for u in p['unsure'])
        self.assertEqual(shape(direct), shape(via))

    def test_unreadable_page_exits_nonzero(self):
        bad = os.path.join(self.tmp, 'bad.json')
        open(bad, 'w', encoding='utf-8', newline='\n').write('{nope')
        code, _, err = run('ingest', bad, '--out', os.path.join(self.tmp, 'x.jsonl'))
        self.assertNotEqual(code, 0)

    def test_empty_pages_exit_1(self):
        code, _, _ = run('ingest', self.write('p.json', {'threads': []}), '--out', os.path.join(self.tmp, 'x.jsonl'))
        self.assertEqual(code, 1)


class DecideTest(Base):
    def proposal(self):
        prop = gi.propose(self.msgs, self.ws)
        path = os.path.join(self.tmp, 'proposed.json')
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(prop, fh)
        return prop, path

    def row(self, prop, company):
        return next(r for r in prop['rows'] if r['company'] == company)

    def test_title_and_company_fix_the_unknown_role_row(self):
        prop, path = self.proposal()
        n = self.row(prop, 'Pellucid')['n']
        code, text, _ = run('decide', path, str(n), '--title', 'Chief of Staff', '--workspace', self.ws)
        self.assertEqual(code, 0)
        self.assertIn('Pellucid', text)
        self.assertIn('Chief of Staff', text)
        saved = json.load(open(path, encoding='utf-8'))
        self.assertEqual(self.row(saved, 'Pellucid')['title'], 'Chief of Staff')
        run('decide', path, str(self.row(saved, 'Pellucid')['n']), '--company', 'Pellucid Labs', '--workspace', self.ws)
        saved = json.load(open(path, encoding='utf-8'))
        self.assertEqual(self.row(saved, 'Pellucid Labs')['title'], 'Chief of Staff')

    def test_kind_changes_status_and_is_validated(self):
        prop, path = self.proposal()
        n = self.row(prop, 'Northwind')['n']
        self.assertEqual(self.row(prop, 'Northwind')['status'], 'rejected')
        code, text, _ = run('decide', path, str(n), '--kind', 'interview', '--workspace', self.ws)
        self.assertEqual(code, 0)
        saved = json.load(open(path, encoding='utf-8'))
        self.assertEqual(self.row(saved, 'Northwind')['status'], 'interviewing')
        code, _, err = run('decide', path, '1', '--kind', 'bogus', '--workspace', self.ws)
        self.assertEqual(code, 2)
        self.assertIn('unknown kind', err)

    def test_dismiss_removes_row_and_marks_its_mail_seen_on_apply(self):
        prop, path = self.proposal()
        row = self.row(prop, 'Northwind')
        ids = row['gmail_ids'].split()
        code, text, _ = run('decide', path, str(row['n']), '--dismiss', '--workspace', self.ws)
        self.assertIn('dismissed', text)
        saved = json.load(open(path, encoding='utf-8'))
        self.assertFalse([r for r in saved['rows'] if r['company'] == 'Northwind'])
        self.assertTrue(set(ids) <= {d['id'] for d in saved['dismissed']})
        gi.apply(saved, self.ws, '')
        self.assertTrue(set(ids) <= gi.load_seen(self.ws))

    def test_ranges_lists_and_bad_numbers(self):
        prop, path = self.proposal()
        code, text, _ = run('decide', path, '1-2', '--keep', '--workspace', self.ws)
        self.assertEqual(code, 0)
        self.assertEqual(len([l for l in text.splitlines() if l.startswith('#') or l.startswith('was')]), 2)
        code, _, err = run('decide', path, '99', '--keep', '--workspace', self.ws)
        self.assertEqual(code, 2)
        self.assertIn('no such row', err)
        code, _, _ = run('decide', path, '1', '--workspace', self.ws)  # nothing to change
        self.assertEqual(code, 2)

    def test_decide_does_not_store_bodies(self):
        prop, path = self.proposal()
        run('decide', path, '1', '--role', 'Chief of Staff', '--workspace', self.ws)
        self.assertNotIn('"body"', open(path, encoding='utf-8').read())


class TableTest(Base):
    def seed_tracker(self):
        path = tracker.path_of(self.ws)
        tracker.init(path)
        rows = tracker.read(path)
        tracker.upsert(rows, {'company': 'Northwind', 'title': 'Strategy & Operations Lead', 'status': 'applied',
                              'date_applied': '2026-06-01', 'source': 'pipeline', 'job_key': ''})
        tracker.write(path, rows)

    def test_sections_in_order_and_counts_last(self):
        self.seed_tracker()
        prop = gi.propose(self.msgs, self.ws)
        text = gi.table(prop)
        heads = [l for l in text.splitlines() if l.startswith('## ')]
        self.assertEqual([h.split(' (')[0] for h in heads],
                         ['## Updates to tracked applications', '## New applications', '## Ignored, dismissed and unsure',
                          '## Counts by resulting status'])
        up = text.index('## Updates'), text.index('## New'), text.index('## Ignored'), text.index('## Counts')
        self.assertEqual(list(up), sorted(up))
        updates = text[up[0]:up[1]]
        self.assertIn('Northwind', updates)
        self.assertNotIn('Brightwater', updates)
        self.assertIn('Brightwater', text[up[1]:up[2]])
        self.assertIn('Unsure', text[up[2]:up[3]])
        self.assertRegex(text[up[3]:], r'offer 1')
        self.assertRegex(text[up[3]:], r'rejected 1')

    def test_row_numbers_and_decisions_unchanged_by_the_new_layout(self):
        prop = gi.propose(self.msgs, self.ws)
        text = gi.table(prop)
        for r in prop['rows']:
            self.assertIn(f"| {r['n']} | {r['action']} | {r['company']} |", text)
        self.assertEqual({u['id'] for u in prop['unsure']}, {'m07', 'm09', 'm10'})

    def test_layout_comes_from_the_template(self):
        self.assertTrue(os.path.exists(gi.TEMPLATE))
        orig = gi.TEMPLATE
        try:
            p = os.path.join(self.tmp, 'tpl.md')
            with open(p, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('<!-- propose -->\nCUSTOM {n_new} new / {counts}\n<!-- apply -->\nDONE {added}\n<!-- end -->\n')
            gi.TEMPLATE = p
            self.assertTrue(gi.table(gi.propose(self.msgs, self.ws)).startswith('CUSTOM '))
            gi.TEMPLATE = os.path.join(self.tmp, 'missing.md')  # a missing file falls back to the built-in layout
            self.assertIn('## New applications', gi.table(gi.propose(self.msgs, self.ws)))
        finally:
            gi.TEMPLATE = orig

    def test_apply_ends_with_counts_by_new_status(self):
        prop = gi.propose(self.msgs, self.ws)
        for r in prop['rows']:
            if not r['title']:
                r['title'] = 'Chief of Staff'
        path = os.path.join(self.tmp, 'proposed.json')
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(prop, fh)
        code, text, _ = run('apply', path, '--workspace', self.ws, '--rows', 'all')
        self.assertEqual(code, 0)
        lines = text.strip().splitlines()
        self.assertTrue(lines[0].startswith('tracker.csv: '))
        tail = text[text.index('## Counts by new status'):]
        self.assertIn('offer 1', tail)
        self.assertIn('rejected 1', tail)
        code, js, _ = run('apply', path, '--workspace', self.ws, '--rows', 'all', '--json')
        self.assertEqual(json.loads(js)['counts']['offer'], 1)

    def test_counts_helper(self):
        rows = [{'status': 'rejected'}, {'status': 'applied'}, {'status': 'rejected'}, {'status': 'offer'}]
        self.assertEqual(gi.counts_by_status(rows), 'applied 1, offer 1, rejected 2')
        self.assertEqual(gi.counts_by_status([]), 'none')


class PackWordsTest(Base):
    MSG = {'id': 'x1', 'thread_id': 'x1', 'date': '2026-07-01', 'sender': 'Larkspur Careers <no-reply@greenhouse.io>',
           'subject': 'Thank you for applying to Larkspur', 'snippet': 'Thanks for applying for the Growth Evangelist role.'}

    def write_pack(self, targets):
        p = os.path.join(self.ws, 'pack.json')
        pack = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {'titles': {}}
        pack.setdefault('titles', {})['targets'] = targets
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(pack, fh)

    def test_default_list_unchanged_without_pack_words(self):
        self.assertEqual(gi.extract_role(self.MSG), '')
        self.assertEqual(gi.pack_role_words(os.path.join(self.tmp, 'nowhere')), [])

    def test_words_from_pack_titles_extend_role_detection(self):
        self.write_pack(['Growth Evangelist', 'Senior Chief of Staff'])
        words = gi.pack_role_words(self.ws)
        self.assertIn('evangelist', words)
        self.assertNotIn('chief', words)  # already in the default list
        recs, _ = gi.records([self.MSG], (), words)
        self.assertEqual(recs[0]['role'], 'Growth Evangelist')
        recs, _ = gi.records([self.MSG], ())
        self.assertEqual(recs[0]['role'], '')

    def test_propose_reads_the_workspace_pack(self):
        self.write_pack(['Growth Evangelist'])
        prop = gi.propose([self.MSG], self.ws)
        self.assertEqual(prop['rows'][0]['title'], 'Growth Evangelist')

    def test_broken_pack_falls_back(self):
        with open(os.path.join(self.ws, 'pack.json'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('{broken')
        self.assertEqual(gi.pack_role_words(self.ws), [])


if __name__ == '__main__':
    unittest.main()
