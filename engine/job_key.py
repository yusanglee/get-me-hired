"""Deterministic dedup key for a posting: one role seen on four boards is one row.

The idea (a pure function of company + title, length-capped with a hash so long
titles never collide) comes from ai-job-search's tools/job_key.py (MIT). This
version normalizes harder, because cross-board dedup has to match "Sr. Product
Manager (Remote, US)" at "Acme, Inc." with "Senior Product Manager" at "Acme".
"""
import hashlib, re, unicodedata

COMPANY_SUFFIX = re.compile(r'\b(incorporated|inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|pbc|s\.a|the)\b\.?', re.I)
TITLE_SWAPS = [
    (r'\bsr\b\.?', 'senior'), (r'\bjr\b\.?', 'junior'), (r'\bmgr\b\.?', 'manager'), (r'\bpm\b', 'product manager'),
    (r'\bvp\b', 'vice president'), (r'\bdir\b\.?', 'director'), (r'\b(ii|2)\b', 'ii'), (r'\b(iii|3)\b', 'iii'),
    (r'&', ' and '),
]
# Location and work-mode tails that boards append to titles.
TITLE_TAIL = re.compile(r'\s*(\(|\[|\s-\s|\s–\s|\s—\s|,\s*)(remote|hybrid|on-?site|us|usa|united states|north america|emea|'
                        r'[a-z .]+,\s*[a-z]{2}(?=\s*[)\]]?\s*$))\b.*$', re.I)  # "City, ST" only as the very end
CAP = 60
# A parenthetical that only says where, how or at what level ("(Remote, US)", "(Miami or San Francisco)",
# "(All Levels)") is dropped; one that names the team or product ("(Card)", "(Post-Purchase)") is part of the
# role and stays, so two different roles at one company don't share a key.
NOISE = re.compile(r'\b(remote|hybrid|on-?site|in[- ]office|us|usa|u\.s|united states|north america|emea|apac|latam|europe|'
                   r'canada|uk|anywhere|multiple|all|levels?|l\d+|ic\d+|contract|full[- ]time|part[- ]time)\b', re.I)


def slug(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def norm_company(name):
    name = COMPANY_SUFFIX.sub(' ', re.sub(r'\([^)]*\)', ' ', name or ''))
    return slug(name)


def norm_title(title):
    t = TITLE_TAIL.sub('', re.sub(r'\s+', ' ', title or '').strip())
    t = re.sub(r'\(([^)]*)\)', lambda m: m.group(0) if _keep_paren(m.group(1)) else ' ', t)
    t = t.lower()
    for pat, rep in TITLE_SWAPS:
        t = re.sub(pat, rep, t)
    return slug(t)


def _keep_paren(inner):
    """True for a parenthetical that is part of the role: a level (i, ii, iii, iv) or a team/product name, not a
    place, work mode or level range."""
    from .locfmt import cities_in
    if re.search(r'\b(i|ii|iii|iv)\b', inner, re.I):
        return True
    return not (NOISE.search(inner) or cities_in(inner) or re.fullmatch(r'[\s,/&-]*', inner))


def _cap(s):
    return s if len(s) <= CAP else s[:CAP].rstrip('-') + '-' + hashlib.sha1(s.encode()).hexdigest()[:6]


def make_key(company, title):
    c, t = norm_company(company), norm_title(title)
    if not c or not t:  # non-Latin or empty: fall back to a hash of the raw text
        raw = f'{company}|{title}'.casefold()
        return f'{c or "co"}_{t or "role"}-{hashlib.sha1(raw.encode()).hexdigest()[:8]}'
    return f'{_cap(c)}_{_cap(t)}'


job_key = make_key  # the name the plan and callers use


def company_names(company, groups=()):
    """Every normalized name one company goes by: the name itself, each name in parentheses ("Northwind (Tailspin)" is
    also "tailspin"), and every name in a config `company_aliases` group that holds any of those
    (e.g. [["Northwind", "Northwind Pay", "Tailspin"]]: a parent and the brands it hires for)."""
    names = {norm_company(company)} | {slug(p) for p in re.findall(r'\(([^)]*)\)', company or '')}
    names.discard('')
    for g in groups or ():
        members = {norm_company(m) for m in g if isinstance(m, str)} - {''}
        if names & members:
            names |= members
    return names


def alias_keys(company, title, groups=()):
    """job_keys for one role under every name its company goes by (company_names). Includes make_key's own key."""
    t = norm_title(title)
    keys = {make_key(company, title)}
    if t:
        keys |= {f'{_cap(c)}_{_cap(t)}' for c in company_names(company, groups)}
    return keys
