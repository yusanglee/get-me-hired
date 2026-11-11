"""Where each application form stands after the form-filler agent: one small record per role.

    python3 -m engine.fills set <id> --status ready|needs_user|blocked [--left "..."]... [--note "..."] --workspace <ws>
    python3 -m engine.fills show [--date D] [--json] [<id> ...] --workspace <ws>

Records live in <vault>/Pipeline/state/fills/<id>.json. The day session writes one from the form-filler's reply
(`ready`: every field done, stopped at Submit; `needs_user`: something is left for the user, listed in `left`;
`blocked`: the form couldn't be filled) and sets `ready` once the user has finished what was left. `gmh applied`
refuses a role whose record says the form isn't finished.
"""
import argparse, csv, datetime, glob, json, os, re, sys

from . import layout

STATUSES = ('ready', 'needs_user', 'blocked')
ID_RE = re.compile(r'^[\w.-]{1,120}$')


def fills_dir(ws):
    return os.path.join(layout.pipeline(ws), 'state', 'fills')


def path_of(ws, rid):
    if not ID_RE.match(rid or ''):
        raise ValueError(f'not a role id: {rid!r}')
    return os.path.join(fills_dir(ws), rid + '.json')


def load(ws, rid):
    try:
        with open(path_of(ws, rid), encoding='utf-8') as fh:
            rec = json.load(fh)
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def load_all(ws):
    out = {}
    for p in glob.glob(os.path.join(fills_dir(ws), '*.json')):
        rid = os.path.basename(p)[:-len('.json')]
        rec = load(ws, rid)
        if rec:
            out[rid] = rec
    return out


def record(ws, rid, status, left=(), note='', now=None):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    left = [x.strip() for x in left if x and x.strip()]
    if status == 'needs_user' and not left:
        raise ValueError('needs_user: say what is left for the user (--left "...", once per item)')
    rec = {'id': rid, 'status': status, 'left': left if status != 'ready' else [], 'note': note.strip(),
           'at': (now or datetime.datetime.now()).isoformat(timespec='minutes')}
    os.makedirs(fills_dir(ws), exist_ok=True)
    with open(path_of(ws, rid), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(rec, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return rec


def unfinished(ws, rid):
    """Why `rid` can't be recorded as applied yet, or None. No record (filled by hand, or a manual-ATS role) is not
    a reason: only a record that says the form isn't done."""
    rec = load(ws, rid)
    if not rec or rec.get('status') == 'ready':
        return None
    left = '; '.join(rec.get('left') or []) or rec.get('note') or 'no detail'
    return (f"{rid}: the form isn't finished ({rec.get('status')}: {left}). Once it is, run "
            f"`gmh fills set {rid} --status ready`; nothing recorded")


def line(rec):
    left = ('; left: ' + '; '.join(rec['left'])) if rec.get('left') else ''
    note = f" ({rec['note']})" if rec.get('note') else ''
    return f"{rec['id']}  {rec['status']}{left}{note}  [{rec.get('at', '')}]"


def names(ws, date=None):
    """{role id: (company, title)} from the reviewed CSVs (the given day's first, then newest first), then the run
    records' roles. Whatever can't be found is simply missing."""
    q = layout.queue(ws)
    files = sorted(glob.glob(os.path.join(q, 'reviewed-*.csv')), reverse=True)
    first = os.path.join(q, f'reviewed-{date}.csv') if date else None
    if first in files:
        files.remove(first)
        files.insert(0, first)
    out = {}
    for p in files:
        try:
            with open(p, encoding='utf-8', newline='') as fh:
                for r in csv.DictReader(fh):
                    if r.get('id') and r['id'] not in out:
                        out[r['id']] = (r.get('company') or '', r.get('title') or '')
        except (OSError, csv.Error):
            continue
    for p in sorted(glob.glob(os.path.join(q, 'run-*.json')), reverse=True):
        try:
            with open(p, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        for r in (rec.get('roles') or []) + (rec.get('dropped') or []):
            if isinstance(r, dict) and r.get('id') and r['id'] not in out:
                out[r['id']] = (r.get('company') or '', r.get('title') or '')
    return out


def rows(ws, ids=None, date=None):
    """One dict per role: id, company, title, status, left (a string: what is left, else the note)."""
    recs, nm = load_all(ws), names(ws, date)
    out = []
    for rid in (ids or sorted(recs)):
        rec = recs.get(rid)
        c, t = nm.get(rid, ('', ''))
        out.append(dict(id=rid, company=c, title=t, status=rec['status'] if rec else 'no record',
                        left=('; '.join(rec.get('left') or []) or rec.get('note', '')) if rec else ''))
    return out


def table(rs):
    cols = ('id', 'company', 'title', 'status', 'left')
    cell = lambda v: str(v or '').replace('|', '/').replace('\n', ' ')
    return '\n'.join(' | '.join(cell(r[c]) for c in cols) for r in [dict(zip(cols, cols))] + rs)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gmh fills', description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=['set', 'show'])
    ap.add_argument('ids', nargs='*')
    ap.add_argument('--status', choices=STATUSES)
    ap.add_argument('--left', action='append', default=[], help='set: one thing left for the user (repeatable)')
    ap.add_argument('--note', default='')
    ap.add_argument('--date', help='show: the day whose reviewed CSV names the roles (default: any, newest first)')
    ap.add_argument('--json', action='store_true', help='show: JSON instead of the table')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    a = ap.parse_args(argv)
    ws = os.path.abspath(os.path.expanduser(a.workspace))
    try:
        if a.cmd == 'set':
            if len(a.ids) != 1 or not a.status:
                ap.error('set: one role id and --status')
            print(line(record(ws, a.ids[0], a.status, a.left, a.note)))
        else:
            rs = rows(ws, a.ids, a.date)
            if a.json:
                print(json.dumps(rs, indent=1, ensure_ascii=False))
            elif rs:
                print(table(rs))
            else:
                print('No fill records yet.')
    except ValueError as e:
        sys.exit(f'gmh fills: {e}')


if __name__ == '__main__':
    main()
