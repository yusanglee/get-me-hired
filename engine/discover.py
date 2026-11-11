"""Stage 1: discover roles on the watchlist's ATS boards and on job boards, using the workspace's pack.

Ported from the original pipeline's discover.py. The PM-only title regexes are gone: a posting's
title passes `packs.title_ok`, a role with no posted range is kept only when `packs.is_senior`,
and job-board searches use the pack's titles.board_queries wherever config.json leaves a source's
queries empty (explicit queries in config win, so a board's volume never grows by surprise).

    python3 -m engine.discover --workspace <ws> [--skip-source linkedin]

Reads:  <ws>/pack.json (or config "pack"), <ws>/config.json, companies.txt (<ws>/ first, else
        <vault>/Pipeline/), <vault>/Pipeline/state/ats_cache.json and seen.json, tracker.csv,
        legacy applied.csv, and the Workflow/ stage folders (already-applied dedup).
Writes: <vault>/Pipeline/queue/discovered-<date>.csv and one JD per kept role in
        <vault>/Pipeline/state/jd/, in the original formats, plus the updated cache and seen files, and
        queue/run-<date>.json with every posting dropped for location or pay and its reason (and its JD,
        so it can be rescued; title misses are not kept) (engine/runrecord.py).
<vault> is config paths.vault; for a workspace made by /setup it is the workspace itself.
"""
import argparse, csv, datetime, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
from . import layout, packs, runrecord, tracker, triage
from .job_key import alias_keys, make_key
from .locations import location_match
from .pay import salary_full, below_floor, lookup_pay, PAIR_RE
from .profile import load_config
from .sources import ats as ats_mod

COLUMNS = ['company', 'title', 'locations', 'location_raw', 'salary_min', 'salary_max', 'salary_source', 'ats', 'url',
           'updated', 'first_seen', 'new', 'already_in_workflow', 'id', 'source']
STAGES = ['01-New Job Posts', '02-Ready to Apply', '03-Applied', '04-Interviewing', 'Passed']
APPLIED_STAGES = ['03-Applied', '04-Interviewing']  # a folder here means applied; earlier stages are only prepared
ATS_PREFIX = {'gh': 'greenhouse', 'lv': 'lever', 'ab': 'ashby'}
# Query-driven boards turned on when config.json has no "sources" section. builtin and remote100k
# search by category path, which is role-specific, so they run only when config names their opts.
DEFAULT_SOURCES = ('himalayas', 'remotive', 'nodesk', 'linkedin')
# source -> (opts key, pack "sources" key) for the boards that search by role category
CATEGORY_OPTS = {'builtin': ('paths', 'builtin_path'), 'remote100k': ('categories', 'remote100k_category')}
PM_PACK = 'product-management'  # the pack whose category defaults live in the searchers


class Ctx:
    """A workspace's settings, pack and pipeline folders."""

    def __init__(self, workspace, today=None):
        self.ws = os.path.abspath(os.path.expanduser(workspace))
        self.cfg = load_config(os.path.join(self.ws, 'config.json'))
        self.pack_path = os.path.join(self.ws, self.cfg.get('pack') or 'pack.json')
        self.pack = packs.load(self.pack_path)
        self.vault = layout.vault(self.ws, self.cfg)
        self.P = os.path.join(self.vault, 'Pipeline')
        self.state = os.path.join(self.P, 'state')
        self.queue = os.path.join(self.P, 'queue')
        self.today = today or datetime.date.today()

    def companies_file(self):
        for d in (self.ws, self.P):
            if os.path.exists(os.path.join(d, 'companies.txt')):
                return os.path.join(d, 'companies.txt')
        return None

    def legacy_applied(self):
        p = os.path.join(self.state, 'applied.csv')
        return [p] if os.path.exists(p) else []

    def known(self, stages=STAGES):
        """(job_keys, ids) already applied or in Workflow: tracker.csv, legacy applied.csv, and folders in these
        Workflow stages. Folder names abbreviate titles ("Staff PM Core"); job_key expands PM, so they match too."""
        aliases = self.cfg.get('company_aliases') or ()
        keys, ids = tracker.known_keys(self.ws, self.legacy_applied(), aliases)
        for _, company, title in workflow_folders(self.vault, stages):
            keys |= alias_keys(company, title, aliases)
        return keys, ids

    def applied(self):
        """known() for roles actually applied to: a folder in 01-New or 02-Ready to Apply is prepared, not applied."""
        return self.known(APPLIED_STAGES)


def workflow_folders(vault, stages):
    """(date, company, title) for every 'YYYY-MM-DD Company - Title' folder in the given stages."""
    out = []
    for stage in stages:
        d = os.path.join(vault, 'Workflow', stage)
        for f in os.listdir(d) if os.path.isdir(d) else []:
            m = re.match(r'(\d{4}-\d{2}-\d{2}) (.+?) - (.+)$', f)
            if m:
                out.append(m.groups())
    return out


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def folder_notes(vault):
    """Normalized 'title company' keys for every job-post note already in a Workflow stage."""
    keys = []
    for stage in STAGES:
        for _, _, files in os.walk(os.path.join(vault, 'Workflow', stage)):
            keys += [norm(f[:-3]) for f in files if f.endswith('.md')]
    return keys


def load_companies(path):
    """[(name, [slug, ...])] from companies.txt ('Name | slug, slug'; slugs optional)."""
    out = []
    for line in open(path, encoding='utf-8') if path else []:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, _, slugs = (x.strip() for x in line.partition('|'))
        guesses = [s.strip() for s in slugs.split(',') if s.strip()]
        out.append((name, guesses or [re.sub(r'[^a-z0-9]+', '', name.lower())]))
    return out


def board_sources(cfg, pack, skip=(), notes=None):
    """config sources with the pack's board queries filled in where a source lists none.

    Built In and remote100k search by category, which is role-specific. Their category comes from config
    (sources.builtin.opts.paths, sources.remote100k.opts.categories), else from the pack (sources.builtin_path,
    sources.remote100k_category), else, for the product-management pack only, from the searcher's own defaults.
    With none of those the board is left out and a note is appended to `notes` (when given)."""
    queries = list((pack.get('titles') or {}).get('board_queries') or [])
    src = cfg.get('sources') or {n: {'enabled': True} for n in DEFAULT_SOURCES}
    out = {}
    for name, spec in src.items():
        if name.startswith('_') or not isinstance(spec, dict) or name in skip:
            continue
        spec = dict(spec)
        if not spec.get('queries'):
            spec['queries'] = queries
        if name in CATEGORY_OPTS and spec.get('enabled'):
            opt, pack_key = CATEGORY_OPTS[name]
            opts = dict(spec.get('opts') or {})
            if not opts.get(opt):
                mine = (pack.get('sources') or {}).get(pack_key)
                if mine:
                    opts[opt] = [mine] if isinstance(mine, str) else list(mine)
                    spec['opts'] = opts
                elif pack.get('name') != PM_PACK:
                    if notes is not None:
                        notes.append((name, f"skipped: this pack sets no sources.{pack_key} and config sets no "
                                            f"sources.{name}.opts.{opt}, so it would search product listings"))
                    continue
        out[name] = spec
    return out


# ---------- filters ----------

def keep(ctx, p):
    """(info, reason): info is None unless the posting passes the title, location and salary rules."""
    t = p['title']
    if not packs.title_ok(ctx.pack, t):
        return None, 'title'
    locs = location_match(p['location'], p['workplace'], ctx.cfg, p.get('company'))
    if not locs:
        return None, 'location'
    lo, hi, src, cur = salary_full(p['text'], p['smin'], p['smax'], p.get('bands'), locs, ctx.cfg)
    if cur == 'CAD':
        src += ' CAD'
    if p.get('pay_note'):
        src = f"{src} ({p['pay_note']})"
    if hi is not None:
        if below_floor(hi, cur, ctx.cfg):  # each currency against its own floor; no floor_cad keeps a CAD range
            p['_drop'] = dict(salary_max=hi, locations='/'.join(locs))  # for the run record
            return None, 'salary'
    else:
        policy = packs.no_range_policy(ctx.pack, ctx.cfg)
        if policy == 'exclude':
            return None, 'no_range'
        if policy == 'include_if_level_fits' and not packs.is_senior(ctx.pack, t):
            return None, 'no_range_level'
    return dict(locations='/'.join(locs), smin=lo, smax=hi, salary_source=src), 'kept'


def from_ats(q):
    """An engine ATS posting in the original discover.py shape (description collapsed to one line)."""
    return dict(id=q['id'], title=q['title'], location=q['location'], workplace='Remote' if q['remote'] else '',
                url=q['url'], updated=q['posted_at'] or '', text=re.sub(r'\s+', ' ', q['description'] or ''),
                smin=q['salary_min'], smax=q['salary_max'], bands=q.get('pay_bands') or [], company=q['company'])


def from_board(bp):
    return dict(id=bp['id'], title=bp['title'], location=bp['location'], workplace='Remote' if bp['remote'] else '',
                url=bp['apply_url'] or bp['url'], updated=bp['posted_at'] or '', text=bp['description'],
                smin=bp['salary_min'], smax=bp['salary_max'], bands=bp.get('pay_bands') or [], company=bp['company'])


def _row(company, p, info, seen, ats, already, source):
    return dict(company=company, title=p['title'], locations=info['locations'], location_raw=p['location'],
                salary_min=int(info['smin']) if info['smin'] else '', salary_max=int(info['smax']) if info['smax'] else '',
                salary_source=info['salary_source'], ats=ats, url=p['url'], updated=p['updated'],
                first_seen=seen[p['id']], new=already[1], already_in_workflow=already[0], id=p['id'], source=source)


def _write_jd(ctx, fname, company, p):
    with open(os.path.join(ctx.state, 'jd', fname + '.txt'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(f"{p['title']}\n{company}\n{p['location']}\n{p['url']}\n\n{p['text']}")


def drop_reason(why, applied, company, p):
    """(reason, detail) for the run record: a role already applied to is tagged so whatever the filter that dropped it,
    so a rescue on the review page can't double-apply. `applied` is Ctx.applied(); the id and company+title are both checked."""
    if triage.already_applied(company, p['title'], p['id'], applied):
        return 'already_applied', f'would be dropped for: {why}'
    return why, ''


def level_rank(pack, title):
    """0: a level word in the title (the pack's senior pattern); 1: none; 2: a step-down title. Orders LinkedIn
    description fetches; nothing is dropped for it."""
    down = (pack.get('level') or {}).get('down_level_title')
    if down and re.search(down, title.lower()):
        return 2
    return 0 if packs.is_senior(pack, title) else 1


def _read_jd(ctx, rid):
    """The description saved for this id on an earlier run (the text after _write_jd's header), or None."""
    try:
        with open(os.path.join(ctx.state, 'jd', re.sub(r'[^\w.-]', '_', rid) + '.txt'), encoding='utf-8') as fh:
            text = fh.read().split('\n\n', 1)
    except OSError:
        return None
    return text[1].strip() if len(text) == 2 and text[1].strip() else None


# ---------- job boards ----------

def run_board_sources(ctx, ats_rows, cache, seen, reasons, skip=(), board_runner=None, pay_lookup=None, drops=None):
    """Search the job boards and keep the roles that pass the same rules as the watchlist boards."""
    skipped = []
    sources = board_sources(ctx.cfg, ctx.pack, skip, skipped)
    skip_rows = [dict(source=n, status='skipped', count=0, scanned=0, title_matches=0, detail=d) for n, d in skipped]
    if not any(s.get('enabled') for s in sources.values()):
        return [], skip_rows
    if board_runner is None:
        from .boards import run_boards as board_runner
    pay_lookup = pay_lookup or lookup_pay
    known = {make_key(r['company'], r['title']) for r in ats_rows} | ctx.known()[0]
    title_ok = lambda t: packs.title_ok(ctx.pack, t)
    postings, report = board_runner({**ctx.cfg, 'sources': sources}, title_ok=title_ok, known_keys=known, ats_cache=cache,
                                    jd_cache=lambda rid: _read_jd(ctx, rid), level_rank=lambda t: level_rank(ctx.pack, t))
    ps = [from_board(bp) for bp in postings]
    # No range on the board card (LinkedIn often hides it): look for the same role on the company's own
    # Greenhouse/Lever/Ashby board. A failed lookup leaves the role as no-range, never drops it.
    need = [p for p in ps if not p['smax'] and not PAIR_RE.search(p['text']) and title_ok(p['title'])
            and location_match(p['location'], p['workplace'], ctx.cfg, p.get('company'))]
    memo = {}

    def look(p):
        try:
            return p, pay_lookup(p['company'], p['title'], cache, memo=memo)
        except Exception:
            return p, None
    with ThreadPoolExecutor(6) as ex:
        for p, hit in ex.map(look, need):
            if hit:
                p.update(smin=hit['salary_min'], smax=hit['salary_max'], bands=hit['pay_bands'] or p['bands'],
                         pay_note=f"pay from {hit['ats']}/{hit['slug']}")
            k = 'board_pay_lookup_' + ('found' if hit else 'none')
            reasons[k] = reasons.get(k, 0) + 1
    rows, today, applied = [], ctx.today.isoformat(), ctx.applied()
    for bp, p in zip(postings, ps):
        info, why = keep(ctx, p)
        reasons['board_' + why] = reasons.get('board_' + why, 0) + 1
        if not info:
            if drops is not None and why != 'title':  # kept for the run record, with its JD so it can be rescued
                _write_jd(ctx, re.sub(r'[^\w.-]', '_', p['id']), bp['company'], p)
                reason, detail = drop_reason(why, applied, bp['company'], p)
                drops.add('discover', reason, bp['company'], dict(p, source=bp['source']), detail=detail)
            continue
        new = p['id'] not in seen
        seen.setdefault(p['id'], today)
        _write_jd(ctx, re.sub(r'[^\w.-]', '_', p['id']), bp['company'], p)
        rows.append(_row(bp['company'], p, info, seen, bp['ats'] or 'board', ('no', 'yes' if new else 'no'), bp['source']))
    return rows, report + skip_rows


# ---------- main ----------

def run(ctx, skip_sources=(), ats_adapters=None, resolver=None, board_runner=None, pay_lookup=None, out=print):
    """Discover roles for the workspace. Network calls go through the injectable adapters (tests pass fakes)."""
    if ats_adapters is None or resolver is None:
        ats_adapters = ats_adapters or ats_mod.ADAPTERS
        resolver = resolver or ats_mod.resolve
    os.makedirs(os.path.join(ctx.state, 'jd'), exist_ok=True)
    os.makedirs(ctx.queue, exist_ok=True)
    cache_path, seen_path = os.path.join(ctx.state, 'ats_cache.json'), os.path.join(ctx.state, 'seen.json')
    misses_path = os.path.join(ctx.state, 'ats_misses.json')  # name -> date of a definite "no board"; retried after RETRY_DAYS
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    misses = json.load(open(misses_path, encoding='utf-8')) if os.path.exists(misses_path) else {}
    seen = json.load(open(seen_path, encoding='utf-8')) if os.path.exists(seen_path) else {}
    companies = load_companies(ctx.companies_file())

    with ThreadPoolExecutor(12) as ex:
        unreachable = ats_mod.probe_companies(cache, misses, companies, resolver, ctx.today, ex.map)
    resolved = [(name, cache.get(name)) for name, _ in companies]
    json.dump(cache, open(cache_path, 'w', encoding='utf-8', newline='\n'), indent=1, sort_keys=True)
    json.dump(misses, open(misses_path, 'w', encoding='utf-8', newline='\n'), indent=1, sort_keys=True)

    def fetch(item):
        name, r = item
        if not r:
            return name, None
        try:
            return name, ats_adapters[r[0]](r[1], name) or []
        except Exception:
            return name, []
    with ThreadPoolExecutor(12) as ex:
        boards = list(ex.map(fetch, resolved))

    today = ctx.today.isoformat()
    notes = folder_notes(ctx.vault)
    keys, ids = ctx.known()
    applied = ctx.applied()
    rows, reasons, drops = [], {}, runrecord.Drops()
    for name, posts in boards:
        for q in posts or []:
            p = from_ats(q)
            info, why = keep(ctx, p)
            reasons[why] = reasons.get(why, 0) + 1
            if not info:
                if why != 'title':  # kept for the run record, with its JD so it can be rescued
                    _write_jd(ctx, p['id'], name, p)
                    reason, detail = drop_reason(why, applied, name, p)
                    drops.add('discover', reason, name, dict(p, source=ATS_PREFIX.get(p['id'].split('-')[0], '')), detail=detail)
                continue
            already = (any(norm(p['title']) in f and norm(name).split()[0] in f for f in notes)
                       or p['id'] in ids or make_key(name, p['title']) in keys)
            new = p['id'] not in seen
            seen.setdefault(p['id'], today)
            _write_jd(ctx, p['id'], name, p)
            rows.append(_row(name, p, info, seen, p['id'].split('-')[0], ('yes' if already else 'no', 'yes' if new else 'no'),
                             ATS_PREFIX.get(p['id'].split('-')[0], p['id'].split('-')[0])))
    board_rows, board_report = run_board_sources(ctx, rows, cache, seen, reasons, skip_sources, board_runner, pay_lookup, drops)
    rows += board_rows
    json.dump(seen, open(seen_path, 'w', encoding='utf-8', newline='\n'), indent=1, sort_keys=True)
    rows.sort(key=lambda r: (r['company'], r['title']))
    path = os.path.join(ctx.queue, f'discovered-{today}.csv')
    # Write beside it, then rename: a run killed mid-write leaves no partial CSV for the rerun guard to take as done.
    tmp = path + '.part'
    with open(tmp, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
    rec = runrecord.save_discover(ctx, path, rows, drops, reasons, board_report, resolved)

    on_board = [n for n, r in resolved if r]
    out(f"Pack: {ctx.pack.get('label') or ctx.pack.get('name')}" + ('' if ctx.pack.get('approved') else ' (draft, not approved)'))
    out(f"Companies: {len(companies)} listed, {len(on_board)} resolved to a public board, {len(companies) - len(on_board)} not found")
    out(f"Postings scanned: {sum(reasons.values())} | filtered out: " + ', '.join(f'{k}={v}' for k, v in sorted(reasons.items()) if k != 'kept'))
    out(f"Kept: {len(rows)} roles ({sum(r['new'] == 'yes' for r in rows)} new) across {len({r['company'] for r in rows})} companies -> {path}")
    missing = [n for n, r in resolved if not r and n not in unreachable]
    if missing:
        out('Not resolved: ' + ', '.join(missing))
    if unreachable:
        out("Couldn't reach (will retry next run): " + ', '.join(unreachable))
    if board_report:
        out(f"Job boards: {len(board_rows)} new roles kept after title, location, salary and dedup")
        for r in board_report:
            out(f"  {r['source']:<11} {r['status']:<8} scanned={r['scanned']:<4} title_matches={r['title_matches']:<3} {r['detail']}")
    out(f'Run record (kept and dropped roles): {rec}')
    return path, rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.discover', description=__doc__.split('\n')[0])
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('--skip-source', action='append', default=[], help='job board to leave out this run (repeatable)')
    ap.add_argument('--force', action='store_true', help="run again even though today's discovery already exists")
    a = ap.parse_args(argv)
    try:
        ctx = Ctx(a.workspace)
    except packs.PackError as e:
        sys.exit(str(e))
    today = ctx.today.isoformat()
    if not runrecord.rerun_ok('discover', today, ctx.queue, os.path.join(ctx.queue, f'discovered-{today}.csv'), a.force):
        sys.exit(3)
    run(ctx, skip_sources=set(a.skip_source))


if __name__ == '__main__':
    main()
