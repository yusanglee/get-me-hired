"""LinkedIn Jobs via the public, unauthenticated "jobs-guest" endpoints.

Ported to Python from ai-job-search's linkedin-search CLI (MIT, Copyright (c)
2026 Mads Lorentzen; see engine/vendor/LICENSE-ai-job-search). Regex parsing of
the shallow card markup, one card at a time so a malformed card can't break the
rest.

Terms: LinkedIn's User Agreement bans automated access, and its robots.txt
disallows /jobs-guest/. This source is OFF by default and opt-in per user; it
never uses a logged-in account or cookies. Keep volume low: LinkedIn starts
answering 429 after roughly 10 pages per IP.
"""
import html, re, time
from urllib.parse import urlencode, urlsplit
from .base import posting, fetch, FetchError

KIND = 'board'
NOTE = 'Opt-in. Unauthenticated guest endpoints; against LinkedIn ToS; low volume only.'
SEARCH_URL = 'https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search'
DETAIL_URL = 'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting'
HEADERS = {'X-Requested-With': 'XMLHttpRequest'}
# Oct 22 check: the guest API ignores f_WT and f_E (onsite, remote and no filter return the same cards; so do entry
# and senior). Both are still sent; don't read a card's work type or level from the search that found it.
WORK_TYPE = {'onsite': '1', 'on-site': '1', 'remote': '2', 'hybrid': '3'}
# Searched newest first: the last day, then the last 7, then the last 14; older is stale.
# The guest API ignores sortBy, so each window is its own search, and the newest postings get the page
# budget first. 10 cards a page; paging stops near 1,000 results (Oct 21: start=980 had cards, 990 none).
DEFAULT_WINDOWS = (1, 7, 14)
PAGE_SIZE, MAX_PAGES = 10, 100
DEFAULT_MAX_REQUESTS = 200
# LinkedIn's experience filter (f_E). Default: mid-senior and up, which drops internship, entry and associate
# postings before they cost a page. opts.experience: [] turns it off.
EXPERIENCE = {'internship': 1, 'entry': 2, 'associate': 3, 'mid-senior': 4, 'director': 5, 'executive': 6}
DEFAULT_EXPERIENCE = ('mid-senior', 'director', 'executive')
# The last search's stats, for the run report and the run record: requests, unique cards per window, why it
# stopped, and per window and per query/place stream the pages fetched, cards returned and how the stream ended
# (ran out, page cap, more left when the budget or an error cut it short, not reached).
LAST_RUN = {}
# LinkedIn place strings for the countries a user can be hired in (config locations.remote_countries)
COUNTRY_PLACES = {'US': 'United States', 'CA': 'Canada'}
CANADIAN_HOME_PLACES = {'Toronto': 'Toronto, Ontario, Canada', 'Vancouver': 'Vancouver, British Columbia, Canada',
                        'Montreal': 'Montreal, Quebec, Canada', 'Ottawa': 'Ottawa, Ontario, Canada',
                        'Calgary': 'Calgary, Alberta, Canada', 'Edmonton': 'Edmonton, Alberta, Canada',
                        'Waterloo': 'Waterloo, Ontario, Canada'}


def places_from_config(cfg):
    """Search places for a config with no sources.linkedin.opts.locations: one per remote country ("United States",
    "Canada"), plus a Canadian home metro's own city. A US-only config, or none, gives ['United States']."""
    loc = (cfg or {}).get('locations') or {}
    rc = loc.get('remote_countries')
    if rc is None:
        rc = ['US'] if loc.get('remote_us', True) else []
    places = [COUNTRY_PLACES[c] for c in rc if c in COUNTRY_PLACES]
    home = CANADIAN_HOME_PLACES.get(loc.get('home'))
    if home and home not in places:
        places.append(home)
    return places or ['United States']


def config_opts(cfg):
    """The config's own LinkedIn opts with `locations` filled in from the config when it names none. The caller
    that builds the source's opts merges this in (an explicit opts.locations always wins)."""
    spec = ((cfg or {}).get('sources') or {}).get('linkedin', {})
    opts = dict(spec.get('opts') or {})
    if not (opts.get('locations') or opts.get('location')):
        opts['locations'] = spec.get('locations') or places_from_config(cfg)
    return opts


def _clean(s):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def parse_cards(markup):
    out = []
    for chunk in re.split(r'data-entity-urn="urn:li:jobPosting:', markup)[1:]:
        m = re.match(r'(\d+)', chunk)
        if not m:
            continue
        jid = m.group(1)
        link = re.search(r'class="base-card__full-link[^"]*"[^>]*href="([^"]+)"', chunk, re.I)
        title = re.search(r'class="base-search-card__title"[^>]*>([\s\S]*?)</h3>', chunk, re.I)
        title = _clean(title.group(1)) if title else ''
        if not title:
            sr = re.search(r'class="sr-only"[^>]*>([\s\S]*?)</span>', chunk, re.I)
            title = _clean(sr.group(1)) if sr else ''
        if not title:
            continue
        sub = re.search(r'class="base-search-card__subtitle"[^>]*>([\s\S]*?)</h4>', chunk, re.I)
        company = _clean(sub.group(1)) if sub else ''
        curl = re.search(r'href="([^"]+)"', sub.group(1)) if sub else None
        loc = re.search(r'class="job-search-card__location"[^>]*>([\s\S]*?)</span>', chunk, re.I)
        dt = re.search(r'class="job-search-card__listdate[^"]*"[^>]*datetime="([^"]+)"', chunk, re.I)
        out.append({'id': jid, 'title': title, 'company': company,
                    'company_url': html.unescape(curl.group(1)).split('?')[0] if curl else '',
                    'location': _clean(loc.group(1)) if loc else '', 'date': dt.group(1) if dt else '',
                    'url': html.unescape(link.group(1)).split('?')[0] if link else f'https://www.linkedin.com/jobs/view/{jid}'})
    return out


def _div(markup, cls):
    m = re.search(r'<div[^>]*class="[^"]*' + re.escape(cls) + r'[^"]*"[^>]*>', markup, re.I)
    if not m:
        return None
    i, depth = m.end(), 1
    while depth and i < len(markup):
        o, c = markup.find('<div', i), markup.find('</div>', i)
        if c == -1:
            return None
        if o != -1 and o < c:
            depth, i = depth + 1, o + 4
        else:
            depth, i = depth - 1, c + 6
    return markup[m.end():i - 6]


def parse_detail(markup):
    """Description, criteria, and whether a 'no longer accepting' banner sits in the top card."""
    body = _div(markup, 'show-more-less-html__markup') or _div(markup, 'description__text') or ''
    body = re.sub(r'<\s*br\s*/?>|</(p|li|ul|ol|div|h\d)>', '\n', re.sub(r'\s+', ' ', body), flags=re.I)
    desc = re.sub(r'\n{3,}', '\n\n', '\n'.join(_clean(l) for l in body.split('\n'))).strip()
    crit = {_clean(a).lower(): _clean(b) for a, b in re.findall(
        r'class="description__job-criteria-subheader"[^>]*>([\s\S]*?)</h3>[\s\S]*?class="description__job-criteria-text[^"]*"[^>]*>([\s\S]*?)</span>', markup, re.I)}
    start = re.search(r'class="(?:show-more-less-html__markup|description__text)', markup, re.I)
    top = markup[:start.start()] if start else markup
    org = re.search(r'class="topcard__org-name-link[^"]*"[^>]*href="([^"]+)"', markup, re.I)
    return {'description': desc, 'criteria': crit,
            'company_url': html.unescape(org.group(1)).split('?')[0] if org else '',
            'closed': bool(re.search(r'closed-job__flavor|no longer accepting applications', top, re.I))}


def search(queries, since_days=14, opts=None, pause=2.0):
    """Job cards only (no descriptions; see enrich). opts: locations, a list of LinkedIn
    place strings or {"location": ..., "work_type": "remote"|"hybrid"|"onsite"} (default
    ['United States'], or the places config_opts(cfg) derives from locations.remote_countries / the home metro); windows_days (default [1, 7, 14], none past since_days), searched in that
    order; pages per window, query and place (default and max 100); max_requests, search pages per
    run across everything (default 200), spent newest window first; experience, LinkedIn levels to
    keep (default mid-senior, director, executive; [] for all). A throttled or failed page ends the
    search but keeps what was found."""
    opts = opts or {}
    windows = sorted({max(1, min(int(w), since_days)) for w in (opts.get('windows_days') or DEFAULT_WINDOWS)})
    pages = max(1, min(int(opts.get('pages', MAX_PAGES)), MAX_PAGES))
    budget = int(opts.get('max_requests', DEFAULT_MAX_REQUESTS))
    exp = opts.get('experience', DEFAULT_EXPERIENCE)
    f_e = ','.join(str(EXPERIENCE.get(str(e).lower(), e)) for e in exp)
    places = [l if isinstance(l, dict) else {'location': l, 'work_type': opts.get('work_type')}
              for l in (opts.get('locations') or [opts.get('location', 'United States')])]
    out, used, stop = {}, 0, ''
    LAST_RUN.clear()
    stats = {d: {(q, place['location'], place.get('work_type') or ''): {'pages': 0, 'cards': 0, 'end': 'not reached'}
                 for q in queries for place in places} for d in windows}
    for days in windows:
        # Round-robin: page 1 of every query and place, then page 2, so no query starves the others.
        streams = [(q, place) for q in queries for place in places]
        for page in range(pages):
            if not streams or stop:
                break
            still = []
            for q, place in streams:
                st = stats[days][(q, place['location'], place.get('work_type') or '')]
                if used >= budget:
                    stop = f'page budget of {budget} used'
                    break
                params = {'keywords': q, 'location': place['location'], 'f_TPR': f'r{days * 86400}',
                          'start': page * PAGE_SIZE}
                if WORK_TYPE.get((place.get('work_type') or '').lower()):
                    params['f_WT'] = WORK_TYPE[place['work_type'].lower()]
                if f_e:
                    params['f_E'] = f_e
                try:
                    cards = parse_cards(fetch(SEARCH_URL + '?' + urlencode(params), headers=HEADERS, retries=4))
                    used += 1
                    if not cards and page:  # an empty page after a full one is often throttling: retry once
                        time.sleep(pause * 5)
                        cards = parse_cards(fetch(SEARCH_URL + '?' + urlencode(params), headers=HEADERS, retries=2))
                        used += 1
                except (FetchError, OSError) as e:
                    stop = f'stopped on an error: {e}'
                    st['end'] = 'error'
                    break
                st['pages'] += 1
                st['cards'] += len(cards)
                for c in cards:
                    out.setdefault(c['id'], dict(c, window=days))
                if len(cards) == PAGE_SIZE:
                    still.append((q, place))
                    st['end'] = 'page cap' if page + 1 == pages else 'more left'  # final unless a later page runs
                else:
                    st['end'] = 'ran out'
                time.sleep(pause)
            streams = still
        if stop:
            break
    LAST_RUN.update(requests=used, budget=budget, cards=len(out), stopped=stop,
                    by_window={d: sum(1 for c in out.values() if c['window'] == d) for d in windows},
                    windows={d: {'pages': sum(s['pages'] for s in ss.values()), 'cards': sum(s['cards'] for s in ss.values()),
                                 'streams': [dict(query=k[0], location=k[1], work_type=k[2], **s) for k, s in ss.items()]}
                             for d, ss in stats.items()})
    cards = sorted(out.values(), key=lambda c: (c['window'], -int(re.sub(r'\D', '', c['date'])[:8] or 0)))
    return [posting(id=f"li-{c['id']}", source='linkedin', company=c['company'], title=c['title'],
                    location=c['location'], url=c['url'], posted_at=c['date'][:10],
                    remote='remote' in c['location'].lower() or (opts.get('work_type') or '').lower() == 'remote',
                    company_linkedin=c['company_url'])  # feeds the "I'm interested" queue
            for c in cards]


def enrich(p):
    """Fetch the description for one card. Run only on cards that passed the title
    filter, to keep LinkedIn request volume low. A closed posting gets p['closed']."""
    d = parse_detail(fetch(f"{DETAIL_URL}/{p['id'][3:]}", headers=HEADERS, retries=4) or '')
    time.sleep(1.5)
    p['description'] = d['description']
    p['company_linkedin'] = p['company_linkedin'] or d['company_url']
    p['closed'] = d['closed']
    return p


def is_linkedin_url(url):
    host = (urlsplit(url).hostname or '').lower()
    return host == 'linkedin.com' or host.endswith('.linkedin.com')
