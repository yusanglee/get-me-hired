"""Is each queued posting still open? Answers it for Greenhouse, Lever and Ashby roles from their public board APIs.

Rows are the apply/manual calls in queue/reviewed-<date>.csv. A row's board comes from its id prefix (gh/lv/ab),
its slug from the row's url, else from its id, else from state/ats_cache.json by company name. Each board is
fetched once. Status per row:
  open     its id (or its posting url) is on the board
  closed   the board was read and the role is not on it
  unknown  not a Greenhouse/Lever/Ashby posting (check by hand), or the board couldn't be read
Read-only: nothing is written. Closed rows come with a ready-to-run `gmh review picks` line to pass them.

    gmh review open-check [--date D] [--json]
"""
import re
from concurrent.futures import ThreadPoolExecutor

PREFIX = {'gh': 'greenhouse', 'lv': 'lever', 'ab': 'ashby'}
UUID_TAIL = re.compile(r'-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def _id_slug(rid):
    """Best guess at the slug inside gh-<slug>-<job id>. Slugs and Lever/Ashby ids hold hyphens, so strip a UUID
    tail whole; otherwise the job id is the last segment. The board's own ids settle it either way."""
    rest = rid.split('-', 1)[1] if '-' in rid else ''
    if UUID_TAIL.search(rest):
        return UUID_TAIL.sub('', rest)
    return rest.rpartition('-')[0]


def _url_key(u):
    return re.sub(r'^https?://(www\.)?', '', (u or '').split('?')[0].split('#')[0]).rstrip('/').lower()


def candidates(row, ats, cache):
    """Slugs worth trying for a row, most likely first."""
    from .sources.ats import board_from_url
    out = []
    b = board_from_url(row.get('url'))
    if b and b[0] == ats:
        out.append(b[1])
    out.append(_id_slug(row.get('id', '')))
    name = (row.get('company') or '').strip().lower()
    for k, v in (cache or {}).items():
        if k.strip().lower() == name and isinstance(v, (list, tuple)) and len(v) == 2 and v[0] == ats:
            out.append(v[1])
    return list(dict.fromkeys(s for s in out if s))


def open_check(rows, adapters, cache=None, workers=6):
    """[{id, company, title, status, reason}] for rows; adapters maps ats -> fn(slug, company) -> postings or None
    (an adapter that raises counts as unreadable)."""
    memo = {}

    def board(ats, slug):
        if (ats, slug) not in memo:
            try:
                memo[ats, slug] = adapters[ats](slug, '') or None
            except Exception:
                memo[ats, slug] = None
        return memo[ats, slug]

    plan = []
    for r in rows:
        ats = PREFIX.get((r.get('id') or '').split('-', 1)[0])
        plan.append((r, ats, candidates(r, ats, cache) if ats in adapters else []))
    first = list(dict.fromkeys((ats, c[0]) for _, ats, c in plan if c))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda k: board(*k), first))
    out = []
    for r, ats, slugs in plan:
        res = dict(id=r.get('id', ''), company=r.get('company', ''), title=r.get('title', ''))
        if not slugs:
            why = ('not a Greenhouse, Lever or Ashby posting: check by hand' if ats not in adapters
                   else f'no {ats} board found for it: check by hand')
            out.append({**res, 'status': 'unknown', 'reason': why})
            continue
        read, found = [], None
        for s in slugs:
            ps = board(ats, s)
            if ps is None:
                continue
            read.append(s)
            ids = {p.get('id') for p in ps}
            urls = {_url_key(p.get(k)) for p in ps for k in ('url', 'apply_url')} - {''}
            if r.get('id') in ids or (r.get('url') and _url_key(r['url']) in urls):
                found = s
                break
        if found:
            out.append({**res, 'status': 'open', 'reason': f'on the {ats} board {found}'})
        elif read:
            out.append({**res, 'status': 'closed', 'reason': f'not on the {ats} board {read[0]} any more'})
        else:
            out.append({**res, 'status': 'unknown',
                        'reason': f"couldn't read the {ats} board ({', '.join(slugs)}): check by hand"})
    return out


def picks_line(results, rec):
    """`gmh review picks "pass 3 d12: closed"` for the closed rows found in the run record, or ''."""
    ref = {e['id']: e['ref'] for e in (rec.get('roles') or []) + (rec.get('dropped') or []) if e.get('id') and e.get('ref')}
    refs = [str(ref[r['id']]) for r in results if r['status'] == 'closed' and r['id'] in ref]
    return f'gmh review picks "pass {" ".join(refs)}: closed"' if refs else ''


def lines(results, rec):
    out = [f"{r['id']}  {r['company']}: {r['title']}  {r['status']}  {r['reason']}" for r in results]
    closed = sum(r['status'] == 'closed' for r in results)
    out.append(f"{len(results)} checked: {sum(r['status'] == 'open' for r in results)} open, {closed} closed, "
               f"{sum(r['status'] == 'unknown' for r in results)} unknown")
    if closed:
        out.append(picks_line(results, rec) or 'Closed roles are not in the run record; pass them by id.')
    return out
