"""Run every enabled job board, then filter, enrich, guard, dedup and resolve to the ATS.

    from engine.boards import run_boards
    postings, report = run_boards(cfg, title_ok=..., known_keys=..., ats_cache=...)

cfg['sources'] maps a source name to {"enabled": bool, "queries": [...], "opts": {...}}.
Sources not listed are off. `title_ok(title) -> bool` is the caller's cheap title
filter, applied before any detail page is fetched. `known_keys` holds job_keys
already in the tracker or workflow, so a role seen before is dropped here.
`ats_cache` maps company name -> [ats, slug] from the watchlist; an aggregator hit
for one of those companies is swapped for the original ATS posting, so it gets the
real apply form and an id the form fillers understand. A company not on the watchlist is
looked up by slug guesses on Greenhouse, Lever and Ashby (an exact normalized title match is
required), because job boards like LinkedIn hide the external apply link from guests: without
this, a role at an Ashby company found on LinkedIn would be left for a manual application.
cfg "resolve_guess": false turns the guessing off.
"""
import datetime
from concurrent.futures import ThreadPoolExecutor
from .sources import remote_apis, html_boards, linkedin, ats
from .sources.base import health, FetchError
from .locations import remote_countries
from .job_key import make_key, norm_title
from .guard import clean_posting
from .pay import slug_guesses

SEARCHERS = {**remote_apis.SEARCHERS, **html_boards.SEARCHERS, 'linkedin': linkedin.search}
NOTES = {**remote_apis.NOTES, **html_boards.NOTES, 'linkedin': linkedin.NOTE}
ENRICHERS = {**{n: html_boards.enrich for n in html_boards.SEARCHERS}, 'linkedin': linkedin.enrich}
# Which boards run when config has no "sources" section is discover.DEFAULT_SOURCES; every other board is opt-in.


def source_opts(name, spec, cfg=None):
    """The opts a source's searcher gets: the spec's own, plus what the config implies. LinkedIn gets its search
    places from the config (linkedin.config_opts; explicit opts.locations win) and Himalayas gets
    locations.remote_countries (explicit opts.remote_countries win). A US-only config changes nothing."""
    opts = dict(spec.get('opts') or {})
    if cfg is None:
        return opts
    if name == 'linkedin':
        if not (opts.get('locations') or opts.get('location')):
            places = spec.get('locations') or linkedin.places_from_config(cfg)
            if places != ['United States']:  # the searcher's own default; leave opts untouched for a US-only config
                opts['locations'] = places
    elif name == 'himalayas' and not opts.get('remote_countries'):
        rc = remote_countries(cfg.get('locations') or {})
        if rc and rc != ['US']:  # likewise the searcher's default
            opts['remote_countries'] = rc
    return opts


def _search(name, spec, since_days, cfg=None):
    try:
        return name, SEARCHERS[name](spec.get('queries') or [], since_days, source_opts(name, spec, cfg)), None
    except (FetchError, OSError, ValueError) as e:
        return name, [], e


def _safe(fn):
    def run(p):
        try:
            return fn(p)
        except (FetchError, OSError, ValueError):
            return p  # keep the card; it just lacks a description
    return run


def _known_board(p, ats_cache):
    """The (ats, slug) behind an aggregator posting from its apply link or the watchlist, or None."""
    hit = ats.board_from_url(p.get('apply_url'))
    if not hit:
        for name, r in ats_cache.items():
            if r and make_key(name, 'x').split('_')[0] == make_key(p['company'], 'x').split('_')[0]:
                hit = tuple(r)
                break
    return tuple(hit) if hit else None


def _guesses(company):
    """Boards to try: the name's slugs, then its first word for multi-word names ('Oscar Health' -> oscar)."""
    slugs = slug_guesses(company)
    words = slugs[-1].split('-') if slugs else []
    if len(words) > 1 and len(words[0]) >= 4:
        slugs.append(words[0])
    return [(a, s) for s in dict.fromkeys(slugs) for a in ats.ADAPTERS]


def _fetch_board(key, company):
    try:
        return ats.ADAPTERS[key[0]](key[1], company) or []
    except Exception:  # a wrong guess or a board that's down is just a miss
        return []


def prefetch_guesses(postings, ats_cache, board_cache, workers=6):
    """Fetch, in parallel, the guessed boards of every aggregator posting with no known board."""
    todo = {}
    for p in postings:
        if not p.get('ats') and p.get('company') and not _known_board(p, ats_cache):
            for key in _guesses(p['company']):
                if key not in board_cache:
                    todo.setdefault(key, p['company'])
    with ThreadPoolExecutor(workers) as ex:
        for key, found in zip(todo, ex.map(lambda k: _fetch_board(k, todo[k]), todo)):
            board_cache[key] = found


def _resolve_to_ats(p, ats_cache, board_cache, guess=True):
    """Swap an aggregator posting for the same role on the company's own ATS board."""
    known = _known_board(p, ats_cache)
    # Guess only for postings with no ATS at all; one whose apply link names an ATS resolves through `known`.
    keys = [known] if known else (_guesses(p['company']) if guess and p.get('company') and not p.get('ats') else [])
    want = norm_title(p['title'])
    for key in keys:
        if key not in board_cache:
            board_cache[key] = _fetch_board(key, p['company'])
        for q in board_cache[key]:
            if norm_title(q['title']) == want:
                how = '' if known else f'; {key[0]} board "{key[1]}" found by name, check it is this company'
                return dict(q, source=f"{q['source']} (via {p['source']}{how})")
    return p


def _linkedin_details(kept, jd_cache, max_details, level_rank=None):
    """Descriptions for LinkedIn title matches: a role seen on an earlier day reuses its saved description; at
    most max_details are fetched, titles with a level word first (level_rank 0), then titles with none (1), then
    step-down titles (2), newest first within each; the rest wait for the next run. Returns (kept, counts)."""
    out, fetched, cached, deferred, dupes = [], 0, 0, 0, 0
    todo, keys = [], set()
    uniq = []
    for p in kept:  # the same role posted for several places: one description fetch (merged later anyway)
        k = make_key(p['company'], p['title'])
        if k in keys:
            dupes += 1
            continue
        keys.add(k)
        uniq.append(p)
    kept = uniq
    if level_rank:
        kept = sorted(kept, key=lambda p: level_rank(p['title']))  # stable: newest first within a rank
    for p in kept:
        text = jd_cache(p['id']) if jd_cache else None
        if text:
            p['description'] = text
            out.append(p)
            cached += 1
        elif fetched < max_details:
            todo.append(p)
            fetched += 1
        else:
            deferred += 1
    with ThreadPoolExecutor(1) as ex:
        out += list(ex.map(_safe(ENRICHERS['linkedin']), todo))
    return out, {'fetched': fetched, 'cached': cached, 'deferred': deferred, 'repeats': dupes}


def run_boards(cfg, title_ok=lambda t: True, known_keys=(), ats_cache=None, since_days=None, workers=6, jd_cache=None,
               level_rank=None):
    sources = {n: s for n, s in (cfg.get('sources') or {}).items() if s.get('enabled') and n in SEARCHERS}
    since = since_days or cfg.get('since_days', 14)
    cutoff = (datetime.date.today() - datetime.timedelta(days=since)).isoformat()
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda kv: _search(kv[0], kv[1], since, cfg), sources.items()))

    known, seen, board_cache, out, report = set(known_keys), {}, {}, [], []
    for name, postings, err in results:
        kept = [p for p in postings if title_ok(p['title'])
                and not (p['company'] and make_key(p['company'], p['title']) in known)]  # skip detail fetches for known roles
        details = None
        if name == 'linkedin':
            max_details = int(((cfg.get('sources') or {}).get('linkedin', {}).get('opts') or {}).get('max_details', 150))
            kept, details = _linkedin_details(kept, jd_cache, max_details, level_rank)
        elif name in ENRICHERS:
            with ThreadPoolExecutor(3) as ex:
                kept = list(ex.map(_safe(ENRICHERS[name]), kept))
        if name in ENRICHERS:
            # titles from slugs can change on enrich; closed LinkedIn postings drop out
            kept = [p for p in kept if title_ok(p['title']) and not p.pop('closed', False)
                    and not (p['posted_at'] and p['posted_at'] < cutoff)]  # sitemaps carry no dates
        rep = {**health(name, kept if name in ENRICHERS else postings, err),
               'scanned': len(postings), 'title_matches': len(kept)}
        if name == 'linkedin' and linkedin.LAST_RUN:
            lr = linkedin.LAST_RUN
            windows = ', '.join(f'{d}d:{n}' for d, n in lr['by_window'].items())
            rep['detail'] = '; '.join(filter(None, [
                rep.get('detail'), f"{lr['requests']} search pages ({windows} new cards)", lr['stopped'],
                details and f"descriptions: {details['fetched']} fetched, {details['cached']} reused, "
                            f"{details['repeats']} repeat postings skipped, "
                            f"{details['deferred']} left for the next run (opts.max_details)"]))
            rep['stats'] = dict(lr, details=details)  # kept in the run record, to diagnose missed postings
        report.append(rep)
        guess = cfg.get('resolve_guess', True)
        if guess:
            prefetch_guesses(kept, ats_cache or {}, board_cache)
        for p in kept:
            p = _resolve_to_ats(p, ats_cache or {}, board_cache, guess)
            k = make_key(p['company'], p['title'])
            p['job_key'] = k
            if k in known:
                continue
            if k in seen:  # same role on two boards: keep the one with the richer record
                prev = seen[k]
                if (p['ats'] and not prev['ats']) or len(p['description']) > len(prev['description']) * 1.5:
                    out[out.index(prev)] = p
                    seen[k] = p
                continue
            seen[k] = p
            out.append(p)
    for p in out:
        clean_posting(p)
    return out, report
