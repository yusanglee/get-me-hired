"""Greenhouse, Lever and Ashby public job-board APIs, polled per company.

These are the cleanest sources: official, unauthenticated, and they return the
original posting with its real apply URL. Ported from the original pipeline's
discover.py. Each adapter returns a list of postings, or None when the slug has
no board on that ATS.
"""
import datetime, html, re
from .base import posting, fetch_json, strip_html, FetchError
from ..pay import ashby_bands

KIND = 'ats'
NOTE = 'Official public job-board APIs; no login.'


def _get(url):
    try:
        return fetch_json(url, retries=1)
    except FetchError as e:
        if e.transient:
            raise  # a bad moment, not a missing board: callers must not remember it as a miss
        return None


def greenhouse(slug, company=''):
    d = _get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true')
    if not d or 'jobs' not in d:
        return None
    out = []
    for j in d['jobs']:
        text = strip_html(html.unescape(j.get('content') or ''))  # Greenhouse double-escapes
        loc = (j.get('location') or {}).get('name', '')
        out.append(posting(
            id=f"gh-{slug}-{j['id']}", source='greenhouse', company=company or j.get('company_name', ''),
            title=j.get('title', ''), location=loc, remote='remote' in loc.lower(),
            url=j.get('absolute_url', ''), ats='greenhouse', posted_at=(j.get('updated_at') or '')[:10],
            description=text))
    return out


def lever(slug, company=''):
    d = _get(f'https://api.lever.co/v0/postings/{slug}?mode=json')
    if not isinstance(d, list) or not d:
        return None
    out = []
    for j in d:
        sr = j.get('salaryRange') or {}
        parts = [j.get('descriptionPlain') or '', j.get('additionalPlain') or '']
        for l in j.get('lists') or []:
            parts.append(l.get('text', '') + '\n' + strip_html(l.get('content', '')))
        cat = j.get('categories') or {}
        locs = [cat.get('location', '')] + (cat.get('allLocations') or [])
        loc = ' / '.join(dict.fromkeys(x for x in locs if x))
        yearly = sr.get('interval') in (None, 'per-year-salary')
        wp = (j.get('workplaceType') or '').lower()
        out.append(posting(
            id=f"lv-{slug}-{j['id']}", source='lever', company=company or slug, title=j.get('text', ''),
            location=loc, remote=wp == 'remote' or 'remote' in loc.lower(),
            salary_min=sr.get('min') if yearly else None, salary_max=sr.get('max') if yearly else None,
            url=j.get('hostedUrl', ''), apply_url=j.get('applyUrl') or j.get('hostedUrl', ''), ats='lever',
            posted_at=datetime.datetime.fromtimestamp((j.get('createdAt') or 0) / 1000, datetime.timezone.utc).strftime('%Y-%m-%d'),
            description='\n'.join(parts)))
    return out


def ashby(slug, company=''):
    d = _get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true')
    if not d or not d.get('jobs'):
        return None
    out = []
    for j in d['jobs']:
        smin = smax = None
        comp = j.get('compensation') or {}
        for c in comp.get('summaryComponents') or []:
            if c.get('compensationType') == 'Salary' and c.get('interval') in (None, '1 YEAR'):
                smin, smax = c.get('minValue'), c.get('maxValue')
        locs = [j.get('location') or ''] + [s.get('location', '') for s in j.get('secondaryLocations') or []]
        wp = (j.get('workplaceType') or '').lower()
        out.append(posting(
            id=f"ab-{slug}-{j.get('id')}", source='ashby', company=company or slug, title=j.get('title', ''),
            # workplaceType wins over isRemote: Ashby sets isRemote on some Hybrid and OnSite postings (seen Oct 20)
            location=' / '.join(x for x in locs if x), remote=wp == 'remote' if wp else bool(j.get('isRemote')),
            salary_min=smin, salary_max=smax, url=j.get('jobUrl', ''), apply_url=j.get('applyUrl') or j.get('jobUrl', ''),
            ats='ashby', posted_at=(j.get('publishedAt') or '')[:10], pay_bands=ashby_bands(comp),
            description=(j.get('descriptionPlain') or '') + '\n' + (comp.get('compensationTierSummary') or '')))
    return out


ADAPTERS = {'greenhouse': greenhouse, 'lever': lever, 'ashby': ashby}


def resolve(slugs, company=''):
    """First (ats, slug) whose board has postings, or None for a definite miss. Slug guesses can hit the
    wrong company's board; callers cache the answer so it can be corrected by hand. If nothing hit and
    any attempt failed transiently (network, 429/5xx), raises FetchError(transient=True): not a miss."""
    flaky = None
    for slug in slugs:
        for ats, fn in ADAPTERS.items():
            try:
                if fn(slug, company):
                    return [ats, slug]
            except FetchError as e:
                if not e.transient:
                    raise
                flaky = e
    if flaky:
        raise FetchError(f'could not reach every board for {company or slugs}: {flaky}', transient=True)
    return None


RETRY_DAYS = 14  # a company with no board is probed again after this long


def probe_companies(cache, misses, companies, resolver, today, mapper=map):
    """Resolve the companies that need it into `cache` (name -> [ats, slug] | None) and `misses` (name -> date of
    the definite miss), in place. A cached board is trusted; a cached None is probed again once its miss date is
    missing (an old cache) or older than RETRY_DAYS. A transient failure changes nothing for that company.
    `companies` is [(name, [slug, ...])]; `mapper` lets a caller supply a thread pool's map.
    Returns the names that could not be reached this run."""
    def due(name):
        if name not in cache:
            return True
        if cache[name]:
            return False
        try:
            return (today - datetime.date.fromisoformat(misses[name])).days > RETRY_DAYS
        except (KeyError, ValueError, TypeError):
            return True
    todo = list(dict((c[0], c) for c in companies if due(c[0])).values())

    def probe(c):
        try:
            return c[0], resolver(c[1], c[0]), False
        except Exception:
            return c[0], None, True
    unreachable = []
    for name, hit, failed in mapper(probe, todo):
        if failed:
            unreachable.append(name)
        elif hit:
            cache[name] = hit
            misses.pop(name, None)
        else:
            cache[name] = None
            misses[name] = today.isoformat()
    return unreachable


# Pull out the ATS board behind an aggregator's apply link, so an aggregator hit can
# be re-fetched from the source of truth and deduped against watchlist results.
BOARD_URL = [
    ('greenhouse', re.compile(r'(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)', re.I)),
    ('lever', re.compile(r'jobs\.(?:eu\.)?lever\.co/([\w.-]+)', re.I)),
    ('ashby', re.compile(r'jobs\.ashbyhq\.com/([\w.%-]+)', re.I)),
]


def board_from_url(url):
    for ats, rx in BOARD_URL:
        m = rx.search(url or '')
        if m:
            return ats, m.group(1)
    return None
