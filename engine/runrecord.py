"""Run record and review page for each discover + score run, so no role leaves the funnel unseen.

`gmh discover` and `gmh score` each add their half to queue/run-<date>.json: every scored role
with its tier, the reason for the tier and the fit formula's terms, and every role dropped on the
way (discover: location, pay, no range; score: already applied, already in a Workflow folder,
same role in another location), with stage, reason, pay, link and the fit it would have scored.
Postings whose title is outside the pack are not recorded at all. A role posted in several
locations is one entry. After scoring it writes queue/review-<date>.html, one self-contained page
for the browser pane that groups the roles by tier, and prints a short summary for chat.

Picks made on the page (apply, hold, pass, manual; a pick on a C or cap role promotes it, a pick
on a dropped role, ref "d<n>", rescues it) come back as text the user pastes in chat and land in
queue/reviewed-<date>.csv, the file stage 3 onward reads. Existing rows in that file (Claude's
stage 2b calls) are updated in place, never dropped.

Folders follow picks: a pass moves the role's built folder (named in Pipeline/specs) from Workflow/02-Ready to Apply
to Workflow/Passed; a later apply, manual or hold moves it back. Applied folders never move. `folders` is the
catch-up: it moves to Passed every Ready folder whose latest reviewed call is pass (only that direction, since old
reviewed files can trail hand moves into Passed).

    gmh review summary [--date D]          the chat summary of a run
    gmh review page [--date D] [--open]    rebuild the review page (--open: in the default browser)
    gmh review picks "apply 1 4 d3; hold 7: waiting on referral" [--date D] [--dry-run]
    gmh review todo [--date D]             apply/manual rows still missing their gap read or their material choices
    gmh review reads [--date D] [--ids ID ...] [--json]   A/B/critical-gap roles with no valid posting read (or those ids)
    gmh review reads --apply FILE...       check and cache posting-reader replies; re-score if no picks yet (engine/reads.py)
    gmh review reads --briefs [--per 9]    write posting-reader briefs (<= --per roles each); one path per line
    gmh review open-check [--date D] [--json]   are the apply/manual rows still open? (Greenhouse, Lever, Ashby; read-only)
    gmh review folders [--dry-run]         move passed roles' folders out of 02-Ready to Apply
    gmh review fill <id> --set gap_type=minor --set top_gap="..." --set summary_variant="..."
                    --set template_script=... --set lead_material="..." [--set peak_money=in]
<date> defaults to the latest run in the queue.
"""
import argparse, collections, csv, datetime, glob, json, os, re, shutil, sys
from . import triage

CALLS = ('apply', 'hold', 'pass', 'manual')
# The columns the vault's stage 2b file uses; an existing reviewed CSV keeps its own header.
REVIEWED_COLUMNS = ['call', 'gap_type', 'top_gap', 'company', 'title', 'locations', 'salary_max', 'fit', 'summary_variant',
                    'template_script', 'lead_material', 'peak_money', 'notes', 'url', 'id']
PICK_MARK = 'Review page pick'
# Stage 2b columns Claude fills from the JD once a role is marked apply (or manual).
STAGE_2B = ('gap_type', 'top_gap', 'summary_variant', 'template_script', 'lead_material', 'peak_money')
GAP_TYPES = ('none', 'minor', 'major', 'critical')
REASONS = {
    'location': 'Location outside your metros and remote rules',
    'salary': 'Top of posted range below your floor',
    'no_range_level': 'No posted range, and the title is not senior',
    'no_range': 'No posted pay range',
    'already_applied': 'Already applied (tracker, applied.csv, or an Applied or Interviewing folder)',
    'in_workflow': 'In a Workflow folder (new, ready to apply or passed), not applied',
    'duplicate': 'Same role posted in another location',
    'passed': 'You passed on it in an earlier review',
    'already_picked': 'Picked apply or manual in an earlier review, not yet in Workflow or the tracker',
}
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'review_page.html')


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _split(s):
    return [x.strip() for x in (s or '').split(';') if x.strip()]


class Drops:
    """Roles a stage dropped, with the reason. Postings (discover) and CSV rows (score) both fit.
    Title drops are not kept. The same role in several locations is one entry (locations joined)."""

    def __init__(self):
        self.rows, self._seen = [], {}

    def add(self, stage, reason, company, p, detail='', prior=None):
        if reason == 'title':
            return
        extra = p.get('_drop') or {}
        loc = p.get('location_raw') or p.get('location', '')
        key = (stage, reason, company, p.get('title', ''))
        if key in self._seen:
            d = self._seen[key]
            if loc and loc not in d['location'].split(' / '):
                d['location'] = ' / '.join(filter(None, [d['location'], loc]))
            d['postings'] += 1
            return
        self._seen[key] = d = dict(postings=1, 
            stage=stage, reason=reason, company=company, title=p.get('title', ''),
            location=loc,
            locations=extra.get('locations') or p.get('locations', ''),
            salary_max=_int(extra.get('salary_max') or p.get('smax') or p.get('salary_max')),
            url=p.get('url', ''), id=p.get('id', ''), source=p.get('source', ''), detail=detail)
        if prior:  # an earlier review's call: date, worst gap_type and top_gap, notes
            d['prior'] = prior
        self.rows.append(d)


# ---------- files ----------

def path_for(queue, date):
    return os.path.join(queue, f'run-{date}.json')


def date_of(csv_path):
    m = re.search(r'(?:discovered|scored)-(.+)\.csv$', os.path.basename(csv_path))
    return m.group(1) if m else datetime.date.today().isoformat()


def load(queue, date):
    p = path_for(queue, date)
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    return dict(version=1, date=date, roles=[], dropped=[], picks={})


def save(queue, rec):
    p = path_for(queue, rec['date'])
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(rec, fh, indent=1, ensure_ascii=False)
    return p


def latest_date(queue):
    runs = sorted(glob.glob(os.path.join(queue, 'run-*.json')))
    if not runs:
        raise SystemExit(f'no run-*.json in {queue}: run gmh discover and gmh score first')
    return os.path.basename(runs[-1])[4:-5]


# ---------- same-day rerun guard ----------

def rerun_warning(stage, date, queue, path):
    """The text shown when `stage` ('discover' or 'score') is about to redo a finished run. Written for a person;
    the first line is a stable marker that Claude looks for."""
    rec = load(queue, date)
    at = (rec.get(stage) or {}).get('at') or datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
    picks = len(rec.get('picks') or {})
    what = ("rebuilds today's list of found roles and the review page", 'roles found earlier today stop being marked "new"') \
        if stage == 'discover' else ("rebuilds today's scores and the review page",)
    lines = [f'RERUN-GUARD: {stage} {date}',
             f"Today's job search already ran ({date}, finished at {at[11:16]})." if stage == 'discover' else
             f"Today's scoring already ran ({date}, finished at {at[11:16]}).",
             'Running it again:',
             *[f'  - {w}' for w in what],
             '  - changes the role numbers on the review page, so a picks line copied from the current page may now '
             'point at different roles (copy picks again from the new page)',
             f'  - keeps the picks already confirmed ({picks})']
    if stage == 'discover':
        lines.append('  - can take 15 minutes or more')
    lines.append('To keep today\'s results, do nothing. To run it again anyway, tell Claude "run it again" (it re-runs with --force).')
    return '\n'.join(lines)


def rerun_ok(stage, date, queue, path, force=False):
    """False (after printing the warning) when `path`, this stage's output, already exists and the person has not
    forced a rerun. In a terminal the person is asked; anywhere else the caller exits with code 3."""
    if force or not os.path.exists(path):
        return True
    print(rerun_warning(stage, date, queue, path))
    if sys.stdin.isatty() and sys.stdout.isatty():
        return input('Run it again anyway? [y/N] ').strip().lower() in ('y', 'yes')
    return False


# ---------- stage hooks ----------

def save_discover(ctx, csv_path, rows, drops, reasons, board_report, resolved):
    """Start the day's record over: a new discover run makes any earlier score half stale (picks are kept)."""
    date = date_of(csv_path)
    old = load(ctx.queue, date)
    rec = dict(version=1, date=date, pack=ctx.pack.get('label') or ctx.pack.get('name'), roles=[], picks=old.get('picks', {}),
               dropped=drops.rows, discover=dict(
                   at=_now(), file=os.path.relpath(csv_path, ctx.P).replace(os.sep, '/'), kept=len(rows), new=sum(r['new'] == 'yes' for r in rows),
                   counts={k: v for k, v in sorted(reasons.items()) if not k.endswith('title')},
                   companies=len(resolved), unresolved=[n for n, r in resolved if not r],
                   boards=board_report or []))
    return save(ctx.queue, rec)


def explain(rows, scoring, cap, window, prior, limits):
    """Set r['why'] (one line: why this tier) and r['base_tier'] on scored rows, best first, gates last."""
    a, b, m = scoring['tier_a'], scoring['tier_b'], scoring.get('near_miss_margin', 0)
    ahead = collections.Counter()
    for r in rows:
        fit, t = int(r.get('fit') or 0), r['tier']
        if t == 'gate':
            r['base_tier'], r['why'] = 'gate', 'Hard gate failed, so it was not scored: ' + (r.get('flags') or '')
            continue
        fit_tier = triage.tier(fit, scoring)
        base = r['base_tier'] = triage.held_tier(fit_tier, r.get('over_bar'), scoring, r.get('gap_hold'))
        co = r['company']
        if t == 'gap':  # out of review before the cap, so it takes no cap slot
            rd = r.get('read') or {}
            r['why'] = f"Critical gap: {rd.get('top_gap') or 'see the read'}, so it was taken out of review" + \
                (f": \"{rd['gap_quote']}\"" if rd.get('gap_quote') else '.')
            continue
        if t == 'A':
            r['why'] = f'Fit {fit} is at or above the A line ({a}).'
        elif t == 'B' and fit_tier == 'A':
            gap = f"major gap ({(r.get('read') or {}).get('top_gap') or 'see the read'})"
            over = triage.held_tier(fit_tier, r.get('over_bar'), scoring) == 'B'
            r['why'] = (f'Fit {fit} is at or above the A line ({a}), held to B: ' +
                        ('it asks for more than your profile shows (see flags)' + (f'; also a {gap}.' if r.get('gap_hold') else '.')
                         if over else f'{gap}.'))
        elif t == 'B':
            r['why'] = f'Fit {fit} is in the B band ({b} to {a - 1}).'
        elif t == 'C+':
            r['why'] = f'Fit {fit} is within {m} of the B line ({b}): a near miss, sent to review.'
        elif t == 'C':
            r['why'] = f'Fit {fit} is below {b - m if m else b}, so it was not sent to review.'
            if 'over office-day limit' in (r.get('flags') or ''):
                r['why'] = f"On-site veto: {r.get('locations')} asks for more office days than your limit, so fit was set to {fit}."
        elif t == 'cap':
            before, had = ahead[co], prior.get(co.lower(), 0)
            lim = next((v for k, v in limits.items() if k == co.lower()), None)
            if had + before >= cap:
                r['why'] = (f'Would be {base}, held back by the company cap: at most {cap} reviewable roles per company in '
                            f'{window} days, and {co} already has {had} recent application(s) or queued role(s) and {before} higher-ranked '
                            f'role(s) in this run.')
            elif lim:
                r['why'] = (f"Would be {base}, held back by {co}'s own limit of {lim['max_applications']} applications "
                            f"in {lim['window_days']} days, already used up.")
            else:
                r['why'] = f'Would be {base}, held back by a company cap.'
        if base != 'C':
            ahead[co] += 1


def save_score(ctx, src, rows, drops, prior, out=print):
    """Write the score half of the record, rebuild the page, print the summary. Returns the record path."""
    date, queue = date_of(src), os.path.dirname(os.path.abspath(src))
    rec = load(queue, date)
    sc, pc = ctx.cfg['scoring'], ctx.cfg['per_company']
    limits = {k.lower(): v for k, v in (ctx.cfg.get('company_limits') or {}).items() if not k.startswith('_')}
    explain(rows, sc, pc['max_applications'], pc['window_days'], prior, limits)
    roles = []
    for i, r in enumerate(rows, 1):
        roles.append(dict(
            ref=i, tier=r['tier'], base_tier=r.get('base_tier'), why=r.get('why', ''), fit=int(r.get('fit') or 0),
            ats=int(r.get('ats') or 0), parts=r.get('parts'), company=r['company'], title=r['title'],
            locations=r.get('locations', ''), location_raw=r.get('location_raw', ''), salary_min=_int(r.get('salary_min')),
            salary_max=_int(r.get('salary_max')), salary_source=r.get('salary_source', ''), gaps=_split(r.get('gaps')),
            flags=_split(r.get('flags')), review=r.get('review', ''), url=r.get('url', ''), id=r['id'],
            source=r.get('source', ''), new=r.get('new') == 'yes', first_seen=r.get('first_seen', ''),
            top_locations=r.get('top_locations') or []))
        if r.get('read'):  # only roles with a valid read get these keys, so a run with no reads is unchanged
            roles[-1]['read'] = r['read']
            if r.get('gap_hold') and r['tier'] == 'B' and triage.tier(roles[-1]['fit'], sc) == 'A':
                roles[-1]['gap_hold'] = True
    rec['roles'] = roles
    rec['dropped'] = [d for d in rec.get('dropped', []) if d['stage'] != 'score'] + drops.rows
    score_drops(ctx, rec['dropped'], sc)
    rec['pack'] = rec.get('pack') or ctx.pack.get('label') or ctx.pack.get('name')
    rec['score'] = dict(at=_now(), file=os.path.relpath(src.replace('discovered-', 'scored-'), ctx.P).replace(os.sep, '/'),
                        tiers=dict(collections.Counter(r['tier'] for r in roles)),
                        settings=dict(tier_a=sc['tier_a'], tier_b=sc['tier_b'], near_miss_margin=sc.get('near_miss_margin', 0),
                                      cap=pc['max_applications'], window_days=pc['window_days'],
                                      location_drops=location_listing(ctx.cfg)))
    p = save(queue, rec)
    page = build_page(rec, queue)
    standing_copy(page, ctx.ws)
    for line in summary(rec):
        out(line)
    out(f'Review page: {page} ({page_size(page)})')
    return p


def jd_path(state, rid):
    """The saved JD for a posting id (board ids are saved with unsafe characters replaced), or None."""
    for name in (rid, re.sub(r'[^\w.-]', '_', rid or '')):
        p = os.path.join(state, 'jd', name + '.txt')
        if name and os.path.exists(p):
            return p
    return None


def score_drops(ctx, dropped, scoring):
    """Number the dropped roles d1, d2, ... and add the fit each would have scored (from its saved JD), so a
    rescue is an informed call. A role with no saved JD gets no score."""
    from .score import add_location_bonus, evidence, gate_location, gate_profile
    from . import gates, packs
    ev, prof = evidence(ctx), gate_profile(ctx, out=lambda *a: None)
    for i, d in enumerate(dropped, 1):
        d['ref'] = f'd{i}'
        jd = jd_path(ctx.state, d['id'])
        if not jd:
            continue
        with open(jd, encoding='utf-8') as fh:
            text = fh.read()
        s = packs.score(ctx.pack, d['title'], text, ev, d.get('salary_max'))
        s['locations'] = d.get('locations', '')
        add_location_bonus(ctx.cfg, s)
        extra, hold = triage.over_bar(text, prof, ctx.pack)
        flags = _split(s['flags'])
        if any(f.startswith('asks ') and 'years' in f for f in extra):
            flags = [f for f in flags if not re.fullmatch(r'\d+\+ years asked', f)]
        d.update(fit=s['fit'], ats=s['ats'], gaps=_split(s['gaps']), flags=flags + extra, top_locations=s['top_locations'],
                 would_be=triage.held_tier(triage.tier(s['fit'], scoring), hold, scoring))
        res = gates.check(text, prof, location=gate_location(ctx, prof, d.get('location') or d.get('locations'))) if prof is not None else []
        if gates.verdict(res) == gates.FAIL:  # a rescue would hit the same hard gate scoring applies
            d.update(would_be='gate', gate=gates.summary(res, (gates.FAIL,)))


# ---------- summary ----------

def _n(c, k):
    return c.get(k, 0)


def summary(rec, listing=None, unread=None):
    """A few lines for chat: what's worth a look, and what was held back or dropped and why. `unread`: how many A/B
    roles have no valid read (default: those whose record has none; the CLI checks the cache, which can be newer)."""
    roles, drops = rec.get('roles', []), rec.get('dropped', [])
    t = collections.Counter(r['tier'] for r in roles)
    new = sum(r['new'] for r in roles)
    review = [f'{_n(t, k)} {k}' for k in ('A', 'B', 'C+') if _n(t, k)]
    held = [f'{_n(t, k)} {k}' for k in ('C', 'cap', 'gap', 'gate') if _n(t, k)]
    top = sum(1 for r in roles if r['tier'] in ('A', 'B', 'C+') and r.get('top_locations'))
    lines = [f"Run {rec['date']}: {len(roles)} roles scored ({new} new). To review: {', '.join(review) or 'none'}"
             + (f' ({top} in a first-choice location).' if top else '.')
             + (f" Not sent to review: {', '.join(held)}." if held else '')]
    capped = collections.defaultdict(list)
    for r in roles:
        if r['tier'] == 'cap':
            capped[r['company']].append(r['base_tier'])
    if capped:
        top = sorted(capped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        rest = top[6:]
        lines.append('Held back by a company cap: ' + '; '.join(
            f"{co} x{len(v)} (would be {', '.join(f'{n} {t}' for t, n in sorted(collections.Counter(v).items()))})" for co, v in top[:6])
            + (f"; {len(rest)} more companies ({sum(len(v) for _, v in rest)} roles)" if rest else ''))
    if unread is None:
        unread = sum(1 for r in roles if r['tier'] in ('A', 'B') and not r.get('read'))
    held_b = sum(1 for r in roles if r.get('gap_hold'))
    got = [f'{n} {what}' for n, what in ((_n(t, 'gap'), 'critical (own section)'), (held_b, 'A held to B for a major gap'),
                                          (unread, 'A/B roles not read yet (gmh review reads)')) if n]
    if got:
        lines.append('Gap read: ' + ', '.join(got) + '.')
    for r in roles:  # every major/critical badge gets its gap text, so a pick never rests on a bare badge
        rd = r.get('read') or {}
        if rd.get('gap_type') in ('major', 'critical') and r['tier'] in ('A', 'B', 'C+', 'gap'):
            g = rd.get('top_gap') or 'no gap text recorded'
            lines.append(f"  #{r.get('ref', '?')} {r['company']}: {r['title']} [{r['tier']}, {rd['gap_type']} gap]: "
                         + (g if len(g) <= 160 else g[:157] + '...'))
    gated = [r for r in roles if r['tier'] == 'gate']
    if gated:
        lines.append('Hard gate (ineligible as posted): ' + '; '.join(f"{r['company']}: {r['title']}" for r in gated))
    d = collections.Counter(x['reason'] for x in drops if x['reason'] != 'title')
    named = [f"{_n(d, k)} {lbl}" for k, lbl in (('already_applied', 'already applied'), ('in_workflow', 'already in Workflow'), ('already_picked', 'picked before'), ('passed', 'passed before'),
                                                ('duplicate', 'duplicate location'), ('location', 'location'),
                                                ('salary', 'pay below floor'), ('no_range_level', 'no range, not senior'), ('no_range', 'no posted range'))
             if _n(d, k)]
    if named:
        listed = [x for x in page_drops(page_data(dict(rec, dropped=drops), listing)) if x.get('listed')]
        ls = _listing(rec, listing)
        tiers = ' or '.join(ls['tiers'])
        pay = sum(1 for x in drops if x.get('would_be') in ls['tiers'] and x['reason'] in ('salary', 'no_range_level', 'no_range'))
        rest = sum(1 for x in drops if x['reason'] == 'location') - len(listed)
        good = []
        if listed:
            good.append(f"{len(listed)} location drop{'s' if len(listed) > 1 else ''}"
                        + (' in the US' if ls['us_only'] else '') + ' (the page lists only these'
                        + (f'; the other {rest} are under "show all"' if rest else '') + ')')
        if pay:
            good.append(f"{pay} pay or range drop{'s' if pay > 1 else ''}")
        lines.append('Dropped before scoring: ' + ', '.join(named) + '.'
                     + (f" On fit alone, these would score {tiers}: {'; '.join(good)}. Rescue any from the page."
                        if good else ''))
    picks = rec.get('picks') or {}
    if picks:
        lines.append('Picks so far: ' + ', '.join(f'{v} {k}' for k, v in collections.Counter(p['call'] for p in picks.values()).items()))
    return lines


# ---------- page ----------

# Location drops the page lists by default (config review.location_drops): these would-be tiers, and with us_only,
# only in the US or where the location text doesn't say. The rest stay in the run record, reachable by search and
# the section's "show all" button. Score saves the setting in the record, so a rebuild after picks uses it too.
LOCATION_DROPS = dict(tiers=['A'], us_only=True)
DROP_TIERS = ('A', 'B', 'C+', 'C')


def location_listing(cfg):
    """config review.location_drops, e.g. {"tiers": ["A", "B"], "us_only": false}; missing keys take the defaults."""
    got = ((cfg or {}).get('review') or {}).get('location_drops') or {}
    out = dict(LOCATION_DROPS, **{k: v for k, v in got.items() if k in LOCATION_DROPS})
    if not isinstance(out['tiers'], list) or not out['tiers'] or any(t not in DROP_TIERS for t in out['tiers']):
        raise SystemExit(f"config review.location_drops.tiers: a list of {', '.join(DROP_TIERS)}, e.g. [\"A\"]")
    out['us_only'] = bool(out['us_only'])
    return out


def _listing(rec, listing=None):
    return listing or ((rec.get('score') or {}).get('settings') or {}).get('location_drops') or LOCATION_DROPS


# What the review page reads (engine/review_page.html). Everything else in the run record stays in the record: the
# page has to stay small enough for Claude to read before publishing it as the user's artifact.
ROLE_KEYS = ('ref', 'tier', 'base_tier', 'why', 'fit', 'ats', 'parts', 'company', 'title', 'locations', 'location_raw',
             'salary_min', 'salary_max', 'gaps', 'flags', 'url', 'id', 'source', 'new', 'first_seen', 'top_locations',
             'read')
# Roles, score parts and posting reads go on the page as arrays in these orders (the page's script turns them back
# into objects): key names repeated on every role were about a fifth of a large page.
PART_KEYS = ('base', 'strengths', 'gaps', 'level', 'ats', 'location', 'strength_hits', 'strength_n', 'strength_plain',
             'gap_hits')
READ_KEYS = ('gap_type', 'top_gap', 'gap_quote', 'strengths')
STRENGTH_KEYS = ('label', 'level', 'posting')
DROP_KEYS = ('ref', 'id', 'company', 'title', 'reason', 'detail', 'top_locations', 'location', 'locations', 'salary_max',
             'source', 'postings', 'fit', 'ats', 'would_be', 'gate', 'prior', 'gaps', 'flags', 'url', 'listed', 'country')
# Compact rows: drops listed only under "show all", and look-back reasons (already applied, duplicates, earlier
# picks and passes) that are rarely rescued. No pills; still listed, searchable and pickable.
HIDDEN_DROP_KEYS = ('ref', 'id', 'company', 'title', 'reason', 'detail', 'location', 'salary_max', 'source', 'postings',
                    'fit', 'ats', 'would_be', 'prior', 'url', 'listed', 'country')
LOOK_BACK = ('already_applied', 'duplicate', 'in_workflow', 'already_picked', 'passed')
# Over budget, drop rows go in this order (then lowest fit first): the least likely rescues first. Compact rows all
# go before any full row.
TRIM_ORDER = ('duplicate', 'already_applied', 'in_workflow', 'already_picked', 'passed', 'location', 'no_range',
              'no_range_level', 'salary')
MAX_PLACES = 4
MAX_TIP = 160  # a strength's posting quote is a hover tip; longer ones are cut
# The page's size budget: about 35K tokens. Claude reads the whole page before each publish (in parts when one read
# is too large), so a smaller page is a cheaper publish. Past the budget, drop rows are left off the page in
# TRIM_ORDER, lowest fit first (compact rows, then the strengths' hover quotes, then full rows; counted per reason,
# and still in the run record).
# Scored roles always stay: picks need them. `gmh review page` and `gmh score` print the size and warn when over.
PAGE_BUDGET = 120_000
TOKEN_BYTES = 3.5  # bytes per token for this page (JSON and HTML), measured roughly


def _places(s, sep):
    """A long joined location list cut to its first MAX_PLACES, with how many more."""
    parts = [p for p in (s or '').split(sep) if p.strip()]
    if len(parts) <= MAX_PLACES:
        return s
    return sep.join(parts[:MAX_PLACES]) + f'{sep}+{len(parts) - MAX_PLACES} more'


def short_url(u):
    """A LinkedIn job link cut to its job id (the title slug is long and the id alone opens the same posting)."""
    m = re.match(r'(https?://(?:[\w-]+\.)?linkedin\.com/jobs/view/)[^/?#]*?-?(\d{6,})/?(?:[?#].*)?$', u or '')
    return f'{m.group(1)}{m.group(2)}/' if m else u


def _cut(s, n):
    return s if not s or len(s) <= n else s[:n - 1].rstrip() + '…'


def _row(d, keys):
    """A dict as an array in `keys` order, trailing missing values left off."""
    out = [d.get(k) for k in keys]
    while out and out[-1] is None:
        out.pop()
    return out


def _slim_role(r):
    out = {k: r[k] for k in ROLE_KEYS if k in r}
    if out.get('locations'):
        out.pop('location_raw', None)  # the page shows the raw text only when no location matched
    if out.get('new'):
        out.pop('first_seen', None)  # the page shows "new today" instead
    if out.get('url'):
        out['url'] = short_url(out['url'])
    p = r.get('parts')
    if p:
        hits = p.get('strength_hits') or []
        plain = [h for h in hits if re.fullmatch(r"[\w\s'&-]+", h or '')]
        out['parts'] = _row(dict({k: p[k] for k in PART_KEYS[:6] if k in p}, strength_hits=plain[:7],
                                 strength_n=len(hits), strength_plain=len(plain) == len(hits),
                                 gap_hits=[g[0] for g in p.get('gap_hits') or []]), PART_KEYS)
    if r.get('read'):
        rd = {k: r['read'][k] for k in READ_KEYS if k in r['read']}
        rd['strengths'] = [_row(dict(s, posting=_cut(s.get('posting'), MAX_TIP)), STRENGTH_KEYS)
                           for s in (rd.get('strengths') or [])[:3]]
        out['read'] = _row(rd, READ_KEYS)
    return out


def _compact(d):
    return d.get('listed') is False or d.get('reason') in LOOK_BACK


def _slim_drop(d):
    keys = HIDDEN_DROP_KEYS if _compact(d) else DROP_KEYS
    out = {k: d[k] for k in keys if k in d and (k in ('country', 'listed') or d[k] not in (None, '', []))}
    if 'location' in out:
        out['location'] = _places(out['location'], ' / ')
    if 'locations' in out:
        out['locations'] = _places(out['locations'], '/')
    if out.get('url'):
        out['url'] = short_url(out['url'])
    return out


def page_data(rec, listing=None):
    """The run record as the page reads it: location drops carry `country` ('us', 'intl' or '' when unclear) and
    `listed` (shown before "show all"); `location_drops` says the rule. Roles and drops are tables (cols + rows);
    page_roles and page_drops read them back. The record on disk is not changed."""
    from .locations import country
    ls = _listing(rec, listing)
    drops = [dict(d) for d in rec.get('dropped', [])]
    for d in drops:
        if d.get('reason') == 'location':
            d['country'] = country(d.get('location', ''))
            d['listed'] = d.get('would_be') in ls['tiers'] and not (ls['us_only'] and d['country'] == 'intl')
    disc = rec.get('discover') or {}
    out = {k: rec[k] for k in ('version', 'date', 'pack', 'picks') if k in rec}
    shown = [_slim_drop(d) for d in drops if not _compact(d)]
    hidden = [_slim_drop(d) for d in drops if _compact(d)]
    out.update(location_drops=ls, discover={k: disc[k] for k in ('companies', 'unresolved') if k in disc},
               score={'settings': ((rec.get('score') or {}).get('settings') or {})},
               shape={'parts': list(PART_KEYS), 'read': list(READ_KEYS), 'strength': list(STRENGTH_KEYS)},
               roles={'cols': list(ROLE_KEYS), 'rows': [_row(_slim_role(r), ROLE_KEYS) for r in rec.get('roles', [])]},
               dropped={'cols': list(DROP_KEYS), 'rows': [[d.get(k) for k in DROP_KEYS] for d in shown]},
               hidden={'cols': list(HIDDEN_DROP_KEYS), 'rows': [[d.get(k) for k in HIDDEN_DROP_KEYS] for d in hidden]},
               omitted={})
    return out


def _table(t):
    return [{c: v for c, v in zip(t['cols'], r) if v is not None} for r in (t or {}).get('rows', [])]


def page_roles(data):
    """The page's roles as its script sees them (objects, with parts and read unpacked)."""
    obj = lambda keys, row: {k: v for k, v in zip(keys, row or []) if v is not None}
    out = []
    for r in _table(data.get('roles')):
        if r.get('parts'):
            r['parts'] = obj(PART_KEYS, r['parts'])
        if r.get('read'):
            r['read'] = obj(READ_KEYS, r['read'])
            r['read']['strengths'] = [obj(STRENGTH_KEYS, s) for s in r['read'].get('strengths') or []]
        out.append(r)
    return out


def page_drops(data):
    """The page's drops as its script sees them: the listed table, then the hidden one, as dicts."""
    return _table(data.get('dropped')) + _table(data.get('hidden'))


def _size(text):
    return len(text.encode('utf-8'))


def fit_budget(data, fixed, budget=PAGE_BUDGET):
    """Leave compact drop rows off, then the strengths' hover quotes, then full drop rows (TRIM_ORDER, then lowest
    fit) until the page (template `fixed` bytes + data) fits the budget. Scored roles always stay. Counts what was left off per
    reason in data['omitted']. Returns the page data as JS."""
    text = page_json(data)
    room = 200  # for the omitted counts
    if fixed + _size(text) <= budget:
        return text
    keep = {r: i for i, r in enumerate(TRIM_ORDER)}
    read_i = ROLE_KEYS.index('read')
    for name, cols in (('hidden', HIDDEN_DROP_KEYS), ('quotes', None), ('dropped', DROP_KEYS)):
        if name == 'quotes':  # the strengths' hover quotes (labels and levels stay) go before any listed drop row
            for row in data['roles']['rows']:
                rd = row[read_i] if len(row) > read_i else None
                if rd and len(rd) > 3:
                    rd[3] = [s_[:2] for s_ in rd[3]]
            text = page_json(data)
            if fixed + _size(text) <= budget:
                return text
            continue
        rows = data[name]['rows']
        if not rows:
            continue
        fit_i, reason_i = cols.index('fit'), cols.index('reason')
        # most worth keeping first: reasons late in TRIM_ORDER (or not in it), then best fit; the tail goes
        rows.sort(key=lambda r: (-keep.get(r[reason_i], len(TRIM_ORDER)), -(r[fit_i] if r[fit_i] is not None else -1)))
        sizes = [_size(json.dumps(r, ensure_ascii=False, separators=(',', ':'))) + 2 for r in rows]
        over = fixed + _size(text) - budget + room
        cut = 0
        while cut < len(rows) and over > 0:
            cut += 1
            over -= sizes[-cut]
        for r in rows[len(rows) - cut:]:
            data['omitted'][r[reason_i]] = data['omitted'].get(r[reason_i], 0) + 1
        del rows[len(rows) - cut:]
        text = page_json(data)
        if fixed + _size(text) <= budget:
            return text
    return text


def page_json(data):
    """The page data as JS: one role or dropped role per line, so the page can be read in parts."""
    line = lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':'))
    tables = ('roles', 'dropped', 'hidden')
    head = json.dumps({k: v for k, v in data.items() if k not in tables}, ensure_ascii=False, separators=(',', ':'))
    body = ''
    for k in tables:
        t = data.get(k) or {'cols': [], 'rows': []}
        body += f',"{k}":{{"cols":{line(t["cols"])},"rows":[\n' + ',\n'.join(line(r) for r in t['rows']) + '\n]}'
    text = head[:-1] + (body if head != '{}' else body[1:]) + '}'
    return text.replace('<', '\\u003c')


def page_size(path):
    """'<KB> KB, about <tokens> tokens': what a full read of the page costs, and a warning past the budget."""
    n = os.path.getsize(path)
    out = f'{n // 1024} KB, about {int(n / TOKEN_BYTES) // 100 * 100:,} tokens'
    if n > PAGE_BUDGET:
        out += (f'; over the {PAGE_BUDGET // 1000} KB budget even with drops left off: read it in parts before '
                'publishing, never fall back to the local file')
    return out


def template():
    """The page template without its indentation and whole-line // comments (the page is read in full before each
    publish, so its source should carry no more than it needs)."""
    with open(TEMPLATE, encoding='utf-8') as fh:
        html = fh.read()
    html = re.sub(r'(?m)^[ \t]+', '', html)
    return re.sub(r'(?m)^//.*\n', '', html)


def build_page(rec, queue, listing=None):
    html = template()
    data = fit_budget(page_data(rec, listing), _size(html) - len('/*__RUN_DATA__*/null'))
    html = html.replace('__RUN_DATE__', rec['date']).replace('/*__RUN_DATA__*/null', data)
    p = os.path.join(queue, f"review-{rec['date']}.html")
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(html)
    return p


def standing_copy(page, ws):
    """<ws>/run-review/run-review.html: the latest page under a fixed title, for the user's one standing
    "Run Review" artifact (republished to the same private link after each run; config review.artifact_url)."""
    d = os.path.join(ws, 'run-review')
    os.makedirs(d, exist_ok=True)
    with open(page, encoding='utf-8') as fh:
        html = re.sub(r'<title>Run Review [^<]*</title>', '<title>Run Review</title>', fh.read(), count=1)
    out = os.path.join(d, 'run-review.html')
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(html)
    return out


# ---------- picks ----------

class PickError(ValueError):
    pass


def parse_picks(text):
    """'apply 1 4 d3; hold 7: waiting on referral' -> [{'ref': 1, 'call': 'apply', 'note': ''}, ...].
    Segments split on ';' or newlines; each starts with a call (or 'clear'), then refs (12, #12, 2-5 for scored
    roles; d3, d3-5 for dropped ones), then an optional note."""
    out = []
    for seg in re.split(r'[;\n]', text):
        words = seg.replace(',', ' ').split()
        if not words:
            continue
        call = words[0].lower()
        if call not in CALLS + ('clear',):
            raise PickError(f"'{seg.strip()}': start with one of {', '.join(CALLS)} or clear")
        refs, i = [], 1
        while i < len(words):  # refs end at the first other word, or after one ending in ':' ("hold 7: 3 days")
            m = re.fullmatch(r'(#|d)?(\d+)(?:-d?(\d+))?', words[i].rstrip(':').lower())
            if not m:
                break
            span = range(int(m.group(2)), int(m.group(3) or m.group(2)) + 1)
            refs += [f'd{n}' for n in span] if m.group(1) == 'd' else list(span)
            i += 1
            if words[i - 1].endswith(':'):
                break
        if not refs:
            raise PickError(f"'{seg.strip()}': no role numbers")
        note = ' '.join(words[i:]).strip(' -:')
        out += [dict(ref=r, call=call, note=note) for r in refs]
    return out


def _ref(v):
    """A pick's ref: an int for a scored role, 'd<n>' for a dropped one."""
    if isinstance(v, str) and v.lower().startswith('d'):
        return v.lower()
    return _int(str(v).lstrip('#')) if v not in (None, '') else None


READY, PASSED = '02-Ready to Apply', 'Passed'


def spec_folders(vault):
    """{role id: its Workflow folder name} from Pipeline/specs/*.json (the folder stage 3 builds)."""
    out = {}
    for p in glob.glob(os.path.join(vault, 'Pipeline', 'specs', '*.json')):
        with open(p, encoding='utf-8') as fh:
            s = json.load(fh)
        if s.get('id') and s.get('folder'):
            out[s['id']] = s['folder']
    return out


def folder_moves(vault, calls, dry_run=False, back=True):
    """Move each role's folder to where its call puts it: pass -> Passed, apply/manual/hold -> 02-Ready to Apply
    (back=False skips that direction). calls: [(id, company, title, call)]. A role with no built folder, or whose
    folder is already in place or applied, is skipped; a destination that already exists is reported, never merged.
    Returns [{id, company, title, call, name, src, dst, action ('move' | 'conflict')}]."""
    names, wf, out = spec_folders(vault), os.path.join(vault, 'Workflow'), []
    for rid, company, title, call in calls:
        name = names.get(rid)
        frm, to = (READY, PASSED) if call == 'pass' else (PASSED, READY) if back and call in ('apply', 'manual', 'hold') else (None, None)
        if not name or not frm or not os.path.isdir(os.path.join(wf, frm, name)):
            continue
        src, dst = os.path.join(wf, frm, name), os.path.join(wf, to, name)
        m = dict(id=rid, company=company, title=title, call=call, name=name, src=src, dst=dst,
                 action='conflict' if os.path.exists(dst) else 'move')
        if m['action'] == 'move' and not dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
        out.append(m)
    return out


def describe_folder_move(m, dry_run=False):
    frm, to = (os.path.basename(os.path.dirname(x)) for x in (m['src'], m['dst']))
    verb = ('would move' if dry_run else 'moved') if m['action'] == 'move' else f'left alone ({to} already has it)'
    return f"{verb}: {m['company']}: {m['title']} [{m['call']}]  {frm} -> {to}/{m['name']}"


def latest_calls(queue):
    """[(id, company, title, call)]: each role's call in the newest reviewed-<date>.csv that lists it."""
    calls = {}
    for p in sorted(glob.glob(os.path.join(queue, 'reviewed-*.csv'))):
        with open(p, encoding='utf-8', newline='') as fh:
            for r in csv.DictReader(fh):
                if r.get('id'):
                    calls[r['id']] = (r['id'], r.get('company', ''), r.get('title', ''), (r.get('call') or '').strip().lower())
    return list(calls.values())


def apply_picks(queue, date, picks, dry_run=False, reader=None, applied=None):
    """Record picks in run-<date>.json and upsert them into reviewed-<date>.csv. A pick on a dropped role
    rescues it; a pass moves the role's built folder to Workflow/Passed and a later apply/manual/hold moves it back
    (folder_moves; the vault is the folder above Pipeline/queue). `applied`, when given, is (job_keys, ids) already applied to
    (Ctx.applied()): an apply or manual pick on such a role warns, whatever the role's own reason. A new row, or an existing one with gap_type or top_gap
    empty, takes them from the role's valid read (`reader(id)`, as reads.Reader; without one, the read in the run
    record). Returns (lines, warnings, path)."""
    rec = load(queue, date)
    entries = rec.get('roles', []) + [d for d in rec.get('dropped', []) if d.get('ref')]
    by_ref = {e['ref']: e for e in entries}
    by_id = {}
    for e in entries:
        by_id.setdefault(e['id'], e)  # a scored role wins over a dropped posting with the same id
    chosen, warn = {}, []
    for p in picks:
        call = (p.get('call') or '').lower()
        role = by_id.get(p.get('id')) or (None if p.get('id') else by_ref.get(_ref(p.get('ref'))))  # the id wins over a ref
        if call not in CALLS + ('clear',):
            raise PickError(f"unknown call '{p.get('call')}'")
        if not role:
            raise PickError(f"no role {p.get('ref') or p.get('id')} in the {date} run")
        if role.get('tier') == 'gate' and call in ('apply', 'manual'):
            warn.append(f"#{role['ref']} {role['company']}: failed a hard gate ({'; '.join(role['flags'])}); check eligibility first")
        if role.get('tier') == 'gap' and call in ('apply', 'manual'):
            warn.append(f"#{role['ref']} {role['company']}: critical gap ({(role.get('read') or {}).get('top_gap') or 'see the read'}); check before applying")
        if 'reason' in role and call in ('apply', 'manual') and role['reason'] in ('already_applied', 'in_workflow', 'already_picked'):
            warn.append(f"{role['ref']} {role['company']}: {REASONS[role['reason']].lower()}; rescuing it may mean applying twice")
        if applied and call in ('apply', 'manual') and role.get('reason') != 'already_applied' \
                and triage.already_applied(role['company'], role['title'], role['id'], applied):
            warn.append(f"{role.get('ref')} {role['company']}: {REASONS['already_applied'].lower()}; applying again would be a duplicate")
        if 'reason' in role and call in ('apply', 'manual'):
            prior = role.get('prior') or {}
            if prior.get('gap_type') == 'critical':
                warn.append(f"{role['ref']} {role['company']}: passed {prior.get('gap_date') or prior.get('date')} with a critical gap"
                            f" ({prior.get('top_gap') or 'no gap text'}); its fit score doesn't see that gap")
            if role.get('gate'):
                warn.append(f"{role['ref']} {role['company']}: would fail a hard gate ({role['gate']}); check eligibility first")
        chosen[role['id']] = (role, call, (p.get('note') or '').strip())
    path = os.path.join(queue, f'reviewed-{date}.csv')
    cols, rows = REVIEWED_COLUMNS, []
    if os.path.exists(path):
        with open(path, encoding='utf-8', newline='') as fh:
            rd = csv.DictReader(fh)
            cols, rows = list(rd.fieldnames or REVIEWED_COLUMNS), list(rd)
    index = {r.get('id'): r for r in rows}
    lines, stamp = [], _now()
    read_of = lambda role: reader(role['id']) if reader else role.get('read')
    for rid, (role, call, note) in chosen.items():
        dropped = 'reason' in role
        if dropped:
            where = f"rescued, dropped for: {REASONS.get(role['reason'], role['reason']).lower()}"
            label = f"{role['ref']} {role['company']}: {role['title']} [dropped: {role['reason']}]"
        else:
            where = f"tier {role['tier']}" + (f", was {role['base_tier']}" if role['tier'] == 'cap' else '')
            label = f"#{role['ref']} {role['company']}: {role['title']} [{role['tier']}]"
        mark = f'{PICK_MARK} ({where})' + (f': {note}' if note else '')
        if call == 'clear':
            rec.get('picks', {}).pop(rid, None)
            if rid in index and index[rid].get('notes', '').startswith(PICK_MARK):
                rows.remove(index.pop(rid))
                lines.append(f'cleared {label} (row removed)')
            else:
                lines.append(f'cleared {label}' + (' (stage 2b row kept)' if rid in index else ''))
            continue
        rec.setdefault('picks', {})[rid] = dict(ref=role['ref'], call=call, note=note, at=stamp)
        if rid in index:
            row = index[rid]
            old = row.get('call')
            row['call'] = call
            gap_from_read(row, read_of(role), only_empty=True)
            if note and f'{PICK_MARK}: {note}' not in row.get('notes', ''):
                row['notes'] = '; '.join(filter(None, [row.get('notes', ''), f'{PICK_MARK}: {note}']))
            lines.append(f'{call:<6} {label}' + (f' (was {old})' if old and old != call else ''))
        else:
            row = {c: '' for c in cols}
            row.update(call=call, top_gap=(role.get('gaps') or [''])[0], company=role['company'], title=role['title'],
                       locations=role.get('locations') or role.get('location', ''), salary_max=role.get('salary_max') or '',
                       fit=role.get('fit', ''), notes=mark, url=role['url'], id=rid)
            gap_from_read(row, read_of(role))
            rows.append(row)
            index[rid] = row
            lines.append(f'{call:<6} {label} (new row)')
    vault = os.path.dirname(os.path.dirname(os.path.abspath(queue)))
    moves = folder_moves(vault, [(rid, role['company'], role['title'], call) for rid, (role, call, _) in chosen.items()
                                 if call != 'clear'], dry_run=True)
    if not dry_run:
        with open(path, 'w', encoding='utf-8', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        save(queue, rec)
        build_page(rec, queue)
        moves = folder_moves(vault, [(m['id'], m['company'], m['title'], m['call']) for m in moves])  # after the CSV is safe
    lines += [describe_folder_move(m, dry_run) for m in moves]
    return lines, warn, path


def queued_applied(queue, date, applied):
    """Apply/manual rows of reviewed-<date>.csv already applied to (by id, or company + title) per `applied`, Ctx.applied()."""
    return [r for r in _read_reviewed(queue, date)[2] if r.get('call') in ('apply', 'manual')
            and triage.already_applied(r.get('company', ''), r.get('title', ''), r.get('id', ''), applied)]


def gap_from_read(row, read, only_empty=False):
    """Copy a read's gap_type and top_gap into a reviewed row (only the empty ones with only_empty), and its pay
    into salary_max when the row has none. True if changed."""
    if not read:
        return False
    new = dict(gap_type=read.get('gap_type') or '', top_gap=read.get('top_gap') or '')
    if not row.get('salary_max') and (read.get('pay') or {}).get('max'):
        new['salary_max'] = str(read['pay']['max'])
    if only_empty:
        new = {k: v for k, v in new.items() if v and not row.get(k)}
    row.update(new)
    return bool(new)


# ---------- stage 2b fill-in ----------

def _read_reviewed(queue, date):
    path = os.path.join(queue, f'reviewed-{date}.csv')
    if not os.path.exists(path):
        return path, REVIEWED_COLUMNS, []
    with open(path, encoding='utf-8', newline='') as fh:
        rd = csv.DictReader(fh)
        return path, list(rd.fieldnames or REVIEWED_COLUMNS), list(rd)


MATERIALS = ('summary_variant', 'template_script', 'lead_material')


def todo(queue, date):
    """apply/manual rows in reviewed-<date>.csv still missing part of stage 2b: the gap read (no gap_type) and/or the
    material choices (any of summary_variant, template_script, lead_material). Each with `missing` (['read'],
    ['materials'] or both) and its JD path."""
    state = os.path.join(os.path.dirname(os.path.abspath(queue)), 'state')
    _, _, rows = _read_reviewed(queue, date)
    out = []
    for r in rows:
        if r.get('call') not in ('apply', 'manual'):
            continue
        missing = (['read'] if not r.get('gap_type') else []) + (['materials'] if not all(r.get(c) for c in MATERIALS) else [])
        if missing:
            out.append(dict(id=r['id'], company=r.get('company', ''), title=r.get('title', ''), call=r['call'], missing=missing,
                            jd=jd_path(state, r['id'])))
    return out


def fill(queue, date, rid, values):
    """Set stage 2b columns on one reviewed row. Only STAGE_2B columns; the call is the user's and is not changed.
    Returns warnings (a critical gap on an apply row: the rules say pass, so the user decides)."""
    bad = [k for k in values if k not in STAGE_2B]
    if bad:
        raise PickError(f"not a stage 2b column: {', '.join(bad)} (allowed: {', '.join(STAGE_2B)})")
    if 'gap_type' in values and values['gap_type'] not in GAP_TYPES:
        raise PickError(f"gap_type must be one of {', '.join(GAP_TYPES)}")
    path, cols, rows = _read_reviewed(queue, date)
    row = next((r for r in rows if r.get('id') == rid), None)
    if not row:
        raise PickError(f'no row {rid} in {path}')
    row.update(values)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    if row.get('gap_type') == 'critical' and row.get('call') == 'apply':
        return [f"{row.get('company')}: critical gap ({row.get('top_gap')}); the call stays apply until the user changes it"]
    return []


# ---------- posting reads ----------

def reads_to_do(ctx, date, ids=None):
    """Roles for the posting-reader: with `ids`, those (any role or dropped posting of the run, or a reviewed row);
    else the run's tier A, B and gap roles with no valid read. Each: id, company, title, tier, fit, jd (path or None),
    and the rules score's hints (strength_hits, gap_hits, flags)."""
    from . import reads
    rec, reader = load(ctx.queue, date), reads.Reader(ctx)
    entries = {e['id']: e for e in rec.get('dropped', []) if e.get('id')}
    entries.update({e['id']: e for e in rec.get('roles', [])})  # a scored role wins over a dropped posting
    reviewed = {r['id']: r for r in _read_reviewed(ctx.queue, date)[2] if r.get('id')}
    if ids:
        unknown = [i for i in ids if i not in entries and i not in reviewed]
        if unknown:
            raise PickError(f"not in the {date} run or its reviewed rows: {', '.join(unknown)}")
        pick = [entries.get(i) or dict(reviewed[i], tier='reviewed') for i in ids]
    else:
        pick = [r for r in rec.get('roles', []) if r['tier'] in ('A', 'B', 'gap') and not reader(r['id'])]
    out = []
    for e in pick:
        p = e.get('parts') or {}
        out.append(dict(id=e['id'], company=e.get('company', ''), title=e.get('title', ''),
                        tier=e.get('tier') or 'dropped', fit=e.get('fit'), jd=jd_path(ctx.state, e['id']),
                        strength_hits=p.get('strength_hits', []), gap_hits=[g[0] for g in p.get('gap_hits', [])],
                        flags=e.get('flags') or []))
    return out


def reads_lines(items):
    plain = lambda h: re.fullmatch(r"[\w\s'&-]+", h)
    lines = []
    for t in items:
        lines.append(f"{t['id']}  {t['company']}: {t['title']} [{t['tier']}" + (f", fit {t['fit']}" if t['fit'] is not None else '')
                     + f"]  JD: {t['jd'] or 'not saved'}")
        st = [h for h in t['strength_hits'] if plain(h)]
        hints = [('strengths', ', '.join(st[:8]) + (f' (+{len(t["strength_hits"]) - len(st[:8])} more)' if len(t['strength_hits']) > len(st[:8]) else '')
                  if t['strength_hits'] else ''), ('gaps', ', '.join(t['gap_hits'])), ('flags', '; '.join(t['flags']))]
        if any(v for _, v in hints):
            lines.append('    ' + ' | '.join(f'{k}: {v}' for k, v in hints if v))
    return lines


def reads_briefs(ctx, date, items, per=9):
    """Write posting-reader briefs, at most `per` roles each, to the default scratch paths. Each is self-contained for
    one agent: the resume and gap-rules paths, the roles, the file to save the reply as and the reply format.
    Returns the brief paths."""
    from . import layout
    resume = next((p for p in (os.path.join(d, 'master-resume.md') for d in (ctx.ws, ctx.vault)) if os.path.exists(p)), None)
    if not resume:
        raise PickError(f'no master-resume.md in {ctx.ws} or {ctx.vault}: the posting-reader needs the approved resume')
    rules = next((p for p in (os.path.join(d, 'application-workflow.md') for d in (ctx.ws, ctx.vault)) if os.path.exists(p)), None)
    per = max(1, int(per))
    paths = []
    for n, i in enumerate(range(0, len(items), per), 1):
        key = f'{n:02d}'
        path = layout.scratch(ctx.ws, 'reads-brief', key, date)
        brief = dict(
            kind='posting-reader-brief', date=date, resume_path=os.path.abspath(resume),
            gap_rules_path=os.path.abspath(rules) if rules else None,
            roles=items[i:i + per],
            reply_path=layout.scratch(ctx.ws, 'reads-reply', key, date),
            reply_format='Return only JSON: {"rows": [{"id": "...", "gap_type": "none|minor|major|critical", "top_gap": "...", '
                         '"gap_quote": "...", "strengths": [{"label": "...", "level": "excellent|strong", "resume": "...", '
                         '"posting": "..."}], "needs": ["...", "..."], "concerns": "", "pay": {"min": 150000, "max": 190000, '
                         '"currency": "USD", "quote": "..."} or null}]}, one row per role listed here. '
                         'Apply with: gmh review reads --apply <reply files>.')
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(brief, fh, indent=1, ensure_ascii=False)
            fh.write('\n')
        paths.append(os.path.abspath(path))
    return paths


def apply_reads(ctx, date, file, out=print):
    """Check and cache a posting-reader reply (reads.validate: all or nothing). With no picks yet, score again on the
    run's discovered file (same inputs plus reads; the rerun guard is for a person, and nothing is lost before picks).
    With picks, role numbers must not shift: only fill empty gap_type/top_gap on the date's reviewed rows."""
    from . import reads, score
    files = [file] if isinstance(file, str) else list(file)
    rows, seen = [], {}
    try:
        reader = reads.Reader(ctx)
        known = reads.known_ids(ctx.queue, date)
        for f in files:  # every file is checked before anything is saved
            with open(f, encoding='utf-8') as fh:
                reply = json.load(fh)
            part = reads.validate(reply, known, ctx.state)
            for r in part:
                if r['id'] in seen:
                    raise ValueError(f"{r['id']} is in both {seen[r['id']]} and {f}: nothing saved")
                seen[r['id']] = f
            rows += part
    except (OSError, ValueError) as e:  # ReadError is a ValueError
        raise SystemExit(f'gmh review reads: {e}')
    out(f'Cached {len(reads.save(ctx.state, rows, reader.resume))} read(s) in {os.path.join(ctx.state, "reads")}')
    rec = load(ctx.queue, date)
    if not rec.get('picks'):
        src = os.path.join(ctx.P, (rec.get('discover') or {}).get('file') or '')
        if not os.path.isfile(src):
            raise SystemExit(f'gmh review reads: no discovered file to score again for {date} ({src}); run gmh score')
        ctx.today = datetime.date.fromisoformat(date)  # the run's own day, so the cap windows count from it
        score.run(ctx, src, out=out)
        return
    path, cols, reviewed = _read_reviewed(ctx.queue, date)
    n = sum([gap_from_read(r, reader(r['id']), only_empty=True) for r in reviewed if r.get('id')])
    if n:
        with open(path, 'w', encoding='utf-8', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            w.writerows(reviewed)
    out(f'Picks already exist, so the run was not scored again (role numbers would shift under them). '
        f'Filled gap_type/top_gap (and pay with no posted range) on {n} reviewed row(s); the page shows the reads after the next score.')


# ---------- command ----------

ARTIFACT_URL_RE = re.compile(r'^https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9-]{8,}/?$')


def save_artifact_url(ws, url):
    """Record the user's one standing "Run Review" artifact (config review.artifact_url), so every later run
    republishes to the same private link. Returns the previous URL ('' if none)."""
    url = (url or '').strip()
    if not ARTIFACT_URL_RE.match(url):
        raise PickError(f'not a claude.ai artifact link: {url!r} (expected https://claude.ai/artifact/<id> or '
                        'https://claude.ai/code/artifact/<id>)')
    p = os.path.join(ws, 'config.json')
    with open(p, encoding='utf-8') as fh:
        raw = json.load(fh)
    review = raw.setdefault('review', {})
    old = review.get('artifact_url') or ''
    review['artifact_url'] = url.rstrip('/')
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(raw, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return old


def open_file(path):
    """Open a file in the default app: os.startfile on Windows, `open` on macOS, else the browser module."""
    if sys.platform.startswith('win'):
        os.startfile(path)
    elif sys.platform == 'darwin':
        import subprocess
        subprocess.run(['open', path], check=False)
    else:
        import webbrowser
        webbrowser.open('file://' + path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gmh review', description=__doc__.split('\n')[0])
    ap.add_argument('action', choices=['summary', 'page', 'picks', 'todo', 'fill', 'folders', 'open-check', 'reads', 'applied-check',
                                       'artifact-url', 'drops'])
    ap.add_argument('text', nargs='?', help='picks: the picks text, e.g. "apply 1 4 d3; hold 7"; fill: the role id; '
                                            'artifact-url: the standing Run Review artifact link')
    ap.add_argument('--set', action='append', default=[], metavar='COLUMN=VALUE', help='fill: a stage 2b column (repeatable)')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('--date', help='run date (default: the latest run-*.json)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--json', action='store_true', help='open-check, reads: JSON instead of lines')
    ap.add_argument('--ids', nargs='+', metavar='ID', help='reads: list these postings instead of the unread A/B roles')
    ap.add_argument('--apply', metavar='FILE', nargs='+', help="reads: check and cache posting-reader replies (one or more files)")
    ap.add_argument('--briefs', action='store_true', help='reads: write posting-reader briefs and print their paths')
    ap.add_argument('--per', type=int, default=9, help='reads --briefs: roles per brief (default 9)')
    ap.add_argument('--open', action='store_true', help='page: open it in the default browser')
    a = ap.parse_args(argv)
    if a.action == 'artifact-url':
        ws = os.path.abspath(os.path.expanduser(a.workspace))
        if not a.text:
            from .profile import load_config
            cfg = load_config(os.path.join(ws, 'config.json'))
            print((cfg.get('review') or {}).get('artifact_url') or 'none yet: publish the Run Review page once, then '
                  'gmh review artifact-url <its link>')
            return
        try:
            old = save_artifact_url(ws, a.text)
        except PickError as e:
            sys.exit(f'gmh review artifact-url: {e}')
        print(f"Run Review artifact saved: {a.text.strip().rstrip('/')}" + (f' (was {old})' if old and old != a.text.strip().rstrip('/') else ''))
        return
    from .discover import Ctx
    ctx = Ctx(a.workspace)
    if a.action == 'folders':
        moves = folder_moves(ctx.vault, latest_calls(ctx.queue), a.dry_run, back=False)
        print('\n'.join(describe_folder_move(m, a.dry_run) for m in moves))
        n = sum(m['action'] == 'move' for m in moves)
        print(f"{n} passed role folder(s) {'to move' if a.dry_run else 'moved'} to Workflow/Passed, "
              f"{len(moves) - n} left alone" + (' (dry run, nothing moved)' if a.dry_run else ''))
        return
    date = a.date or latest_date(ctx.queue)
    if a.action == 'applied-check':
        hits = queued_applied(ctx.queue, date, ctx.applied())
        for r in hits:
            print(f"{r['id']}  {r['company']}: {r['title']} [{r['call']}]  already applied (tracker, applied.csv or an Applied folder)")
        print(f"{len(hits)} queued role(s) already applied" + ('; clear them with `gmh review picks "clear <id>"`' if hits else ''))
        sys.exit(1 if hits else 0)
    todo_line = lambda t: f"{t['id']}  {t['company']}: {t['title']} [{t['call']}]  missing: {' and '.join(t['missing'])}  JD: {t['jd'] or 'not saved'}"
    if a.action == 'summary':
        from . import reads
        rec, reader = load(ctx.queue, date), reads.Reader(ctx)  # the cache can be newer than the record
        unread = sum(1 for r in rec.get('roles', []) if r['tier'] in ('A', 'B') and not reader(r['id']))
        print('\n'.join(summary(rec, location_listing(ctx.cfg), unread)))
    elif a.action == 'reads':
        if a.apply:
            apply_reads(ctx, date, a.apply)
            return
        try:
            items = reads_to_do(ctx, date, a.ids)
        except PickError as e:
            sys.exit(f'gmh review reads: {e}')
        if a.briefs:
            if a.per < 1:
                sys.exit('gmh review reads: --per must be at least 1')
            if not items:
                sys.exit('gmh review reads: every A, B and critical-gap role already has a valid read; no briefs written')
            try:
                paths = reads_briefs(ctx, date, items, a.per)
            except PickError as e:
                sys.exit(f'gmh review reads: {e}')
            print(json.dumps(paths, indent=1) if a.json else '\n'.join(paths))
            return
        if a.json:
            print(json.dumps(dict(date=date, roles=items), indent=1, ensure_ascii=False))
        else:
            print('\n'.join(reads_lines(items)) or 'Every A, B and critical-gap role already has a valid read.')
    elif a.action == 'drops':
        rec = load(ctx.queue, date)
        rows = [d for d in rec.get('dropped', []) if not a.text or d.get('reason') == a.text]
        rows.sort(key=lambda d: -(d.get('fit') if d.get('fit') is not None else -1))
        print(f"{len(rows)} dropped role(s){' (' + a.text + ')' if a.text else ''} in the {date} run, best fit first; "
              'rescue one with gmh review picks "apply d<n>"')
        for d in rows:
            fit = f"fit {d['fit']}, would be {d.get('would_be')}" if d.get('fit') is not None else 'not scored'
            print(f"  {d.get('ref', '?'):>6}  {d.get('company')}: {d.get('title')}  [{fit}]  {_places(d.get('location', ''), ' / ')}")
    elif a.action == 'todo':
        left = todo(ctx.queue, date)
        print('\n'.join(todo_line(t) for t in left) or 'Nothing to fill: every apply/manual row has its gap read and material choices.')
    elif a.action == 'open-check':
        from . import opencheck
        from .sources.ats import ADAPTERS
        rows = [r for r in _read_reviewed(ctx.queue, date)[2] if r.get('call') in ('apply', 'manual')]
        cp = os.path.join(ctx.state, 'ats_cache.json')
        cache = json.load(open(cp, encoding='utf-8')) if os.path.exists(cp) else {}
        res, rec = opencheck.open_check(rows, ADAPTERS, cache), load(ctx.queue, date)
        if a.json:
            print(json.dumps(dict(date=date, results=res, picks=opencheck.picks_line(res, rec)), indent=1, ensure_ascii=False))
        else:
            print('\n'.join(opencheck.lines(res, rec)) if res else f'No apply or manual rows in reviewed-{date}.csv.')
    elif a.action == 'fill':
        if not a.text or not a.set:
            sys.exit('usage: gmh review fill <id> --set gap_type=minor --set top_gap="..." ...')
        try:
            vals = dict(x.split('=', 1) for x in a.set)
            for w in fill(ctx.queue, date, a.text, vals):
                print('Warning: ' + w)
        except (PickError, ValueError) as e:
            sys.exit(f'gmh review fill: {e}')
        print(f"Filled {', '.join(vals)} for {a.text}")
    elif a.action == 'page':
        page = build_page(load(ctx.queue, date), ctx.queue, location_listing(ctx.cfg))
        print(f'{page} ({page_size(page)})')
        print('standing copy:', standing_copy(page, ctx.ws))
        if a.open:
            open_file(page)
    else:
        try:
            if not a.text:
                sys.exit('give picks text, e.g. gmh review picks "apply 1 4; hold 7"')
            from . import reads
            lines, warn, path = apply_picks(ctx.queue, date, parse_picks(a.text), a.dry_run, reads.Reader(ctx), ctx.applied())
        except PickError as e:
            sys.exit(f'gmh review picks: {e}')
        print('\n'.join(lines))
        for w in warn:
            print('Warning: ' + w)
        print(('Would write ' if a.dry_run else 'Wrote ') + path)
        if not a.dry_run:
            left = todo(ctx.queue, date)
            if left:
                print('Stage 2b to fill now (read: gmh review reads --ids <id> then --apply; materials: gmh review fill <id> --set ...):')
                for t in left:
                    print('  ' + todo_line(t))

    page = os.path.join(ctx.queue, f'review-{date}.html')
    if a.action in ('picks', 'fill') and not a.dry_run and os.path.exists(page):
        standing_copy(page, ctx.ws)  # picks show on the standing page after its next publish

if __name__ == '__main__':
    main()
