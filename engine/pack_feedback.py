"""Pack feedback: what the user's own reviews say about their gaps and strengths, as pack-catalog proposals.

Mines Pipeline/queue/reviewed-*.csv (top_gap and gap_type of each row, notes of passed roles) and the read cache
Pipeline/state/reads/*.json (gap_type, top_gap, gap_quote, strengths), groups phrases that repeat across roles,
drops the ones pack.json / pack-base.json already cover, and proposes the rest in pack-catalog's format. It only
proposes: nothing here writes pack.json or pack-base.json.
"""
import collections, csv, datetime, glob, json, os, re

from . import packs
from .tracker import vault_of
from .runrecord import PICK_MARK

RANK = {'none': 0, 'minor': 1, 'major': 2, 'critical': 3}
LEVELS = {'strong': 1, 'excellent': 2}
STOP = set('a an and are as at be by for from has have in is it of on or the their to with your you our will can'.split())
PICK_NOTE = re.compile(re.escape(PICK_MARK) + r'(?: \([^)]*\))?: (.*?)(?=; |$)')
FILE_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})')


def _stem(w):
    for suf in ('ing', 'ies', 'ed', 'es', 's'):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)] + ('y' if suf == 'ies' else '')
    return w


def tokens(phrase):
    """The phrase's content words, lowercased and lightly stemmed, as a set (word order and plurals don't matter)."""
    return frozenset(_stem(w) for w in re.findall(r"[a-z0-9+#]+", (phrase or '').lower()) if w not in STOP)


def _json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _safe(rid):
    return re.sub(r'[^\w.-]', '_', rid)


def _file_day(path, stamp=None):
    m = FILE_DATE.search(os.path.basename(path))
    for s in (m.group(1) if m else None, (stamp or '')[:10]):
        try:
            return datetime.date.fromisoformat(s)
        except (TypeError, ValueError):
            pass
    return datetime.date.fromtimestamp(os.path.getmtime(path))


def _recent(day, days, today):
    return days is None or day >= today - datetime.timedelta(days=days)


def collect(ws, days=None, today=None):
    """([gap observations], [strength observations], roles): each observation is
    {id, phrase, kind, type (gap_type, or level), quote}; roles maps id -> {company, title}."""
    today = today or datetime.date.today()
    pipe = os.path.join(vault_of(ws), 'Pipeline')  # config paths.vault, else the workspace
    roles, gaps, strengths = {}, {}, {}  # gaps/strengths: (id, tokens) -> observation (worst/best kept)

    def gap(rid, phrase, kind, quote=''):
        phrase = re.sub(r'\s+', ' ', (phrase or '').strip().lower())
        if not rid or not tokens(phrase) or kind == 'none':
            return
        key = (rid, tokens(phrase))
        old = gaps.get(key)
        if not old or RANK.get(kind, 2) > RANK.get(old['type'], 2):
            gaps[key] = dict(id=rid, phrase=phrase, type=kind, quote=quote or (old or {}).get('quote', ''))

    for path in sorted(glob.glob(os.path.join(pipe, 'queue', 'reviewed-*.csv'))):
        if not _recent(_file_day(path), days, today):
            continue
        with open(path, encoding='utf-8', newline='') as fh:
            for row in csv.DictReader(fh):
                rid = (row.get('id') or '').strip()
                if not rid:
                    continue
                roles.setdefault(rid, dict(company=row.get('company', ''), title=row.get('title', '')))
                kind = (row.get('gap_type') or '').strip().lower() or 'major'
                gap(rid, row.get('top_gap'), kind)
                if (row.get('call') or '').strip().lower() == 'pass':
                    for note in PICK_NOTE.findall(row.get('notes') or ''):
                        gap(rid, note, 'major', note)
    for path in sorted(glob.glob(os.path.join(pipe, 'state', 'reads', '*.json'))):
        r = _json(path)
        if not isinstance(r, dict) or not r.get('id'):
            continue
        if not _recent(_file_day(path, str(r.get('read_at') or '')), days, today):
            continue
        rid = r['id']
        if rid not in roles:
            jd = os.path.join(pipe, 'state', 'jd', _safe(rid) + '.txt')
            head = ['', '']
            if os.path.exists(jd):
                with open(jd, encoding='utf-8', errors='replace') as fh:
                    head = fh.read().split('\n')[:2]
            roles[rid] = dict(company=head[1].strip() if len(head) > 1 else '', title=head[0].strip())
        gap(rid, r.get('top_gap'), str(r.get('gap_type') or '').lower(), r.get('gap_quote') or '')
        for s in r.get('strengths') or []:
            label = re.sub(r'\s+', ' ', str(s.get('label') or '').strip().lower())
            if not tokens(label):
                continue
            key, level = (rid, tokens(label)), str(s.get('level') or 'strong').lower()
            if key not in strengths or LEVELS.get(level, 1) > LEVELS.get(strengths[key]['type'], 1):
                strengths[key] = dict(id=rid, phrase=label, type=level, quote=s.get('posting') or '')
    return list(gaps.values()), list(strengths.values()), roles


def group(obs, merge=0.6):
    """Observations -> groups [{phrase, roles: {id: observation}}]. Phrases join a group when their word sets match,
    or overlap by at least `merge` (Jaccard); the most common wording names it. One observation per role."""
    groups = []  # [tokens, [observations]]
    for o in sorted(obs, key=lambda o: (o['phrase'], o['id'])):
        t = tokens(o['phrase'])
        for g in groups:
            if len(t & g[0]) / len(t | g[0]) >= merge:
                g[1].append(o)
                break
        else:
            groups.append([t, [o]])
    out = []
    for _, os_ in groups:
        names = collections.Counter(o['phrase'] for o in os_)
        name = sorted(names, key=lambda p: (-names[p], len(p), p))[0]
        best = {}
        for o in os_:
            old = best.get(o['id'])
            if not old or (RANK.get(o['type'], 2), LEVELS.get(o['type'], 1)) > (RANK.get(old['type'], 2), LEVELS.get(old['type'], 1)):
                best[o['id']] = o
        out.append(dict(phrase=name, roles=best))
    return out


def _patterns(pack_dir, keys):
    """Every regex the workspace's pack.json and pack-base.json hold under these keys."""
    out = []
    for f in ('pack.json', 'pack-base.json'):
        p = _json(os.path.join(pack_dir, f)) or {}
        for k in keys:
            for x in p.get(k) or []:
                if isinstance(x, dict) and x.get('pattern'):
                    try:
                        out.append(re.compile(x['pattern'], re.I))
                    except re.error:
                        pass
    return out


def covered(g, patterns, roles=None):
    """True when an existing pattern matches the group's phrase, any of its quotes, or (title gaps) a role title."""
    texts = [g['phrase']] + [o['quote'] for o in g['roles'].values() if o['quote']]
    texts += [(roles or {}).get(i, {}).get('title', '') for i in g['roles']] if roles is not None else []
    return any(rx.search(t) for rx in patterns for t in texts if t)


def _who(rid, roles):
    r = roles.get(rid) or {}
    return ': '.join(x for x in (r.get('company'), r.get('title')) if x) or rid


def _example(o, roles):
    q = (o['quote'] or '').strip()
    return _who(o['id'], roles) + (f' - "{q[:120]}"' if q else '')


def _counts(g, order):
    c = collections.Counter(o['type'] for o in g['roles'].values())
    return ', '.join(f'{c[t]} {t}' for t in order if c[t])


def propose(ws, days=None, min_roles=2, today=None, max_examples=3):
    """The feedback proposal (pack-catalog format plus `_note`, `_evidence`, `_examples`) and a stats dict."""
    ws = os.path.abspath(os.path.expanduser(ws))
    gap_obs, str_obs, roles = collect(ws, days, today)
    gap_pats = _patterns(ws, ('gaps', 'gap_catalog', 'title_gaps'))
    str_pats = _patterns(ws, ('strengths', 'strength_catalog'))
    stats = dict(gap_observations=len(gap_obs), strength_observations=len(str_obs), roles=len(roles),
                 repeats_covered=[], below_minimum=0)
    prop = {'_note': 'Feedback from your own reviews: additions for the pack. Edit, merge into the pack-seed proposal, '
                     'then run pack-catalog.', 'strengths': [], 'gaps': [], 'title_gaps': [], 'terms': [], 'exclude': []}
    for key, obs, pats in (('gaps', gap_obs, gap_pats), ('strengths', str_obs, str_pats)):
        kept = []
        for g in group(obs):
            n = len(g['roles'])
            if n < min_roles:
                stats['below_minimum'] += 1
            elif covered(g, pats, roles if key == 'gaps' else None):
                stats['repeats_covered'].append((key, g['phrase'], n))
            else:
                kept.append(g)
        for g in sorted(kept, key=lambda g: (-len(g['roles']), g['phrase'])):
            n, types = len(g['roles']), [o['type'] for o in g['roles'].values()]
            pattern = packs.words_pattern([g['phrase']])
            if key == 'gaps':
                weight, order = (10 if 'critical' in types else 6), ('critical', 'major', 'minor')
            else:
                weight, order = (4 if types.count('excellent') * 2 > n else 3), ('excellent', 'strong')
            ex = sorted(g['roles'].values(), key=lambda o: (-RANK.get(o['type'], 0), -LEVELS.get(o['type'], 0), o['id']))[:max_examples]
            prop[key].append(dict(
                label=g['phrase'], pattern=pattern, weight=weight,
                _evidence=f"in {n} roles: {_counts(g, order)}; e.g. " + '; '.join(_who(o['id'], roles) for o in ex),
                _examples=[_example(o, roles) for o in ex]))
    return prop, stats


def describe(prop, stats, days=None, min_roles=2):
    """The proposal in plain words, with the next step."""
    span = f'the last {days} days' if days else 'all saved reviews'
    out = [f"Pack feedback from {span}: {stats['roles']} roles, {stats['gap_observations']} gap notes, "
           f"{stats['strength_observations']} strengths (a phrase needs {min_roles}+ roles to count)."]
    for key, head, lead in (('gaps', 'Gaps you keep running into', 'postings that require it would score'),
                            ('strengths', 'Strengths the reads keep finding', 'postings that mention it would score')):
        out += ['', f'{head}:'] if prop[key] else []
        for e in prop[key]:
            out += [f"- {e['label']}: {e['_evidence']}", f"    {lead} {e['weight']} points {'lower' if key == 'gaps' else 'higher'}; "
                    f"starting pattern {e['pattern']}"] + [f'    {x}' for x in e['_examples']]
    if not (prop['gaps'] or prop['strengths']):
        out += ['', 'Nothing new to propose.']
    if stats['repeats_covered']:
        out += ['', 'Already in your pack (left out): ' + ', '.join(f'{p} ({n})' for _, p, n in stats['repeats_covered'])]
    return '\n'.join(out)
