"""Same-day rerun guard on `gmh discover` / `gmh score`, and the ATS negative cache that retries transient failures."""
import contextlib, datetime, io, json, os, sys, tempfile, unittest, urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from engine import boards, discover, runrecord, score, setup  # noqa: E402
from engine.sources import ats, base  # noqa: E402
import test_discover_score as tds  # noqa: E402  (the module, so unittest doesn't collect its test classes twice)
from test_discover_score import ADAPTERS, fake_resolve  # noqa: E402

TODAY = datetime.date(2026, 10, 20)


class Tty(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class Guard(tds.CosEndToEnd):
    """CosEndToEnd's workspace and fakes, driving main() instead of run()."""

    def cli(self, mod, *args, tty=False, answer='n'):
        out, real, real_run = Tty(tty), discover.Ctx, mod.run
        searchers = {n: self.searcher(n) for n in discover.DEFAULT_SOURCES}
        fakes = dict(ats_adapters=ADAPTERS, resolver=fake_resolve, pay_lookup=lambda *x, **y: None) if mod is discover else {}
        run = lambda c, *a, **k: real_run(c, *a, **{**k, **fakes})
        # main() builds its own Ctx and calls run() with the real adapters: pin the date and swap in the fakes
        ctx = lambda ws: real(ws, today=TODAY)
        with mock.patch.dict(boards.SEARCHERS, searchers), mock.patch.object(mod, 'run', run), \
                mock.patch.object(discover, 'Ctx', ctx), mock.patch.object(score, 'Ctx', ctx), \
                mock.patch('sys.stdin', Tty(tty)), \
                mock.patch('builtins.input', return_value=answer) as inp, contextlib.redirect_stdout(out):
            try:
                mod.main(['--workspace', self.ws, *args])
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), inp

    def paths(self):
        q = discover.Ctx(self.ws, today=TODAY).queue
        return os.path.join(q, 'discovered-2026-10-20.csv'), os.path.join(q, 'scored-2026-10-20.csv')

    def newer(self, path, delta):
        t = os.path.getmtime(path) + delta
        os.utime(path, (t, t))

    def test_discover_guard_and_force(self):
        self.assertEqual(self.cli(discover)[0], 0)
        disc, _ = self.paths()
        before = open(disc, encoding='utf-8').read()
        code, text, _ = self.cli(discover)
        self.assertEqual(code, 3)
        self.assertEqual(text.splitlines()[0], 'RERUN-GUARD: discover 2026-10-20')
        self.assertIn('already ran (2026-10-20, finished at', text)
        self.assertIn('--force', text)
        self.assertLess(len(text.splitlines()), 12)
        self.assertEqual(open(disc, encoding='utf-8').read(), before)  # nothing overwritten, nothing marked seen
        self.assertEqual(self.cli(discover, '--force')[0], 0)

    def test_warning_counts_confirmed_picks(self):
        self.cli(discover)
        q = os.path.dirname(self.paths()[0])
        rec = runrecord.load(q, '2026-10-20')
        rec['picks'] = {'gh-acme-1': {'call': 'apply'}, 'gh-acme-6': {'call': 'hold'}}
        runrecord.save(q, rec)
        self.assertIn('already confirmed (2)', self.cli(discover)[1])

    def test_score_follows_a_newer_discover_and_guards_a_newer_score(self):
        self.cli(discover)
        disc, scored = self.paths()
        self.assertEqual(self.cli(score)[0], 0)  # no scored file yet
        self.newer(disc, 10)  # discover ran again after that score
        self.assertEqual(self.cli(score)[0], 0)
        self.newer(scored, 20)  # scored is now the newer one
        code, text, _ = self.cli(score)
        self.assertEqual(code, 3)
        self.assertEqual(text.splitlines()[0], 'RERUN-GUARD: score 2026-10-20')
        self.assertEqual(self.cli(score, '--force')[0], 0)

    def test_tty_asks(self):
        self.cli(discover)
        code, text, inp = self.cli(discover, tty=True, answer='n')
        self.assertEqual(code, 3)
        inp.assert_called_once_with('Run it again anyway? [y/N] ')
        self.assertIn('RERUN-GUARD', text)
        code, _, inp = self.cli(discover, tty=True, answer='yes')
        self.assertEqual(code, 0)
        inp.assert_called_once()


for _n in dir(tds.CosEndToEnd):
    if _n.startswith('test_'):
        if _n not in Guard.__dict__:
            setattr(Guard, _n, None)  # the inherited end-to-end tests already run in test_discover_score


def http_error(code):
    return urllib.error.HTTPError('http://x', code, 'err', {}, None)


class Transient(unittest.TestCase):
    def test_fetch_error_flags(self):
        with mock.patch('time.sleep'):
            for err, transient in ((http_error(503), True), (http_error(429), True), (http_error(403), False),
                                   (urllib.error.URLError('down'), True), (TimeoutError(), True)):
                with mock.patch('urllib.request.urlopen', side_effect=err), self.assertRaises(base.FetchError) as cx:
                    base.fetch('http://x', retries=1)
                self.assertEqual(cx.exception.transient, transient, err)
            with mock.patch('urllib.request.urlopen', side_effect=http_error(404)):
                self.assertEqual(base.fetch('http://x'), '')

    def test_resolve_distinguishes_miss_from_outage(self):
        with mock.patch.object(ats, 'fetch_json', side_effect=base.FetchError('HTTP 403', transient=False)):
            self.assertIsNone(ats.resolve(['acme']))  # definite
        with mock.patch.object(ats, 'fetch_json', side_effect=base.FetchError('HTTP 503', transient=True)), \
                self.assertRaises(base.FetchError) as cx:
            ats.resolve(['acme'])
        self.assertTrue(cx.exception.transient)
        with mock.patch.object(ats, 'fetch_json', return_value=None):
            self.assertIsNone(ats.resolve(['acme']))
        # one working guess wins even if another attempt failed
        def fj(url, **kw):
            if 'greenhouse' in url:
                raise base.FetchError('x', transient=True)
            return [{'id': 'a', 'text': 't'}] if 'lever' in url else None
        with mock.patch.object(ats, 'fetch_json', fj):
            self.assertEqual(ats.resolve(['acme']), ['lever', 'acme'])

    def test_board_callers_treat_an_outage_as_a_miss(self):
        boom = base.FetchError('HTTP 503', transient=True)
        with mock.patch.dict(ats.ADAPTERS, {'greenhouse': mock.Mock(side_effect=boom)}):
            self.assertEqual(boards._fetch_board(('greenhouse', 'acme'), 'Acme'), [])

    def probe(self, cache, misses, resolver, day):
        return ats.probe_companies(cache, misses, [('Acme', ['acme']), ('Nowhere', ['nowhere'])], resolver, day)

    def test_probe_rules(self):
        d0 = datetime.date(2026, 10, 1)
        cache, misses = {}, {}

        def flaky(slugs, name):
            if name == 'Acme':
                raise base.FetchError('HTTP 503', transient=True)
        self.assertEqual(self.probe(cache, misses, flaky, d0), ['Acme'])
        self.assertEqual((cache, misses), ({'Nowhere': None}, {'Nowhere': '2026-10-01'}))  # outage not cached
        hit = lambda slugs, name: ['greenhouse', 'acme'] if name == 'Acme' else None
        self.assertEqual(self.probe(cache, misses, hit, d0 + datetime.timedelta(days=14)), [])
        self.assertEqual(cache['Acme'], ['greenhouse', 'acme'])
        self.assertEqual(misses, {'Nowhere': '2026-10-01'})
        seen = []
        counter = lambda slugs, name: seen.append(name)
        self.probe(cache, misses, counter, d0 + datetime.timedelta(days=14))
        self.assertEqual(seen, [])  # a hit is trusted, a miss within 14 days is not re-probed
        self.probe(cache, misses, counter, d0 + datetime.timedelta(days=15))
        self.assertEqual(seen, ['Nowhere'])
        self.assertEqual(misses['Nowhere'], '2026-10-16')
        cache['Acme'], misses['Acme'] = None, '2026-01-01'  # a hit later drops the miss date
        self.probe(cache, misses, hit, d0 + datetime.timedelta(days=15))
        self.assertNotIn('Acme', misses)
        self.assertEqual(cache['Acme'], ['greenhouse', 'acme'])

    def test_legacy_none_without_date_is_reprobed_once(self):
        cache, misses, seen = {'Acme': None, 'Nowhere': None}, {'Nowhere': '2026-10-19'}, []
        self.probe(cache, misses, lambda s, n: seen.append(n), datetime.date(2026, 10, 20))
        self.assertEqual(seen, ['Acme'])
        self.assertEqual(misses['Acme'], '2026-10-20')

    def test_discover_run_retries_after_outage(self):
        t = tds.CosEndToEnd('test_discover_then_score')
        t.setUp()
        self.addCleanup(t.tearDown)
        fail, lines = [True], []

        def resolver(slugs, name):
            if fail[0] and name == 'Acme Robotics':
                raise base.FetchError('HTTP 503', transient=True)
            return fake_resolve(slugs, name)

        def go():
            ctx = discover.Ctx(t.ws, today=TODAY)
            with mock.patch.dict(boards.SEARCHERS, {n: t.searcher(n) for n in discover.DEFAULT_SOURCES}):
                discover.run(ctx, ats_adapters=ADAPTERS, resolver=resolver, pay_lookup=lambda *a, **k: None, out=lines.append)
            return [json.load(open(os.path.join(ctx.state, f), encoding='utf-8')) for f in ('ats_cache.json', 'ats_misses.json')]
        cache, misses = go()
        self.assertNotIn('Acme Robotics', cache)
        self.assertEqual(misses, {'Nowhere Corp': '2026-10-20'})
        self.assertTrue(any(l.startswith("Couldn't reach (will retry next run): Acme Robotics") for l in lines))
        self.assertFalse(any('Acme Robotics' in l for l in lines if l.startswith('Not resolved')))
        fail[0] = False
        self.assertEqual(go()[0]['Acme Robotics'], ['greenhouse', 'acme'])

    def test_setup_resolve_companies_follows_the_same_rules(self):
        ws = tempfile.mkdtemp()
        open(os.path.join(ws, 'companies.txt'), 'w', encoding='utf-8', newline='\n').write('Acme Robotics | acme\nNowhere Corp\n')
        fail, seen = [True], []

        def fetch(slugs, name):
            seen.append(name)
            if name == 'Acme Robotics':
                if fail[0]:
                    raise base.FetchError('boom', transient=True)
                return ['greenhouse', 'acme']
        state, day = os.path.join(ws, 'Pipeline', 'state'), datetime.date(2026, 10, 1)
        self.assertEqual(setup.resolve_companies(ws, fetch, day), {'Nowhere Corp': None})
        self.assertEqual(json.load(open(os.path.join(state, 'ats_misses.json'), encoding='utf-8')), {'Nowhere Corp': '2026-10-01'})
        fail[0], seen[:] = False, []
        cache = setup.resolve_companies(ws, fetch, day + datetime.timedelta(days=3))
        self.assertEqual(seen, ['Acme Robotics'])
        self.assertEqual(cache, {'Acme Robotics': ['greenhouse', 'acme'], 'Nowhere Corp': None})
        seen[:] = []
        setup.resolve_companies(ws, fetch, day + datetime.timedelta(days=20))
        self.assertEqual(seen, ['Nowhere Corp'])


if __name__ == '__main__':
    unittest.main()
