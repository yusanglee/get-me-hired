"""Role-family packs: the title filter and triage scoring rules for one kind of job.

A pack replaces the PM-only regexes in the original pipeline's discover.py and score.py.
Base packs ship in packs/ (product-management.json, chief-of-staff.json). They hold
role-family facts: which titles belong, seniority words, the requirement vocabulary,
and two catalogs of domain signals. /setup copies a base pack into the user's
workspace as pack.json and `draft()` picks, from the catalogs, the strengths the
user's resume shows evidence for and the gaps it doesn't. The user approves the
draft; only then is pack.json marked approved.

Workspace pack.json (base packs have *_catalog instead of strengths/gaps):

  {
    "name": "product-management", "label": "Product Management", "approved": false,
    "titles": {
      "include": "<regex>",              # a title must match this
      "exclude": ["associate product manager", ...],   # whole-word phrases, any match drops it
      "other_family": "<regex>",         # look-alike titles from other families (design, marketing ...)
      "family_override": "<regex>",      # ... unless this also matches ("product manager")
      "senior": "<regex>",               # senior enough to keep when no pay range is posted
      "no_range": "include_if_level_fits",   # optional; no posted range: include_if_level_fits | include | exclude.
                                         # Wins over config salary.no_range_policy (same values, same default)
      "board_queries": ["senior product manager", ...],  # what to type into job-board searches
      "targets": ["Chief of Staff", ...]   # the user's own title list (gmh setup titles), shown back to them
    },
    "level": {
      "title": [{"pattern": "staff|principal", "points": 6}, ...],   # first match wins
      "pay": [{"min_top": 300000, "points": 6}, ...],   # used when the title has no level word
      "down_level_title": "<regex>",     # titles that are a step down ("product manager ii")
      "down_level_below": 260000         # no level word and a posted top under this: possible down-level
    },
    "requirements": {"alternatives": "<regex>"},   # optional; see gap_hit
    "triage": {"manager_of_managers": "<regex>"},  # optional; asks to manage managers (engine.triage.MANAGERS_RE if absent)
    "sources": {"builtin_path": "/jobs/remote/<category>",   # optional; Built In category path(s)
                "remote100k_category": "<category>"},        # optional; remote100k category/categories
    "strengths": [{"pattern": "marketplace", "weight": 4}, ...],
    "strength_cap": 45,
    "gaps": [{"pattern": "\\bb2b\\b", "label": "B2B/enterprise", "weight": 10}, ...],
    "title_gaps": [{"pattern": "\\bads?\\b", "label": "ads products", "weight": 12}],
    "terms": ["a/b testing", "sql", ...],         # ATS vocabulary for the coverage share
    "built": "new", "base": "pack-base.json"      # only on packs built in setup (see below)
  }
Catalog entries may carry a plain-words "label" (strengths too) and a "note"; draft() drops notes.

A user whose role family has no base pack builds one in /setup instead (`new_pack`, then
`check_catalog`): titles and generic level rules from their own title list, then strength and gap
catalogs and ATS terms that Claude proposes from a sample of real postings and the resume. The
engine checks each proposed entry against the sample before it is written. The result is kept in
the workspace as pack-base.json (the catalogs) and pack.json (drafted from it), never in packs/.

Scoring (same formula as the original score.py):
  fit = 35 + min(strength points, strength_cap) - gap points + level + (ats - 50) // 5, clamped 0..100
where ats is the share of the posting's terms that appear in the user's resume text.
"""
import copy, json, os, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK_DIR = os.path.join(REPO, 'packs')

# Generic posting structure; a pack can override any of these under "requirements".
REQ_DEFAULTS = {
    'head': r"(requirements|qualifications|what you'll bring|what you bring|what we're looking for|about you|you have|you might be a fit|minimum)",
    'end': r"(benefits|perks|what we offer|compensation|salary|pay range|base pay|equal opportunity|about us|our values|\$\d)",
    'preferred_head': r"(preferred qualifications|preferred skills|nice[- ]to[- ]haves?|bonus points|gold stars|ideally you|it'?s a plus|pluses|preferred:)",
    'plus_line': r'[^.\n]*\b(is a plus|a plus|nice to have|preferred|bonus|ideally)\b[^.\n]*',
    'alternatives': None,
}


NO_RANGE_POLICIES = ('include_if_level_fits', 'include', 'exclude')
NO_RANGE_DEFAULT = 'include_if_level_fits'


class PackError(ValueError):
    pass


def base_packs():
    return sorted(f[:-5] for f in os.listdir(PACK_DIR) if f.endswith('.json') and not f.startswith('_'))


def load(path_or_name):
    """A pack from a file path, or a base pack by name."""
    path = path_or_name if os.path.sep in str(path_or_name) or str(path_or_name).endswith('.json') \
        else os.path.join(PACK_DIR, f'{path_or_name}.json')
    if not os.path.exists(path):
        raise PackError(f'no pack at {path} (base packs: {", ".join(base_packs())})')
    return validate(json.load(open(path, encoding='utf-8')))


def validate(pack):
    errs = []

    def rx(where, pat):
        if pat in (None, ''):
            return
        try:
            re.compile(pat)
        except re.error as e:
            errs.append(f'{where}: bad regex {pat!r} ({e})')

    t = pack.get('titles') or {}
    if not t.get('include'):
        errs.append('titles.include is required')
    for k in ('include', 'other_family', 'family_override', 'senior'):
        rx(f'titles.{k}', t.get(k))
    if not isinstance(t.get('exclude', []), list):
        errs.append('titles.exclude must be a list of phrases')
    if t.get('no_range') not in (None, '') and t['no_range'] not in NO_RANGE_POLICIES:
        errs.append(f"titles.no_range must be one of {', '.join(NO_RANGE_POLICIES)}, not {t['no_range']!r}")
    rx('triage.manager_of_managers', (pack.get('triage') or {}).get('manager_of_managers'))
    rx('triage.years_re', (pack.get('triage') or {}).get('years_re'))
    for k in ('builtin_path', 'remote100k_category'):
        v = (pack.get('sources') or {}).get(k)
        if v not in (None, '') and not (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) and x for x in v))):
            errs.append(f'sources.{k} must be a string or a list of strings')
    if (pack.get('sources') or {}).get('builtin_path') and not all(
            str(x).startswith('/') for x in ([pack['sources']['builtin_path']] if isinstance(pack['sources']['builtin_path'], str)
                                              else pack['sources']['builtin_path'])):
        errs.append("sources.builtin_path must start with '/' (e.g. /jobs/remote/nursing)")
    lv = pack.get('level') or {}
    for i, x in enumerate(lv.get('title') or []):
        rx(f'level.title[{i}]', x.get('pattern'))
    rx('level.down_level_title', lv.get('down_level_title'))
    for k, v in (pack.get('requirements') or {}).items():
        rx(f'requirements.{k}', v)
    for key in ('strengths', 'strength_catalog'):
        for i, x in enumerate(pack.get(key) or []):
            rx(f'{key}[{i}]', x.get('pattern'))
            if not isinstance(x.get('weight'), int):
                errs.append(f'{key}[{i}].weight must be an integer')
    for key in ('gaps', 'gap_catalog', 'title_gaps'):
        for i, x in enumerate(pack.get(key) or []):
            rx(f'{key}[{i}]', x.get('pattern'))
            if not x.get('label') or not isinstance(x.get('weight'), int):
                errs.append(f'{key}[{i}] needs a label and an integer weight')
    if errs:
        raise PackError('pack: ' + '; '.join(errs))
    return pack


# ---- building a pack for a family no base pack covers ----

GENERIC_SENIOR = ['senior', 'sr', 'staff', 'principal', 'lead', 'director', 'head']
# Weight ranges for proposed catalog entries, the same spread as the shipped packs.
WEIGHTS = {'strengths': (1, 5), 'gaps': (4, 15), 'title_gaps': (4, 15)}
NAME_RE = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')


def words_pattern(words):
    """Plain level words ("senior", "lead") as a whole-word regex; "sr" also matches "sr."."""
    alts = [re.escape(w.strip().lower()).replace(r'\ ', r'\s+') + (r'\.?' if w.strip().lower() == 'sr' else '')
            for w in words if w and w.strip()]
    return r'\b(' + '|'.join(alts) + r')\b' if alts else ''


def new_pack(name, label, titles, senior_words=None):
    """A workspace pack for a role family no base pack covers: the user's titles become the title filter and
    the job-board searches; level rules are generic (top level words +6, senior +3, no pay rules); exclude
    and other-family rules start empty. Catalogs, strengths, gaps and terms are empty until check_catalog."""
    if not NAME_RE.fullmatch(name or ''):
        raise PackError(f'pack name {name!r}: use lowercase words joined by hyphens, like ux-research')
    if not (label or '').strip():
        raise PackError('give the pack a label, like "UX Research"')
    words = [w.strip().lower() for w in (senior_words or GENERIC_SENIOR) if w.strip()]
    top = [w for w in words if w in ('staff', 'principal', 'lead', 'director', 'head', 'group', 'vp')]
    rest = [w for w in words if w not in top]
    pack = {
        'name': name, 'label': label.strip(), 'approved': False, 'built': 'new',
        'titles': {'include': r'(?!)', 'exclude': [], 'other_family': '', 'family_override': '',
                   'senior': words_pattern(words), 'board_queries': []},
        'level': {'title': [x for x in ({'pattern': words_pattern(top), 'points': 6},
                                        {'pattern': words_pattern(rest), 'points': 3}) if x['pattern']],
                  'pay': [], 'down_level_title': '', 'down_level_below': None},
        'requirements': {'alternatives': None},
        'strengths': [], 'strength_cap': 45, 'gaps': [], 'title_gaps': [], 'terms': [],
    }
    pack, notes = set_titles(pack, titles, replace=True)
    return pack, notes


def suggest(titles):
    """[(base pack, label, the titles it keeps)], most titles first: which base pack, if any, covers the user's titles."""
    out = []
    for name in base_packs():
        pack = load(name)
        out.append((name, pack.get('label'), [t for t in titles if title_ok(pack, t)]))
    return sorted(out, key=lambda x: (-len(x[2]), x[0]))


def _hits(pattern, texts):
    rx = re.compile(pattern)
    return sum(1 for t in texts if rx.search(t))


def check_catalog(pack, proposal, sample, resume_text, allow_unseen=False):
    """Check Claude's proposed catalog entries against a sample of real postings and the resume, and build the
    pack's base form (strength_catalog, gap_catalog, title_gaps, terms, extra exclude phrases).

    proposal: {"strengths": [{"label", "pattern", "weight"}], "gaps": [same], "title_gaps": [same],
               "terms": ["..."], "exclude": ["..."]}
    sample: [{"title", "text"}] postings. A strength counts where its pattern appears anywhere in a posting;
    a gap where it appears in the required part of the requirements (packs.score's rule); a title gap in the
    title. Entries no sample posting shows are refused unless allow_unseen, or, for a strength the resume
    shows, unless the entry says "keep_unseen": true (the user chose to keep it). Keys starting with "_"
    (seed evidence) are ignored. Returns (base, report); raises
    PackError listing every problem, so nothing is written from a half-good proposal."""
    errs, report = [], {'sample': len(sample), 'strengths': [], 'gaps': [], 'title_gaps': [], 'terms': [], 'exclude': []}
    if not sample and not allow_unseen:
        raise PackError('no sample postings to check against: run pack-sample first')
    full = [s['text'].lower() for s in sample]
    reqs = [required_only(pack, requirement_text(pack, s['text']).lower()) for s in sample]
    titles = [s['title'] for s in sample]
    low_resume = resume_text.lower()
    allowed = {'strengths', 'gaps', 'title_gaps', 'terms', 'exclude'}
    for k in {k for k in proposal if not k.startswith('_')} - allowed:
        errs.append(f'unknown key {k!r} (use {", ".join(sorted(allowed))})')
    base = copy.deepcopy(pack)
    for k in ('strengths', 'gaps'):
        base.pop(k, None)
    for key, cat in (('strengths', 'strength_catalog'), ('gaps', 'gap_catalog'), ('title_gaps', 'title_gaps')):
        lo, hi = WEIGHTS[key]
        out, seen = [], set()
        for i, x in enumerate(proposal.get(key) or []):
            where = f'{key}[{i}]'
            if not isinstance(x, dict):
                errs.append(f'{where}: must be an object with label, pattern and weight')
                continue
            label, pat, w = (x.get('label') or '').strip(), x.get('pattern') or '', x.get('weight')
            if not label:
                errs.append(f'{where}: needs a plain-words label')
            if not isinstance(w, int) or isinstance(w, bool) or not lo <= w <= hi:
                errs.append(f'{where} ({label}): weight must be a whole number from {lo} to {hi}')
            try:
                re.compile(pat)
            except re.error as e:
                errs.append(f'{where} ({label}): bad pattern {pat!r} ({e})')
                continue
            if not pat.strip() or re.search(pat, ''):
                errs.append(f'{where} ({label}): pattern {pat!r} matches empty text')
                continue
            if pat != pat.lower() and not pat.startswith('(?i)') and key != 'title_gaps' and re.search(r'(?<!\\)[A-Z]', pat):
                errs.append(f'{where} ({label}): write the pattern in lowercase (postings are lowercased before matching)')
                continue
            if pat in seen:
                errs.append(f'{where} ({label}): same pattern listed twice')
                continue
            seen.add(pat)
            n = (_hits(pat, full) if key == 'strengths' else
                 sum(1 for r in reqs if gap_hit(pack, pat, r)) if key == 'gaps' else
                 sum(1 for t in titles if re.search(pat, t, re.I)))
            in_resume = bool(re.search(pat, low_resume)) if key != 'title_gaps' else None
            keep = key == 'strengths' and bool(x.get('keep_unseen'))
            if keep and not in_resume:
                errs.append(f'{where} ({label}): keep_unseen is only for strengths your resume shows')
            elif n == 0 and not allow_unseen and not keep:
                errs.append(f'{where} ({label}): no sample posting shows it ({len(sample)} checked)')
            report[key].append(dict(label=label, pattern=pat, weight=w, postings=n, in_resume=in_resume, keep_unseen=keep))
            out.append({'label': label, 'pattern': pat, 'weight': w, 'note': f'in {n} of {len(sample)} sample postings'})
        base[cat] = out
    terms = []
    for t in proposal.get('terms') or []:
        t = re.sub(r'\s+', ' ', str(t)).strip().lower()
        if not t or t in terms:
            continue
        rx = r'\b' + re.escape(t) + r'\b'
        n = _hits(rx, full)
        if n == 0 and not allow_unseen:
            errs.append(f'term {t!r}: no sample posting uses it')
        report['terms'].append(dict(term=t, postings=n, in_resume=bool(re.search(rx, low_resume))))
        terms.append(t)
    base['terms'] = terms
    ex = list(base['titles'].get('exclude') or [])
    for e in proposal.get('exclude') or []:
        e = re.sub(r'\s+', ' ', str(e)).strip().lower()
        if not e or e in ex:
            continue
        blocked = [t for t in base['titles'].get('targets') or [] if re.search(r'\b' + re.escape(e) + r'\b', t, re.I)]
        if blocked:
            errs.append(f'exclude {e!r} would block your own title {blocked[0]!r}')
        ex.append(e)
        report['exclude'].append(dict(phrase=e, titles=sum(1 for t in titles if re.search(r'\b' + re.escape(e) + r'\b', t, re.I))))
    base['titles']['exclude'] = ex
    if not base['strength_catalog']:
        errs.append('propose at least one strength')
    if errs:
        raise PackError('catalog not written:\n- ' + '\n- '.join(errs))
    return validate(base), report


def plain_label(pattern):
    """A readable name for a catalog entry that has none: the first alternative of the pattern and of each group,
    without regex syntax ("(top-tier|management) consulting" -> "top-tier consulting")."""
    text = pattern
    while True:
        new = re.sub(r'\((?:\?:)?([^()]*)\)', lambda m: m.group(1).split('|')[0], text)
        if new == text:
            break
        text = new
    text = re.sub(r'\[\^?([^\]]*)\]', lambda m: m.group(1)[:1], text.split('|')[0])  # [- ] -> '-'
    text = re.sub(r'\\[bBsSwWdD]|[\^$?*+{}\\.]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip() or pattern


def examples(pattern, texts, k=3, width=40):
    """Up to k different snippets around the pattern's matches, one per posting: shows whether it hits real
    requirements or boilerplate ("minimum education", "recruiting scams", a mission statement)."""
    rx, out = re.compile(pattern), []
    for t in texts:
        m = rx.search(t)
        if m:
            snip = ' '.join(t[max(0, m.start() - width):m.end() + width].split())
            if snip not in out:
                out.append(snip)
        if len(out) == k:
            break
    return out


def seed_proposal(base, sample, resume_text):
    """A base pack's catalogs as a pack-catalog proposal, every entry labeled and annotated ("_evidence") with
    how many sample postings show it and whether the resume does. Claude edits it (adds the user's own
    strengths, drops what no posting shows) before pack-catalog checks it; the user approves the result."""
    full = [s['text'].lower() for s in sample]
    reqs = [required_only(base, requirement_text(base, s['text']).lower()) for s in sample]
    titles = [s['title'] for s in sample]
    low = resume_text.lower()
    n = len(sample)

    def entry(x, hits, resume, texts=()):
        e = {'label': x.get('label') or plain_label(x['pattern']), 'pattern': x['pattern'], 'weight': x['weight']}
        e['_evidence'] = f'in {hits} of {n} sample postings' + ('' if resume is None else
                                                                  f"; resume: {'yes' if resume else 'no'}")
        if texts:
            e['_examples'] = examples(x['pattern'], texts)
        return e
    out = {'_note': 'Seeded from the ' + str(base.get('label') or base.get('name')) + ' base pack. Entries no sample '
                    'posting shows ("in 0 of") must be removed or confirmed before pack-catalog accepts them.',
           'strengths': [entry(x, _hits(x['pattern'], full), bool(re.search(x['pattern'], low)), full)
                         for x in base.get('strength_catalog') or base.get('strengths') or []],
           'gaps': [entry(x, sum(1 for r in reqs if gap_hit(base, x['pattern'], r)), bool(re.search(x['pattern'], low)), reqs)
                    for x in base.get('gap_catalog') or base.get('gaps') or []],
           'title_gaps': [entry(x, sum(1 for t in titles if re.search(x['pattern'], t, re.I)), None)
                          for x in base.get('title_gaps') or []],
           'terms': list(base.get('terms') or []),
           '_terms_evidence': {t: _hits(r'\b' + re.escape(t) + r'\b', full) for t in base.get('terms') or []},
           'exclude': []}
    return out


def draft(base, resume_text):
    """A workspace pack from a base pack: catalog strengths with evidence in the resume, and
    catalog gaps without any. A first guess for the user to correct, never approved here."""
    pack = copy.deepcopy(base)
    low = resume_text.lower()
    strengths = [s for s in pack.pop('strength_catalog', []) if re.search(s['pattern'], low)]
    gaps = [g for g in pack.pop('gap_catalog', []) if not re.search(g['pattern'], low)]
    pack.update(strengths=[{k: v for k, v in s.items() if k != 'note'} for s in strengths],
                gaps=[{k: v for k, v in g.items() if k != 'note'} for g in gaps],
                approved=False, drafted_from=base.get('name'))
    return validate(pack)


# ---- title filter ----

def title_pattern(title):
    """A plain title ("Strategy & Operations") as a title regex: whole words, any spacing, '&' or 'and'."""
    words = re.split(r'\s+', title.strip().lower())
    parts = [r'(and|&)' if w in ('&', 'and') else re.escape(w) for w in words if w]
    return r'\b' + r'\s+'.join(parts) + r'\b'


def _query(title):
    return re.sub(r'\s+', ' ', title.lower().replace('&', ' and ')).strip()


def set_titles(pack, titles, replace=False):
    """Add the user's target titles (plain words) to the pack: the title filter, the job-board searches and
    titles.targets. replace=True makes them the only titles searched for. A title the pack's exclude list or
    other-family rule would block is let through (the blocking exclude phrases are removed, the title is added
    to family_override). Returns (pack, notes): notes say what changed for each title."""
    pack = copy.deepcopy(pack)
    t = pack.setdefault('titles', {})
    titles = [x.strip() for x in titles if x and x.strip()]
    if not titles:
        raise PackError('give at least one title')
    have = [] if replace else list(t.get('targets') or [])
    targets = have + [x for x in titles if x.lower() not in {h.lower() for h in have}]
    pats = [title_pattern(x) for x in titles]
    if replace:
        t['include'] = '|'.join(title_pattern(x) for x in targets)
        t['board_queries'] = list(dict.fromkeys(_query(x) for x in targets))
    else:
        new = [p for x, p in zip(titles, pats) if not re.search(t.get('include') or r'(?!)', x, re.I)]
        t['include'] = '|'.join(filter(None, [t.get('include')] + new))
        q = list(t.get('board_queries') or [])
        t['board_queries'] = q + [x for x in dict.fromkeys(_query(x) for x in titles) if x not in q]
    t['targets'] = targets
    notes = []
    for x, p in zip(titles, pats):
        blocked = [e for e in t.get('exclude') or [] if re.search(r'\b' + re.escape(e) + r'\b', x, re.I)]
        if blocked:
            t['exclude'] = [e for e in t['exclude'] if e not in blocked]
            notes.append(f"{x}: removed {', '.join(repr(b) for b in blocked)} from the excluded phrases")
        if t.get('other_family') and re.search(t['other_family'], x, re.I) and not (
                t.get('family_override') and re.search(t['family_override'], x, re.I)):
            t['family_override'] = '|'.join(filter(None, [t.get('family_override'), p]))
            notes.append(f'{x}: allowed past the other-family rule')
        notes.append(f"{x}: {'matches' if title_ok(pack, x) else 'STILL BLOCKED, edit pack.json by hand'}")
    return validate(pack), notes


def _exclude_re(pack):
    ex = (pack.get('titles') or {}).get('exclude') or []
    return re.compile(r'\b(' + '|'.join(re.escape(x) for x in ex) + r')\b', re.I) if ex else None


def title_ok(pack, title):
    t = pack['titles']
    if not re.search(t['include'], title, re.I):
        return False
    ex = _exclude_re(pack)
    if ex and ex.search(title):
        return False
    if t.get('other_family') and re.search(t['other_family'], title, re.I):
        return bool(t.get('family_override') and re.search(t['family_override'], title, re.I))
    return True


def no_range_policy(pack, cfg=None):
    """What to do with a posting that has no pay range: the pack's titles.no_range, else config salary.no_range_policy,
    else 'include_if_level_fits' (keep only titles with a level word)."""
    mine = (pack.get('titles') or {}).get('no_range')
    got = mine or ((cfg or {}).get('salary') or {}).get('no_range_policy') or NO_RANGE_DEFAULT
    if got not in NO_RANGE_POLICIES:
        raise PackError(f"no_range policy must be one of {', '.join(NO_RANGE_POLICIES)}, not {got!r}")
    return got


def is_senior(pack, title):
    pat = (pack.get('titles') or {}).get('senior')
    return bool(pat and re.search(pat, title, re.I))


# ---- scoring ----

def _req(pack, key):
    return (pack.get('requirements') or {}).get(key, REQ_DEFAULTS[key])


def requirement_text(pack, jd):
    """The posting's requirements section only: from its heading to the first benefits/pay/EEO marker."""
    m = re.search(_req(pack, 'head'), jd, re.I)
    seg = jd[m.start():] if m else jd
    e = re.compile(_req(pack, 'end'), re.I).search(seg, 30)
    return seg[:e.start()] if e else seg[:2500]


def required_only(pack, req):
    """Requirement text minus the preferred / nice-to-have part, so a 'plus' never costs points."""
    m = re.compile(_req(pack, 'preferred_head'), re.I).search(req, 20)
    req = req[:m.start()] if m else req
    return re.sub(_req(pack, 'plus_line'), ' ', req, flags=re.I)


def gap_hit(pack, rx, req):
    """A gap counts unless an 'X, Y, or <something the user has>' alternative sits next to it."""
    alt = _req(pack, 'alternatives')
    for m in re.finditer(rx, req):
        window = req[max(0, m.start() - 150):m.end() + 200]
        if not (alt and re.search(alt, window, re.I)):
            return True
    return False


def term_re(pack):
    terms = pack.get('terms') or []
    return re.compile(r'\b(' + '|'.join(re.escape(t) for t in terms) + r')\b', re.I) if terms else None


def level_points(pack, title, top):
    lv, t = pack.get('level') or {}, title.lower()
    for x in lv.get('title') or []:
        if re.search(x['pattern'], t):
            return x['points']
    if top:
        for x in sorted(lv.get('pay') or [], key=lambda x: -x['min_top']):
            if top >= x['min_top']:
                return x['points']
    return 0


def score(pack, title, jd, evidence, salary_max=None, parts=False):
    """Triage score for one posting. `evidence` is the user's resume text (master resume).
    parts=True adds a 'parts' dict: the fit formula's terms, for the run review page."""
    low, ev = jd.lower(), evidence.lower()
    req = required_only(pack, requirement_text(pack, jd).lower())
    strengths = [s for s in pack.get('strengths') or [] if re.search(s['pattern'], low)]
    s_pts = sum(s['weight'] for s in strengths)
    gaps = [(g['label'], g['weight']) for g in pack.get('gaps') or []
            if gap_hit(pack, g['pattern'], req) or re.search(g['pattern'], title.lower())]
    for g in pack.get('title_gaps') or []:
        if re.search(g['pattern'], title, re.I) and not any(lab == g['label'] for lab, _ in gaps):
            gaps.append((g['label'], g['weight']))
    g_pts = sum(w for _, w in gaps)
    tre = term_re(pack)
    terms = {t.lower() for t in tre.findall(jd)} if tre else set()
    covered = {t for t in terms if t in ev or t.replace('-', ' ') in ev}
    ats = round(100 * len(covered) / len(terms)) if terms else 0
    years = [int(y) for y in re.findall(r'(\d{1,2})\+?\s*(?:or more\s*)?years', low) if int(y) < 30]
    top = int(salary_max) if salary_max else None
    level = level_points(pack, title, top)
    lv, flags = pack.get('level') or {}, []
    below = lv.get('down_level_below')
    if (lv.get('down_level_title') and re.search(lv['down_level_title'], title.lower())) or \
            (level == 0 and top and below and top < below):
        flags.append('possible down-level')
    if not top:
        flags.append('no posted range')
    if years and max(years) >= 15:
        flags.append(f'{max(years)}+ years asked')
    s_cap = min(s_pts, pack.get('strength_cap', 45))
    fit = max(0, min(100, 35 + s_cap - g_pts + level + (ats - 50) // 5))
    out = dict(fit=fit, ats=ats, strengths=len(strengths), gaps='; '.join(l for l, _ in gaps), flags='; '.join(flags))
    if parts:
        out['parts'] = dict(base=35, strengths=s_cap, strength_hits=[s.get('label') or s['pattern'] for s in strengths],
                            gaps=-g_pts, gap_hits=[[l, w] for l, w in gaps], level=level, ats=(ats - 50) // 5)
    return out
