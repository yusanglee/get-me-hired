"""Source-host check: catch posting links whose domain imitates a known ATS or job board.

A posting from boards.greenhouse.io is fine; one from greenhouse-jobs.com, greenhovse.io or
greenhouse.com is a look-alike and is never opened or filled. Company career sites
(careers.example.com) are 'other': allowed, since every employer has its own.

    check('https://job-boards.greenhouse.io/acme/jobs/1') -> ('known', 'greenhouse.io')
    check('https://greenhovse.io/acme')                  -> ('lookalike', 'greenhouse.io')
"""
import re
from urllib.parse import urlparse

KNOWN = ('greenhouse.io', 'ashbyhq.com', 'lever.co', 'myworkdayjobs.com', 'myworkdaysite.com', 'smartrecruiters.com',
         'workable.com', 'jobvite.com', 'icims.com', 'bamboohr.com', 'teamtailor.com', 'rippling.com', 'eightfold.ai',
         'careerpuck.com', 'gem.com', 'recruitee.com', 'breezy.hr', 'jazzhr.com', 'successfactors.com', 'taleo.net',
         'linkedin.com', 'builtin.com', 'himalayas.app', 'remotive.com', 'remoteok.com', 'remote100k.com', 'nodesk.co',
         'hiring.cafe', 'wellfound.com', 'indeed.com', 'glassdoor.com', 'comparably.com', 'ycombinator.com')
TWO_PART_TLDS = ('co.uk', 'com.au', 'co.jp', 'com.br', 'co.in')


def registrable(host):
    """'job-boards.greenhouse.io' -> 'greenhouse.io' (last two labels, three for co.uk-style suffixes)."""
    parts = (host or '').lower().rstrip('.').split('.')
    n = 3 if '.'.join(parts[-2:]) in TWO_PART_TLDS else 2
    return '.'.join(parts[-n:])


def _dist(a, b):
    """Optimal string alignment distance (edits and adjacent swaps)."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def check(url):
    """('known' | 'lookalike' | 'other' | 'invalid', the known domain it matches or imitates, or '')."""
    try:
        u = urlparse(url or '')
    except ValueError:
        return 'invalid', ''
    host = (u.hostname or '').lower()
    if u.scheme not in ('http', 'https') or not host or '.' not in host:
        return 'invalid', ''
    reg = registrable(host)
    if reg in KNOWN:
        return 'known', reg
    if 'xn--' in host:
        return 'lookalike', 'punycode host'
    name = reg.split('.')[0]
    for k in KNOWN:
        kname = k.split('.')[0]
        if len(kname) < 5:
            continue  # short names (gem) would match too many real domains
        if name == kname or (kname in re.split(r'[-.]', host) or kname in name.split('-')):
            return 'lookalike', k  # same name on another domain, or the name inside someone else's domain
        if len(kname) >= 6 and _dist(name, kname) <= (1 if len(kname) < 9 else 2):
            return 'lookalike', k
    return 'other', ''
