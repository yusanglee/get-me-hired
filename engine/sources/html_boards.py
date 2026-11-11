"""Boards without an API, read politely from their public pages.

Each search() returns lightweight postings from list pages or sitemaps (title,
company, URL, sometimes salary). Descriptions are fetched afterward by enrich(),
and only for postings that already passed the title filter, so a run makes a
handful of detail requests rather than hundreds. Every request checks robots.txt.

* Built In: category pages (robots allows ?page=), JobPosting JSON-LD on job
  pages. Applying needs a Built In account, so apply_url stays the Built In page.
* remote100k: category pages; job pages carry JobPosting JSON-LD and the
  employer's own apply link (often Workday or Greenhouse).
* NoDesk: the job sitemap (no dates) plus JobPosting JSON-LD for slugs whose
  words match the query.
* Fractionus: fractional and interim roles from the Webflow job list.

Not supported, by choice: Hiring Cafe (every request hits a Cloudflare challenge;
getting past it would mean defeating bot detection), SimplyHired (Indeed's terms
ban automated access), remote.co (times out; mostly routes into paid FlexJobs),
Flexa (UK-heavy, JS-rendered). Browse those yourself.
"""
import html, json, re, time
from urllib.parse import urljoin, urlencode
from .base import posting, fetch, strip_html, squash, FetchError

KIND = 'board'
PAUSE = 1.0


def _get(url):
    time.sleep(PAUSE)
    return fetch(url, respect_robots=True, retries=2)


def jsonld_jobposting(markup):
    """The first schema.org JobPosting in a page, or None. Handles @graph and an
    entity-encoded '+' in the script type (Built In writes ld&#x2B;json)."""
    for block in re.findall(r'<script[^>]*ld(?:\+|&#x2B;|&#43;)json[^>]*>([\s\S]*?)</script>', markup, re.I):
        try:
            data = json.loads(block)
        except ValueError:
            try:
                data = json.loads(html.unescape(block))
            except ValueError:
                continue
        items = data.get('@graph', [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        for x in items:
            if isinstance(x, dict) and x.get('@type') == 'JobPosting':
                return x
    return None


def from_jsonld(p, jp):
    """Fill a posting's gaps from a JobPosting object."""
    org = jp.get('hiringOrganization') or {}
    p['company'] = p['company'] or squash(org.get('name', '') if isinstance(org, dict) else str(org))
    p['title'] = p['title'] or squash(html.unescape(jp.get('title', '')))
    p['description'] = strip_html(html.unescape(jp.get('description') or '')) or p['description']
    p['posted_at'] = p['posted_at'] or (jp.get('datePosted') or '')[:10]
    if jp.get('jobLocationType') == 'TELECOMMUTE':
        p['remote'] = True
    req = jp.get('applicantLocationRequirements')
    reqs = req if isinstance(req, list) else [req] if req else []
    places = [r.get('name', '') for r in reqs if isinstance(r, dict)]
    locs = jp.get('jobLocation')
    for l in (locs if isinstance(locs, list) else [locs] if locs else []):
        a = (l or {}).get('address') or {}
        if isinstance(a, dict):
            places.append(', '.join(x for x in (a.get('addressLocality'), a.get('addressRegion'), a.get('addressCountry')) if isinstance(x, str) and x))
    if places and not p['location']:
        p['location'] = ' / '.join(dict.fromkeys(x for x in places if x))
    sal = jp.get('baseSalary') or {}
    val = sal.get('value') if isinstance(sal, dict) else None
    if isinstance(val, dict) and sal.get('currency', 'USD') == 'USD' and (val.get('unitText') or 'YEAR').upper() == 'YEAR':
        p['salary_min'] = p['salary_min'] or val.get('minValue')
        p['salary_max'] = p['salary_max'] or val.get('maxValue')
    return p


def _money(text):
    nums = [float(n.replace(',', '')) for n in re.findall(r'\$\s?(\d{2,3}(?:,\d{3})+)', text or '')]
    return (min(nums), max(nums)) if nums else (None, None)


# ---------- Built In ----------
def builtin(queries, since_days=14, opts=None):
    """opts: paths (category paths, default remote product management), pages (default 3).
    engine.discover fills paths from the pack (sources.builtin_path) and skips this board for any pack but
    product-management that sets none, so the product default below is only reached by that pack or a direct call."""
    opts = opts or {}
    paths = opts.get('paths') or ['/jobs/remote/product-management']
    out = {}
    for path in paths:
        for page in range(1, opts.get('pages', 3) + 1):
            url = 'https://builtin.com' + path + (f'?page={page}' if page > 1 else '')
            try:
                markup = _get(url)
            except FetchError:
                break
            links = dict.fromkeys(re.findall(r'href="(/job/[^"?#]+/\d+)"', markup))
            for link in links:
                m = re.search(r'href="' + re.escape(link) + r'"[^>]*>([\s\S]{0,300}?)</a>', markup)
                title = squash(strip_html(m.group(1))) if m else ''
                jid = link.rsplit('/', 1)[-1]
                out.setdefault(jid, posting(id=f'bi-{jid}', source='builtin', title=title,
                                            url='https://builtin.com' + link))
            if not links:
                break
    return list(out.values())


# ---------- remote100k ----------
def remote100k(queries, since_days=14, opts=None):
    """opts: categories (default ['product']); e.g. ['operations','management'] for Chief of Staff.
    engine.discover fills categories from the pack (sources.remote100k_category); see builtin()."""
    opts = opts or {}
    out = {}
    for cat in opts.get('categories') or ['product']:
        try:
            markup = _get(f'https://remote100k.com/remote-jobs/{cat}')
        except FetchError:
            continue
        for m in re.finditer(r'<a href="(/remote-job/[^"]+)" data-days="(\d+)"([\s\S]*?)</a>', markup):
            link, days, card = m.groups()
            if int(days) > since_days:
                continue
            title = re.search(r'job-card-mobile-title[^>]*>([\s\S]*?)</h3>', card)
            company = re.search(r'job-card-mobile-company[^>]*>([\s\S]*?)</span>', card)
            loc = re.search(r'bi-geo-alt"></i>([\s\S]*?)</span>', card)
            lo, hi = _money(strip_html(card))
            out.setdefault(link, posting(
                id='r100k-' + link.rsplit('/', 1)[-1][:80], source='remote100k',
                company=strip_html(company.group(1)) if company else '', title=strip_html(title.group(1)) if title else '',
                location=strip_html(loc.group(1)) if loc else 'Remote', remote=True, salary_min=lo, salary_max=hi,
                url='https://remote100k.com' + link))
    return list(out.values())


# ---------- NoDesk ----------
def nodesk(queries, since_days=14, opts=None):
    """Slugs read '<company>-<title words>', so match every query word against the slug."""
    markup = _get('https://nodesk.co/sitemap-jobs.xml')
    words = [set(re.findall(r'[a-z]+', q.lower())) for q in queries]
    out = []
    for url in re.findall(r'<loc>(https://nodesk\.co/remote-jobs/[^<]+)</loc>', markup):
        slug = set(url.rstrip('/').rsplit('/', 1)[-1].split('-'))
        if any(w and w <= slug for w in words):
            out.append(posting(id='nd-' + url.rstrip('/').rsplit('/', 1)[-1][:80], source='nodesk', url=url, remote=True,
                               title=url.rstrip('/').rsplit('/', 1)[-1].replace('-', ' ')))
    return out[:opts.get('max', 60) if opts else 60]


# ---------- Fractionus ----------
def fractionus(queries, since_days=14, opts=None):
    """Fractional, interim and fixed-term roles. opts: pages (default 3)."""
    opts = opts or {}
    out = {}
    for page in range(1, opts.get('pages', 3) + 1):
        url = 'https://www.fractionus.com/jobs' + (f'?cca22b44_page={page}' if page > 1 else '')
        try:
            markup = _get(url)
        except FetchError:
            break
        cards = re.findall(r'<div role="listitem" class="job-list-item[^"]*"><a href="(/jobs/[^"]+)"([\s\S]*?)</a></div>', markup)
        for link, card in cards:
            if 'Active' not in card:
                continue
            company = re.search(r'heading-style-h4[^"]*"[^>]*>([\s\S]*?)</p>', card)
            title = re.search(r'<h3[^>]*>([\s\S]*?)</h3>', card)
            tags = [strip_html(t) for t in re.findall(r'text-size-tiny">([\s\S]*?)</div>', card)]
            rate = re.findall(r'class="paragraph(?:-2)?">\s*([\d,]+)\s*</p>', card)
            hours = 'hrs/week' in card
            out.setdefault(link, posting(
                id='fr-' + link.rsplit('/', 1)[-1][:80], source='fractionus',
                company=strip_html(company.group(1)) if company else '', title=strip_html(title.group(1)) if title else '',
                location=' / '.join(t for t in tags if t not in ('Active',)), url='https://www.fractionus.com' + link,
                description=(f'Rate ${rate[0]}-${rate[1]}/hr. ' if len(rate) >= 2 else '') + ('Part-time hours. ' if hours else '')))
        if not cards:
            break
    return list(out.values())


def _fractionus_detail(p, markup):
    """Fractionus builds its JSON-LD in the browser from a CONFIG object; read that
    object and the three description blocks directly."""
    def cfg(key):
        m = re.search(key + r'\s*:\s*"([^"]*)"', markup)
        return html.unescape(m.group(1)) if m else ''
    p['posted_at'] = cfg('datePosted')[:10] or p['posted_at']
    p['company'] = p['company'] or cfg('companyName')
    loc = ' / '.join(x for x in (cfg('locationType'), cfg('locationRaw')) if x)
    p['location'] = loc or p['location']
    p['remote'] = 'remote' in loc.lower()
    parts = []
    for div in ('job-details', 'job-responsibilities', 'job-requirements'):
        m = re.search(r'<div[^>]*id="' + div + r'"[^>]*>', markup)
        if not m:
            continue
        i, depth = m.end(), 1  # walk nested divs to the matching close
        while depth and i < len(markup):
            o, c = markup.find('<div', i), markup.find('</div>', i)
            if c == -1:
                break
            depth, i = (depth + 1, o + 4) if o != -1 and o < c else (depth - 1, c + 6)
        parts.append(strip_html(markup[m.end():i]))
    p['description'] = (p['description'] + '\n'.join(x for x in parts if x)) or cfg('summary')


def enrich(p):
    """Fetch the job page for one posting and fill description, company, dates and
    salary from JobPosting JSON-LD; pick up the employer's own apply link if shown."""
    try:
        markup = _get(p['url'])
    except FetchError:
        return p
    jp = jsonld_jobposting(markup)
    if p['source'] == 'fractionus':
        _fractionus_detail(p, markup)
    elif jp:
        from_jsonld(p, jp)
    elif not p['description']:
        body = re.search(r'<main[\s\S]*?</main>', markup)
        p['description'] = strip_html(body.group(0) if body else markup)[:20000]
    from .base import ats_of
    for href in re.findall(r'href="(https?://[^"]+)"', markup):
        if ats_of(href):
            p['apply_url'], p['ats'] = html.unescape(href).split('?ref=')[0], ats_of(href)
            break
    return p


SEARCHERS = {'builtin': builtin, 'remote100k': remote100k, 'nodesk': nodesk, 'fractionus': fractionus}
NOTES = {
    'builtin': 'Public category and job pages, robots.txt honored. Applying needs a Built In account.',
    'remote100k': 'Public pages, robots.txt honored. Links through to the employer ATS.',
    'nodesk': 'Job sitemap + job pages, robots.txt honored.',
    'fractionus': 'Fractional/interim roles. Public list pages, robots.txt honored.',
}
