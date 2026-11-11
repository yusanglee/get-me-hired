"""The source contract every job source follows.

Two kinds of source exist:

* ATS boards (Greenhouse, Lever, Ashby) are polled per company:
  `fetch_board(slug) -> list[Posting] | None`. None means "no board under this slug".
* Job boards and aggregators (Himalayas, LinkedIn, ...) are searched by query:
  `search(queries, since_days, opts) -> list[Posting]`.

Every source module defines NAME, KIND ("ats" or "board"), and NOTE (one line on
terms of use), and returns postings built by `posting()` so all downstream code
sees one shape. Description text is raw third-party content: run it through
`engine.guard.clean_posting` before an LLM reads it.
"""
import gzip, html, json, re, time, random, urllib.error, urllib.request, urllib.robotparser
from urllib.parse import urlsplit

UA = 'Mozilla/5.0 (get-me-hired job search; personal use)'
BROWSER_HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5',
    'Accept-Language': 'en-US,en;q=0.9',
}
FIELDS = ('id', 'source', 'company', 'title', 'location', 'remote', 'salary_min', 'salary_max',
          'url', 'apply_url', 'ats', 'posted_at', 'description', 'company_linkedin', 'pay_bands')


def posting(**kw):
    """A normalized posting. Unknown keys are rejected so adapters stay honest."""
    extra = set(kw) - set(FIELDS)
    if extra:
        raise ValueError(f'unknown posting fields: {sorted(extra)}')
    p = {k: kw.get(k) for k in FIELDS}
    p['title'] = squash(p['title'] or '')
    p['company'] = squash(p['company'] or '')
    p['location'] = squash(p['location'] or '')
    p['description'] = p['description'] or ''
    p['remote'] = bool(p['remote'])
    p['apply_url'] = p['apply_url'] or p['url']
    p['ats'] = p['ats'] or ats_of(p['apply_url'] or '')
    p['pay_bands'] = p['pay_bands'] or []  # [{'label', 'min', 'max'}]: location bands, when the source gives them
    return p


def squash(s):
    return re.sub(r'\s+', ' ', s).strip()


def strip_html(s):
    s = re.sub(r'<\s*br\s*/?>|</(p|li|div|h\d)>', '\n', s or '', flags=re.I)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    return re.sub(r'[ \t]+', ' ', re.sub(r'\n\s*\n+', '\n', s)).strip()


ATS_HOSTS = {
    'greenhouse': ('greenhouse.io',), 'lever': ('lever.co',), 'ashby': ('ashbyhq.com',),
    'workday': ('myworkdayjobs.com', 'myworkdaysite.com'), 'smartrecruiters': ('smartrecruiters.com',),
    'icims': ('icims.com',), 'workable': ('workable.com',), 'jobvite': ('jobvite.com',),
    'bamboohr': ('bamboohr.com',), 'rippling': ('rippling.com', 'rippling-ats.com'),
    'teamtailor': ('teamtailor.com',), 'gem': ('gem.com',), 'eightfold': ('eightfold.ai',),
}


def ats_of(url):
    """Which ATS hosts this URL, judged by the real hostname (look-alike domains fail)."""
    host = (urlsplit(url).hostname or '').lower()
    for ats, apexes in ATS_HOSTS.items():
        if any(host == a or host.endswith('.' + a) for a in apexes):
            return ats
    return None


class FetchError(Exception):
    """A failed fetch. transient=True means it may work later (429/5xx, network, timeout); False is a definite no."""

    def __init__(self, msg='', transient=False):
        super().__init__(msg)
        self.transient = transient


_robots = {}


def robots_allows(url):
    """Honor robots.txt for scraped (non-API) pages. Unreadable robots.txt allows."""
    parts = urlsplit(url)
    root = f'{parts.scheme}://{parts.netloc}'
    if root not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(root + '/robots.txt', headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                rp.parse(r.read().decode('utf-8', 'ignore').splitlines())
        except Exception:
            rp = None
        _robots[root] = rp
    rp = _robots[root]
    return True if rp is None else rp.can_fetch(UA, url)


def fetch(url, timeout=25, retries=3, headers=None, respect_robots=False):
    """GET with backoff on 429/5xx. Returns body text, or '' on 404."""
    if respect_robots and not robots_allows(url):
        raise FetchError(f'robots.txt disallows {url}')
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={**BROWSER_HEADERS, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if r.headers.get('Content-Encoding') == 'gzip':
                    data = gzip.decompress(data)
                return data.decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ''
            if (e.code == 429 or e.code >= 500) and attempt < retries:
                time.sleep(delay + random.random())
                delay = min(delay * 2, 16)
                continue
            raise FetchError(f'HTTP {e.code} for {url}', transient=e.code == 429 or e.code >= 500) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise FetchError(f'{type(e).__name__} for {url}: {e}', transient=True) from e


def fetch_json(url, **kw):
    body = fetch(url, **kw)
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError as e:
        raise FetchError(f'not JSON from {url}') from e


def health(name, postings, error=None):
    """Flag a source that runs but returns junk, so silent rot gets noticed.

    Idea from ai-job-search's portal health check: zero results, missing
    companies, or undecoded entities in titles all mean a parser has drifted.
    """
    if error:
        return {'source': name, 'status': 'error', 'count': 0, 'detail': str(error)}
    n = len(postings)
    if n == 0:
        return {'source': name, 'status': 'empty', 'count': 0, 'detail': 'no results; parser drift or no matches'}
    no_company = sum(1 for p in postings if not p['company'])
    entities = sum(1 for p in postings if re.search(r'&(amp|lt|gt|quot|#\d+);', p['title']))
    problems = []
    if no_company / n > 0.2:
        problems.append(f'{no_company}/{n} missing company')
    if entities:
        problems.append(f'{entities} titles with HTML entities')
    return {'source': name, 'status': 'degraded' if problems else 'ok', 'count': n, 'detail': '; '.join(problems)}
