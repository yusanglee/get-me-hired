"""The user's facts (profile.yaml) and pipeline settings (config.json).

Everything the original pipeline hard-coded about one person lives here instead:
identity and contact, home location, work authorization, education, employment,
EEO answers, salary rule, file-name prefix, stale resume numbers, and the
location rules (which metros count, and how far the user will commute).

    from engine.profile import load_profile, load_config
    prof = load_profile('~/JobSearch/profile.yaml')
    cfg = load_config('~/JobSearch/config.json')
    prof.get('identity.email'); cfg['salary']['floor_usd']

A missing value is None, never a guess: answer rules that point at a missing key
fall through to "ask the user".
"""
import copy, json, os, re, shutil, subprocess
from . import yamlish

REQUIRED = ('identity.first_name', 'identity.last_name', 'identity.email')

# Patterns for metros a user can name in config. Anything else needs its own "pattern".
KNOWN_METROS = {
    'LA': r'los angeles|santa monica|culver city|playa vista|el segundo|burbank|glendale|pasadena|west hollywood|hollywood|venice|marina del rey|\bla\b|l\.a\.',
    'SF': r'san francisco|\bsf\b|bay area',
    'NYC': r'new york|\bnyc\b|brooklyn|manhattan',
    'Chicago': r'chicago',
    'Seattle': r'seattle|bellevue|redmond',
    'Austin': r'austin',
    'Boston': r'boston|cambridge, ma',
    'DC': r'washington,? d\.?c|\bdc\b|arlington, va',
    'Denver': r'denver|boulder',
}
# Canadian metros. Province abbreviations are matched only right after a comma (", ON"), never as bare words, and a
# province alone goes to the usual metro (Ontario -> Toronto, BC -> Vancouver, QC -> Montreal) unless another Ontario
# city is named just before it. US lookalikes (Vancouver WA, Waterloo IA, Ottawa IL) are excluded.
_OTHER_ON = ('ottawa', 'waterloo', 'kitchener', 'london', 'kingston', 'windsor')
_ON_ABBR = ''.join(f'(?<!{c})' for c in _OTHER_ON)
_ON_FULL = ''.join(f'(?<!{c}, )(?<!{c},)' for c in _OTHER_ON)
KNOWN_METROS.update({
    'Toronto': (r'toronto|\bgta\b|mississauga|markham|brampton|vaughan|oakville|richmond hill|scarborough|etobicoke|north york|'
                + _ON_ABBR + r',\s*on\b(?![- ]?(?:site|call|demand))|' + _ON_FULL + 'ontario'),
    'Vancouver': r'vancouver(?!,?\s*(?:wa\b|washington))|burnaby|coquitlam|new westminster|british columbia|\bbc\b',
    'Montreal': r'montr[eé]al|longueuil|laval|qu[eé]bec|\bqc\b',
    'Ottawa': r'ottawa(?!,?\s*(?:il\b|ks\b|oh\b|illinois|kansas|ohio))|gatineau|kanata',
    'Calgary': r'calgary|(?<!edmonton),\s*ab\b',
    'Edmonton': r'edmonton',
    'Waterloo': r'waterloo(?!,?\s*(?:ia\b|iowa))|kitchener',
})
CANADIAN_METROS = ('Toronto', 'Vancouver', 'Montreal', 'Ottawa', 'Calgary', 'Edmonton', 'Waterloo')
SUPPORTED_COUNTRIES = ('US', 'CA')
METRO_STATE = {'LA': ('CA', 'California'), 'SF': ('CA', 'California'), 'NYC': ('NY', 'New York'), 'Chicago': ('IL', 'Illinois'),
               'Seattle': ('WA', 'Washington'), 'Austin': ('TX', 'Texas'), 'Boston': ('MA', 'Massachusetts'),
               'DC': ('DC', 'District of Columbia'), 'Denver': ('CO', 'Colorado'),
               'Toronto': ('ON', 'Ontario'), 'Vancouver': ('BC', 'British Columbia'), 'Montreal': ('QC', 'Quebec'),
               'Ottawa': ('ON', 'Ontario'), 'Calgary': ('AB', 'Alberta'), 'Edmonton': ('AB', 'Alberta'),
               'Waterloo': ('ON', 'Ontario')}
LEGACY_METROS = {'los_angeles': 'LA', 'san_francisco': 'SF', 'new_york_city': 'NYC'}
NON_US_REMOTE = (r'canada|uk|united kingdom|emea|europe|india|apac|latam|mexico|brazil|germany|ireland|poland|australia|'
                 r'singapore|japan|israel|spain|france|netherlands|toronto|london|dublin|berlin')

NO_RANGE_POLICIES = ('include', 'exclude', 'include_if_level_fits')  # same set as packs.NO_RANGE_POLICIES

DEFAULT_CONFIG = {
    # floor_usd / floor_cad: the lowest top-of-range pay worth a look, in that currency (no conversion between them);
    # a CAD range with no floor_cad is not dropped for pay
    'salary': {'floor_usd': None, 'floor_cad': None, 'rule': 'top_of_range', 'no_range_policy': 'include_if_level_fits',
               'down_level_below': None, 'band_policy': 'home_first'},
    # remote_countries: where "Remote" postings may be hired ("US", "CA"); absent means ["US"] when remote_us is true,
    # [] when false. normalize_locations fills it in and sets remote_us to "remote counts at all".
    # top: optional first-choice locations (metro names and/or 'Remote'); roles there get top_bonus fit points
    # and are shown in green. Empty means one tier: every target location counts the same.
    'locations': {'home': None, 'home_state': None, 'remote_us': True, 'metros': [], 'non_us_remote': NON_US_REMOTE,
                  'top': [], 'top_bonus': 5},
    # over_bar_tier: "B" holds roles asking more years than the profile, or managers of managers when the
    # profile says no, out of tier A (engine/triage.py over_bar); "A" turns the hold off (flags stay)
    # gap_rules: what a cached posting read does (engine/reads.py): critical "section" (own tier "gap", out of review)
    # or "flag"; major "B" (an A is held to B) or "flag"
    'scoring': {'tier_a': 70, 'tier_b': 55, 'near_miss_margin': 5, 'over_bar_tier': 'B',
                'gap_rules': {'critical': 'section', 'major': 'B'}},
    # company cap: at most max_applications reviewable roles per company, counting applications made in the
    # last window_days (rolling); company_limits adds employer-specific limits (max 0 = never apply)
    'per_company': {'max_applications': 5, 'window_days': 90},
    'paths': {'soffice': None},
    'resume': {'pages': 2, 'page_breaks': {}, 'max_bullet_lines': 2, 'max_summary_lines': 4, 'max_extra_bullets': 1,
               'font': None, 'sections': ['EXECUTIVE SUMMARY', 'PROFESSIONAL EXPERIENCE', 'SKILLS', 'EDUCATION']},
    'sources': {},
    'gates': {'enabled': True},
    'since_days': 14,
    # LinkedIn follow-up only right after applying: Gmail-imported applications older than this are
    # history (used for dedup), never follow-ups. Applications made through the plugin always qualify.
    'linkedin': {'gmail_followup_days': 7},
}


class Profile(dict):
    """A dict with dotted-path lookup: prof.get('eeo.gender')."""

    def get(self, path, default=None):
        node = self
        for part in str(path).split('.'):
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                return default
        return default if node is None else node

    def require(self, path):
        v = self.get(path)
        if v in (None, ''):
            raise KeyError(f'profile.yaml is missing {path}')
        return v


def load_profile(path):
    path = os.path.expanduser(path)
    data = yamlish.load(path) if path.endswith(('.yaml', '.yml')) else json.load(open(path, encoding='utf-8'))
    prof = Profile(data or {})
    missing = [k for k in REQUIRED if prof.get(k) in (None, '')]
    if missing:
        raise ValueError(f'{path}: missing required {", ".join(missing)}')
    return prof


def full_name(prof):
    return f"{prof.require('identity.first_name')} {prof.require('identity.last_name')}"


def filename_prefix(prof):
    """'First_Last_' by default; profile files.prefix overrides it."""
    custom = prof.get('files.prefix')
    if custom:
        return custom
    return re.sub(r'[^A-Za-z0-9]+', '_', full_name(prof)).strip('_') + '_'


def home_display(prof):
    """'Los Angeles, CA' from home.city + home.state_code (or home.state)."""
    city, st = prof.get('home.city'), prof.get('home.state_code') or prof.get('home.state')
    return ', '.join(x for x in (city, st) if x) or None


def salary_ask(prof, top, bottom=None):
    """The number to enter when a form requires one: max(top x factor, range bottom, floor), rounded.
    With no posted range, the floor. Factor, floor and rounding come from profile salary.*."""
    floor = prof.get('salary.floor')
    if not top:
        return str(floor) if floor else None
    factor, step = prof.get('salary.top_factor', 0.75), prof.get('salary.round_to', 5000)
    v = max(top * factor, bottom or 0, floor or 0)
    return str(int(round(v / step) * step))


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def normalize_locations(loc):
    """Accept the original pipeline's shape ({los_angeles: 'any', san_francisco: 'hybrid_ok', sf_max_office_days: 3})
    and return the generic one ({metros: [{name, pattern, policy, max_office_days}], ...})."""
    loc = dict(loc or {})
    metros = list(loc.get('metros') or [])
    for key, name in LEGACY_METROS.items():
        if key in loc and not any(m.get('name') == name for m in metros):
            m = {'name': name, 'policy': loc.pop(key)}
            if name == 'SF' and 'sf_max_office_days' in loc:
                m['max_office_days'] = loc.pop('sf_max_office_days')
            metros.append(m)
    for m in metros:
        if not m.get('pattern'):
            if m['name'] not in KNOWN_METROS:
                raise ValueError(f"location {m['name']!r} needs a 'pattern' (regex on the posting's location text)")
            m['pattern'] = KNOWN_METROS[m['name']]
        m.setdefault('policy', 'any')
    loc['metros'] = metros
    rc = loc.get('remote_countries')
    if rc is None:
        loc['remote_countries'] = ['US'] if loc.get('remote_us') else []
    else:
        codes = []
        for c in [rc] if isinstance(rc, str) else rc:
            c = str(c).strip().upper()
            if c not in SUPPORTED_COUNTRIES:
                raise ValueError(f"locations.remote_countries {c!r}: supported countries are {', '.join(SUPPORTED_COUNTRIES)}")
            if c not in codes:
                codes.append(c)
        loc['remote_countries'] = codes
        loc['remote_us'] = bool(codes)  # the older switch now means "Remote counts as a location"
    names = {m['name'] for m in metros} | ({'Remote'} if loc.get('remote_us') else set())
    unknown = [t for t in loc.get('top') or [] if t not in names]
    if unknown:
        raise ValueError(f"locations.top names {', '.join(map(repr, unknown))}: not a configured metro"
                         + (" or 'Remote'" if loc.get('remote_us') else " (remote_us is off, so 'Remote' can't be top)"))
    for rule in loc.get('company_rules') or []:
        missing = [k for k in ('company', 'when', 'as') if not rule.get(k)]
        if missing:
            raise ValueError(f"locations.company_rules entry {rule!r} needs {', '.join(missing)}")
        for k in ('company', 'when'):
            try:
                re.compile(rule[k])
            except re.error as e:
                raise ValueError(f"locations.company_rules {k!r} {rule[k]!r} is not a valid regex: {e}")
        if rule['as'] not in names:
            raise ValueError(f"locations.company_rules 'as' {rule['as']!r}: not a configured metro"
                             + (" or 'Remote'" if loc.get('remote_us') else ''))
    if not loc.get('home') and metros:
        loc['home'] = metros[0]['name']
    if not loc.get('home_state') and loc.get('home') in METRO_STATE:
        loc['home_state'] = list(METRO_STATE[loc['home']])  # [code, name]: pay bands are often labeled by state
    return loc


def load_config(path_or_dict):
    raw = path_or_dict if isinstance(path_or_dict, dict) else json.load(open(os.path.expanduser(path_or_dict), encoding='utf-8'))
    cfg = _merge(DEFAULT_CONFIG, {k: v for k, v in raw.items() if not k.startswith('_')})
    cfg['locations'] = normalize_locations(_merge(DEFAULT_CONFIG['locations'], raw.get('locations') or {}))
    policy = cfg['salary'].get('no_range_policy')
    if policy not in NO_RANGE_POLICIES:
        from .packs import PackError  # the same error the pack's own policy raises; imported late (packs imports this module)
        raise PackError(f"config salary.no_range_policy must be one of {', '.join(NO_RANGE_POLICIES)}, not {policy!r}")
    return cfg


def find_soffice(cfg=None):
    """LibreOffice's soffice: config paths.soffice, then $SOFFICE, then PATH, then the usual install spots."""
    candidates = [((cfg or {}).get('paths') or {}).get('soffice'), os.environ.get('SOFFICE'),
                  shutil.which('soffice'), shutil.which('libreoffice'),
                  '/Applications/LibreOffice.app/Contents/MacOS/soffice', '/usr/bin/soffice', '/usr/lib/libreoffice/program/soffice',
                  r'C:\Program Files\LibreOffice\program\soffice.exe']
    for c in candidates:
        if c and os.path.exists(os.path.expanduser(c)):
            return os.path.expanduser(c)
    return None


def soffice_pdf(soffice, out_dir, *docs):
    """Convert .docx files to PDF with LibreOffice. It can hang (another LibreOffice instance may hold the user profile), so it times out."""
    try:
        subprocess.run([soffice, '--headless', '--convert-to', 'pdf', '--outdir', out_dir, *docs], check=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        name = os.path.basename(docs[0]) if len(docs) == 1 else f'{len(docs)} documents'
        raise RuntimeError(f"LibreOffice didn't finish converting {name} in 3 minutes; quit LibreOffice "
                           '(close any open LibreOffice windows) and try again') from None
