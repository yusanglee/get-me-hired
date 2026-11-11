"""Pay ranges: parse them, pick the band for where the user would work, and look up
pay the job board didn't show.

Three problems this solves (all seen Oct 20, 2026):
* A posting lists several location bands ("Bay Area $160K-$215K, Los Angeles $150K-$200K").
  Taking the overall top overstates pay for a user who'd work in LA. `pick_band` uses
  the band for the user's best-matching location (home metro first).
* An aggregator card (LinkedIn) shows no range, but the company's own posting does.
  `lookup_pay` finds the same role on the company's Greenhouse, Lever or Ashby board.
* Ashby returns bands as structured tiers; `ashby_bands` reads them.

Currencies (only when the config asks for Canada: locations.remote_countries has "CA" or salary.floor_cad is set;
otherwise every figure is read exactly as before): a range written "CA$120,000 - CA$150,000", "C$", "CAD $", or
"$120k-$150k CAD" is CAD; "US$" or "USD" is USD; a plain "$" is USD unless every matched location is a Canadian metro
and the posting never mentions USD. Floors are per currency (salary.floor_usd, salary.floor_cad) and nothing is
converted: a CAD range with no floor_cad is never dropped for pay.
"""
import re
from .job_key import norm_title, norm_company, slug
from .locations import preference_order, remote_countries
from .profile import CANADIAN_METROS

# An amount is "$150,000", "$150k", or the same with a US prefix: "US$", "US $", "U.S. $", "USD $", or "USD" alone
# ("USD 150,000"). The prefix matters only before the second figure: "US$111,974 to US$172,826" (Nov 11).
_US = r'(?:(?<![A-Za-z])(?:USD|US|U\.S\.)\s?)?(?:\$|(?<=USD)|(?<=USD )|(?<=usd)|(?<=usd ))\s?'
_FIG = r'(\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d+)?\s?[kK])'
AMT = _US + _FIG
# The second figure may drop the mark when the first has it: "$150,000 - 200,000", "USD 150,000 – 200,000"; not
# after "and" ("$150k and 200k users").
_BARE = r'(?<!and )(?<!and)'
AMT2 = r'(?:' + _US + r'|' + _BARE + r')' + _FIG
# A short note may sit between the figures: "$135,000 (entry level qualifications) to $160,000 (highly experienced)"
PAIR_RE = re.compile(AMT + r'\s*(?:USD|US dollars)?\s*(?:\([^()$\n]{1,60}\)\s*)?(?:-|to|–|—|and)\s*' + AMT2, re.I)
# With Canada on: amounts may carry a currency before ("CA$", "C$", "CAD $", "US$", "USD $", "CAD"/"USD" with no $)
# or after ("CAD", "USD")
_NUM = r'(\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d+)?\s?[kK])'
_PRE_C = r'(?<![A-Za-z])(?:(CAD|USD|CA|US|U\.S\.|C)\s?)?(?:\$|(?<=CAD|USD|cad|usd)|(?<=CAD |USD |cad |usd ))\s?'
_POST_C = r'(?:\s?(CAD|USD|Canadian dollars?|US dollars?)\b)?'
_AMT_C = _PRE_C + _NUM + _POST_C
_AMT_C2 = r'(?:' + _PRE_C + r'|' + _BARE + r')' + _NUM + _POST_C  # second figure: the mark may be dropped, as in AMT2
PAIR_RE_CA = re.compile(_AMT_C + r'\s*(?:\([^()$\n]{1,60}\)\s*)?(?:-|to|–|—|and)\s*' + _AMT_C2, re.I)
USD_MENTION = re.compile(r'\bUSD\b|\bUS\$|\bU\.S\. dollars|\bUS dollars', re.I)
CAD_MENTION = re.compile(r'\bCAD\b|\bC\$|\bCA\$|Canadian dollars?', re.I)
REMOTE_BAND = r'\bremote\b'
OTHER_BAND = r'all other|other (u\.?s\.?|us|locations|states|areas|cities)|national|anywhere in the u'
CITY_STATE = re.compile(r"[A-Z][a-z]+(?: [A-Z][a-z]+)*,\s*(?:[A-Z]{2}\b|[A-Z][a-z]+)")  # 'San Jose, CA', 'Plano, Texas'
LABEL_SPAN = 140


def to_num(s):
    s = s.replace(',', '').replace(' ', '')
    return float(s[:-1]) * 1000 if s[-1] in 'kK' else float(s)


def _cur(*tags):
    """'CAD' / 'USD' from currency tags found around a figure when they agree, else None (not stated)."""
    kinds = {('CAD' if t.lower().startswith(('c', 'ca')) else 'USD') for t in tags if t}
    return kinds.pop() if len(kinds) == 1 else None


def pairs(text, cad=False):
    """Every plausible annual (lo, hi) pair in the text, with its position."""
    return [x[:4] for x in _pairs_cur(text, cad)]


def _pairs_cur(text, cad=False):
    """(lo, hi, start, end, currency) for every plausible pair. currency is None unless cad is on and the text says."""
    out = []
    if not cad:
        for m in PAIR_RE.finditer(text or ''):
            lo, hi = to_num(m.group(1)), to_num(m.group(2))
            if 50_000 <= lo <= hi <= 1_500_000:
                out.append((lo, hi, m.start(), m.end(), None))
        return out
    for m in PAIR_RE_CA.finditer(text or ''):
        lo, hi = to_num(m.group(2)), to_num(m.group(5))
        if 50_000 <= lo <= hi <= 1_500_000:
            out.append((lo, hi, m.start(), m.end(), _cur(m.group(1), m.group(3), m.group(4), m.group(6))))
    return out


def text_bands(text, cad=False):
    """Location-labeled bands written in the description, e.g. 'Zone A (San Francisco, NYC): $X - $Y'.
    The label is the text just before each pair, back to the previous pair or line break."""
    ps = _pairs_cur(text, cad)
    if len({(x[0], x[1]) for x in ps}) < 2:
        return []
    bands, prev_end = [], 0
    for lo, hi, s, e, cur in ps:
        start = max(prev_end, s - LABEL_SPAN)
        label = text[start:s]
        label = re.split(r'\n', label)[-1] if '\n' in label.strip() else label
        bands.append({'label': label.strip(' :-–—\t'), 'min': lo, 'max': hi, **({'currency': cur} if cad else {})})
        prev_end = e
    return bands


def ashby_bands(comp):
    """Ashby compensationTiers -> [{'label', 'min', 'max'}] for annual salary components."""
    out = []
    for tier in (comp or {}).get('compensationTiers') or []:
        for c in tier.get('components') or []:
            if c.get('compensationType') == 'Salary' and c.get('interval') in (None, '1 YEAR') and c.get('maxValue'):
                out.append({'label': tier.get('title') or '', 'min': c.get('minValue'), 'max': c.get('maxValue')})
    return out


def _state_rx(cfg):
    st = cfg['locations'].get('home_state') or []
    st = [st] if isinstance(st, str) else st
    parts = [rf'\b{re.escape(x)}\b' for x in st if len(x) == 2] + [rf'(?i:\b{re.escape(x)}\b)' for x in st if len(x) > 2]
    return '|'.join(parts) or None


def pick_band(bands, hits, cfg, with_currency=False):
    """The band for where the user would work: (min, max, location_name), or None if no band names
    any of the posting's matched locations. Location order: home metro, remote, then config order.
    Remote checks an explicit 'Remote' band first. For the home metro and remote, a band labeled only
    by state ('CA, CT, NJ, NY, WA') counts when it includes the home state; a city band ('San Jose, CA')
    does not. Remote falls back to an 'all other locations' band last. with_currency: also return the matched
    bands' stated currency (None when they don't say) as a fourth item."""
    metros = {m['name']: m['pattern'] for m in cfg['locations']['metros']}
    home, state = cfg['locations'].get('home'), _state_rx(cfg)

    def other_metro(label, name):
        return any(re.search(p, label.lower()) for n, p in metros.items() if n != name)

    for name in preference_order(hits, cfg):
        tests = []
        if name in metros:
            tests.append(lambda b, p=metros[name]: re.search(p, b['label'].lower()))
        if name == 'Remote':
            tests.append(lambda b: re.search(REMOTE_BAND, b['label'].lower()))
        if state and name in (home, 'Remote'):
            tests.append(lambda b, n=name: re.search(state, b['label']) and not CITY_STATE.search(b['label'])
                         and not other_metro(b['label'], n if n != 'Remote' else home))
        if name == 'Remote':
            tests.append(lambda b: re.search(OTHER_BAND, b['label'].lower()))
        for test in tests:
            match = [b for b in bands if test(dict(b, label=b.get('label') or ''))]
            if match:
                lo, hi = min(b['min'] or b['max'] for b in match), max(b['max'] for b in match)
                if with_currency:
                    return lo, hi, name, next((b.get('currency') for b in match if b.get('currency')), None)
                return lo, hi, name
    return None


def canada_on(cfg):
    """Whether currencies matter for this config: CA among the remote countries, or a CAD floor set."""
    if not cfg:
        return False
    return 'CA' in remote_countries(cfg.get('locations') or {}) or bool((cfg.get('salary') or {}).get('floor_cad'))


def _resolve_currency(cur, text, hits):
    """A stated currency stands. Unstated: CAD only when every matched location is a Canadian metro and the posting
    never mentions USD, or the posting says CAD somewhere and never USD; else USD (the conservative default)."""
    if cur:
        return cur
    if USD_MENTION.search(text or ''):
        return 'USD'
    if hits and all(h in CANADIAN_METROS for h in hits):
        return 'CAD'
    return 'CAD' if CAD_MENTION.search(text or '') else 'USD'


def floor_for(cfg, currency):
    """The pay floor for a currency (salary.floor_cad for CAD, else salary.floor_usd); None when not set."""
    sal = (cfg or {}).get('salary') or {}
    return sal.get('floor_cad') if currency == 'CAD' else sal.get('floor_usd')


def below_floor(hi, currency, cfg):
    """Whether a range topping out at `hi` (in `currency`) is under that currency's floor. No floor set for the
    currency means never: a CAD range with no salary.floor_cad is kept."""
    floor = floor_for(cfg, currency)
    return bool(floor and hi is not None and hi < floor)


def salary_full(text, smin=None, smax=None, bands=None, hits=(), cfg=None):
    """(lo, hi, source, currency). currency is 'USD' unless Canada is on in cfg (see canada_on) and the range is CAD."""
    cad = canada_on(cfg)
    bands = list(bands or []) + text_bands(text, cad)
    if bands and cfg and hits:
        pick = pick_band(bands, hits, cfg, with_currency=True)
        if pick:
            return pick[0], pick[1], f'band:{pick[2]}', (_resolve_currency(pick[3], text, hits) if cad else 'USD')
    if smax:
        return smin, smax, 'board', (_resolve_currency(None, text, hits) if cad else 'USD')
    ps = _pairs_cur(text, cad)
    if not ps:
        return None, None, 'none', 'USD'
    if cad:
        tagged = [(x, _resolve_currency(x[4], text, hits)) for x in ps]
        want = 'CAD' if hits and all(h in CANADIAN_METROS for h in hits) else 'USD'
        have = {c for _, c in tagged}
        cur = want if want in have else sorted(have)[0]
        ps = [x for x, c in tagged if c == cur]
    else:
        cur = 'USD'
    return min(p[0] for p in ps), max(p[1] for p in ps), 'jd_text', cur


def salary(text, smin=None, smax=None, bands=None, hits=(), cfg=None):
    """(lo, hi, source) for a posting. With location bands, the band for the user's location wins.
    source: 'band:<loc>', 'board', 'jd_text', or 'none'; ' CAD' is added when Canada is on and the range is in
    Canadian dollars (use salary_full for the currency itself and below_floor for the per-currency floor)."""
    lo, hi, src, cur = salary_full(text, smin, smax, bands, hits, cfg)
    return lo, hi, (src + ' CAD' if cur == 'CAD' else src)


def slug_guesses(company):
    """Board slugs to try for a company not on the watchlist: 'Acme Health, Inc.' -> acmehealth, acme-health."""
    s = slug(norm_company(company) or company)
    return list(dict.fromkeys(x for x in (s.replace('-', ''), s) if x))


def lookup_pay(company, title, ats_cache=None, adapters=None, memo=None, guess=True):
    """Find the same role on the company's own ATS board and return its pay, or None.

    Looks at the watchlist's resolved board for this company first (ats_cache: name -> [ats, slug]),
    then, if `guess`, tries slug guesses on Greenhouse, Lever and Ashby. Title match is by
    normalized title, so 'Sr. Product Manager (Remote)' matches 'Senior Product Manager'.
    Returns {'salary_min', 'salary_max', 'pay_bands', 'url', 'ats', 'slug'}; None when not found
    or when the board posting has no range either. `memo` caches boards across calls in one run."""
    if adapters is None:
        from .sources.ats import ADAPTERS as adapters
    memo = {} if memo is None else memo
    want, co = norm_title(title), norm_company(company)
    boards = [tuple(r) for name, r in (ats_cache or {}).items() if r and norm_company(name) == co]
    if guess:
        boards += [(ats, s) for s in slug_guesses(company) for ats in adapters]
    for key in dict.fromkeys(boards):
        if key not in memo:
            try:
                memo[key] = adapters[key[0]](key[1], company) or []
            except Exception:  # a failed guess is just a miss
                memo[key] = []
        for q in memo[key]:
            if norm_title(q['title']) == want and (q.get('salary_max') or q.get('pay_bands') or pairs(q.get('description', ''))):
                lo, hi, _ = salary(q.get('description', ''), q.get('salary_min'), q.get('salary_max'))
                return {'salary_min': lo, 'salary_max': hi, 'pay_bands': q.get('pay_bands') or [],
                        'url': q.get('url'), 'ats': key[0], 'slug': key[1]}
    return None
