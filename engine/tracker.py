"""The application tracker: workspace tracker.csv (the source of truth) and an offline HTML report.

One row per application, keyed by job_key(company, title). A Google Sheet, if the user
connects one, mirrors this file one way; nothing reads the Sheet back.

Status moves forward only (applied -> assessment -> interviewing -> offer), except that
rejected, withdrawn, accepted, declined and no_response close a row whatever stage it reached.
An older event never overwrites a newer one. `set` is the user's own call and overrides that order.

Lifecycle (Phase 5): `followups` lists open applications quiet for 10+ days with fewer than two
follow-ups; `stale` lists applications still at "applied" after 60+ days, to close as no_response;
`materials` lists the exact files submitted (resume, cover letter, posting, notes) for interview
prep, thank-you notes and follow-up drafts. Listing commands never write; `set` and `followed-up` do,
and run only after the user approves that specific change.

Folders follow status: a row that reaches interviewing or offer has its Workflow folder moved from 03-Applied to
04-Interviewing and its `folder` cell updated (`set` and the Gmail import do this for the rows they change).
`folders` lists the rows whose folder lags their status and, without --dry-run, moves them (the catch-up).

Holds are not applications, so they never become tracker rows (discover, score, the company cap and follow-ups
read every row as applied). `holds` reads them from the vault's queue/reviewed-<date>.csv files instead: a role
whose latest call is hold and that isn't in the tracker yet. The report lists them in an On hold section.

Usage:
  python3 -m engine.tracker report --workspace <dir>      # writes <workspace>/report.html
  python3 -m engine.tracker status --workspace <dir>      # counts by status
  python3 -m engine.tracker seed-legacy --workspace <dir> # copy the original pipeline's applied.csv in
  python3 -m engine.tracker set <id|job_key> <status> [--date D] [--note N] --workspace <dir>
  python3 -m engine.tracker followups [--days 10] --workspace <dir>
  python3 -m engine.tracker followed-up <id|job_key> [--date D] --workspace <dir>
  python3 -m engine.tracker stale [--days 60] --workspace <dir>
  python3 -m engine.tracker materials <id|job_key> --workspace <dir>
  python3 -m engine.tracker folders [--dry-run] --workspace <dir>
  python3 -m engine.tracker holds [--days 14] --workspace <dir>
  python3 -m engine.tracker find "<words>" [--json] --workspace <dir>      # up to 5 closest rows, best first (exit 1: none)
  python3 -m engine.tracker prep <id|job_key> --workspace <dir>            # interview prep inputs, markdown
  python3 -m engine.tracker sheet-rows [--since D] [--mark] --workspace <dir>  # rows changed since the last Sheet mirror, TSV
  python3 -m engine.tracker statuses                                       # the status vocabulary
"""
import argparse, collections, csv, datetime, difflib, html, json, os, re, shutil, sys
from .job_key import alias_keys, job_key

COLUMNS = ['date_applied', 'company', 'title', 'location', 'id', 'job_key', 'status', 'status_date', 'source', 'url', 'folder',
           'gmail_ids', 'notes', 'followups', 'linkedin_interest', 'linkedin_connect']
STATUSES = ['applied', 'assessment', 'interviewing', 'offer', 'accepted', 'declined', 'rejected', 'withdrawn', 'no_response']
RANK = {'applied': 0, 'assessment': 1, 'interviewing': 2, 'offer': 3}
STAGE_FOLDER = {'interviewing': '04-Interviewing', 'offer': '04-Interviewing'}  # status -> the Workflow folder it lives in
MOVES_FROM = '03-Applied'  # only applied folders move; a row closed later stays where it reached
CLOSED = {'rejected', 'withdrawn', 'accepted', 'declined', 'no_response'}
OPEN = {'applied', 'assessment', 'interviewing', 'offer'}


def path_of(workspace):
    return os.path.join(os.path.expanduser(workspace), 'tracker.csv')


def read(path):
    if not os.path.exists(path):
        return []
    return [dict(r) for r in csv.DictReader(open(path, encoding='utf-8', newline=''))]


def write(path, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction='ignore', quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') or '' for c in COLUMNS})
    os.replace(tmp, path)


def init(path):
    if not os.path.exists(path):
        write(path, [])


def advance(current, current_date, new, new_date):
    """Whether an event (new status on new_date) should replace the row's status."""
    if not current:
        return True
    if new_date and current_date and new_date < current_date:
        return False
    if new in CLOSED:
        return current not in CLOSED or new_date > (current_date or '')
    if current in CLOSED:
        return bool(new_date and current_date and new_date > current_date and RANK.get(new, 0) > 0)
    return RANK.get(new, 0) > RANK.get(current, 0)


def upsert(rows, item):
    """Merge one application (dict with company, title, status, status_date, ...) into rows.
    Returns 'added', 'updated' or 'unchanged'."""
    key = item.get('job_key') or job_key(item['company'], item['title'])
    item = {**item, 'job_key': key}
    for r in rows:
        if key in (r.get('job_key'), job_key(r['company'], r['title'])) or (item.get('id') and r.get('id') == item.get('id')):
            changed = False
            ids = [x for x in (r.get('gmail_ids') or '').split() if x]
            for x in (item.get('gmail_ids') or '').split():
                if x not in ids:
                    ids.append(x)
                    changed = True
            r['gmail_ids'] = ' '.join(ids)
            if item.get('date_applied') and (not r.get('date_applied') or item['date_applied'] < r['date_applied']):
                r['date_applied'] = item['date_applied']
                changed = True
            if item.get('status') and advance(r.get('status'), r.get('status_date'), item['status'], item.get('status_date')):
                if (r.get('status'), r.get('status_date')) != (item['status'], item.get('status_date')):
                    r['status'], r['status_date'] = item['status'], item.get('status_date', '')
                    changed = True
            for k in ('id', 'url', 'folder', 'location'):
                if item.get(k) and not r.get(k):
                    r[k] = item[k]
                    changed = True
            return 'updated' if changed else 'unchanged'
    row = {c: item.get(c, '') for c in COLUMNS}
    row['status'] = row['status'] or 'applied'
    row['status_date'] = row['status_date'] or row['date_applied']
    rows.append(row)
    return 'added'


def known_keys(workspace, legacy_paths=(), aliases=()):
    """job_keys and ids already applied: tracker.csv plus any legacy applied.csv files. Each row is keyed under every
    name its company goes by (job_key.alias_keys with config `company_aliases`), so "Northwind Pay" matches a
    tracked "Northwind (Tailspin)" role of the same title when the config groups them."""
    keys, ids = set(), set()
    for p in [path_of(workspace), *legacy_paths]:
        for r in read(p):
            if r.get('company') and r.get('title'):
                keys |= alias_keys(r['company'], r['title'], aliases)  # today's rule, under every company name
                if r.get('job_key'):
                    keys.add(r['job_key'])
            if r.get('id'):
                ids.add(r['id'])
    return keys, ids


def legacy_applied(cfg):
    """The original pipeline's applied.csv, when the workspace points at a vault."""
    from . import layout
    vault = layout.named(cfg)
    p = os.path.join(vault, 'Pipeline', 'state', 'applied.csv') if vault else None
    return [p] if p and os.path.exists(p) else []


def seed_legacy(workspace, cfg):
    """Copy every row of the original pipeline's applied.csv into tracker.csv (source=pipeline).
    Safe to re-run: rows already in the tracker are left as they are."""
    from .locfmt import role_location, run_locations
    path = path_of(workspace)
    init(path)
    rows = read(path)
    counts = collections.Counter()
    from . import layout
    pipeline = layout.pipeline(workspace, cfg)
    runs = run_locations(pipeline)
    for p in legacy_applied(cfg):
        for r in read(p):
            if r.get('company') and r.get('title'):
                counts[upsert(rows, {'company': r['company'], 'title': r['title'], 'id': r.get('id', ''),
                                     'date_applied': r.get('date_applied', ''), 'status': 'applied',
                                     'status_date': r.get('date_applied', ''), 'source': 'pipeline',
                                     'url': r.get('url', ''), 'folder': r.get('folder', ''),
                                     'location': role_location(pipeline, r.get('id', ''), runs) if r.get('id') else ''})] += 1
    write(path, rows)
    return counts


# ---- lifecycle ----

def fill_locations(rows, pipeline, hints_csv=None):
    """Fill blank `location` cells from what the pipeline saved (posting location line, the run's remote match),
    with an optional hints CSV (company, title, location) for cities when the posting has none and for work mode.
    A row nothing says anything about stays blank. Returns (rows filled, rows left blank)."""
    from .locfmt import role_location, run_locations, format_location
    hints = {}
    if hints_csv:
        for h in read(hints_csv):
            if h.get('company') and h.get('title'):
                hints[job_key(h['company'], h['title'])] = h.get('location', '')
    runs = run_locations(pipeline)
    filled, missing = [], []
    for r in rows:
        if r.get('location'):
            continue
        hint = hints.get(r.get('job_key') or job_key(r['company'], r['title']), '')
        loc = role_location(pipeline, r['id'], runs, hint) if r.get('id') else format_location('', hint=hint)
        if loc:
            r['location'] = loc
            filled.append(r)
        else:
            missing.append(r)
    return filled, missing


def find(rows, key):
    """The row whose id or job_key is key."""
    hits = [r for r in rows if key in (r.get('id'), r.get('job_key'))]
    if len(hits) != 1:
        raise KeyError(f'{key}: {len(hits)} tracker rows match (use an id or job_key from `status` or `followups`)')
    return hits[0]


def set_status(rows, key, status, date, note=''):
    """The user's own status change: applied as given, whatever the current status."""
    if status not in STATUSES:
        raise ValueError(f'{status}: not one of {", ".join(STATUSES)}')
    r = find(rows, key)
    r['status'], r['status_date'] = status, date
    if note:
        r['notes'] = '; '.join(filter(None, [r.get('notes', ''), f'{date}: {note}']))
    return r


def _days(since, today):
    try:
        return (today - datetime.date.fromisoformat((since or '')[:10])).days
    except ValueError:
        return None


def last_touch(r):
    """The latest of the status date and any follow-up date."""
    return max([r.get('status_date') or r.get('date_applied') or ''] + (r.get('followups') or '').split())


def followups_due(rows, today, quiet_days=10, max_followups=2):
    """Open applications with no news for quiet_days (since the status date or the last follow-up)
    and fewer than max_followups follow-ups sent. Offers are left to the user."""
    out = []
    for r in rows:
        n = len((r.get('followups') or '').split())
        d = _days(last_touch(r), today)
        if r.get('status') in OPEN - {'offer'} and n < max_followups and d is not None and d >= quiet_days:
            out.append({**r, 'quiet_days': d, 'followups_sent': n})
    return sorted(out, key=lambda r: -r['quiet_days'])


def stale(rows, today, days=60):
    """Applications still at 'applied' with nothing since for `days`: candidates to close as no_response."""
    out = []
    for r in rows:
        d = _days(last_touch(r), today)
        if r.get('status') == 'applied' and d is not None and d >= days:
            out.append({**r, 'quiet_days': d})
    return sorted(out, key=lambda r: -r['quiet_days'])


def log_followup(rows, key, date):
    r = find(rows, key)
    r['followups'] = ' '.join(filter(None, [(r.get('followups') or '').strip(), date]))
    return r


def materials(r, vault):
    """The files submitted for one application: everything in its Workflow folder."""
    folder = r.get('folder') or ''
    d = folder if os.path.isabs(folder) else os.path.join(os.path.expanduser(vault or ''), folder)
    if not folder or not os.path.isdir(d):
        return d, []
    return d, sorted(os.path.join(d, f) for f in os.listdir(d) if not f.startswith('.'))


def folder_move(r, vault):
    """Where this row's folder should go for its status: None when it stays, else a dict with src, dst (absolute),
    folder (the new `folder` cell) and action: 'move' (src there, dst free), 'relink' (already moved, only the cell
    lags), 'conflict' (both exist: left alone) or 'missing' (neither exists)."""
    stage, folder = STAGE_FOLDER.get(r.get('status') or ''), (r.get('folder') or '').rstrip('/')
    if folder and not os.path.isabs(folder):
        folder = folder.replace('\\', '/')  # cells are stored with '/', but accept a Windows-written '\\'
    if not stage or not folder or os.path.basename(os.path.dirname(folder)) != MOVES_FROM:
        return None
    root = os.path.dirname(os.path.dirname(folder))
    new = f'{root}/{stage}/{os.path.basename(folder)}' if root else f'{stage}/{os.path.basename(folder)}'
    absolute = lambda f: f if os.path.isabs(f) else os.path.join(os.path.expanduser(vault or ''), f)
    src, dst = absolute(folder), absolute(new)
    there, taken = os.path.isdir(src), os.path.exists(dst)
    action = 'conflict' if there and taken else 'move' if there else 'relink' if os.path.isdir(dst) else 'missing'
    return {'row': r, 'src': src, 'dst': dst, 'old': folder, 'folder': new, 'action': action}


def move_folders(rows, vault, dry_run=False):
    """Move each row's folder to the Workflow folder of its status (folder_move) and update its `folder` cell.
    Safe to repeat: a moved folder is only relinked; a conflict or missing folder is reported, never merged.
    Returns the planned moves; with dry_run nothing is moved or changed."""
    plans = [m for m in (folder_move(r, vault) for r in rows) if m]
    if not dry_run:
        for m in plans:
            if m['action'] == 'move':
                os.makedirs(os.path.dirname(m['dst']), exist_ok=True)
                shutil.move(m['src'], m['dst'])
            if m['action'] in ('move', 'relink'):
                m['row']['folder'] = m['folder']
    return plans


def describe_move(m, dry_run=False):
    r, what = m['row'], {'move': 'would move' if dry_run else 'moved', 'relink': 'would relink' if dry_run else 'relinked',
                         'conflict': 'left alone: destination already exists', 'missing': 'left alone: folder not found'}
    return (f"{what[m['action']]}: {r['company']} | {r['title']} ({r.get('status')})\n"
            f"    {m['old']}\n -> {m['folder']}")


def vault_of(ws):
    """The workspace's vault (config paths.vault), else the workspace itself: engine.layout.vault."""
    from . import layout
    return layout.vault(ws)


HELD_DAYS = 14  # a hold this old is flagged "held a while"


def holds(rows, vault, today, held_days=HELD_DAYS):
    """Roles on hold: each role's latest call across queue/reviewed-*.csv (oldest file first) is hold, and no
    tracker row has its id or job_key. `since` is the first file of the unbroken run of hold calls. Each comes with
    its folder (02-Ready to Apply, when one was built), note, posting link and fit. Newest hold first."""
    import glob
    from .runrecord import READY, spec_folders
    q = os.path.join(os.path.expanduser(vault or ''), 'Pipeline', 'queue')
    latest = {}
    for p in sorted(glob.glob(os.path.join(q, 'reviewed-*.csv'))):
        date = os.path.basename(p)[len('reviewed-'):-len('.csv')]
        for r in read(p):
            if not r.get('id'):
                continue
            call, prev = (r.get('call') or '').strip().lower(), latest.get(r['id'])
            since = prev['since'] if prev and prev['call'] == 'hold' and call == 'hold' else date
            latest[r['id']] = {**r, 'call': call, 'since': since}
    applied_ids = {r.get('id') for r in rows if r.get('id')}
    applied_keys = {r.get('job_key') or job_key(r['company'], r['title']) for r in rows}
    names = spec_folders(os.path.expanduser(vault or ''))
    out = []
    for rid, r in latest.items():
        if r['call'] != 'hold' or rid in applied_ids or job_key(r.get('company', ''), r.get('title', '')) in applied_keys:
            continue
        d = os.path.join(os.path.expanduser(vault or ''), 'Workflow', READY, names[rid]) if rid in names else ''
        days = _days(r['since'], today)
        out.append({'id': rid, 'company': r.get('company', ''), 'title': r.get('title', ''), 'location': r.get('locations', ''),
                    'fit': r.get('fit', ''), 'since': r['since'], 'days': days, 'old': days is not None and days >= held_days,
                    'note': r.get('notes', ''), 'url': r.get('url', ''), 'folder': d if d and os.path.isdir(d) else ''})
    return sorted(out, key=lambda h: (h['since'], h['company']), reverse=True)


# ---- find, prep, sheet-rows, statuses (read-only: none of these writes tracker.csv) ----

def _tokens(text):
    return set(re.findall(r'[a-z0-9]+', (text or '').lower()))


def fuzzy(rows, words, limit=5, floor=0.3):
    """Up to `limit` rows closest to `words`, best first: token overlap (share of the query's words found in the
    row's company, title, id and job_key, a prefix counts) plus difflib similarity to the company/title text."""
    q = (words or '').lower().strip()
    qt = _tokens(q)
    if not qt:
        return []
    scored = []
    for r in rows:
        fields = [r.get('company'), r.get('title'), r.get('id'), r.get('job_key')]
        rt = set().union(*(_tokens(f) for f in fields))
        hit = sum(1 for t in qt if t in rt or any(len(t) >= 3 and x.startswith(t) for x in rt))
        text = ' '.join(filter(None, [r.get('company'), r.get('title')])).lower()
        ratio = max([difflib.SequenceMatcher(None, q, text).ratio()] +
                    [difflib.SequenceMatcher(None, q, (f or '').lower()).ratio() for f in fields])
        score = 0.7 * hit / len(qt) + 0.3 * ratio
        if q in (r.get('id'), r.get('job_key')):
            score = 2
        if score >= floor:
            scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1].get('company') or '', x[1].get('title') or ''))
    return [r for _, r in scored[:limit]]


def mirror_state_path(ws, cfg=None):
    from . import layout
    return os.path.join(layout.pipeline(ws, cfg), 'state', 'sheet-mirror.json')


def last_mirror(ws, cfg=None):
    """The date of the last Sheet mirror (Pipeline/state/sheet-mirror.json), or '' when never recorded."""
    try:
        with open(mirror_state_path(ws, cfg), encoding='utf-8') as fh:
            return str(json.load(fh).get('last_mirror') or '')[:10]
    except (OSError, ValueError, AttributeError):
        return ''


def mark_mirror(ws, date, cfg=None):
    p = mirror_state_path(ws, cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'last_mirror': date}, fh)
    return p


def changed_since(rows, since):
    """Rows whose application, status or last follow-up date is on or after `since` (all rows when since is empty)."""
    if not since:
        return list(rows)
    return [r for r in rows if max(r.get('date_applied') or '', r.get('status_date') or '', last_touch(r)) >= since]


def tsv(rows):
    clean = lambda v: re.sub(r'[\t\r\n]+', ' ', v or '')
    return '\n'.join('\t'.join(clean(r.get(c)) for c in COLUMNS) for r in rows)


def statuses_text():
    return '\n'.join(s + (' (closed)' if s in CLOSED else '') for s in STATUSES)


def submitted(r, ws):
    """(resume path, cover path, posting path, resume text) of one row's submitted materials ('' when absent)."""
    from . import linkedin
    vault = vault_of(ws)
    _, files = materials(r, vault)
    pick = lambda word, exts: next((f for f in files if word in os.path.basename(f).lower() and f.lower().endswith(exts)), '')
    resume, cover = pick('resume', ('.docx', '.pdf', '.md')), pick('cover', ('.docx', '.pdf', '.md'))
    posting = next((f for f in files if f.endswith('.md') and os.path.basename(f) != 'application-notes.md'
                    and f not in (resume, cover)), '')
    jd = os.path.join(vault, 'Pipeline', 'state', 'jd', (r.get('id') or '') + '.txt')
    if not posting and r.get('id') and os.path.exists(jd):
        posting = jd
    text = ''
    if resume.endswith('.docx'):
        text = linkedin.docx_text(resume)
    elif resume.endswith('.md'):
        with open(resume, encoding='utf-8') as fh:
            text = fh.read()
    return resume, cover, posting, text


def number_lines(text):
    """[(number, source line)] for every line of text holding a number the checks recognise (redline.numbers)."""
    from .redline import numbers
    out = []
    for line in (text or '').splitlines():
        for n in sorted(numbers(line)):
            out.append((n, line.strip()))
    return out


def prep_markdown(r, ws):
    resume, cover, posting, text = submitted(r, ws)
    nums = number_lines(text)
    if nums:
        body = '\n'.join(f'- {n}: "{line}"' for n, line in nums)
    else:
        body = '(no numbers found)' if text else '(the submitted resume could not be read: no numbers listed)'
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'interview-prep.md')
    with open(tpl, encoding='utf-8') as fh:
        out = fh.read()
    for k, v in (('role', r.get('title')), ('company', r.get('company')), ('status', r.get('status')),
                 ('resume_path', os.path.abspath(resume) if resume else '(none found)'),
                 ('cover_path', os.path.abspath(cover) if cover else '(none found)'),
                 ('posting_path', os.path.abspath(posting) if posting else '(none found)'), ('numbers', body)):
        out = out.replace('{' + k + '}', v or '')
    return out


# ---- report ----

TIERS = ['A', 'B', 'C+', 'C', 'cap', 'gate']


def gap_counts(queue_dir):
    """{gap: {tier: n}} over every scored role in queue/scored-*.csv (each role once, newest file wins)."""
    import glob
    latest = {}
    for f in sorted(glob.glob(os.path.join(queue_dir, 'scored-*.csv'))):
        for r in read(f):
            latest[r.get('id') or (r.get('company'), r.get('title'))] = r
    out = {}
    for r in latest.values():
        for g in filter(None, (x.strip() for x in (r.get('gaps') or '').split(';'))):
            cell = out.setdefault(g, {})
            cell[r.get('tier') or '?'] = cell.get(r.get('tier') or '?', 0) + 1
    return out


def gap_table(gaps, limit=15):
    """The skills-gap heatmap: the most frequent gaps by tier; darker cells are more roles."""
    if not gaps:
        return ''
    top = sorted(gaps.items(), key=lambda kv: -sum(kv[1].values()))[:limit]
    peak = max(n for _, cell in top for n in cell.values())
    cells = lambda cell: ''.join(
        f'<td class="h" style="background:color-mix(in srgb,var(--accent) {round(70 * cell.get(t, 0) / peak)}%,transparent)">'
        f'{cell.get(t, "") or ""}</td>' for t in TIERS)
    body = ''.join(f'<tr><td>{html.escape(g)}</td>{cells(cell)}<td class="n">{sum(cell.values())}</td></tr>' for g, cell in top)
    return ('<h2>Gaps the scorer found</h2><p class="sub">Requirements in scored postings that your resume does not show, '
            'by tier. Frequent gaps in A and B roles are the ones worth closing (or explaining).</p>'
            '<div class="wrap"><table class="heat"><thead><tr><th>Gap</th>' + ''.join(f'<th>{t}</th>' for t in TIERS) +
            f'<th>Roles</th></tr></thead><tbody>{body}</tbody></table></div>')


def report(rows, out, title='Applications', gaps=None, fits=None, vault=None, today=None, held=None):
    """Write the dashboard (engine/dashboard.py): one offline HTML page with filters, search, sortable columns
    and summary tiles, the On hold section (held: from holds()), and the skills-gap heatmap when gaps are given.
    Returns the path."""
    from .dashboard import render
    page = render(rows, today=today, fits=fits, vault=vault, gaps_html=gap_table(gaps), title=title, holds=held)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(page)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.tracker')
    ap.add_argument('cmd', choices=['report', 'status', 'seed-legacy', 'set', 'followups', 'followed-up', 'stale', 'materials',
                                    'locations', 'folders', 'holds', 'find', 'prep', 'sheet-rows', 'statuses'])
    ap.add_argument('--hints', help='locations: a CSV with company, title, location (e.g. an export of a Sheet tracker)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('args', nargs='*')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--note', default='')
    ap.add_argument('--days', type=int)
    ap.add_argument('--since', help='sheet-rows: rows changed on or after this date (default: the last recorded mirror)')
    ap.add_argument('--mark', action='store_true', help='sheet-rows: record today as the last mirror date')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'))
    a = ap.parse_args(argv)
    if a.cmd == 'statuses':
        print(statuses_text())
        return
    if not a.workspace:
        ap.error('--workspace is required (or set GMH_WORKSPACE)')
    ws = os.path.expanduser(a.workspace)
    if a.cmd == 'seed-legacy':
        from .profile import load_config
        c = seed_legacy(a.workspace, load_config(os.path.join(ws, 'config.json')))
        print(f"tracker.csv: {c['added']} added, {c['updated'] + c['unchanged']} already there")
        return
    path = path_of(a.workspace)
    rows = read(path)
    today = datetime.date.fromisoformat(a.date)
    line = lambda r, extra='': (f"{r.get('id') or r.get('job_key')}  {r['company']} | {r['title']} | {r.get('status')} since "
                                f"{r.get('status_date')}{extra}")
    if a.cmd in ('set', 'followed-up', 'materials') and not a.args:
        sys.exit(f'{a.cmd} needs an <id|job_key> (see `status`, `followups` or tracker.csv)')
    if a.cmd in ('find', 'prep') and not a.args:
        ap.error(f'{a.cmd} needs ' + ('words to look for' if a.cmd == 'find' else 'an <id|job_key>'))
    if a.cmd == 'find':
        hits = fuzzy(rows, ' '.join(a.args))
        if a.json:
            print(json.dumps([{k: r.get(k, '') for k in ('id', 'company', 'title', 'status', 'status_date', 'date_applied')}
                              for r in hits], indent=1))
        for r in ([] if a.json else hits):
            print(f"{r.get('id') or r.get('job_key')}\t{r['company']}\t{r['title']}\t{r.get('status')}\t"
                  f"{r.get('status_date') or r.get('date_applied')}")
        if not hits:
            print('no tracker row matches: ' + ' '.join(a.args), file=sys.stderr)
            sys.exit(1)
    elif a.cmd == 'prep':
        try:
            print(prep_markdown(find(rows, a.args[0]), ws))
        except KeyError as e:
            sys.exit(f'{e.args[0]}')
    elif a.cmd == 'sheet-rows':
        from .profile import load_config
        cfgp = os.path.join(ws, 'config.json')
        cfg = load_config(cfgp) if os.path.exists(cfgp) else {}
        since = a.since or last_mirror(ws, cfg)
        print(tsv(changed_since(rows, since)))
        if a.mark:
            print(f'last mirror recorded: {a.date} ({mark_mirror(ws, a.date, cfg)})', file=sys.stderr)
    elif a.cmd == 'report':
        vault = vault_of(ws)
        from .dashboard import scores
        print(report(rows, os.path.join(ws, 'report.html'), gaps=gap_counts(os.path.join(vault, 'Pipeline', 'queue')),
                     fits=scores(vault), vault=vault, today=a.date, held=holds(rows, vault, today)))
    elif a.cmd == 'holds':
        held = holds(rows, vault_of(ws), today, a.days or HELD_DAYS)
        print(f"{len(held)} role(s) on hold ({sum(h['old'] for h in held)} held {a.days or HELD_DAYS}+ days)")
        for h in held:
            print(f"  {h['company']} | {h['title']} | held since {h['since']} ({h['days']} days)" + (' | HELD A WHILE' if h['old'] else '')
                  + f"\n    {h['folder'] or 'no folder built'}" + (f"\n    note: {h['note'][:160]}" if h['note'] else ''))
    elif a.cmd == 'set':
        if len(a.args) != 2:
            sys.exit('set needs <id|job_key> <status>')
        r = set_status(rows, a.args[0], a.args[1], a.date, a.note)
        moves = move_folders([r], vault_of(ws))
        write(path, rows)
        print('set:', line(r))
        for m in moves:
            print(describe_move(m))
    elif a.cmd == 'folders':
        moves = move_folders(rows, vault_of(ws), a.dry_run)
        if not a.dry_run and any(m['action'] in ('move', 'relink') for m in moves):
            write(path, rows)
        for m in moves:
            print(describe_move(m, a.dry_run))
        print(f"{len(moves)} row(s) whose folder lags their status" + (' (dry run, nothing moved or written)' if a.dry_run else ''))
    elif a.cmd == 'followed-up':
        r = log_followup(rows, a.args[0], a.date)
        write(path, rows)
        print('follow-up logged:', line(r, f"; follow-ups {r['followups']}"))
    elif a.cmd == 'followups':
        due = followups_due(rows, today, a.days or 10)
        print(f'{len(due)} follow-up(s) due')
        for r in due:
            print('  ' + line(r, f"; quiet {r['quiet_days']} days; {r['followups_sent']} sent"))
    elif a.cmd == 'stale':
        old = stale(rows, today, a.days or 60)
        print(f'{len(old)} application(s) with no news for {a.days or 60}+ days (close with: set <key> no_response)')
        for r in old:
            print('  ' + line(r, f"; quiet {r['quiet_days']} days"))
    elif a.cmd == 'locations':
        from .profile import load_config
        cfg = load_config(os.path.join(ws, 'config.json'))
        from . import layout
        filled, missing = fill_locations(rows, layout.pipeline(ws, cfg), a.hints)
        if not a.dry_run:
            write(path, rows)
        for r in filled:
            print(f"  {r['company']} | {r['title'][:60]} -> {r['location']}")
        print(f"{len(filled)} filled{' (dry run, nothing written)' if a.dry_run else ''}; {len(missing)} left blank"
              + ''.join(f"\n  blank: {r['company']} | {r['title'][:60]}" for r in missing))
    elif a.cmd == 'materials':
        from .profile import load_config
        cfg = load_config(os.path.join(ws, 'config.json'))
        d, files = materials(find(rows, a.args[0]), vault_of(ws))
        print(d)
        for f in files:
            print('  ' + os.path.basename(f))
        if not files:
            print('  (no folder found: the application has no archived materials)')
    else:
        c = collections.Counter(r.get('status') or 'applied' for r in rows)
        print(f'{len(rows)} applications: ' + ', '.join(f'{s} {c[s]}' for s in STATUSES if c[s]))


if __name__ == '__main__':
    main()
