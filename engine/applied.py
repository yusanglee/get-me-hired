"""Stage 7: record an application after the user approved it and the ATS showed its confirmation.

Ported from the original pipeline's mark_applied.py (Phase 7): adds the role to tracker.csv (the source of
truth) and moves its folder from Workflow/02-Ready to Apply to 03-Applied. Run only for an application the
user approved and saw confirmed. Safe to repeat: a role already in the tracker is left as it is. A role whose
fill record (`gmh fills`) says the form isn't finished is refused.

    python3 -m engine.applied <id> [<id> ...] --workspace <ws> [--date YYYY-MM-DD]
"""
import argparse, csv, datetime, glob, json, os, shutil
from . import fills, layout, tracker
from .locfmt import role_location, run_locations
from .profile import load_config


def mark(ws, ids, date):
    vault = layout.vault(ws)
    P = os.path.join(vault, 'Pipeline')
    specs = {}
    for p in glob.glob(os.path.join(P, 'specs', '*.json')):
        with open(p, encoding='utf-8') as fh:
            s = json.load(fh)
        specs[s['id']] = s
    urls = {}
    for p in sorted(glob.glob(os.path.join(P, 'queue', 'reviewed-*.csv'))):
        with open(p, encoding='utf-8', newline='') as fh:
            urls.update({r['id']: r.get('url', '') for r in csv.DictReader(fh)})
    path = tracker.path_of(ws)
    tracker.init(path)
    rows, out = tracker.read(path), []
    runs = run_locations(P)
    for i in ids:
        why = fills.unfinished(ws, i)
        if why:
            out.append(why)
            continue
        s = specs.get(i)
        if not s:
            out.append(f'{i}: no spec found (was it tailored?); nothing recorded')
            continue
        src = os.path.join(vault, 'Workflow', '02-Ready to Apply', s['folder'])
        dst = os.path.join(vault, 'Workflow', '03-Applied', s['folder'])
        if os.path.isdir(src) and not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
        res = tracker.upsert(rows, {'company': s['company'], 'title': s['title'], 'id': i, 'date_applied': date,
                                    'status': 'applied', 'status_date': date, 'source': 'pipeline', 'url': urls.get(i, ''),
                                    'folder': os.path.relpath(dst, vault).replace(os.sep, '/'), 'location': role_location(P, i, runs)})
        out.append(f"{'applied' if res == 'added' else 'already recorded'}: {s['company']} | {s['title']}")
    tracker.write(path, rows)
    return out


QUEUED = ('apply', 'manual')


def queues(ws):
    """Each day's apply queue, oldest first: (date, ids queued apply or manual in reviewed-<date>.csv, how many of
    them are in the tracker). A queued role counts as done once it is in the tracker."""
    in_tracker = {r.get('id') for r in tracker.read(tracker.path_of(ws))}
    out = []
    for p in sorted(glob.glob(os.path.join(layout.queue(ws), 'reviewed-*.csv'))):
        with open(p, encoding='utf-8', newline='') as fh:
            ids = [r.get('id') for r in csv.DictReader(fh) if (r.get('call') or '').strip().lower() in QUEUED]
        if ids:
            out.append((os.path.basename(p)[len('reviewed-'):-len('.csv')], ids, sum(i in in_tracker for i in ids)))
    return out


def queue_status(ws, ids):
    """Where each day's apply queue stands, for the reviewed-<date>.csv files that queued any of `ids`. When a
    day's queue is all done, say so and suggest LinkedIn follow-up; it is never started from here (apply to all
    first, then follow up)."""
    out = []
    for date, queued, done in queues(ws):
        if not any(i in ids for i in queued):
            continue
        if done == len(queued):
            out.append(f'All {len(queued)} roles queued on {date} are marked applied. Next, when you want it: '
                       'LinkedIn follow-up (/get-me-hired:linkedin-followup; gmh linkedin queue lists the companies).')
        else:
            out.append(f'{date} queue: {done} of {len(queued)} marked applied, {len(queued) - done} to go. '
                       'LinkedIn follow-up is suggested once all are in (mark a closed or dropped role pass with gmh review picks).')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.applied', description=__doc__.split('\n')[0])
    ap.add_argument('ids', nargs='+')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    a = ap.parse_args(argv)
    ws = os.path.expanduser(a.workspace)
    for line in mark(ws, a.ids, a.date) + queue_status(ws, a.ids):
        print(line)


if __name__ == '__main__':
    main()
