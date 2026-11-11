"""Where today stands, for the one day session (the today skill, /get-me-hired:today): what has run, what is waiting, and the next step.

    python3 -m engine.today --workspace <ws> [--json] [--date YYYY-MM-DD]

Read-only apart from refreshing <workspace>/HOME.md (`gmh home`). Everything comes from the files (run record,
queue CSVs, reads cache, fill records, tracker, session summaries), so a new session can pick the day up after a
crash, a compaction or a closed window. The suggested next step is a suggestion: the user decides.
"""
import argparse, csv, datetime, json, os, sys

from . import fills, home, layout, runrecord, tracker
from .profile import load_config

QUEUED = ('apply', 'manual')

# The steps of the day, in order (skills/today/SKILL.md uses the same names, in brackets).
STEPS = {
    'check': 'Check the setup (gmh setup check)',
    'find': "Find and score today's roles (discover runs 15 minutes or more, in the background)",
    'score': "Score today's found roles",
    'reads': 'Read the A and B roles against your resume (posting-reader agents)',
    'pick': 'Review the page and pick roles',
    'prepare': 'Prepare the picked roles: reads, resume choices, forms, answers, drafts (you approve each)',
    'fill': 'Fill forms in batches, A first (form-filler agent); stops at Submit',
    'submit': 'Approve the filled batch; submit the ones you OK; record them',
    'earlier': "Finish an earlier day's queue",
    'linkedin': 'LinkedIn follow-up (optional)',
    'wrap': 'Wrap up the day',
}


def _exists(*parts):
    return os.path.exists(os.path.join(*parts))


def _reviewed(queue, date):
    p = os.path.join(queue, f'reviewed-{date}.csv')
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def _unread(ws, date):
    """A/B roles of the day's run with no valid read; None when that can't be worked out (no pack, no run)."""
    try:
        from .discover import Ctx
        from . import reads
        ctx = Ctx(ws)
        rec = runrecord.load(ctx.queue, date)
        reader = reads.Reader(ctx)
        return sum(1 for r in rec.get('roles', []) if r.get('tier') in ('A', 'B') and not reader(r['id']))
    except Exception:  # a status read must never stop the day
        return None


def queue_counts(ws, rows, applied_ids, fill_recs):
    """Where each queued role of one day stands. Buckets, in order: applied, to_prepare (read or materials missing),
    manual (a by-hand ATS, not applied), to_fill (prepared, no fill record), needs_user, blocked, ready (filled,
    waiting for the user's submit OK). Each bucket lists ids."""
    out = {k: [] for k in ('applied', 'to_prepare', 'manual', 'to_fill', 'needs_user', 'blocked', 'ready')}
    for r in rows:
        call = (r.get('call') or '').strip().lower()
        if call not in QUEUED:
            continue
        rid = r.get('id') or ''
        if rid in applied_ids:
            out['applied'].append(rid)
        elif not r.get('gap_type') or not all(r.get(c) for c in runrecord.MATERIALS):
            out['to_prepare'].append(rid)
        elif call == 'manual':
            out['manual'].append(rid)
        else:
            st = (fill_recs.get(rid) or {}).get('status')
            out[{'ready': 'ready', 'needs_user': 'needs_user', 'blocked': 'blocked'}.get(st, 'to_fill')].append(rid)
    return out


def next_step(d):
    """The suggested next step for the day, from the status."""
    t = d['run']
    if not t['discovered']:
        return 'find'
    if not t['scored']:
        return 'score'
    if t['unread']:
        return 'reads'
    if not t['picked']:
        return 'pick'
    q = d['queue'] or {}
    if q.get('to_prepare'):
        return 'prepare'
    if q.get('to_fill') or q.get('blocked'):
        return 'fill'
    if q.get('ready') or q.get('needs_user'):
        return 'submit'
    if d['earlier']:
        return 'earlier'
    if d['linkedin_waiting']:
        return 'linkedin'
    return 'wrap'


def _linkedin_waiting(ws, cfg, date):
    try:
        from . import linkedin
        rows = tracker.read(tracker.path_of(ws))
        days = ((cfg.get('linkedin') or {}).get('gmail_followup_days')) or 7
        return linkedin.interest_queue(rows, {}, 1, None, date, days)[1]
    except Exception:
        return 0


def gmail_status(ws, today):
    """When Gmail sync last applied anything (state/gmail/sync.json `updated`, UTC), and whether that was today
    (local date). {'last': None, 'today': False} when it has never run."""
    p = os.path.join(ws, 'state', 'gmail', 'sync.json')
    try:
        with open(p, encoding='utf-8') as fh:
            v = json.load(fh).get('updated')
        dt = datetime.datetime.fromisoformat(v)
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return {'last': dt.isoformat(timespec='minutes'), 'today': dt.date() == today}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'last': None, 'today': False}


def data(ws, today=None):
    ws = os.path.abspath(os.path.expanduser(ws))
    today = today or datetime.date.today()
    date = today.isoformat()
    cfg_p = os.path.join(ws, 'config.json')
    cfg = load_config(cfg_p) if os.path.exists(cfg_p) else {}
    queue = layout.queue(ws, cfg)
    rec = runrecord.load(queue, date) if _exists(queue, f'run-{date}.json') else {}
    rows = _reviewed(queue, date)
    run = {
        'discovered': _exists(queue, f'discovered-{date}.csv'),
        'scored': _exists(queue, f'scored-{date}.csv'),
        'scored_roles': len(rec.get('roles') or []),
        'tiers': {k: sum(1 for r in rec.get('roles') or [] if r.get('tier') == k) for k in ('A', 'B', 'gap')},
        'unread': _unread(ws, date) if _exists(queue, f'run-{date}.json') else None,
        'picked': rows is not None or bool(rec.get('picks')),
        'discover_partial': _exists(queue, f'discovered-{date}.csv.part'),
    }
    applied_ids = {r.get('id') for r in tracker.read(tracker.path_of(ws)) if r.get('id')}
    fill_recs = fills.load_all(ws)
    q = queue_counts(ws, rows, applied_ids, fill_recs) if rows is not None else None
    from . import applied
    earlier = [{'date': dd, 'left': len(ids) - done, 'queued': len(ids)}
               for dd, ids, done in applied.queues(ws) if dd < date and done < len(ids)]
    from . import materials
    d = {'workspace': ws, 'today': date, 'run': run, 'queue': q, 'earlier': earlier,
         'gmail': gmail_status(ws, today), 'materials_pending': materials.pending_count(ws),
         'bios_unapproved': materials.sent_bio_count(ws),
         'linkedin_waiting': _linkedin_waiting(ws, cfg, date),
         'waiting': home.waiting(home.recent(ws, today)),
         'fills': {k: v for k, v in fill_recs.items() if q and any(k in ids for ids in q.values())},
         'links': [{'label': l, 'target': t, 'note': n} for l, t, n in home.links(ws, cfg, today)]}
    step = next_step(d)
    d['next'] = {'step': step, 'say': STEPS[step]}
    return d


def lines(d):
    r, q = d['run'], d['queue']
    yes = lambda b: 'done' if b else 'not yet'
    g = d['gmail']
    L = [f"Today ({d['today']})",
         '- Gmail sync: ' + ('done today' if g['today'] else 'not yet today') + (f" (last applied {g['last'][:16].replace('T', ' ')})"
                                                                              if g['last'] else ' (never run: /get-me-hired:import-history first)'),
         f"- Find: {yes(r['discovered'])}" + (' (an earlier run stopped mid-write; run it again)' if r['discover_partial'] else ''),
         f"- Score: {yes(r['scored'])}" + (f" ({r['scored_roles']} roles: {r['tiers']['A']} A, {r['tiers']['B']} B, "
                                           f"{r['tiers']['gap']} critical gap)" if r['scored'] else ''),
         f"- Reads: " + ('-' if r['unread'] is None else ('all A and B roles read' if not r['unread'] else f"{r['unread']} A/B roles not read yet")),
         f"- Picks: {yes(r['picked'])}"]
    if q is not None:
        n = sum(len(v) for v in q.values())
        L.append(f"- Queue: {n} roles: {len(q['applied'])} applied, {len(q['to_prepare'])} to prepare, "
                 f"{len(q['to_fill'])} to fill, {len(q['ready'])} filled and waiting for your OK, "
                 f"{len(q['needs_user'])} need you, {len(q['blocked'])} blocked, {len(q['manual'])} manual (you apply)")
        for k in ('needs_user', 'blocked'):
            for rid in q[k]:
                rec = d['fills'].get(rid) or {}
                L.append(f"    {rid}: {k.replace('_', ' ')}: " + ('; '.join(rec.get('left') or []) or rec.get('note') or ''))
    for e in d['earlier']:
        L.append(f"- Earlier: {e['left']} of {e['queued']} roles queued on {e['date']} not applied yet")
    if d['linkedin_waiting']:
        L.append(f"- LinkedIn follow-up: {d['linkedin_waiting']} compan(ies) waiting (optional)")
    if d.get('bios_unapproved'):
        L.append(f"- Resume bios: {d['bios_unapproved']} used on built resumes but not approved (one list: gmh materials bios)")
    if d.get('materials_pending'):
        L.append(f"- Resume updates: {d['materials_pending']} proposal(s) waiting for your OK (/get-me-hired:materials)")
    for w in d['waiting']:
        L.append(f"- Left by a session ({w['task']}, {w['date']}): {w['item']}")
    L += ['', f"Next: {d['next']['say']}  [step: {d['next']['step']}]"]
    return L


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gmh today', description=__doc__.split('\n')[0])
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--date', help='YYYY-MM-DD (default: today)')
    a = ap.parse_args(argv)
    ws = os.path.abspath(os.path.expanduser(a.workspace))
    if not os.path.isdir(ws):
        sys.exit(f'no workspace folder at {ws}')
    day = datetime.date.fromisoformat(a.date) if a.date else None
    d = data(ws, day)
    try:
        home.write(ws, day)
    except OSError:
        pass
    print(json.dumps(d, indent=1, ensure_ascii=False) if a.json else '\n'.join(lines(d)))


if __name__ == '__main__':
    main()
