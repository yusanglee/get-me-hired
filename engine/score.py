"""Stage 2a: rules-based triage scoring of discovered roles, using the workspace's pack.

Ported from the original pipeline's score.py; the PM-only signal tables now live in the pack and
`packs.score` applies them (same formula). Reads the latest queue/discovered-*.csv and each JD in
state/jd/, drops roles already applied to (tracker.csv, legacy applied.csv, by id or job_key), in Workflow, or called
pass, apply or manual in an earlier reviewed-<date>.csv (holds are scored again, flagged 'held <date>'),
runs the hard gates (eligibility and language, engine/gates.py; posting links that imitate an ATS
or job-board domain, engine/hosts.py: a FAIL gets tier 'gate', unscored, with the reason in flags),
scores the rest against the user's resume text, adds the first-choice location bonus (config
locations.top and top_bonus; the role's `top_locations` go to the run record), applies the office-day
veto for hybrid-only metros, the per-company cap and employer limits, and writes queue/scored-<date>.csv, best first.
A role with a valid cached read (engine/reads.py) follows config scoring.gap_rules: a critical gap gives it tier 'gap'
(out of review and the cap, listed after the scored rows and before the gate rows), a major gap holds an A to B.
Roles marked review=yes go to stage 2b (Claude reads the JD and makes the call). It also adds every
scored and dropped role, with the reason for its tier, to queue/run-<date>.json, writes the review page
queue/review-<date>.html and prints a run summary (engine/runrecord.py, `gmh review`).

    python3 -m engine.score --workspace <ws> [--discovered <csv>]

Resume text ("evidence"): <ws>/master-resume.md, else <vault>/master-resume.md, else the
workspace's resume templates.
"""
import argparse, collections, csv, datetime, glob, os, re, sys
from . import gates, hosts, locations, packs, pay, reads, runrecord, tracker, triage
from .discover import Ctx, STAGES, workflow_folders
from .job_key import make_key

COLUMNS = ['tier', 'fit', 'ats', 'company', 'title', 'locations', 'salary_max', 'gaps', 'flags', 'review', 'url', 'id']
NUM = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
DAYS_RE = re.compile(r'\b(\d|one|two|three|four|five)\s+days\s+(?:a|per|each)\s+week', re.I)


def evidence(ctx):
    for d in (ctx.ws, ctx.vault):
        p = os.path.join(d, 'master-resume.md')
        if os.path.exists(p):
            return open(p, encoding='utf-8').read()
    from .setup import resume_text
    return resume_text(ctx.ws)


def office_veto(ctx, row, jd):
    """For a role whose only location is a hybrid_ok metro: 'onsite' (over the office-day limit),
    'unstated' (no office policy in the posting), or None."""
    m = next((m for m in ctx.cfg['locations']['metros'] if m['name'] == row['locations']), None)
    if not m or m.get('policy') != 'hybrid_ok':
        return None
    low = jd.lower()
    days = [int(d) if d.isdigit() else NUM[d.lower()] for d in DAYS_RE.findall(jd)]
    max_days = m.get('max_office_days', 3)
    if (days and max(days) > max_days) or ('#li-onsite' in low and 'hybrid' not in low):
        return 'onsite'
    if not days and not re.search(r'hybrid|remote', low):
        return 'unstated'
    return None


def gate_location(ctx, prof, location):
    """The posting's location text for gates.check, or None when Canada is not in play (no CA among the remote
    countries, no floor_cad, and a profile with no Canada answers): then the gates read the posting exactly as before."""
    if prof is None or not (gates.canada_in_play(prof) or pay.canada_on(ctx.cfg)):
        return None
    return location or None


def add_location_bonus(cfg, r):
    """Add config locations.top_bonus to fit when the role matches a first-choice location; sets r['top_locations']."""
    pts, top = locations.top_bonus(r.get('locations', ''), cfg)
    r['top_locations'] = top
    if pts:
        r['fit'] = max(0, min(100, r['fit'] + pts))
        if r.get('parts') is not None:
            r['parts']['location'] = pts


def _split(s):
    return [x.strip() for x in (s or '').split(';') if x.strip()]


def _within(date, today, days):
    try:
        return (today - datetime.date.fromisoformat(date[:10])).days <= days
    except (TypeError, ValueError):
        return False


def prior_applications(ctx, picked=()):
    """Lowercased company -> roles that count toward the company cap (config per_company: max_applications
    roles per window_days, rolling). Applications count by date_applied in tracker.csv and legacy applied.csv,
    so one made before the window no longer counts. Roles prepared in 02-Ready to Apply, and Applied or
    Interviewing folders with no applied record, count by folder date. `picked` (rows called apply or manual in an
    earlier review, not yet applied) count too. A role counts once (by job_key)."""
    window = ctx.cfg['per_company'].get('window_days', 90)
    per, logged = {}, set()
    for p in [tracker.path_of(ctx.ws), *ctx.legacy_applied()]:
        for r in tracker.read(p):
            if not (r.get('company') and r.get('title')):
                continue
            key = make_key(r['company'], r['title'])
            logged.update(filter(None, (key, r.get('job_key'))))
            if _within(r.get('date_applied'), ctx.today, window):
                per.setdefault(r['company'].lower(), set()).add(key)
    for r in picked:
        per.setdefault(r['company'].lower(), set()).add(make_key(r['company'], r['title']))
    for date, company, title in workflow_folders(ctx.vault, ['02-Ready to Apply', '03-Applied', '04-Interviewing']):
        key = make_key(company, title)
        if key not in logged and _within(date, ctx.today, window):
            per.setdefault(company.lower(), set()).add(key)
    return {co: len(keys) for co, keys in per.items()}


def employer_limits(ctx, rows):
    """Employer-imposed caps (config company_limits, e.g. OpenAI 5 per 180 days), counted from
    tracker.csv and legacy applied.csv; rows past the limit get tier 'cap'."""
    lim = {k: v for k, v in (ctx.cfg.get('company_limits') or {}).items() if not k.startswith('_')}
    if not lim:
        return
    log = {}
    for p in [tracker.path_of(ctx.ws), *ctx.legacy_applied()]:
        for a in tracker.read(p):
            if a.get('company') and a.get('title'):
                log.setdefault(a.get('job_key') or make_key(a['company'], a['title']), a)
    for co, L in lim.items():
        used = sum(1 for a in log.values() if a['company'].lower() == co and _within(a.get('date_applied'), ctx.today, L['window_days']))
        left = L['max_applications'] - used
        for r in rows:
            if r['company'].lower() != co:
                continue
            note = f"{r['company']} limit: {used} of {L['max_applications']} used in {L['window_days']} days"
            r['flags'] = '; '.join(filter(None, [r.get('flags', ''), note]))
            if left <= 0 and r.get('tier') in ('A', 'B', 'C+'):
                r['tier'] = 'cap'


def gates_on(ctx):
    return (ctx.cfg.get('gates') or {}).get('enabled', True)


def gate_profile(ctx, out=print):
    """The profile the hard gates read, or None when gates are off (config gates.enabled) or there is no profile."""
    if not gates_on(ctx):
        return None
    from .profile import load_profile
    p = os.path.join(ctx.ws, 'profile.yaml')
    if not os.path.exists(p):
        out('Note: no profile.yaml, so the eligibility and language gates were skipped.')
        return None
    return load_profile(p)


GAP_RANK = {'none': 0, 'minor': 1, 'major': 2, 'critical': 3}


def prior_calls(ctx):
    """{id or job_key: {call, date, gap_type, top_gap, notes, gap_date}} from reviewed-<date>.csv files before
    today. The latest call wins; gap_type and top_gap are the worst gap any review recorded (a role passed
    for a critical gap, then passed again for the company cap, keeps its critical gap). Today's file is left
    out, so scoring again after today's picks doesn't drop them."""
    out = {}
    today = ctx.today.isoformat()
    for p in sorted(glob.glob(os.path.join(ctx.queue, 'reviewed-*.csv'))):
        date = os.path.basename(p)[len('reviewed-'):-len('.csv')][:10]
        if date >= today:
            continue
        with open(p, encoding='utf-8', newline='') as fh:
            for r in csv.DictReader(fh):
                call = (r.get('call') or '').strip().lower()
                if not (call and r.get('company') and r.get('title')):
                    continue
                gap = (r.get('gap_type') or '').strip().lower()
                for k in (r.get('id'), make_key(r['company'], r['title'])):
                    if not k:
                        continue
                    prev = out.get(k) or {}
                    c = dict(prev, call=call, date=date, notes=(r.get('notes') or '').strip())
                    if GAP_RANK.get(gap, -1) >= GAP_RANK.get(prev.get('gap_type'), -1) and gap in GAP_RANK:
                        c.update(gap_type=gap, top_gap=(r.get('top_gap') or '').strip(), gap_date=date)
                    out[k] = c
    return out


def read_pay(r, rd):
    """Fill a row with no posted range from its posting read's pay (reads.check_pay checked it against the posting).
    The parser's range always wins. Sets salary_min/max, salary_source 'read' ('read CAD') and r['_currency'];
    True when it filled the row."""
    p = (rd or {}).get('pay') or {}
    if r.get('salary_max') or not p.get('max'):
        return False
    r.update(salary_min=p.get('min') or '', salary_max=p['max'], _currency=p.get('currency') or 'USD',
             salary_source='read' + (' CAD' if p.get('currency') == 'CAD' else ''))
    return True


def call_of(calls, r):
    return calls.get(r['id']) or calls.get(make_key(r['company'], r['title'])) or {}


def run(ctx, src=None, out=print):
    src = src or (sorted(glob.glob(os.path.join(ctx.queue, 'discovered-*.csv'))) or [None])[-1]
    if not src:
        raise SystemExit(f'no discovered-*.csv in {ctx.queue}: run discover first')
    if not ctx.pack.get('approved'):
        out('Note: pack.json is a draft (not approved); scores use its unreviewed strengths and gaps.')
    ev = evidence(ctx)
    applied, known = ctx.applied(), ctx.known()
    calls = prior_calls(ctx)
    prof = gate_profile(ctx, out)
    rows, seen, dropped, gated, picked, log = [], set(), [], [], [], runrecord.Drops()
    for r in csv.DictReader(open(src, encoding='utf-8', newline='')):
        key = (r['company'], re.sub(r'\W+', ' ', r['title'].lower()).strip())
        c = call_of(calls, r)
        if triage.already_applied(r['company'], r['title'], r['id'], applied):
            dropped.append(f"{r['company']}: {r['title']}")
            log.add('score', 'already_applied', r['company'], r)
        elif r['already_in_workflow'] != 'no' or triage.already_applied(r['company'], r['title'], r['id'], known):
            log.add('score', 'in_workflow', r['company'], r)
        elif c.get('call') == 'pass':
            log.add('score', 'passed', r['company'], r, detail=f"passed {c['date']}",
                    prior={k: c[k] for k in ('date', 'gap_type', 'top_gap', 'notes', 'gap_date') if c.get(k)})
        elif c.get('call') in ('apply', 'manual'):  # picked, still being prepared or applied: not a new role
            picked.append(r)
            log.add('score', 'already_picked', r['company'], r, detail=f"picked {c['call']} {c['date']}")
        elif key in seen:  # same role posted in several locations counts once
            log.add('score', 'duplicate', r['company'], r)
        else:
            seen.add(key)
            rows.append(r)
    kept, jds = [], {}
    for r in rows:
        with open(os.path.join(ctx.state, 'jd', r['id'] + '.txt'), encoding='utf-8') as fh:
            jd = jds[r['id']] = fh.read()
        kind, imitates = hosts.check(r.get('url'))
        if kind == 'lookalike' and gates_on(ctx):  # never open or fill a link that imitates an ATS or board
            r.update(tier='gate', fit=0, ats=0, gaps='', review='no',
                     flags=f"gate FAIL: posting link imitates {imitates} ({r.get('url')})")
            gated.append(r)
            continue
        if prof is not None:
            res = gates.check(jd, prof, location=gate_location(ctx, prof, r.get('location_raw') or r.get('locations')))
            if gates.verdict(res) == gates.FAIL:  # hard stop: not scored, but listed with the posting's words
                r.update(tier='gate', fit=0, ats=0, gaps='', review='no', flags=gates.summary(res))
                gated.append(r)
                continue
            r['gate_flags'] = gates.summary(res)
        kept.append(r)
    rows, kept, rds = kept, [], {}
    for r in rows:  # a read's pay fills a missing range before scoring, so level and flags see it
        rd = rds[r['id']] = reads.valid(ctx.state, r['id'], ev, jds[r['id']])
        if read_pay(r, rd) and pay.below_floor(int(r['salary_max']), r['_currency'], ctx.cfg):
            log.add('score', 'salary', r['company'], r, detail=f"pay from the posting read: {(rd.get('pay') or {}).get('quote', '')}"[:200])
            continue
        kept.append(r)
    rows = kept
    for r in rows:
        jd = jds[r['id']]
        r.update(packs.score(ctx.pack, r['title'], jd, ev, r['salary_max'], parts=True))
        add_location_bonus(ctx.cfg, r)
        if r.get('gate_flags'):
            r['flags'] = '; '.join(filter(None, [r['flags'], r.pop('gate_flags')]))
        c = call_of(calls, r)
        if c.get('call') == 'hold':
            r['flags'] = '; '.join(filter(None, [r['flags'], f"held {c['date']}"]))
        extra, r['over_bar'] = triage.over_bar(jd, prof, ctx.pack)
        if extra:
            years = [f for f in extra if f.startswith('asks ') and 'years' in f]
            kept_flags = [f for f in _split(r['flags']) if not (years and re.fullmatch(r'\d+\+ years asked', f))]
            r['flags'] = '; '.join(kept_flags + extra)
        site = office_veto(ctx, r, jd)
        if site == 'onsite':
            r['fit'] = min(r['fit'], 0)
            r['flags'] = '; '.join(filter(None, [r['flags'], f"{r['locations']} on-site, over office-day limit"]))
        elif site == 'unstated':
            r['flags'] = '; '.join(filter(None, [r['flags'], f"{r['locations']} office policy unstated"]))
    rules = triage.gap_rules(ctx.cfg['scoring'])
    for r in rows:
        rd = rds[r['id']]
        if rd:
            triage.apply_read(r, reads.public(rd), rules)
    gapped = [r for r in rows if r.get('tier') == 'gap']  # critical gap: out before tiers, so no cap slot
    rows = [r for r in rows if r.get('tier') != 'gap']
    rows.sort(key=lambda r: (-r['fit'], -r['ats']))
    gapped.sort(key=lambda r: (-r['fit'], -r['ats']))
    prior = prior_applications(ctx, picked)
    triage.assign_tiers(rows, ctx.cfg['scoring'], ctx.cfg['per_company']['max_applications'], prior)
    employer_limits(ctx, rows + gapped)
    rows += gapped + gated
    path = os.path.join(os.path.dirname(src), os.path.basename(src).replace('discovered-', 'scored-'))
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    out(f"Tiers: {dict(collections.Counter(r['tier'] for r in rows))} -> {path}")
    if dropped:
        out(f'Already applied (by id or company+title), dropped: {len(set(dropped))}: ' + '; '.join(sorted(set(dropped))))
    if gated:
        out(f'Hard gates, not scored (tier "gate"): {len(gated)}: ' +
            '; '.join(f"{r['company']}: {r['title']} [{r['flags']}]" for r in gated))
    runrecord.save_score(ctx, src, rows, log, prior, out)
    return path, rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.score', description=__doc__.split('\n')[0])
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('--discovered', help='discovered-*.csv to score (default: the latest in the queue)')
    ap.add_argument('--force', action='store_true', help='score again even though this scoring is already up to date')
    a = ap.parse_args(argv)
    try:
        ctx = Ctx(a.workspace)
    except packs.PackError as e:
        sys.exit(str(e))
    src = a.discovered or (sorted(glob.glob(os.path.join(ctx.queue, 'discovered-*.csv'))) or [None])[-1]
    if src:  # a scored file at least as new as its discovered file means nothing changed since; a newer discover is what score follows
        out = os.path.join(os.path.dirname(src), os.path.basename(src).replace('discovered-', 'scored-'))
        if out != src and os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src) and \
                not runrecord.rerun_ok('score', runrecord.date_of(src), os.path.dirname(os.path.abspath(src)), out, a.force):
            sys.exit(3)
    run(ctx, src)


if __name__ == '__main__':
    main()
