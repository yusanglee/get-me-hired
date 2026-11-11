"""Remote-job boards with official public APIs: Himalayas, Remotive, RemoteOK.

Terms each one sets (checked Oct 2026):
* Himalayas: credit Himalayas, send applicants via applicationLink, don't resubmit
  its jobs to other boards. Search is 20 per page.
* Remotive: credit Remotive; jobs arrive 24h late; at most ~4 calls a day.
* RemoteOK: link back to Remote OK as the source; no logo use. Descriptions are
  known to carry hidden "include this word" filters, so always run the guard.
All three are personal-use reads; get-me-hired never republishes their listings.
"""
import datetime, time
from urllib.parse import urlencode, quote
from .base import posting, fetch_json, strip_html, FetchError

KIND = 'board'


def _since(days):
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)


def _iso(epoch):
    try:
        return datetime.datetime.fromtimestamp(int(float(epoch)), datetime.timezone.utc).strftime('%Y-%m-%d')
    except (TypeError, ValueError):
        return ''


def _num(v):
    try:
        return float(v) if v not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        return None


def himalayas(queries, since_days=14, opts=None):
    """Himalayas search API. opts: country (e.g. 'US'), seniority (e.g. 'Senior,Manager,Director'),
    employment_type, pages (default 3), remote_countries (config locations.remote_countries, default ["US"]):
    pay is kept when paid in USD, or in CAD when "CA" is listed (the CAD range is written into the description as
    "Compensation: C$min - C$max CAD" so engine.pay reads it with its currency)."""
    opts = opts or {}
    countries = [str(c).upper() for c in (opts.get('remote_countries') or ['US'])]
    cutoff = _since(since_days).timestamp()
    out = {}
    for q in queries:
        for page in range(1, opts.get('pages', 3) + 1):
            params = {'q': q, 'sort': 'recent', 'page': page}
            for k in ('country', 'seniority', 'employment_type'):
                if opts.get(k):
                    params[k] = opts[k]
            d = fetch_json('https://himalayas.app/jobs/api/search?' + urlencode(params))
            jobs = (d or {}).get('jobs') or []
            for j in jobs:
                if float(j.get('pubDate') or 0) < cutoff:
                    continue
                cur = (j.get('currency') or 'USD').upper()
                yearly = (j.get('salaryPeriod') or 'annual') == 'annual'
                annual = yearly and cur == 'USD'
                cad_line = ''
                if yearly and cur == 'CAD' and 'CA' in countries and _num(j.get('minSalary')) and _num(j.get('maxSalary')):
                    cad_line = f"Compensation: C${_num(j.get('minSalary')):,.0f} - C${_num(j.get('maxSalary')):,.0f} CAD\n"
                locs = j.get('locationRestrictions') or []
                guid = j.get('guid') or j.get('applicationLink', '')
                out[guid] = posting(
                    id='hm-' + guid.rstrip('/').rsplit('/', 1)[-1][:80], source='himalayas',
                    company=j.get('companyName', ''), title=j.get('title', ''),
                    location=', '.join(locs) if locs else 'Worldwide', remote=True,
                    salary_min=_num(j.get('minSalary')) if annual else None,
                    salary_max=_num(j.get('maxSalary')) if annual else None,
                    url=guid, apply_url=j.get('applicationLink') or guid, posted_at=_iso(j.get('pubDate')),
                    description=cad_line + strip_html(j.get('description') or ''))
            # Pages can hold fewer than 20 jobs before the end, so stop only when a page
            # is empty or reaches past the cutoff (results are sorted newest first).
            if not jobs or any(float(j.get('pubDate') or 0) < cutoff for j in jobs):
                break
            time.sleep(1)
    return list(out.values())


def remotive(queries, since_days=14, opts=None):
    """Remotive API. Keep calls low: one per query, and few queries."""
    cutoff = _since(since_days).strftime('%Y-%m-%d')
    out = {}
    for q in queries[:4]:
        d = fetch_json('https://remotive.com/api/remote-jobs?' + urlencode({'search': q, 'limit': 100}))
        for j in (d or {}).get('jobs') or []:
            date = (j.get('publication_date') or '')[:10]
            if date and date < cutoff:
                continue
            out[j['id']] = posting(
                id=f"rm-{j['id']}", source='remotive', company=j.get('company_name', ''), title=j.get('title', ''),
                location=j.get('candidate_required_location') or 'Worldwide', remote=True,
                url=j.get('url', ''), posted_at=date, description=strip_html(j.get('description') or ''))
    return list(out.values())


def remoteok(queries, since_days=14, opts=None):
    """RemoteOK API, filtered by tag. opts: tags (default derived from queries)."""
    opts = opts or {}
    tags = opts.get('tags') or sorted({q.lower().split()[-2] if len(q.split()) > 1 else q.lower() for q in queries})
    cutoff = _since(since_days).timestamp()
    out = {}
    for tag in tags[:5]:
        d = fetch_json('https://remoteok.com/api?tag=' + quote(tag))
        for j in (d or [])[1:]:  # element 0 is the legal notice
            if float(j.get('epoch') or 0) < cutoff:
                continue
            out[j['id']] = posting(
                id=f"rok-{j['id']}", source='remoteok', company=j.get('company', ''), title=j.get('position', ''),
                location=j.get('location') or 'Remote', remote=True,
                salary_min=_num(j.get('salary_min')), salary_max=_num(j.get('salary_max')),
                url=j.get('url', ''), apply_url=j.get('apply_url') or j.get('url', ''),
                posted_at=(j.get('date') or '')[:10], description=strip_html(j.get('description') or ''))
        time.sleep(1)
    return list(out.values())


SEARCHERS = {'himalayas': himalayas, 'remotive': remotive, 'remoteok': remoteok}
NOTES = {
    'himalayas': 'Official API. Credit Himalayas; apply via its applicationLink.',
    'remotive': 'Official API. Credit Remotive; listings are 24h delayed; max ~4 calls/day.',
    'remoteok': 'Official API. Credit and link back to Remote OK.',
}
