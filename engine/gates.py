"""Hard gates that run before scoring: work eligibility and language.

Adapted from ai-job-search's evaluation rubric (04-job-evaluation.md, MIT, (c) Mads Lorentzen),
rewritten as deterministic rules over the posting text. Each gate returns a verdict and the
posting line it rests on, so a failure is always reported with its quote, never dropped silently:

  FAIL        the posting rules the user out (score.py gives the role tier 'gate', unscored)
  FLAG        a possible mismatch the user should judge (noted in flags, scored normally)
  UNVERIFIED  the posting is silent on something the user's status depends on
  PASS        nothing in the posting conflicts with the profile

"Silence is not permission": a posting that says nothing about sponsorship or citizenship is
not proof that a user who needs sponsorship can apply. For a user who needs neither, silence is fine.

Profile keys read (profile.yaml):
  work_authorization.citizenship        e.g. "United States of America"
  work_authorization.needs_sponsorship  "Yes" / "No"
  work_authorization.permanent_resident optional "Yes" for a green-card holder
  work_authorization.clearance          optional, e.g. "Secret (active)"; missing means none
  work_authorization.authorized_canada / needs_sponsorship_canada   optional "Yes" / "No"; once either is set, a
                                        posting in Canada (from its location text) is checked against these instead of
                                        the U.S. fields, and the U.S.-only citizenship and clearance gates skip it
  work_authorization.permanent_resident_canada   optional "Yes" for a Canadian PR ("citizens or permanent residents only")
  languages                             optional list of {language, level}; level one of
                                        basic, conversational, professional, fluent, native
A profile that lists no languages is read as English only (native), so a posting that requires fluent
Spanish FAILs for it; list every language you speak. A language that is optional ("a plus", "nice to have")
or said not to be needed is not a requirement.
"""
import re
from .locations import countries_in

PASS, FLAG, UNVERIFIED, FAIL = 'PASS', 'FLAG', 'UNVERIFIED', 'FAIL'
ORDER = {PASS: 0, UNVERIFIED: 1, FLAG: 2, FAIL: 3}

LANGUAGES = ('english', 'spanish', 'mandarin', 'chinese', 'cantonese', 'french', 'german', 'japanese', 'korean',
             'portuguese', 'italian', 'dutch', 'russian', 'arabic', 'hindi', 'hebrew', 'turkish', 'polish', 'swedish',
             'norwegian', 'danish', 'finnish', 'greek', 'vietnamese', 'thai', 'indonesian', 'tagalog', 'ukrainian',
             'czech', 'hungarian', 'romanian', 'bengali', 'urdu', 'farsi', 'persian', 'malay', 'tamil', 'punjabi')
LEVELS = {'basic': 1, 'elementary': 1, 'conversational': 2, 'intermediate': 2, 'working': 3, 'professional': 3,
          'business': 3, 'business-level': 3, 'advanced': 4, 'fluent': 4, 'fluency': 4, 'proficient': 3,
          'proficiency': 3, 'bilingual': 4, 'native': 5, 'mother tongue': 5,
          'a1': 1, 'a2': 1, 'b1': 2, 'b2': 3, 'c1': 4, 'c2': 5}
_LANG = '|'.join(LANGUAGES)
_LVL = r'native|fluent|fluency|bilingual|business[- ]level|professional|working|conversational|advanced|proficien(?:t|cy)|c1|c2|b1|b2'
LANG_RES = [
    # "fluent Spanish", "fluent in Spanish", "native-level Japanese", "bilingual in English and Spanish"
    re.compile(rf'\b(?P<lvl>{_LVL})(?:[- ]level)?(?: in| speaker of)? (?P<lang>{_LANG})\b', re.I),
    # "Spanish fluency", "Mandarin (C1)", "Japanese: native", "English proficiency required"
    re.compile(rf'\b(?P<lang>{_LANG})\b(?: language)?[ :(]{{1,3}}(?P<lvl>{_LVL})\b', re.I),
    # "must speak Korean", "ability to communicate in Portuguese"
    re.compile(rf'\b(?:speak|read and write|communicate in|written and spoken)\b (?P<lang>{_LANG})\b', re.I),
]
OPTIONAL_RE = re.compile(r'\b(prefer(red|ably)?|a plus|plus\b|bonus|nice[- ]to[- ]have|desir(ed|able)|ideally|helpful|advantage|benefit|bonus points)', re.I)
# "Bilingual" alone, or a language named as a product/market ("Spanish-language content", "English-speaking markets")
NOT_A_REQUIREMENT_RE = re.compile(r'(language|speaking) (content|markets?|audiences?|users|customers|countries)|'
                                  r'proficiency (test|testing|exam|score)|(test|exam)s? of', re.I)

CITIZEN_RE = re.compile(r'(must|required to|need to) be an? (u\.?s\.?|united states|us) citizen|'
                        r'(u\.?s\.?|united states|us) citizenship (is |will be )?(required|mandatory)|'
                        r'(only|restricted to|limited to) (u\.?s\.?|united states|us) citizens|'
                        r'(u\.?s\.?|united states|us) citizens? (or|and) (lawful )?permanent residents? only', re.I)
CLEARANCE_REQ_RE = re.compile(r'(active|current|existing|hold an?|possess an?|have an?)\s+(\w+\s){0,3}(security )?clearance|'
                              r'(secret|top secret|ts/sci|ts|security|dod|government) clearance (is )?(required|needed|mandatory)|'
                              r'clearance (is )?required', re.I)
# A clearance named only to say it isn't needed: "No Active Clearance Required", "does not require an active
# clearance" (just before the match) or "Active clearance is not required" (just after it)
CLEARANCE_NEG_BEFORE_RE = re.compile(r'(?:\bno|\bnot|\bnever|n[\'\u2019]t)(?:\s+(?:require[sd]?|need(?:ed|s)?|to|an?|any|hold|'
                                     r'have|possess|currently|necessarily))*\s*$', re.I)
CLEARANCE_NEG_AFTER_RE = re.compile(r'^[\s:\-\u2013]*(?:(?:is|are)\s*)?(?:not|n[\'\u2019]t)\s+(?:required|needed|necessary|mandatory)|'
                                    # careers-page boilerplate: "Any active clearance requirement will be listed in the role description"
                                    r'^\s*requirements?\s+(?:will|would|is|are)\s+(?:be\s+)?(?:listed|noted|stated|specified|indicated)', re.I)
CLEARANCE_OBTAIN_RE = re.compile(r'(ability|able|eligib\w*) to (obtain|acquire|get|maintain)\s+(\w+\s){0,3}clearance|'
                                 r'(obtain|acquire)\s+(and maintain )?an?\s+(\w+\s){0,3}clearance', re.I)
NO_SPONSOR_RE = re.compile(r'(not|unable to|cannot|can ?not|won\'t|will not|does not|do not|no longer)\s+(be able to\s+)?'
                           r'(offer|provide|support|sponsor)\w*\s+(\w+\s){0,4}(visa|sponsorship|immigration|h-?1b|employment authorization|work authorization)|'
                           r'no (visa |h-?1b )?sponsorship|without (the need for )?(current or future )?(visa )?sponsorship|'
                           r'sponsorship (is )?not (available|offered|provided)|'
                           r'(not|never) (require|need)\w*,? (now or in the future,? )?(\w+ ){0,2}sponsorship', re.I)
SPONSOR_OK_RE = re.compile(r'(we|will|can|able to|happy to|open to) (do )?sponsor (\w+ ){0,2}(visas?|immigration|h-?1b|work authorization)|'
                           r'(visa|immigration|h-?1b) (support|sponsorship) (is )?(available|offered|provided)|'
                           r'(we )?(offer|provide) (visa|immigration|h-?1b) (support|sponsorship)', re.I)

# Sponsorship named in a work-authorization sense, worded in a way neither rule above reads
SPONSOR_MENTION_RE = re.compile(r'(visa|h-?1b|immigration|employment authorization|work authorization)[^.]{0,60}sponsor|'
                                r'sponsor\w*[^.]{0,60}(visa|h-?1b|immigration|employment authorization|work authorization)', re.I)


def sentence(text, start, end, reach=90):
    """The posting text around a match for quoting: its sentence or line, at most `reach` characters
    each side (scraped postings often run every bullet together with no punctuation)."""
    lo, hi = max(0, start - reach), min(len(text), end + reach)
    a = max(text.rfind('\n', lo, start), text.rfind('. ', lo, start))
    a = a + 1 if a != -1 else lo
    stops = [i for i in (text.find('\n', end, hi), text.find('. ', end, hi)) if i != -1]
    b = min(stops) + 1 if stops else hi
    s = re.sub(r'\s+', ' ', text[a:b]).strip(' .•-*')
    return ('...' if a == lo and lo else '') + s + ('...' if b == hi and hi < len(text) else '')


def optional(text, start, end):
    """Whether the words just before or after a match make it a nice-to-have ("Bonus points: Mandarin")."""
    return bool(OPTIONAL_RE.search(text[max(0, start - 40):min(len(text), end + 30)]))


def clearance_negated(text, m):
    """Whether a clearance match only says no clearance is needed."""
    return bool(CLEARANCE_NEG_BEFORE_RE.search(text[max(0, m.start() - 40):m.start()])
                or CLEARANCE_NEG_AFTER_RE.search(text[m.end():m.end() + 60]))


def _yes(v):
    return str(v or '').strip().lower().startswith(('y', 'true'))


def _is_us_citizen(prof):
    c = str(prof.get('work_authorization.citizenship') or '').lower()
    return bool(re.search(r'united states|^u\.?s\.?a?\.?$|american', c))


CA_CITIZEN_RE = re.compile(r'(must|required to|need to) be an? canadian citizen|canadian citizenship (is |will be )?(required|mandatory)|'
                           r'(only|restricted to|limited to) canadian citizens|'
                           r'canadian citizens? (or|and) (lawful )?permanent residents? only', re.I)


def canada_in_play(prof):
    """Whether the profile answers anything about working in Canada (the Canada-aware gates run only then)."""
    return any(prof.get(f'work_authorization.{k}') not in (None, '') for k in ('authorized_canada', 'needs_sponsorship_canada'))


def eligibility_canada(jd, prof):
    """Work-eligibility gate for a posting in Canada: Canadian citizenship wording and sponsorship, from the
    profile's Canada fields. A silent profile is UNVERIFIED, never a pass."""
    out = []
    authorized, sponsor = prof.get('work_authorization.authorized_canada'), prof.get('work_authorization.needs_sponsorship_canada')
    citizen = 'canad' in str(prof.get('work_authorization.citizenship') or '').lower()
    m = CA_CITIZEN_RE.search(jd)
    if m:
        pr_ok = 'permanent' in jd[m.start():m.end() + 40].lower() and _yes(prof.get('work_authorization.permanent_resident_canada'))
        out.append((PASS if citizen or pr_ok else FAIL, 'Canadian citizenship required', sentence(jd, m.start(), m.end())))
    if sponsor in (None, ''):
        # no explicit answer: an authorization of "No" means sponsorship is needed; nothing at all is unknown
        needs = authorized is not None and not _yes(authorized)
        if not needs:
            if authorized is None:
                out.append((UNVERIFIED, 'profile has no Canada work-authorization answer', 'set work_authorization.authorized_canada'))
            return out
    else:
        needs = _yes(sponsor)
    if needs:
        no, ok = NO_SPONSOR_RE.search(jd), SPONSOR_OK_RE.search(jd)
        if no:
            out.append((FAIL, 'no visa sponsorship', sentence(jd, no.start(), no.end())))
        elif ok:
            out.append((PASS, 'sponsorship offered', sentence(jd, ok.start(), ok.end())))
        elif SPONSOR_MENTION_RE.search(jd):
            x = SPONSOR_MENTION_RE.search(jd)
            out.append((FLAG, 'sponsorship terms unclear; read them', sentence(jd, x.start(), x.end())))
        else:
            out.append((UNVERIFIED, 'posting silent on sponsorship', 'check the employer\'s careers page before drafting'))
    return out


def eligibility(jd, prof, location=None):
    """Work-eligibility gate: citizenship, clearance and sponsorship. Without a location, or when the profile has no
    Canada answers, every posting is read as a U.S. one. With both, a posting only in Canada is checked against the
    Canada fields (the U.S.-only citizenship and clearance gates skip it); one in both countries takes whichever
    country's result is better, since the user can pick where to work."""
    if location and canada_in_play(prof):
        where = countries_in(location)
        if where == {'CA'}:
            return eligibility_canada(jd, prof)
        if where == {'US', 'CA'}:
            us, ca = _eligibility_us(jd, prof), eligibility_canada(jd, prof)
            return ca if ORDER[verdict(ca)] < ORDER[verdict(us)] else us
    return _eligibility_us(jd, prof)


def _eligibility_us(jd, prof):
    """Work-eligibility gate for U.S. postings: citizenship, clearance and sponsorship."""
    out = []
    citizen = _is_us_citizen(prof)
    needs_sponsor = _yes(prof.get('work_authorization.needs_sponsorship'))
    clearance = str(prof.get('work_authorization.clearance') or '').strip()
    m = CITIZEN_RE.search(jd)
    if m:
        q = sentence(jd, m.start(), m.end())
        pr_ok = 'permanent' in m.group(0).lower() and _yes(prof.get('work_authorization.permanent_resident'))
        out.append((PASS if citizen or pr_ok else FAIL, 'citizenship required', q))
    m = next((x for x in CLEARANCE_REQ_RE.finditer(jd) if not clearance_negated(jd, x)), None)
    obtain = (re.search(r'(ability|able|eligib\w*) to (obtain|acquire|get)', jd[m.start():m.end() + 60], re.I) if m
              else CLEARANCE_OBTAIN_RE.search(jd))
    if m and not obtain and not optional(jd, m.start(), m.end()):
        out.append((FLAG if clearance else FAIL, 'security clearance required', sentence(jd, m.start(), m.end())))
    elif m or obtain:
        at = m or obtain
        # an "ability to obtain" clearance normally needs U.S. citizenship; a citizen should still judge it
        out.append((FLAG if citizen or clearance else FAIL, 'must hold or be able to obtain a security clearance',
                    sentence(jd, at.start(), at.end())))
    no, ok = NO_SPONSOR_RE.search(jd), SPONSOR_OK_RE.search(jd)
    if needs_sponsor:
        if no:
            out.append((FAIL, 'no visa sponsorship', sentence(jd, no.start(), no.end())))
        elif ok:
            out.append((PASS, 'sponsorship offered', sentence(jd, ok.start(), ok.end())))
        elif SPONSOR_MENTION_RE.search(jd):
            x = SPONSOR_MENTION_RE.search(jd)
            out.append((FLAG, 'sponsorship terms unclear; read them', sentence(jd, x.start(), x.end())))
        else:
            out.append((UNVERIFIED, 'posting silent on sponsorship', 'check the employer\'s careers page before drafting'))
    return out


DEFAULT_LANGUAGES = {'english': LEVELS['native']}
LANG_WORD_RE = re.compile(rf'\b(?:{_LANG})\b', re.I)
# Text between two languages that keeps them in one requirement: short, inside one sentence or bullet
LINK_RE = re.compile(r'^[^.;:\n]{1,60}$')
# A language named only to say it isn't needed: "Spanish is not required", "no Portuguese needed"
LANG_NEG_RE = re.compile(r'^\W{0,3}(?:(?:is|are)\s+)?(?:not|n[\'\u2019]t)\s+(?:required|needed|necessary|mandatory)', re.I)
LANG_NEG_BEFORE_RE = re.compile(r'\b(?:no|not|without)\s+(?:\w+\s+){0,2}$', re.I)


def _declared(prof):
    """{language: level} from profile `languages`; a profile that lists none is taken as English only (native)."""
    langs = {}
    for item in prof.get('languages') or []:
        if isinstance(item, dict) and item.get('language'):
            lvl = str(item.get('level') or '').lower()
            langs[item['language'].strip().lower()] = LEVELS.get(lvl, 3)
        elif isinstance(item, str):
            langs[item.strip().lower()] = 3
    return langs or dict(DEFAULT_LANGUAGES)


def _chain(jd, m, forward):
    """The languages one requirement names, as groups that must all be met, each met by any one of its
    languages: "Fluency in English and at least one other local language (Spanish or Portuguese)" ->
    [[english], [spanish, portuguese]]. Starts at the match's language and follows languages that sit
    close together in the same sentence, forward ("fluent Spanish or Portuguese") or backward
    ("Spanish or Portuguese fluency"). Returns [[(lang, start, end)]]."""
    found = []
    for x in LANG_WORD_RE.finditer(jd):
        f = (x.group(0).lower(), x.start(), x.end())
        if f[0] == 'chinese' and found and found[-1][0] in ('mandarin', 'cantonese') and not jd[found[-1][2]:f[1]].strip():
            found[-1] = (found[-1][0], found[-1][1], f[2])  # "Mandarin Chinese" names one language
            continue
        found.append(f)
    i = next(k for k, f in enumerate(found) if f[1] <= m.start('lang') < f[2])
    seq, links = [found[i]], []
    step = 1 if forward else -1
    j = i + step
    while 0 <= j < len(found):
        a, b = (seq[-1], found[j]) if forward else (found[j], seq[0])
        link = jd[a[2]:b[1]]
        if not LINK_RE.match(link):
            break
        if forward:
            seq.append(found[j])
            links.append(link)
        else:
            seq.insert(0, found[j])
            links.insert(0, link)
        j += step
    # each link is 'or', 'and', or a bare comma that takes the kind of the next worded link ("A, B, or C")
    kinds = ['or' if re.search(r'\bor\b|/', l, re.I) else 'and' if re.search(r'\band\b|&', l, re.I) else '' for l in links]
    for k in range(len(kinds) - 1, -1, -1):
        kinds[k] = kinds[k] or (kinds[k + 1] if k + 1 < len(kinds) else 'and')
    groups = [[seq[0]]]
    for item, kind in zip(seq[1:], kinds):
        if kind == 'and':
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


# Section headings that make the bullets under them optional, and ones that make them required again
OPTIONAL_SECTION_RE = re.compile(r'nice[- ]to[- ]haves?|would be (nice|great)|bonus( points)?|preferred (qualifications|skills|experience)|'
                                 r'if you (also )?have|extra credit|pluses|good to have', re.I)
REQUIRED_SECTION_RE = re.compile(r'(minimum|basic|required) (qualifications|skills|experience)|requirements|what you(\'ll| will)? need|'
                                 r'must[- ]haves?|who you are|what we(\'re)? look(ing)? for|about you|you (will )?(have|bring)', re.I)


def optional_section(text, start, reach=400):
    """Whether the match sits under a nice-to-have heading ("WOULD BE NICE IF YOU ALSO HAVE - ... - Mandarin"):
    the last optional heading before it comes after the last required one."""
    before = text[max(0, start - reach):start]
    opt = [m.end() for m in OPTIONAL_SECTION_RE.finditer(before)]
    req = [m.end() for m in REQUIRED_SECTION_RE.finditer(before)]
    return bool(opt) and (not req or opt[-1] > req[-1])


def _not_needed(jd, start, end, match_end):
    """Whether the words around one named language make it optional or say it isn't needed."""
    return (optional(jd, start, max(end, match_end)) or bool(OPTIONAL_RE.search(jd[end:max(end, match_end) + 45]))
            or optional_section(jd, start) or bool(LANG_NEG_RE.search(jd[end:end + 40]))
            or bool(LANG_NEG_BEFORE_RE.search(jd[max(0, start - 25):start])))


# Quebec postings: French asked for in wording the language patterns above don't read. The explicit forms fail like
# any required language the profile lacks; a bare "bilingue" (the posting is in French) is a flag to read.
FRENCH_REQ_RES = [
    re.compile(r'bilingual\s*[(\[]?\s*(?:french\s*(?:/|&|and|-)\s*english|english\s*(?:/|&|and|-)\s*french)', re.I),
    re.compile(r'bilingual\s+(?:in\s+)?(?:both\s+)?(?:official languages|french)', re.I),
    re.compile(r'fran[çc]ais\s+(?:requis|exig[ée]|obligatoire|indispensable)', re.I),
    re.compile(r'ma[îi]trise\s+(?:du|de la|de)\s+fran[çc]ais', re.I),
    re.compile(r'french\s+(?:is\s+)?(?:required|mandatory|a must|essential)', re.I),
]
BILINGUE_RE = re.compile(r'\bbilingue\b', re.I)


def french(jd, prof):
    """Quebec French gate: a posting that asks for French (or is bilingual by its own wording) vs the profile's languages."""
    if 'french' in _declared(prof):
        return []
    out = []
    for rx in FRENCH_REQ_RES:
        for m in rx.finditer(jd):
            if not _not_needed(jd, m.start(), m.end(), m.end()) and not out:
                out.append((FAIL, 'French required, not in profile', sentence(jd, m.start(), m.end())))
    if not out:
        m = BILINGUE_RE.search(jd)
        if m and not _not_needed(jd, m.start(), m.end(), m.end()):
            out.append((FLAG, 'bilingual (likely French) wanted, French not in profile', sentence(jd, m.start(), m.end())))
    return out


def language(jd, prof):
    """Language gate: each language the posting requires as a job condition vs the profile's languages.
    A requirement met by any one of several languages ("Spanish or Portuguese") fails only when the
    profile has none of them."""
    declared, seen, out = _declared(prof), set(), []
    for n, rx in enumerate(LANG_RES):
        for m in rx.finditer(jd):
            q = sentence(jd, m.start(), m.end())
            near = jd[max(0, m.start() - 40):m.end() + 40]
            if NOT_A_REQUIREMENT_RE.search(near):
                continue
            lvl = (m.groupdict().get('lvl') or '').lower().replace(' ', '-')
            need = LEVELS.get(lvl.replace('business-level', 'business'), LEVELS.get(lvl, 0))
            for group in _chain(jd, m, forward=n != 1):
                langs = []
                for lang, a, b in group:
                    lang = 'mandarin' if lang == 'chinese' and 'mandarin' in declared else lang
                    if lang not in langs and not _not_needed(jd, a, b, m.end()):
                        langs.append(lang)
                key = frozenset(langs)
                if not langs or key in seen:
                    continue
                seen.add(key)
                name = ' or '.join(l.title() for l in langs)
                have = [l for l in langs if l in declared]
                if not have:
                    out.append((FAIL, f"{name} required, {'neither' if len(langs) == 2 else 'none' if len(langs) > 2 else 'not'} in profile", q))
                elif need > max(declared[l] for l in have):
                    out.append((FLAG, f'{name} bar may exceed declared level', q))
    return out


def check(jd, prof, location=None):
    """All gate results for one posting: [(verdict, label, quote)], worst first. location: the posting's location
    text; with it, and a profile that answers for Canada, a Canadian posting is checked against the Canada fields
    and the French gate runs. Without it everything is read as before."""
    res = eligibility(jd, prof, location) + language(jd, prof)
    if location and (canada_in_play(prof) or 'CA' in countries_in(location)):
        res += [r for r in french(jd, prof) if r not in res]
    return sorted(res, key=lambda r: -ORDER[r[0]])


def verdict(results):
    return max((r[0] for r in results), key=ORDER.get, default=PASS)


def summary(results, levels=(FAIL, FLAG, UNVERIFIED)):
    """One flags-column string: 'gate FAIL: security clearance required ("...")'."""
    return '; '.join(f'gate {v}: {label} ("{q}")' for v, label, q in results if v in levels)
