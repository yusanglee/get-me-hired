"""<workspace>/HOME.md (status, what you can ask for, links) and the short summaries each session leaves when it
ends. The day session (the today skill) reads the same status through `gmh today`.

  gmh home --workspace <dir> [--json]                 rewrite HOME.md and print it (--json: the same as data)
  gmh home log <task> --workspace <dir> --summary "..." [--waiting "..."]... [--next "..."]
                                                       record how a session (or one task in it) ended:
                                                       <workspace>/state/sessions/<date>-<task>.json
  gmh home log <task> --auto [--summary "..."] [--waiting "..."]... [--next "..."] [--date D]
                                                       the same, with the counts filled from the day's files
                                                       (Gmail sync, run, picks, queue, applied, LinkedIn)

HOME.md is regenerated on every run (hand edits are overwritten). It holds how to start each day, the skills you can
ask for (with the model each names, read from its own model:/effort: lines so it can't drift), links to the files and
pages used most, and what is waiting on the user: what the run files show (picks not confirmed, queued roles not
applied) and what the recent sessions left.
"""
import argparse, collections, datetime, glob, json, os, re, sys

from . import layout
from .profile import load_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO, 'skills')
COMMANDS = os.path.join(REPO, 'commands')  # workflows not converted to skills yet
RECENT_DAYS = 7

# What the user can ask for, in daily-loop order, with when. All run in the one day session; none starts a session.
TASKS = [
    ('today', 'Each day: open a session on Opus and run this; it takes you through the whole day in that session'),
    ('daily-run', 'Only the find, score and pick part of a day'),
    ('apply-all', "Only the applying part (a day's picks); you approve each batch before Submit"),
    ('linkedin-followup', 'Optional, once the day\'s applications are in'),
    ('gmail-sync', 'Every few days: replies, rejections and interviews from email'),
    ('outcome', 'When you hear back about one application'),
    ('followup', 'Applications gone quiet: draft follow-up notes'),
    ('interview', 'Before an interview: a prep pack; after: thank-you notes'),
    ('materials', "Offered before today's resumes are built (and at wrap-up for the rest): approve new bullets, bios, summaries, template versions"),
    ('design', 'Change how resumes and cover letters look'),
    ('import-history', 'Once at the start, or after a gap: load past applications from email'),
]
TASK_RE = re.compile(r'^[a-z][a-z-]{1,40}$')
# A later summary of the key task settles what these tasks left waiting (the day's wrap-up covers the parts).
SUPERSEDES = {'apply-all': {'daily-run'}, 'today': {'daily-run', 'apply-all', 'linkedin-followup'}}


def source(name, commands=COMMANDS, skills=SKILLS):
    """The file a task's frontmatter comes from: skills/<name>/SKILL.md, else commands/<name>.md, else None."""
    for p in (os.path.join(skills, name, 'SKILL.md'), os.path.join(commands, name + '.md')):
        if os.path.exists(p):
            return p
    return None


def frontmatter(name, commands=COMMANDS, skills=SKILLS):
    """The model:, effort: and description: lines of skills/<name>/SKILL.md (or commands/<name>.md); {} if neither."""
    p = source(name, commands, skills)
    if not p:
        return {}
    with open(p, encoding='utf-8') as fh:
        text = fh.read()
    m = re.match(r'---\n(.*?)\n---', text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(':')
        if k.strip() in ('model', 'effort', 'description'):
            out[k.strip()] = v.strip()
    return out


def tasks(commands=COMMANDS, skills=SKILLS):
    out = []
    for name, when in TASKS:
        fm = frontmatter(name, commands, skills)
        if fm:
            out.append({'task': name, 'command': f'/get-me-hired:{name}', 'model': fm.get('model', ''),
                        'effort': fm.get('effort', ''), 'when': when})
    return out


def model_label(t):
    return (t['model'].capitalize() + (f", {t['effort']} effort" if t['effort'] else '')) if t['model'] else 'any'


# ---- session summaries ----

def sessions_dir(ws):
    return os.path.join(ws, 'state', 'sessions')


def log(ws, task, summary, waiting=(), next_step='', date=None, now=None):
    """Write how a session or task ended. One file per task per day: a later one of the same task replaces it."""
    if not TASK_RE.match(task):
        raise SystemExit(f'task must be a command name such as daily-run, not {task!r}')
    if not summary.strip():
        raise SystemExit('--summary is required: one or two lines on what this session did')
    date = date or datetime.date.today().isoformat()
    rec = {'task': task, 'date': date, 'at': (now or datetime.datetime.now()).isoformat(timespec='minutes'),
           'summary': summary.strip(), 'waiting': [w.strip() for w in waiting if w.strip()], 'next': next_step.strip()}
    d = sessions_dir(ws)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{date}-{task}.json')
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(rec, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return p


def _gmail_applied(ws, date, rows):
    """What the day's Gmail proposals put in the tracker: (updates by new status, rows added). A proposal row counts
    when a tracker row now holds one of its message ids at the row's status."""
    by_id = {}
    for r in rows:
        for mid in (r.get('gmail_ids') or '').split():
            by_id[mid] = r
    updates, added = collections.Counter(), 0
    for p in glob.glob(os.path.join(ws, 'state', 'gmail', f'proposed-{date}*.json')):
        try:
            with open(p, encoding='utf-8') as fh:
                prop = json.load(fh)
        except (OSError, ValueError):
            continue
        for row in prop.get('rows') or []:
            hit = next((by_id[m] for m in (row.get('gmail_ids') or '').split() if m in by_id), None)
            if not hit or hit.get('status') != row.get('status'):
                continue
            if row.get('action') == 'update':
                updates[row.get('status') or '?'] += 1
            elif row.get('action') in ('add', 'which?'):
                added += 1
    return updates, added


QUEUE_LABELS = (('applied', 'applied'), ('to_prepare', 'to prepare'), ('to_fill', 'to fill'),
                ('ready', 'filled and waiting for your OK'), ('needs_user', 'need you'), ('blocked', 'blocked'),
                ('manual', 'manual'))


def auto_summary(ws, date=None):
    """The counts for `gmh home log --auto`, from the day's files: Gmail sync, the run, picks, the queue
    (engine.today.queue_counts), applications recorded that day and LinkedIn companies done. Counts and company
    names only."""
    from . import today as today_mod, tracker
    day = datetime.date.fromisoformat(date) if date else datetime.date.today()
    date = day.isoformat()
    d = today_mod.data(ws, day)
    ws = d['workspace']
    rows = tracker.read(tracker.path_of(ws))
    updates, added = _gmail_applied(ws, date, rows)
    if updates or added:
        what = ', '.join(f'{n} {s}' for s, n in sorted(updates.items()))
        parts = [f"Gmail: {sum(updates.values())} update(s)" + (f' ({what})' if what else '') + f', {added} added']
    else:
        parts = ['Gmail: ' + ('synced, nothing new' if d['gmail']['today'] else 'not synced that day')]
    r = d['run']
    if r['scored']:
        parts.append(f"Run: {r['scored_roles']} roles scored ({r['tiers']['A']} A, {r['tiers']['B']} B, "
                     f"{r['tiers']['gap']} critical gap)")
    else:
        parts.append('Run: ' + ('found, not scored yet' if r['discovered'] else 'none'))
    reviewed = today_mod._reviewed(layout.queue(ws), date)
    if reviewed is not None:
        calls = collections.Counter((x.get('call') or '').strip().lower() for x in reviewed)
        parts.append('Picks: ' + (', '.join(f'{calls[c]} {c}' for c in ('apply', 'manual', 'hold', 'pass') if calls[c])
                                  or 'none'))
    q = d['queue']
    if q:
        parts.append('Queue: ' + (', '.join(f'{len(q[k])} {label}' for k, label in QUEUE_LABELS if q[k]) or 'empty'))
    mine = [x for x in rows if x.get('date_applied') == date and x.get('source') != 'gmail']
    if mine:
        parts.append(f"Applied: {len(mine)} ({', '.join(sorted({x.get('company') or '?' for x in mine}))})")
    done = sorted({x.get('company') or '?' for x in rows if (x.get('linkedin_interest') or '').split()[-1:] == [date]})
    sent = sum(e.strip().startswith(f'{date} sent') for x in rows for e in (x.get('linkedin_connect') or '').split(';'))
    if done or sent:
        parts.append(f"LinkedIn: {len(done)} compan{'y' if len(done) == 1 else 'ies'} done"
                     + (f" ({', '.join(done)})" if done else '') + (f', {sent} note(s) sent' if sent else ''))
    return '. '.join(parts) + '.'


def recent(ws, today=None, days=RECENT_DAYS):
    """Summaries from the last `days` days, newest first."""
    today = today or datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days - 1)).isoformat()
    out = []
    for p in glob.glob(os.path.join(sessions_dir(ws), '*.json')):
        try:
            with open(p, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and str(rec.get('date', '')) >= cutoff:
            out.append(rec)
    return sorted(out, key=lambda r: (r.get('date', ''), r.get('at', '')), reverse=True)


def waiting(recs):
    """What the newest session of each task left for the user (recs newest first), less what a later session settled."""
    seen, out = set(), []
    for r in recs:
        if r.get('task') in seen:
            continue
        seen.add(r.get('task'))
        seen |= SUPERSEDES.get(r.get('task'), set())
        out += [{'task': r['task'], 'date': r['date'], 'item': w} for w in r.get('waiting') or []]
    return out


def run_waiting(ws, cfg, today=None, days=RECENT_DAYS):
    """What the run files show waiting, summaries or not: the newest run's picks not confirmed yet, and each recent
    day's apply queue that still has roles not in the tracker."""
    from . import applied
    today = today or datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days - 1)).isoformat()
    queue = layout.queue(ws, cfg)
    out = []
    runs = sorted(glob.glob(os.path.join(queue, 'run-*.json')))
    if runs:
        date = os.path.basename(runs[-1])[len('run-'):-len('.json')]
        try:
            with open(runs[-1], encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            rec = {}
        if date >= cutoff and rec.get('roles') and not rec.get('picks') \
                and not os.path.exists(os.path.join(queue, f'reviewed-{date}.csv')):
            out.append({'task': 'daily-run', 'date': date,
                        'item': f"Confirm your picks for the {date} run on the review page"})
    for date, ids, done in applied.queues(ws):
        if date >= cutoff and done < len(ids):
            out.append({'task': 'apply-all', 'date': date,
                        'item': f"{len(ids) - done} of {len(ids)} roles queued on {date} not applied yet"})
    from . import materials
    pending = materials.pending_count(ws)
    if pending:
        out.append({'task': 'materials', 'date': today.isoformat(),
                    'item': f"{pending} proposed resume updates (bullets, bios, summaries, templates) waiting for your OK"})
    return out


# ---- links ----

def links(ws, cfg, today=None):
    """The files and pages used most, as (label, target, note); only ones that exist, plus the design editor."""
    today = today or datetime.date.today()
    base = layout.vault(ws, cfg)
    queue = layout.queue(ws, cfg)
    out = []

    def add(label, path, note=''):
        if path and os.path.exists(path):
            out.append((label, path, note))

    add('Workspace folder', ws)
    add('Dashboard (your applications, filters and tiles)', os.path.join(ws, 'report.html'), 'rebuilt after each tracker change')
    add('Tracker', os.path.join(ws, (cfg.get('tracker') or {}).get('csv') or 'tracker.csv'), 'the source of truth')
    sheet = (cfg.get('tracker') or {}).get('sheet_id')
    if sheet:
        out.append(('Tracker in Google Sheets', f'https://docs.google.com/spreadsheets/d/{sheet}', 'a one-way mirror'))
    pages = sorted(glob.glob(os.path.join(queue, 'review-*.html')))
    if pages:
        newest = pages[-1]
        day = os.path.basename(newest)[len('review-'):-len('.html')]
        add(f"Review page ({'today' if day == today.isoformat() else day})", newest)
    art = (cfg.get('review') or {}).get('artifact_url')
    if art:
        out.append(('Run Review page in Claude (private)', art, 'the Confirm choices button works here'))
    add('Ready to apply (application folders)', layout.ready(ws, cfg))
    add('Master resume (approved facts)', next((p for p in (os.path.join(ws, 'master-resume.md'),
                                                          os.path.join(base, 'master-resume.md')) if os.path.exists(p)), ''))
    add('Approved resumes', os.path.join(ws, 'resume', 'templates'))
    add('Resume drafts waiting for approval', os.path.join(ws, 'resume', 'draft'))
    out.append(('Resume design editor', '/get-me-hired:design', 'ask for it in your day session; it opens http://127.0.0.1:8765'))
    add('Facts for forms', os.path.join(ws, 'profile.yaml'))
    add('Your own answers', os.path.join(ws, 'answer-bank.md'))
    add('Target companies', os.path.join(ws, 'companies.txt'))
    add('Settings', os.path.join(ws, 'config.json'))
    add('Role-family pack (how roles are scored)', os.path.join(ws, cfg.get('pack') or 'pack.json'))
    add('Guide', os.path.join(REPO, 'docs', 'GUIDE.md'))
    return out


def _target(t):
    """A clickable link target: file:// for local paths (spaces and all), the rest as given."""
    if os.path.isabs(t):
        from pathlib import Path
        return Path(t).as_uri()
    return t


# ---- the brief ----

def data(ws, today=None, commands=COMMANDS, skills=SKILLS):
    ws = os.path.abspath(os.path.expanduser(ws))
    today = today or datetime.date.today()
    cfg = load_config(os.path.join(ws, 'config.json')) if os.path.exists(os.path.join(ws, 'config.json')) else {}
    recs = recent(ws, today)
    queue = layout.queue(ws, cfg)
    return {'workspace': ws, 'today': today.isoformat(),
            'daily_run_today': os.path.exists(os.path.join(queue, f'run-{today.isoformat()}.json'))
            or any(r.get('task') in ('daily-run', 'today') and r.get('date') == today.isoformat() for r in recs),
            'tasks': tasks(commands, skills), 'links': [{'label': l, 'target': t, 'note': n} for l, t, n in links(ws, cfg, today)],
            'waiting': run_waiting(ws, cfg, today) + waiting(recs), 'recent': recs}


def markdown(d):
    L = [f"# Job search home", '',
         f"Generated by `gmh home` on {d['today']}; it is rewritten each time, so don't edit it by hand.", '',
         '## How to start each day',
         'Open a new Claude Code session in this folder, switch it to Opus (`/model opus`), and run',
         '`/get-me-hired:today` (or say "run today\'s job search"). That one session takes you through the day: a Gmail',
         'sync, finding and scoring roles, your picks, resumes and drafts, filling forms, your submit approvals, and',
         'LinkedIn follow-up if you want it. Each step that needs a different model runs as a helper agent inside it.',
         'Say "wrap up" at the end of the day (it syncs Gmail again and rebuilds the dashboard); tomorrow, start a new',
         'session. If a session closes mid-day, start a new one',
         'and run `/get-me-hired:today` again: it picks up from the files. In another AI tool, ask for the',
         'get-me-hired today skill by name.', '',
         f"## Today ({d['today']})",
         '- Daily run: ' + ('done today (to run it again, the session asks first)' if d['daily_run_today'] else 'not started yet'),
         '', '## Waiting on you']
    L += [f"- {w['item']} ({w['task']}, {w['date']})" for w in d['waiting']] or ['- Nothing.']
    L += ['', '## What you can ask for', '| Task | Command | Model it names | When |', '|---|---|---|---|']
    L += [f"| {t['task']} | `{t['command']}` | {model_label(t)} | {t['when']} |" for t in d['tasks']]
    L += ['', '## Links']
    for x in d['links']:
        t = x['target']
        item = f"{x['label']}: `{t}`" if t.startswith('/get-me-hired:') else f"[{x['label']}](<{_target(t)}>)"
        L.append(f"- {item}" + (f" ({x['note']})" if x['note'] else ''))
    L += ['', f'## Recent sessions (last {RECENT_DAYS} days)']
    for r in d['recent']:
        L.append(f"- {r['date']} {r['task']}: {r['summary']}" + (f" Next: {r['next']}" if r.get('next') else ''))
    if not d['recent']:
        L.append('- None yet. Each day\'s wrap-up leaves a short summary here.')
    return '\n'.join(L) + '\n'


def write(ws, today=None):
    d = data(ws, today)
    text = markdown(d)
    with open(os.path.join(d['workspace'], 'HOME.md'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    return d, text


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.home')
    ap.add_argument('cmd', nargs='?', choices=['show', 'log'], default='show')
    ap.add_argument('task', nargs='?')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--summary', default='')
    ap.add_argument('--waiting', action='append', default=[])
    ap.add_argument('--next', default='')
    ap.add_argument('--auto', action='store_true', help="log: fill the counts from the day's files")
    ap.add_argument('--date')
    a = ap.parse_args(argv)
    ws = os.path.abspath(os.path.expanduser(a.workspace))
    if not os.path.isdir(ws):
        sys.exit(f'no workspace folder at {ws}')
    if a.cmd == 'log':
        if not a.task:
            sys.exit('usage: gmh home log <task> --summary "..." | --auto [--waiting "..."] [--next "..."]')
        summary = a.summary
        if a.auto:
            summary = auto_summary(ws, a.date) + (' ' + a.summary.strip() if a.summary.strip() else '')
        print(log(ws, a.task, summary, a.waiting, a.next, a.date))
    d, text = write(ws)
    if a.cmd == 'show':
        print(json.dumps(d, indent=1, ensure_ascii=False) if a.json else text, end='' if not a.json else '\n')


if __name__ == '__main__':
    main()
