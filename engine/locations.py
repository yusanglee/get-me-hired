"""Which of the user's target locations a posting matches, and the office/relocation answer for it.

Metros come from config locations.metros (see engine.profile.normalize_locations):
    {"name": "SF", "pattern": "san francisco|bay area", "policy": "hybrid_ok", "max_office_days": 3}
Policies: "any" (on-site fine), "hybrid_ok" (at most max_office_days a week), "remote_only".
Optional tiers: locations.top lists first-choice names (e.g. ["LA", "Remote"]); the other metros are second tier.
Remote postings: locations.remote_countries (["US"], ["US", "CA"], ["CA"]) says where the user can be hired
remotely; the older remote_us true/false means ["US"]/[]. With only "US" the matching below is exactly the original.
Optional company rules: locations.company_rules counts one company's postings as a metro when the location text
matches, e.g. {"company": "brightwater", "when": "multiple locations", "as": "LA"} (regexes, case-insensitive).
"""
import re
from .profile import home_display


CA_TERMS = {'canada', 'toronto'}  # NON_US_REMOTE words that stop being a reason to drop a remote role when CA is in
CA_WORDS = re.compile(r'canada|canadian|ontario|british columbia|alberta|qu[eé]bec|nova scotia|manitoba|saskatchewan|'
                      r'new brunswick|newfoundland|toronto|vancouver|montr[eé]al|ottawa|calgary|edmonton|waterloo|kitchener', re.I)
US_REMOTE_WORDS = re.compile(r'\bus\b|united states|usa|u\.s\.')


def remote_countries(loc_cfg):
    """The country codes where a Remote posting counts: config locations.remote_countries, else ["US"] for
    remote_us true (or absent: today's default) and [] for false."""
    rc = loc_cfg.get('remote_countries')
    if rc is None:
        return ['US'] if loc_cfg.get('remote_us') else []
    return list(rc)


def _remote_eligible(loc, loc_cfg, countries):
    """Whether a lowercased location that says remote is open to someone hireable in `countries` (CA is one of them):
    a country restriction (none, US, Canada, North America, US or Canada) must overlap, and a non-US/CA restriction
    (UK, EMEA...) with no US/CA named is out."""
    rx = loc_cfg.get('non_us_remote') or ''
    others = rx if '(' in rx else '|'.join(w for w in rx.split('|') if w.strip() not in CA_TERMS)
    named = set()
    if US_REMOTE_WORDS.search(loc) or 'north america' in loc:
        named.add('US')
    if CA_WORDS.search(loc) or 'north america' in loc:
        named.add('CA')
    if not named:
        return not (others and re.search(others, loc.replace('remote', '')))
    return bool(named & set(countries))


def location_match(location, workplace, cfg, company=''):
    """Names of the configured metros (plus 'Remote') that this posting's location text matches."""
    loc_cfg = cfg['locations']
    loc = f'{location or ""} {workplace or ""}'.lower()
    hits = [m['name'] for m in loc_cfg['metros'] if re.search(m['pattern'], loc)]
    countries = remote_countries(loc_cfg)
    if loc_cfg.get('remote_us') and 'CA' in countries:
        bare = ' '.join(re.sub(r'[^a-z ]', ' ', loc).split())
        if (('US' in countries and bare in ('united states', 'us', 'usa', 'united states of america'))
                or bare == 'canada' or 'remote-friendly' in loc):
            hits.append('Remote')
        if 'remote' in loc and 'Remote' not in hits and _remote_eligible(loc, loc_cfg, countries):
            hits.append('Remote')
    elif loc_cfg.get('remote_us'):
        bare = ' '.join(re.sub(r'[^a-z ]', ' ', loc).split())
        if bare in ('united states', 'us', 'usa', 'united states of america') or 'remote-friendly' in loc:
            hits.append('Remote')
        if 'remote' in loc and 'Remote' not in hits:
            rest = loc.replace('remote', '')
            if not re.search(loc_cfg['non_us_remote'], rest) or re.search(r'\bus\b|united states|usa|u\.s\.', loc):
                hits.append('Remote')
    for rule in loc_cfg.get('company_rules') or []:
        if (re.search(rule['company'], company or '', re.I) and re.search(rule['when'], loc, re.I)
                and rule['as'] not in hits):
            hits.append(rule['as'])
    return hits


def top_tier(hits, cfg):
    """The matched locations that are first-choice (config locations.top), in match order; [] when tiers are off."""
    top = cfg['locations'].get('top') or []
    names = hits.split('/') if isinstance(hits, str) else hits
    return [h for h in names if h in top]


def top_bonus(hits, cfg):
    """(fit points, first-choice names) for a role matched to `hits`: the bonus when any match is first-choice."""
    top = top_tier(hits, cfg)
    return (int(cfg['locations'].get('top_bonus') or 0) if top else 0), top


def metro(cfg, name):
    return next((m for m in cfg['locations']['metros'] if m['name'] == name), None)


def preference_order(hits, cfg):
    """Where the user would actually work, best first: home metro, then remote, then the rest in config order."""
    home = cfg['locations'].get('home')
    order = [home, 'Remote'] + [m['name'] for m in cfg['locations']['metros']]
    return sorted(dict.fromkeys(hits), key=lambda h: order.index(h) if h in order else len(order))


def office_answer(label, role_locs, prof, cfg):
    """Answer for an office, hybrid or relocation question, or None (ask the user).

    Per-metro wording comes from profile location_answers.<metro>.office (willing to work there?) and
    .not_local (the tail after "No, I live in <home>." when asked whether you live there);
    the home metro and remote have generic defaults built from the profile's home city.
    """
    lab = label.lower()
    home = cfg['locations'].get('home')
    city = prof.get('home.city')
    answers = prof.get('location_answers', {}) or {}
    first = preference_order(role_locs.split('/') if isinstance(role_locs, str) else role_locs, cfg)
    mentioned = [m['name'] for m in cfg['locations']['metros'] if re.search(m['pattern'], lab)]
    target = mentioned[0] if mentioned else (first[0] if first else None)

    def say(name, kind):
        custom = (answers.get(name) or {}).get(kind)
        if custom:
            return custom
        if name == home and city:
            return f'I live in {city} and can work from the {city} office.' if kind == 'office' else f'I live in {city}.'
        m = metro(cfg, name)
        if m and m.get('policy') == 'hybrid_ok' and m.get('max_office_days'):
            return (f"Yes, I can work from the {name} office up to {m['max_office_days']} days a week (hybrid)." if kind == 'office'
                    else f"I can work from the {name} office up to {m['max_office_days']} days a week.")
        return None

    if home in mentioned or target == home:
        return say(home, 'office')
    if re.search(r'do you (currently )?(live|reside) in', lab) and city:
        tail = say(target, 'not_local') if target and target != 'Remote' else None
        return f'No, I live in {city}. {tail}' if tail else f'I live in {home_display(prof)}.'
    if target and target != 'Remote':
        ans = say(target, 'office')
        if ans:
            return ans
    return (answers.get('Remote') or {}).get('office') or 'Yes'


def relocation_assistance(role_locs, prof, cfg):
    """'Do you require relocation assistance?': No when the user would work from home or remotely (nothing to move
    for); else profile preferences.relocation_assistance; else None (ask)."""
    first = preference_order(role_locs.split('/') if isinstance(role_locs, str) else role_locs, cfg)
    if first and first[0] in (cfg['locations'].get('home'), 'Remote'):
        return 'No'
    v = prof.get('preferences.relocation_assistance')
    return str(v) if v not in (None, '') else None


# ---- US or not, from the posting's location text (the run review page shows only US location drops) ----

US_STATES = {
    'al': 'alabama', 'ak': 'alaska', 'az': 'arizona', 'ar': 'arkansas', 'ca': 'california', 'co': 'colorado',
    'ct': 'connecticut', 'de': 'delaware', 'dc': 'district of columbia', 'fl': 'florida', 'ga': 'georgia',
    'hi': 'hawaii', 'id': 'idaho', 'il': 'illinois', 'in': 'indiana', 'ia': 'iowa', 'ks': 'kansas', 'ky': 'kentucky',
    'la': 'louisiana', 'me': 'maine', 'md': 'maryland', 'ma': 'massachusetts', 'mi': 'michigan', 'mn': 'minnesota',
    'ms': 'mississippi', 'mo': 'missouri', 'mt': 'montana', 'ne': 'nebraska', 'nv': 'nevada', 'nh': 'new hampshire',
    'nj': 'new jersey', 'nm': 'new mexico', 'ny': 'new york', 'nc': 'north carolina', 'nd': 'north dakota',
    'oh': 'ohio', 'ok': 'oklahoma', 'or': 'oregon', 'pa': 'pennsylvania', 'ri': 'rhode island',
    'sc': 'south carolina', 'sd': 'south dakota', 'tn': 'tennessee', 'tx': 'texas', 'ut': 'utah', 'vt': 'vermont',
    'va': 'virginia', 'wa': 'washington', 'wv': 'west virginia', 'wi': 'wisconsin', 'wy': 'wyoming',
}
US_WORDS = re.compile(r'\b(u\.s\.a?\.?|usa|united states( of america)?)\b|(^|[\s,(;-])us($|[\s,)>;-])', re.I)
# Countries, provinces and cities that say "not the US". "Georgia" and "Washington" are left out (US states too).
NON_US = re.compile(r'\b(canada|british columbia|ontario(?!, ?ca\b)|alberta|quebec|nova scotia|toronto|vancouver|montreal|'
                    r'united kingdom|\buk\b|england|scotland|wales|ireland|london|dublin|edinburgh|'
                    r'spain|barcelona|madrid|france|paris|germany|berlin|munich|netherlands|amsterdam|sweden|stockholm|'
                    r'finland|helsinki|denmark|copenhagen|norway|oslo|poland|warsaw|portugal|lisbon|italy|milan|'
                    r'switzerland|zurich|europe|emea|apac|latam|'
                    r'china|shanghai|beijing|shenzhen|hong kong|taiwan|taipei|japan|tokyo|korea|seoul|singapore|'
                    r'india|bangalore|bengaluru|hyderabad|australia|sydney|melbourne|new zealand|'
                    r'mexico(?! city, ny)|brazil|s[aã]o paulo|argentina|buenos aires|colombia|bogot[aá]|chile|'
                    r'israel|tel aviv|dubai|uae|philippines|manila|vietnam|indonesia|jakarta)\b', re.I)
STATE_RE = re.compile(r',\s*(' + '|'.join(US_STATES) + r')\b\.?(\s|$|,|\)|/)', re.I)
STATE_NAME_RE = re.compile(r'\b(' + '|'.join(n for n in US_STATES.values() if n not in ('georgia', 'washington')) + r')\b', re.I)


def _part_country(part):
    p = part.strip()
    if not p:
        return None
    if NON_US.search(p):
        return 'intl'  # "Vancouver, British Columbia" before ", BC" could read as anything else
    if US_WORDS.search(p) or STATE_RE.search(p + ' ') or STATE_NAME_RE.search(p):
        return 'us'
    if re.search(r',\s*(georgia|washington)\b', p, re.I):
        return 'us'  # "Atlanta, Georgia" / "Seattle, Washington": a state after a comma
    return None


def country(location):
    """'us' when any listed location is in the US, 'intl' when every one that says is outside it, '' when the text
    doesn't say (e.g. "Greater Houston", "Hybrid - Denver", "Helsinki" passes as intl). Parts split on / ; and |."""
    parts = [_part_country(x) for x in re.split(r'\s/\s|;|\|', location or '')]
    if 'us' in parts:
        return 'us'
    return 'intl' if 'intl' in parts else ''


# ---- the countries a posting is in (US / CA), for the work-eligibility gates ----

PROVINCES = {'ON': 'Ontario', 'BC': 'British Columbia', 'QC': 'Quebec', 'AB': 'Alberta', 'MB': 'Manitoba',
             'SK': 'Saskatchewan', 'NS': 'Nova Scotia', 'NB': 'New Brunswick', 'NL': 'Newfoundland and Labrador',
             'PE': 'Prince Edward Island', 'YT': 'Yukon', 'NT': 'Northwest Territories', 'NU': 'Nunavut'}
# Abbreviations only count right after a comma and in capitals ("Toronto, ON"), never as the bare word "on"
PROVINCE_ABBR_RE = re.compile(r',\s*(' + '|'.join(PROVINCES) + r')\b(?![-a-z])')
PROVINCE_NAME_RE = re.compile(r'\b(ontario|british columbia|qu[eé]bec|alberta|manitoba|saskatchewan|nova scotia|new brunswick|'
                              r'newfoundland|prince edward island|yukon|northwest territories|nunavut)\b', re.I)
CA_CITY_RE = re.compile(r'\b(canada|canadian|toronto|gta|mississauga|vancouver|burnaby|montr[eé]al|ottawa|calgary|edmonton|'
                        r'waterloo|kitchener|winnipeg|halifax|saskatoon|regina)\b', re.I)


def _part_codes(part):
    p = part.strip()
    if not p:
        return set()
    if re.search(r'north america', p, re.I):
        return {'US', 'CA'}
    if re.search(r'\bcanada\b', p, re.I) or PROVINCE_ABBR_RE.search(p) or PROVINCE_NAME_RE.search(p):
        return {'CA'}
    if (US_WORDS.search(p) or STATE_RE.search(p + ' ') or STATE_NAME_RE.search(p)
            or re.search(r',\s*(georgia|washington)\b', p, re.I)):
        return {'US'}
    if CA_CITY_RE.search(p):
        return {'CA'}
    return set()


def countries_in(location):
    """{'US'}, {'CA'}, both, or an empty set when the location text doesn't say. Parts split on / ; and |;
    "Toronto, ON" and "Vancouver, British Columbia" are Canada, "Vancouver, WA" is the US, "North America" is both."""
    out = set()
    for part in re.split(r'\s/\s|;|\|', location or ''):
        out |= _part_codes(part)
    return out
