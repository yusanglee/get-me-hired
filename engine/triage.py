"""Already-applied checks and review tiers for scored roles.

Dedup: a role found on LinkedIn (li- id) and applied through Greenhouse (gh- id) is the
same role. Matching by id alone let two applied roles resurface on Oct 20; matching by
job_key(company, title) catches them. A company that hires under several names ("Northwind (Tailspin)" tracked,
"Tailspin" or a config `company_aliases` sibling found) is matched under each of them (job_key.alias_keys).

Tiers: A and B go to review. A "near-miss" band (tier 'C+') sends C roles within
scoring.near_miss_margin points of the B line to review too, because a rules score that
close to the line is noise, not a verdict.

Over the bar: the rules score doesn't read seniority asks, so a role asking more years than the profile
has (employment.years_experience), or asking to manage managers when the profile says the user hasn't
(employment.managed_managers: "No"), is held to tier B (config scoring.over_bar_tier; "A" turns this
off) and flagged. With the profile silent, it is flagged only. Asks under a nice-to-have heading or
marked "a plus" don't count.

Gap reads: a role with a valid cached read (engine/reads.py) follows config scoring.gap_rules. A critical gap
("section") takes the role out of review into tier 'gap' before the company cap, so it counts toward no cap; a major
gap ("B") holds an A to B like over the bar. "flag" for either only adds a flag.
"""
import csv, os, re
from .job_key import alias_keys, job_key

# "15+ years of product management"; a range ("10-14 years") asks for its low end
YEARS_RE = re.compile(r"\b(?:(\d{1,2})\s*(?:-|\u2013|\u2014|to)\s*)?(\d{1,2})\s*\+?\s*(?:or more\s+)?years?(?:['\u2019]s?)?\s+(?:of\s+)?(?:[\w-]+\s+){0,4}?"
                      r"(?:experience|product|management|leadership|leading|working|managing|building|in\b)", re.I)
# Managing managers: "manage a team of product managers, including people managers", "operating through
# layers of leadership", "lead a team of product leaders", "managers of managers"
MANAGERS_RE = re.compile(r"\bmanag\w*(?:,? (?:and|mentor|grow|build)\w*)* (?:a team of )?(?:product managers|pms),? including (?:people )?managers|"
                         r"\b(?:managers|leaders) of (?:managers|leaders)\b|"
                         r"\bmanag(?:e|es|ed|ing) (?:other )?(?:people )?managers\b|"
                         r"\b(?:through|across) (?:multiple )?layers of (?:\w+ ){0,2}(?:leadership|management|managers)\b|"
                         r"\b(?:lead|leads|leading|manage|manages|managing)\b(?: and \w+)? (?:a team of |an? org(?:anization)? of )?"
                         r"(?:product|pm) (?:leaders|directors|leadership team|managers who manage)\b", re.I)


def applied_index(path):
    """(job_keys, ids) for every row in applied.csv (columns company, title, id)."""
    keys, ids = set(), set()
    if path and os.path.exists(path):
        for r in csv.DictReader(open(path, encoding='utf-8', newline='')):
            if r.get('company') and r.get('title'):
                keys |= alias_keys(r['company'], r['title'])
            if r.get('id'):
                ids.add(r['id'])
    return keys, ids


def already_applied(company, title, pid, index):
    """By id, or by company + title under any name the company goes by: the index (Ctx.applied()) holds every
    alias of each applied role, so the role's own names (its name and any in parentheses) are enough here."""
    keys, ids = index
    return (pid in ids) or not keys.isdisjoint(alias_keys(company, title))


def tier(fit, scoring):
    if fit >= scoring['tier_a']:
        return 'A'
    if fit >= scoring['tier_b']:
        return 'B'
    if fit >= scoring['tier_b'] - scoring.get('near_miss_margin', 0) and scoring.get('near_miss_margin', 0) > 0:
        return 'C+'
    return 'C'


def assign_tiers(rows, scoring, cap, prior=None):
    """Set tier/review on rows sorted best first. Reviewable tiers (A, B, C+) count toward the
    per-company cap, including applications already made (prior: lowercased company -> count)."""
    prior, per = prior or {}, {}
    for r in rows:
        r['tier'] = held_tier(tier(int(r['fit']), scoring), r.get('over_bar'), scoring, r.get('gap_hold'))
        if r['tier'] == 'C+':
            r['flags'] = '; '.join(filter(None, [r.get('flags', ''), f"near-miss C (fit within {scoring['near_miss_margin']} of B)"]))
        if r['tier'] != 'C':
            per[r['company']] = per.get(r['company'], prior.get(r['company'].lower(), 0)) + 1
            if per[r['company']] > cap:
                r['tier'] = 'cap'
        r['review'] = 'yes' if r['tier'] in ('A', 'B', 'C+') else 'no'
    return rows


def profile_years(prof):
    """Years of experience from profile employment.years_experience ("13 years PM, 2013 to 2026" -> 13), or None."""
    m = re.search(r'(\d{1,2})\s*\+?\s*(?:years|yrs)', str((prof or {}) and prof.get('employment.years_experience') or ''), re.I)
    return int(m.group(1)) if m else None


def managers_re(pack=None):
    """The manager-of-managers pattern: the pack's triage.manager_of_managers, else MANAGERS_RE (the product-management one)."""
    pat = ((pack or {}).get('triage') or {}).get('manager_of_managers')
    return re.compile(pat, re.I) if pat else MANAGERS_RE


def years_re(pack=None):
    """The years-of-experience pattern: the pack's triage.years_re (group 1 optional range start, group 2 the years),
    else YEARS_RE (names product/management work; other families set their own)."""
    pat = ((pack or {}).get('triage') or {}).get('years_re')
    if not pat:
        return YEARS_RE
    try:
        return re.compile(pat, re.I)
    except re.error as e:
        raise ValueError(f"pack triage.years_re is not a valid regex: {e}") from None


def over_bar(jd, prof, pack=None):
    """Seniority asks the profile may not meet: (flags, hold) where hold means keep the role out of tier A.
    `pack` supplies triage.manager_of_managers and triage.years_re; without it the default patterns are used."""
    from .gates import optional, optional_section, sentence
    flags, hold = [], False
    asked = [(int(m.group(1) or m.group(2)), m) for m in years_re(pack).finditer(jd)
             if int(m.group(2)) < 30 and not optional(jd, m.start(), m.end()) and not optional_section(jd, m.start())]
    have = profile_years(prof)
    if asked and have is not None:
        n = max(y for y, _ in asked)
        if n > have:
            flags.append(f'asks {n}+ years (profile: {have})')
            hold = True
    m = next((m for m in managers_re(pack).finditer(jd)
              if not optional(jd, m.start(), m.end()) and not optional_section(jd, m.start())), None)
    if m:
        managed = str((prof or {}) and prof.get('employment.managed_managers') or '').strip().lower()
        if not managed.startswith(('y', 'true')):
            quote = sentence(jd, m.start(), m.end(), 60).replace(';', ',')  # flags are ';'-separated
            flags.append('asks to manage managers' + (' (profile: not done)' if managed.startswith(('n', 'false'))
                                                      else ' (profile employment.managed_managers not set)')
                         + f' ("{quote}")')
            hold = hold or managed.startswith(('n', 'false'))
    return flags, hold


def held_tier(t, hold, scoring, gap_hold=False):
    """The tier after the over-the-bar hold (config scoring.over_bar_tier "B", the default; "A" turns it off) and the
    major-gap hold (gap_hold, set by apply_read): A becomes B."""
    return 'B' if t == 'A' and (gap_hold or (hold and scoring.get('over_bar_tier', 'B') == 'B')) else t


GAP_RULES = {'critical': ('section', 'flag'), 'major': ('B', 'flag')}


def gap_rules(scoring):
    """config scoring.gap_rules with the defaults filled in: {"critical": "section", "major": "B"}."""
    got = scoring.get('gap_rules') or {}
    out = {k: got.get(k, v[0]) for k, v in GAP_RULES.items()}
    for k, v in out.items():
        if v not in GAP_RULES[k]:
            raise SystemExit(f"config scoring.gap_rules.{k}: {' or '.join(map(repr, GAP_RULES[k]))}, not {v!r}")
    return out


def apply_read(r, read, rules):
    """Apply a valid read to a kept row: sets r['read'] (as the run record keeps it) and, per the rules, a flag,
    r['gap_hold'] (major gap: hold an A to B) or tier 'gap' (critical gap: out of review, fit and ATS kept).
    Returns True when the row left review."""
    r['read'] = read
    gap, top = read.get('gap_type'), (read.get('top_gap') or '').replace(';', ',')
    rule = rules.get(gap)
    if rule == 'flag':
        r['flags'] = '; '.join(filter(None, [r.get('flags', ''), f"{gap} gap" + (f': {top}' if top else '')]))
    elif gap == 'major' and rule == 'B':
        r['gap_hold'] = True
    elif gap == 'critical' and rule == 'section':
        r.update(tier='gap', review='no')
        return True
    return False
