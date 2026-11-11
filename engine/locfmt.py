"""Where a role is based, in one short, consistent form for the tracker's `location` column.

    "LA; SF; NYC · Hybrid"     cities in posting order, then how you'd work there when the posting says
    "NYC · Remote"             a city, or remote
    "Remote (US)"              remote only

Cities: SF, NYC, LA and DC are abbreviated; other known cities keep their names; anything unrecognized
is left out rather than guessed. Work mode comes only from words that say it (the location line, the
run's own remote match, or a hint such as the user's Sheet note): Hybrid, On-site, Remote.
"""
import csv, glob, os, re

CITIES = [  # (pattern, label): order here doesn't matter; output follows the posting's order
    (r'san francisco|bay area|\bsf\b', 'SF'), (r'new york|\bnyc\b', 'NYC'), (r'los angeles|\bla\b(?! ?jolla)', 'LA'),
    (r'washington,? ?(d\.?c\.?|district of columbia)|\bdc\b', 'DC'), (r'seattle', 'Seattle'), (r'palo alto', 'Palo Alto'),
    (r'menlo park', 'Menlo Park'), (r'mountain view', 'Mountain View'), (r'san jose', 'San Jose'),
    (r'sunnyvale', 'Sunnyvale'), (r'oakland', 'Oakland'), (r'culver city', 'Culver City'),
    (r'santa monica', 'Santa Monica'), (r'el segundo', 'El Segundo'), (r'pasadena', 'Pasadena'),
    (r'torrance', 'Torrance'), (r'irvine', 'Irvine'), (r'san diego', 'San Diego'), (r'austin', 'Austin'),
    (r'chicago', 'Chicago'), (r'boston', 'Boston'), (r'denver', 'Denver'), (r'atlanta', 'Atlanta'),
    (r'pittsburgh', 'Pittsburgh'), (r'miami', 'Miami'), (r'portland', 'Portland'), (r'philadelphia', 'Philadelphia'),
    (r'salt lake', 'Salt Lake City'), (r'toronto|\bgta\b|mississauga|markham|brampton|vaughan|oakville', 'Toronto'),
    (r'vancouver|burnaby', 'Vancouver'), (r'london', 'London'),
    (r'dublin', 'Dublin'), (r'montr[eé]al|longueuil', 'Montreal'), (r'ottawa(?!,? ?(il|ks|oh)\b)|gatineau', 'Ottawa'),
    (r'calgary', 'Calgary'), (r'edmonton', 'Edmonton'), (r'waterloo(?!,? ?(ia|iowa)\b)|kitchener', 'Waterloo'),
]
MODES = [(r'hybrid|in[- ]office \d|\d+% in[- ]office|\d days?(/| a | per )week|office \d days', 'Hybrid'),
         (r'on-?site|in[- ]office(?! \d)|in person', 'On-site'), (r'remote', 'Remote')]
US = re.compile(r'\b(us|usa|u\.s\.?|united states( of america)?)\b', re.I)
CANADA = re.compile(r'\bcanada\b|\bcanadian\b', re.I)


def cities_in(text):
    """Known cities in the order they appear, each once."""
    hits = []
    for pat, label in CITIES:
        for m in re.finditer(pat, text or '', re.I):
            hits.append((m.start(), label))
    out = []
    for _, label in sorted(hits):
        if label not in out:
            out.append(label)
    return out


def modes_in(text):
    found = [label for pat, label in MODES if re.search(pat, text or '', re.I)]
    return [m for m in found if not (m == 'On-site' and 'Hybrid' in found)]  # "25% in office" is hybrid


def format_location(raw, remote=False, hint=''):
    """raw: the posting's location line; remote: the run matched it as remote; hint: other text that names
    cities or a work mode (only used for cities when raw has none). Returns '' when nothing is known."""
    raw = '' if re.match(r'\s*(source:|https?://)', raw or '') else (raw or '')
    cities = cities_in(raw) or cities_in(hint)
    modes = modes_in(raw) + [m for m in modes_in(hint) if m not in modes_in(raw)]
    if remote and 'Remote' not in modes:
        modes.append('Remote')
    if cities:
        return '; '.join(cities) + (' · ' + '/'.join(modes) if modes else '')
    if 'Remote' in modes:
        if (CANADA.search(raw) or CANADA.search(hint)) and not US.search(raw) and not US.search(hint):
            return 'Remote (Canada)'
        if CANADA.search(raw) or CANADA.search(hint):
            return 'Remote (US/Canada)'
        return 'Remote (US)' if (US.search(raw) or US.search(hint) or remote) else 'Remote'
    return ''


def jd_location(pipeline, rid):
    """The location line saved with the role's posting (state/jd/<id>.txt, line 3), or ''."""
    try:
        with open(os.path.join(pipeline, 'state', 'jd', rid + '.txt'), encoding='utf-8') as fh:
            lines = fh.read().split('\n')
    except OSError:
        return ''
    return lines[2] if len(lines) > 2 else ''


def run_locations(pipeline):
    """{id: (location_raw, matched locations)} from every discovered/reviewed/scored CSV (newest wins)."""
    out = {}
    files = sorted(glob.glob(os.path.join(pipeline, 'queue', '*-*.csv')), key=os.path.getmtime)
    for p in files:
        if not re.match(r'(discovered|reviewed|scored)-', os.path.basename(p)):
            continue
        with open(p, encoding='utf-8', newline='') as fh:
            for r in csv.DictReader(fh):
                if r.get('id'):
                    prev = out.get(r['id'], ('', ''))
                    out[r['id']] = (r.get('location_raw') or prev[0], r.get('locations') or prev[1])
    return out


def role_location(pipeline, rid, runs=None, hint=''):
    """The tracker location for a role id from what the pipeline saved about it."""
    raw, matched = (runs if runs is not None else run_locations(pipeline)).get(rid, ('', ''))
    line = jd_location(pipeline, rid)
    if re.match(r'\s*(source:|https?://)', line):
        line = ''
    return format_location(line or raw, remote='remote' in (matched or '').lower(), hint=hint)
