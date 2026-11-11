"""Rolling resume material: grow the approved bullet bank, bios, summaries and template versions from what recent
applications kept asking for, one approved item at a time.

    python3 -m engine.materials save <id> <tailor-reply.json> --workspace <ws>   keep a resume-tailor reply's notes
    python3 -m engine.materials candidates [--days 30] --workspace <ws>           what recent roles kept asking for
    python3 -m engine.materials brief [--days 30] --workspace <ws>                packet for the material-drafter agent
    python3 -m engine.materials propose <drafter-reply.json> --workspace <ws>     check and store the drafts as pending
    python3 -m engine.materials show [--all] --workspace <ws>                     pending proposals, exact text and sources
    python3 -m engine.materials approve <pid> [--text "..."] [--id ID] --workspace <ws>
    python3 -m engine.materials reject <pid> [--reason "..."] --workspace <ws>
    python3 -m engine.materials reopen <pid> --workspace <ws>                    undo a rejection (checked again first)
    python3 -m engine.materials bios [--rejected] --workspace <ws>               bios on built resumes, numbered
    python3 -m engine.materials approve-bios all|1,3,5-9 [--except ..] [--reject ..] --workspace <ws>
    python3 -m engine.materials reopen-bios all|"<exact bio>" --workspace <ws>   undo turned-down bios

Where candidates come from:
- the resume tailor's reply (`gmh materials save` after each tailor run): `missing` (a true strength the posting
  asked for that the master resume states but no bank bullet does, with the master-resume line) and
  `material_feedback` (a bio, summary, skills line or template that fit the role badly);
- the posting reads' standout strengths whose master-resume line no bank bullet covers;
- bios used on resumes already built from a batch (`Pipeline/specs/*.json`) that aren't approved bios yet.

Nothing here writes resume material except `approve`, and only for the one proposal the user approved, with the
exact text they approved. Every proposal is checked when it is stored and again when it is approved:
- each source line is in the master resume (case, spacing and markdown ignored);
- every number in the text appears in its source lines;
- no gap or weakness wording;
- bullets: the experience exists, the id is free, the text isn't already a bullet;
- bios: short, no numbers, not already approved; summaries: a new name;
- templates: approved bios, summaries, skills and bank bullets only, each experience keeps its bullet count, and
  the result is a valid resume document.

Files: `<pipeline>/state/tailor/<id>.json` (saved replies), `<pipeline>/state/materials/candidates.json` and
`proposals.json`. Approving writes `<ws>/resume/bank.json` (bullets, `bios`, `summaries`) or a template (its
`version` goes up; the old one is kept in `resume/templates/.history/`), backs up the bank to `resume/.history/`
first, and appends to `resume/changes.json`.
"""
import argparse, copy, datetime, glob, json, os, re, sys

from . import layout
from . import specs as specs_mod
from .resume import validate as validate_resume

KINDS = ('bullet', 'bio', 'summary', 'template')
FEEDBACK_KINDS = ('bio', 'summary', 'skills', 'template')
SENT = 'used on a built resume'
GAP_RE = re.compile(r"\b(lack(?:s|ed|ing)?|limited|no experience|not yet|gaps?|weakness(?:es)?|learning|aspiring|"
                    r"eager to learn|haven'?t|have not|never|unfamiliar|new to)\b", re.I)
NUM_RE = re.compile(r'(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|x\b|k\b|m\b|mm\b|b\b|\+)?', re.I)
NUM_WORDS = ('two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
             'seventeen eighteen nineteen twenty dozen hundred hundreds thousand thousands million millions').split()
STOP = set('the and for with from into across that this their were was have has had over under about more than '
           'team teams work worked using used through while within each other they them our your'.split())
ID_RE = re.compile(r'^[A-Za-z0-9][\w-]{1,40}$')
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,30}$')


class MaterialError(ValueError):
    pass


# ---------- text helpers ----------

def norm(s):
    s = (s or '').replace('**', '').replace('__', '').replace('`', '')
    s = re.sub(r'[‘’]', "'", s)
    s = re.sub(r'[“”]', '"', s)
    s = re.sub(r'[–—]', '-', s)
    s = re.sub(r'^\s*(?:[-*+>#]+|\d+[.)])\s*', '', s)
    return re.sub(r'\s+', ' ', s).strip().lower()


def numbers(text):
    out = {re.sub(r'[\s,]', '', m.group(0)).lower().lstrip('$') for m in NUM_RE.finditer(norm(text))}
    words = set(re.findall(r'[a-z]+', norm(text)))
    return out | {w for w in NUM_WORDS if w in words}


def _bare(n):
    return re.sub(r'[%x+kmb]+$', '', n)


def numbers_missing(text, sources):
    """Numbers in `text` that none of `sources` states (digits compared without units, and number words)."""
    have = set()
    for s in sources:
        have |= numbers(s)
    bare = {_bare(n) for n in have}
    return sorted(n for n in numbers(text) if n not in have and _bare(n) not in bare)


def words(s):
    return {w for w in re.findall(r"[a-z0-9']+", norm(s)) if len(w) >= 4 and w not in STOP}


def covered(line, bullets, threshold=0.6):
    """Does some bank bullet already say most of what `line` says?"""
    a = words(line)
    if not a:
        return True
    return any(len(a & words(b.get('text', ''))) / len(a) >= threshold for b in bullets.values())


# ---------- workspace ----------

class Ctx:
    def __init__(self, ws):
        self.ws = os.path.abspath(os.path.expanduser(ws))
        self.P = layout.pipeline(self.ws)
        self.state = os.path.join(self.P, 'state')
        self.mdir = os.path.join(self.state, 'materials')
        self.resume = os.path.join(self.ws, 'resume')
        self.templates = specs_mod.load_templates(self.ws)
        self.bank_path = os.path.join(self.resume, 'bank.json')
        with open(self.bank_path, encoding='utf-8') as fh:
            self.raw_bank = json.load(fh)  # bank.json as stored (load_bank also merges skill_sets.json)
        self.bank = specs_mod.load_bank(self.ws)
        self.facts_path = next((p for p in (os.path.join(self.ws, 'master-resume.md'),
                                            os.path.join(layout.vault(self.ws), 'master-resume.md')) if os.path.exists(p)), '')
        text = open(self.facts_path, encoding='utf-8').read() if self.facts_path else ''
        self.master_lines = [norm(l) for l in text.splitlines() if norm(l)]
        self.master = '\n'.join(self.master_lines)

    def in_master(self, line):
        n = norm(line)
        return len(n) >= 12 and any(n in m for m in self.master_lines)

    def experiences(self):
        out = {}
        for doc in self.templates.values():
            for x in doc['experience']:
                if x.get('id'):
                    out.setdefault(x['id'], {'id': x['id'], 'company': x.get('company', ''), 'role': x.get('role', '')})
        return out

    def bank_id_of(self, text, exp=None):
        return next((bid for bid, b in self.bank['bullets'].items()
                     if b.get('text') == text and (exp is None or b.get('experience') in (None, exp))), None)

    def rejected_bios(self):
        try:
            with open(os.path.join(self.mdir, 'bios.json'), encoding='utf-8') as fh:
                return set(json.load(fh).get('rejected', []))
        except (OSError, ValueError):
            return set()

    def sent_bios(self):
        """Bios on resumes already built from a batch (spec overrides) that aren't approved or turned down:
        {norm: text}."""
        prefix = self.bank.get('bio_prefix', '')
        approved = specs_mod.approved_bios(self.templates, self.bank)
        rejected = self.rejected_bios()
        out = {}
        for p in glob.glob(os.path.join(self.P, 'specs', '*.json')):
            try:
                bio = (json.load(open(p, encoding='utf-8')).get('overrides') or {}).get('bio')
            except (OSError, ValueError):
                continue
            if bio and bio not in approved:
                short = bio[len(prefix):] if prefix and bio.startswith(prefix) else bio
                if '·' not in short and norm(short) not in rejected:
                    out.setdefault(norm(short), short)
        return out

    def load_proposals(self):
        try:
            with open(os.path.join(self.mdir, 'proposals.json'), encoding='utf-8') as fh:
                return json.load(fh).get('proposals', [])
        except (OSError, ValueError):
            return []

    def save_proposals(self, props):
        os.makedirs(self.mdir, exist_ok=True)
        with open(os.path.join(self.mdir, 'proposals.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'proposals': props}, fh, indent=1, ensure_ascii=False)
            fh.write('\n')


def pending_count(ws):
    """Pending proposals, for gmh today and HOME.md (0 when there is no materials state)."""
    try:
        with open(os.path.join(layout.pipeline(ws), 'state', 'materials', 'proposals.json'), encoding='utf-8') as fh:
            return sum(1 for p in json.load(fh).get('proposals', []) if p.get('status') == 'pending')
    except (OSError, ValueError, AttributeError):
        return 0


# ---------- save (tailor replies) ----------

def _clean_missing(items):
    out = []
    for m in items or []:
        if isinstance(m, dict) and isinstance(m.get('resume_line'), str) and m['resume_line'].strip():
            out.append({'experience': str(m.get('experience') or ''), 'fact': str(m.get('fact') or '')[:200],
                        'resume_line': m['resume_line'].strip()[:600]})
    return out


def _clean_feedback(items):
    out = []
    for f in items or []:
        if isinstance(f, dict) and f.get('kind') in FEEDBACK_KINDS and str(f.get('issue') or '').strip():
            out.append({'kind': f['kind'], 'template': str(f.get('template') or ''), 'issue': str(f['issue'])[:400],
                        'suggest': str(f.get('suggest') or '')[:400]})
    return out


def save(ws, rid, reply_path, now=None):
    """Keep one resume-tailor reply's notes (missing, material_feedback) for later review. Returns the record."""
    c = Ctx(ws)
    try:
        with open(reply_path, encoding='utf-8') as fh:
            reply = json.load(fh)
    except (OSError, ValueError) as e:
        raise MaterialError(f'{reply_path}: not a JSON tailor reply ({e})')
    if not isinstance(reply, dict):
        raise MaterialError('the tailor reply must be a JSON object')
    tname = (reply.get('spec') or {}).get('template', '')
    rec = {'id': rid, 'saved_at': (now or datetime.datetime.now()).isoformat(timespec='seconds'), 'template': tname,
           'template_version': specs_mod.template_version(c.templates[tname]) if tname in c.templates else '',
           'missing': _clean_missing(reply.get('missing')), 'material_feedback': _clean_feedback(reply.get('material_feedback')),
           'notes': str(reply.get('notes') or '')[:1000]}
    d = os.path.join(c.state, 'tailor')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, specs_mod.safe_id(rid) + '.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(rec, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return rec


# ---------- candidates ----------

def _recent(paths, field, cutoff):
    for p in paths:
        try:
            rec = json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and str(rec.get(field) or '') >= cutoff:
            yield rec


def queued_ids(ws, date):
    """The apply and manual ids of reviewed-<date>.csv: a day's picks."""
    import csv
    p = os.path.join(layout.queue(ws), f'reviewed-{date}.csv')
    if not os.path.exists(p):
        raise MaterialError(f'no reviewed-{date}.csv: pick roles first')
    with open(p, encoding='utf-8', newline='') as fh:
        return {r['id'] for r in csv.DictReader(fh) if (r.get('call') or '').strip().lower() in ('apply', 'manual') and r.get('id')}


def candidates(ws, days=30, now=None, focus=None):
    """What recent roles kept asking for, grouped, with the roles behind each. Writes candidates.json.
    With `focus` (role ids, e.g. a day's picks before their resumes are built), only candidates those roles asked for.
    Returns (candidates, ignored): ignored are claimed master-resume lines the master resume doesn't hold."""
    c = Ctx(ws)
    cutoff = ((now or datetime.datetime.now()) - datetime.timedelta(days=days)).isoformat(timespec='seconds')
    taken = {p.get('key') for p in c.load_proposals()}
    groups, ignored = {}, []

    def add(key, base, role, **extra):
        g = groups.setdefault(key, dict(base, key=key, roles=[], issues=[], suggests=[]))
        if role and role not in g['roles']:
            g['roles'].append(role)
        for k in ('issues', 'suggests'):
            v = extra.get(k[:-1])
            if v and v not in g[k]:
                g[k].append(v)

    def bullet_line(line, exp, role, fact=''):
        if not c.in_master(line):
            if line not in ignored:
                ignored.append(line)
            return
        if covered(line, c.bank['bullets']):
            return
        add('line:' + norm(line), {'kind': 'bullet', 'experience': exp or '', 'resume_line': line.strip(),
                                    'fact': fact}, role)

    for rec in _recent(sorted(glob.glob(os.path.join(c.state, 'tailor', '*.json'))), 'saved_at', cutoff):
        for m in rec.get('missing') or []:
            bullet_line(m['resume_line'], m.get('experience'), rec.get('id'), m.get('fact', ''))
        for f in rec.get('material_feedback') or []:
            kind = 'template' if f['kind'] in ('template', 'skills') else f['kind']
            add(f"{kind}:{f.get('template') or ''}", {'kind': kind, 'template': f.get('template') or '',
                                                      'feedback_kind': f['kind']},
                rec.get('id'), issue=f.get('issue'), suggest=f.get('suggest'))
    for rec in _recent(sorted(glob.glob(os.path.join(c.state, 'reads', '*.json'))), 'read_at', cutoff):
        for s in rec.get('strengths') or []:
            line = (s or {}).get('resume') if isinstance(s, dict) else None
            if line and len(norm(line)) >= 25:
                bullet_line(line, '', rec.get('id'), (s or {}).get('label', ''))

    out = [g for g in groups.values() if g['key'] not in taken]
    if focus is not None:
        focus = set(focus)
        out = [g for g in out if focus & set(g['roles'])]
    out.sort(key=lambda g: (-len(g['roles']), KINDS.index(g['kind']), g['key']))
    for i, g in enumerate(out, 1):
        g['cid'] = f'c{i}'
    os.makedirs(c.mdir, exist_ok=True)
    with open(os.path.join(c.mdir, 'candidates.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'made': (now or datetime.datetime.now()).isoformat(timespec='seconds'), 'days': days,
                   'focus': sorted(focus) if focus is not None else None,
                   'candidates': out, 'ignored': ignored}, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return out, ignored


def load_candidates(c):
    try:
        with open(os.path.join(c.mdir, 'candidates.json'), encoding='utf-8') as fh:
            return {g['cid']: g for g in json.load(fh).get('candidates', [])}
    except (OSError, ValueError):
        return {}


def candidate_lines(cands, ignored, sent=0):
    L = []
    if sent:
        L.append(f'{sent} bios already used on built resumes are not approved yet: review them as one list '
                 '(gmh materials bios; approve with gmh materials approve-bios).')
    if not cands:
        L.append('No resume updates to draft: recent roles asked for nothing the bank, bios and templates lack.')
    else:
        counts = {k: sum(1 for g in cands if g['kind'] == k) for k in KINDS}
        L += [f"{len(cands)} resume update candidates: {counts['bullet']} bullets, {counts['bio']} bios, "
             f"{counts['summary']} summaries, {counts['template']} templates (drafted by the material-drafter)"]
        for g in cands:
            who = f"{len(g['roles'])} role(s)" if g['roles'] else g.get('source', '')
            what = g.get('resume_line') or g.get('text') or '; '.join(g['issues'][:2]) or g['key']
            L.append(f"  {g['cid']}  {g['kind']:<8} {who:<16} {what[:110]}")
    for line in ignored:
        L.append(f'  not in master resume (ignored): {line[:110]}')
    return L


# ---------- brief ----------

def brief(ws, days=30, now=None, focus=None):
    c = Ctx(ws)
    cands, _ = candidates(ws, days, now, focus)
    prefix = c.bank.get('bio_prefix', '')
    exps = c.experiences()
    for eid, x in exps.items():
        own = [(bid, b['text']) for bid, b in sorted(c.bank['bullets'].items()) if b.get('experience') == eid]
        x['examples'] = [{'id': bid, 'text': t} for bid, t in own[:4]]
        x['bullet_ids'] = [bid for bid, _ in own]
    tpls = {}
    for name, doc in sorted(c.templates.items()):
        tpls[name] = {'version': doc.get('version', 1), 'bio': doc.get('bio', ''), 'summary': doc.get('summary', ''),
                      'skills': doc.get('skills', ''),
                      'experience': {x.get('id') or str(i): [c.bank_id_of(b, x.get('id')) or b for b in x['bullets']]
                                     for i, x in enumerate(doc['experience'])}}
    return {
        'facts_path': c.facts_path,
        'candidates': cands,
        'experiences': list(exps.values()),
        'bio_prefix': prefix,
        'bios': sorted(b[len(prefix):] if prefix and b.startswith(prefix) else b
                       for b in specs_mod.approved_bios(c.templates, c.bank)),
        'summaries': {f'template:{n}': t['summary'] for n, t in sorted(c.templates.items())}
                     | {f'bank:{n}': s for n, s in sorted((c.bank.get('summaries') or {}).items())},
        'templates': tpls,
        'skills': c.bank.get('skills', []), 'skill_sets': c.bank.get('skill_sets', {}),
        'rules': [
            'Every proposal rests on master-resume lines quoted exactly in source.',
            'No number, scope, title, team size, tool, client or outcome the source lines do not state; the engine '
            'rejects any number missing from them.',
            'Strengths only: never a gap, a weakness or something the candidate has not done.',
            'Bullets: past-tense verb first, the result in **bold**, about as long as the examples for that experience.',
            'Bios: the text after bio_prefix, three or four short domains joined with " & " or ", ", no numbers.',
            'Summaries: like the template summaries in length and tone, with a short lowercase name.',
            'Templates: change only bio (an approved bio), summary (a summaries key), skills (approved terms or @sets) '
            'or experience bullet lists (bank ids of that experience, same count as now). Propose one only when '
            'several roles flagged the same template.',
            'One proposal per candidate; skip a candidate an existing bullet already says or the master resume cannot '
            'support, and say why in notes.'],
        'return_format': {
            'proposals': [
                {'candidate': 'c1', 'kind': 'bullet', 'experience': 'acme', 'text': 'Led ... **result**',
                 'source': ['exact master-resume line']},
                {'candidate': 'c2', 'kind': 'bio', 'text': 'Platform & Developer Tools', 'source': ['...']},
                {'candidate': 'c3', 'kind': 'summary', 'name': 'platform', 'text': '...', 'source': ['...']},
                {'candidate': 'c4', 'kind': 'template', 'base': 'Ops', 'why': '...',
                 'changes': {'bio': 'an approved bio', 'summary': 'template:Ops', 'skills': ['@core', 'Term'],
                             'experience': {'acme': ['ID1', 'ID2']}}}],
            'notes': ''}}


# ---------- checks ----------

def _common_text(p, c, problems):
    text = (p.get('text') or '').strip()
    if not text:
        problems.append('no text')
        return text, []
    src = [s for s in (p.get('source') or []) if isinstance(s, str) and s.strip()]
    if GAP_RE.search(text):
        problems.append(f'names a gap or weakness ("{GAP_RE.search(text).group(0)}")')
    if '\u2014' in text or '\u2013' in text:
        problems.append('no em or en dashes')
    return text, src


def _sources_ok(src, c, problems):
    if not src:
        problems.append('no source lines (quote the master-resume lines it rests on)')
    for s in src:
        if not c.in_master(s):
            problems.append(f'source not in the master resume: "{s[:80]}"')


def template_doc(base, changes, c):
    """The base template with `changes` applied (bio, summary, skills, experience). Raises MaterialError."""
    doc = copy.deepcopy(c.templates[base])
    prefix = c.bank.get('bio_prefix', '')
    bad = set(changes) - {'bio', 'summary', 'skills', 'experience'}
    if bad or not changes:
        raise MaterialError('changes may only set bio, summary, skills or experience' + (f' (not {", ".join(sorted(bad))})' if bad else ''))
    if 'bio' in changes:
        b = changes['bio'] if '·' in changes['bio'] else prefix + changes['bio']
        if b not in specs_mod.approved_bios(c.templates, c.bank):
            raise MaterialError(f"bio {changes['bio']!r} is not approved (approve it as a bio first)")
        doc['bio'] = b
    if 'summary' in changes:
        s = changes['summary']
        if s.startswith('template:') and s[9:] in c.templates:
            doc['summary'] = c.templates[s[9:]]['summary']
        elif s.startswith('bank:') and s[5:] in (c.bank.get('summaries') or {}):
            doc['summary'] = c.bank['summaries'][s[5:]]
        else:
            raise MaterialError(f'summary {s!r} must be template:<Name> or bank:<name>')
    if 'skills' in changes:
        try:
            doc['skills'] = specs_mod.skills_line(changes['skills'], c.bank)
        except specs_mod.SpecError as e:
            raise MaterialError(str(e))
    for eid, ids in (changes.get('experience') or {}).items():
        i = next((k for k, x in enumerate(doc['experience']) if x.get('id') == eid), None)
        if i is None:
            raise MaterialError(f'template {base} has no experience {eid!r}')
        texts = []
        for bid in ids:
            b = c.bank['bullets'].get(bid)
            if not b:
                raise MaterialError(f'unknown bullet id {bid!r}')
            if b.get('experience') not in (None, eid):
                raise MaterialError(f'bullet {bid} belongs to {b.get("experience")}, not {eid}')
            texts.append(b['text'])
        if len(set(texts)) != len(texts):
            raise MaterialError(f'duplicate bullet in {eid}')
        if len(texts) != len(doc['experience'][i]['bullets']):
            raise MaterialError(f"{eid} must keep {len(doc['experience'][i]['bullets'])} bullets (the page layout)")
        doc['experience'][i]['bullets'] = texts
    try:
        validate_resume(doc)
    except ValueError as e:
        raise MaterialError(str(e))
    if {k: v for k, v in doc.items() if k != 'version'} == {k: v for k, v in c.templates[base].items() if k != 'version'}:
        raise MaterialError('the changes leave the template as it is')
    return doc


def check(p, c, approving=False):
    """Problems with one proposal (empty when it passes)."""
    problems = []
    kind = p.get('kind')
    if kind not in KINDS:
        return [f"kind must be one of {', '.join(KINDS)}"]
    if kind == 'template':
        if p.get('base') not in c.templates:
            return [f"unknown template {p.get('base')!r}"]
        try:
            template_doc(p['base'], p.get('changes') or {}, c)
        except MaterialError as e:
            problems.append(str(e))
        return problems
    text, src = _common_text(p, c, problems)
    if not text:
        return problems
    if kind == 'bio':
        prefix = c.bank.get('bio_prefix', '')
        if '·' in text or len(text) > 70 or re.search(r'\d', re.sub(r'\b0[- ]to[- ]1\b', '', text)):
            problems.append('a bio is the short text after the prefix: no "·", no numbers (0-to-1 is fine), '
                            '70 characters at most')
        if (prefix + text) in specs_mod.approved_bios(c.templates, c.bank):
            problems.append('already an approved bio')
        if src == [SENT]:
            if norm(text) not in c.sent_bios():
                problems.append(f'source "{SENT}" needs the exact text of a bio already on a built resume')
        else:
            _sources_ok(src, c, problems)
        return problems
    _sources_ok(src, c, problems)
    miss = numbers_missing(text, src)
    if miss:
        problems.append('numbers not in the source lines: ' + ', '.join(miss))
    if kind == 'bullet':
        exp = p.get('experience')
        if exp not in c.experiences():
            problems.append(f'unknown experience {exp!r}')
        if len(text) > 320:
            problems.append('too long for a bullet (320 characters at most)')
        if any(norm(b.get('text')) == norm(text) for b in c.bank['bullets'].values()):
            problems.append('already a bank bullet')
        bid = p.get('id')
        if bid and (not ID_RE.match(bid) or bid in c.bank['bullets']):
            problems.append(f'bullet id {bid!r} is taken or not a valid id')
    elif kind == 'summary':
        name = p.get('name') or ''
        if not NAME_RE.match(name):
            problems.append('a summary needs a short lowercase name (letters, digits, dashes)')
        elif name in (c.bank.get('summaries') or {}):
            problems.append(f'summary name {name!r} is taken')
        if not 80 <= len(text) <= 900:
            problems.append('a summary is 80 to 900 characters')
    return problems


# ---------- propose / show / approve / reject ----------

def propose(ws, reply_path, now=None):
    """Check the drafter's proposals and store the ones that pass as pending. Returns (added pids, rejected
    [(index, candidate, problems)])."""
    c = Ctx(ws)
    try:
        reply = json.load(open(reply_path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise MaterialError(f'{reply_path}: not JSON ({e})')
    cands = load_candidates(c)
    props = c.load_proposals()
    n = max([int(p['pid'][1:]) for p in props if re.match(r'^p\d+$', p.get('pid', ''))] or [0])
    taken = {p.get('key') for p in props}
    added, rejected = [], []
    stamp = (now or datetime.datetime.now()).isoformat(timespec='seconds')
    for i, p in enumerate((reply or {}).get('proposals') or []):
        if not isinstance(p, dict):
            rejected.append((i, '', ['not an object']))
            continue
        g = cands.get(p.get('candidate'))
        problems = [] if g else [f"unknown candidate {p.get('candidate')!r} (run gmh materials brief again)"]
        if g and g['key'] in taken:
            problems.append('that candidate already has a proposal')
        problems += check(p, c)
        if problems:
            rejected.append((i, p.get('candidate', ''), problems))
            continue
        n += 1
        keep = {k: p[k] for k in ('kind', 'text', 'experience', 'id', 'name', 'base', 'changes', 'why', 'source') if k in p}
        props.append(dict(keep, pid=f'p{n}', status='pending', candidate=p['candidate'], key=g['key'],
                          roles=g.get('roles', []), issues=g.get('issues', []), created=stamp))
        taken.add(g['key'])
        added.append(f'p{n}')
    c.save_proposals(props)
    return added, rejected


def show_lines(ws, all_=False):
    c = Ctx(ws)
    props = [p for p in c.load_proposals() if all_ or p.get('status') == 'pending']
    if not props:
        return ['No pending resume updates.']
    L = []
    for p in props:
        head = f"{p['pid']} [{p['status']}] {p['kind']}"
        if p['kind'] == 'bullet':
            head += f" for {p.get('experience')}"
        elif p['kind'] == 'summary':
            head += f" '{p.get('name')}'"
        elif p['kind'] == 'template':
            head += f" {p.get('base')} v{c.templates.get(p.get('base'), {}).get('version', 1)} -> next version"
        L.append(head + (f"  ({len(p['roles'])} role(s) asked)" if p.get('roles') else ''))
        if p['kind'] == 'template':
            base = c.templates.get(p.get('base'), {})
            for k, v in (p.get('changes') or {}).items():
                if k == 'experience':
                    for eid, ids in v.items():
                        old = next((x['bullets'] for x in base.get('experience', []) if x.get('id') == eid), [])
                        L.append(f'    {eid}: ' + ', '.join(ids) + f'  (was {len(old)} bullets: ' +
                                 ', '.join(c.bank_id_of(t, eid) or '?' for t in old) + ')')
                else:
                    L.append(f'    {k}: {v}' + (f"  (was: {base.get(k, '')[:80]})" if k in ('bio', 'summary', 'skills') else ''))
            if p.get('why'):
                L.append(f"    why: {p['why']}")
        else:
            L.append(f"    text: {p.get('final_text') or p.get('text')}")
            for s in p.get('source') or []:
                L.append(f'    source: {s}')
        if p.get('reason'):
            L.append(f"    reason: {p['reason']}")
    return L


def _backup_bank(c, stamp):
    d = os.path.join(c.resume, '.history')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f'bank-{stamp}.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(c.raw_bank, fh, indent=1, ensure_ascii=False)


def _write_bank(c):
    with open(c.bank_path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(c.raw_bank, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def _log(c, entry):
    p = os.path.join(c.resume, 'changes.json')
    try:
        log = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        log = []
    log.append(entry)
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(log, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def approve(ws, pid, text=None, new_id=None, now=None):
    """Write one approved proposal (with the exact text the user approved). Returns a one-line description."""
    c = Ctx(ws)
    props = c.load_proposals()
    p = next((x for x in props if x.get('pid') == pid), None)
    if not p:
        raise MaterialError(f'no proposal {pid}')
    if p.get('status') != 'pending':
        raise MaterialError(f"{pid} is {p.get('status')}, not pending")
    if text is not None and p['kind'] == 'template':
        raise MaterialError('a template proposal takes no --text')
    q = dict(p, text=text.strip() if text is not None else p.get('text'), id=new_id or p.get('id'))
    problems = check(q, c, approving=True)
    if problems:
        raise MaterialError(f'{pid} fails its checks: ' + '; '.join(problems))
    when = now or datetime.datetime.now()
    stamp, day = when.strftime('%Y%m%d-%H%M%S'), when.date().isoformat()
    if p['kind'] == 'template':
        base = p['base']
        doc = template_doc(base, p['changes'], c)
        old_v = c.templates[base].get('version', 1)
        hist = os.path.join(c.resume, 'templates', '.history')
        os.makedirs(hist, exist_ok=True)
        with open(os.path.join(hist, f'{base}@v{old_v}.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(c.templates[base], fh, indent=1, ensure_ascii=False)
        doc['version'] = old_v + 1
        with open(os.path.join(c.resume, 'templates', base + '.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write('\n')
        target = f'template {base} v{old_v + 1} ({specs_mod.template_version(doc)})'
    else:
        _backup_bank(c, stamp)
        if p['kind'] == 'bullet':
            exp = q['experience']
            bid = q.get('id')
            if not bid:
                k = 1
                while f'{exp}-m{k:02d}' in c.raw_bank.get('bullets', {}):
                    k += 1
                bid = f'{exp}-m{k:02d}'
            c.raw_bank.setdefault('bullets', {})[bid] = {'text': q['text'], 'experience': exp, 'added': day, 'proposal': pid}
            target = f'bullet {bid} ({exp})'
        elif p['kind'] == 'bio':
            c.raw_bank.setdefault('bios', []).append(q['text'])
            target = 'bio'
        else:
            c.raw_bank.setdefault('summaries', {})[q['name']] = q['text']
            target = f"summary bank:{q['name']}"
        _write_bank(c)
    p.update(status='approved', decided=when.isoformat(timespec='seconds'), target=target)
    if text is not None and text.strip() != (p.get('text') or ''):
        p['final_text'] = text.strip()
    c.save_proposals(props)
    _log(c, {'date': day, 'pid': pid, 'kind': p['kind'], 'target': target,
             **({'changes': p['changes']} if p['kind'] == 'template' else {'text': q['text']})})
    return f'{pid} approved: {target}'


def reject(ws, pid, reason='', now=None):
    c = Ctx(ws)
    props = c.load_proposals()
    p = next((x for x in props if x.get('pid') == pid), None)
    if not p:
        raise MaterialError(f'no proposal {pid}')
    if p.get('status') != 'pending':
        raise MaterialError(f"{pid} is {p.get('status')}, not pending")
    p.update(status='rejected', reason=reason.strip(), decided=(now or datetime.datetime.now()).isoformat(timespec='seconds'))
    c.save_proposals(props)
    return f'{pid} rejected (its candidate will not come back)'


# ---------- bios already used on built resumes (one list, approved in one step) ----------

def sent_bio_list(ws):
    """[(n, text)], numbered from 1, alphabetical: bios on built resumes that aren't approved or turned down."""
    return list(enumerate(sorted(Ctx(ws).sent_bios().values(), key=str.lower), 1))


def sent_bio_count(ws):
    try:
        return len(Ctx(ws).sent_bios())
    except Exception:  # no templates or bank yet: nothing to count
        return 0


def bio_page(items, page=1, per=20):
    """(rows on that page, page, pages): numbering stays global. Raises MaterialError for a page that does not exist."""
    per = max(1, int(per))
    pages = max(1, -(-len(items) // per))
    if not 1 <= page <= pages:
        raise MaterialError(f'page {page} does not exist (page 1 to {pages})')
    return items[(page - 1) * per:page * per], page, pages


# ---------- fit: a reword only to meet a layout rule ----------

def fit(ws, bid, text, now=None):
    """Replace one bank bullet's text with a shorter or reflowed version that keeps every number of the original
    and adds none. Logged (kind 'fit', before and after) in resume/changes.json. Returns (before, after).
    Any other change of wording goes through propose and approve."""
    from . import redline
    c = Ctx(ws)
    b = c.raw_bank.get('bullets', {}).get(bid)
    if not b:
        raise MaterialError(f'no bank bullet {bid!r}')
    before, after = b['text'], (text or '').strip()
    problems = []
    if not after:
        raise MaterialError('no text')
    if after == before:
        raise MaterialError('the text is unchanged')
    old, new = redline.numbers(before) | numbers(before), redline.numbers(after) | numbers(after)
    if redline.numbers(before) != redline.numbers(after) or numbers(before) != numbers(after):
        lost, added = sorted(old - new), sorted(new - old)
        problems.append('numbers changed' + (f'; missing: {", ".join(lost)}' if lost else '')
                        + (f'; added: {", ".join(added)}' if added else '')
                        + ' (a fit reword keeps every number and adds none; use propose for anything else)')
    gap = GAP_RE.search(after)
    if gap and not GAP_RE.search(before):
        problems.append(f'names a gap or weakness ("{gap.group(0)}")')
    if '—' in after or '–' in after:
        problems.append('no em or en dashes')
    if before.count('**') and after.count('**') != before.count('**'):
        problems.append('keep the bold marks (**) the original has')
    if problems:
        raise MaterialError('; '.join(problems))
    when = now or datetime.datetime.now()
    _backup_bank(c, when.strftime('%Y%m%d-%H%M%S'))
    b['text'] = after
    _write_bank(c)
    _log(c, {'date': when.date().isoformat(), 'kind': 'fit', 'target': f'bullet {bid}', 'before': before, 'after': after})
    return before, after


def _refs(text, n):
    """'all' or '1,3,5-9' -> sorted numbers within 1..n. Raises MaterialError."""
    text = (text or '').strip().lower()
    if text == 'all':
        return list(range(1, n + 1))
    if text in ('none', '-'):
        return []
    out = set()
    for part in filter(None, re.split(r'[,\s]+', text)):
        m = re.fullmatch(r'(\d+)(?:-(\d+))?', part)
        if not m:
            raise MaterialError(f'not a number or range: {part!r} (use all, or e.g. 1,3,5-9)')
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if not 1 <= a <= b <= n:
            raise MaterialError(f'{part} is outside 1-{n}')
        out |= set(range(a, b + 1))
    return sorted(out)


def approve_bios(ws, refs, except_refs='', reject_refs='', now=None):
    """Approve listed bios as written (numbers from sent_bio_list; they go into bank.json `bios`), and turn down
    `reject_refs` from the same list in the same step. Returns (approved texts, turned-down texts)."""
    c = Ctx(ws)
    items = sent_bio_list(ws)
    out_ = set(_refs(reject_refs, len(items))) if reject_refs else set()
    pick = set(_refs(refs, len(items))) - (set(_refs(except_refs, len(items))) if except_refs else set()) - out_
    texts = [t for n, t in items if n in pick]
    turned = [t for n, t in items if n in out_]
    if not texts and not turned:
        raise MaterialError('no bios chosen')
    if turned:
        _save_rejected(c, turned)
    if not texts:
        return [], turned
    when = now or datetime.datetime.now()
    _backup_bank(c, when.strftime('%Y%m%d-%H%M%S'))
    bios = c.raw_bank.setdefault('bios', [])
    bios += [t for t in texts if t not in bios]
    _write_bank(c)
    _log(c, {'date': when.date().isoformat(), 'pid': 'sent-bios', 'kind': 'bio', 'target': 'bios', 'texts': texts})
    return texts, turned


def _save_rejected(c, texts):
    rejected = c.rejected_bios() | {norm(t) for t in texts}
    os.makedirs(c.mdir, exist_ok=True)
    with open(os.path.join(c.mdir, 'bios.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'rejected': sorted(rejected)}, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def reject_bios(ws, refs):
    """Turn down listed bios on their own: they aren't offered again."""
    return approve_bios(ws, 'none', reject_refs=refs)[1]


def reopen(ws, pid, now=None):
    """Undo a rejection: the proposal goes back to pending once it passes its checks again (the bank or the master
    resume may have changed since). An approved proposal can't be reopened: it is already in the bank."""
    c = Ctx(ws)
    props = c.load_proposals()
    p = next((x for x in props if x.get('pid') == pid), None)
    if not p:
        raise MaterialError(f'no proposal {pid}')
    if p.get('status') != 'rejected':
        raise MaterialError(f"{pid} is {p.get('status')}; only a rejected proposal can be reopened")
    problems = check(p, c)
    if problems:
        raise MaterialError(f'{pid} no longer passes its checks: ' + '; '.join(problems))
    p['reopened'] = (now or datetime.datetime.now()).isoformat(timespec='seconds')
    p['status'] = 'pending'
    for k in ('reason', 'decided'):
        p.pop(k, None)
    c.save_proposals(props)
    return f'{pid} is pending again'


def rejected_bio_list(ws):
    """Turned-down bios still on a built resume, as text, alphabetical."""
    c = Ctx(ws)
    rej = c.rejected_bios()
    prefix = c.bank.get('bio_prefix', '')
    out = {}
    for p in glob.glob(os.path.join(c.P, 'specs', '*.json')):
        try:
            bio = (json.load(open(p, encoding='utf-8')).get('overrides') or {}).get('bio') or ''
        except (OSError, ValueError):
            continue
        short = bio[len(prefix):] if prefix and bio.startswith(prefix) else bio
        if norm(short) in rej:
            out.setdefault(norm(short), short)
    return sorted(out.values(), key=str.lower)


def reopen_bios(ws, which):
    """Undo turned-down bios ('all' or one bio's exact text): they are offered on the list again."""
    c = Ctx(ws)
    rej = c.rejected_bios()
    if (which or '').strip().lower() == 'all':
        back = set(rej)
    else:
        back = {norm(which)} & rej
        if not back:
            raise MaterialError(f'no turned-down bio {which!r} (gmh materials bios --rejected lists them)')
    with open(os.path.join(c.mdir, 'bios.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'rejected': sorted(rej - back)}, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return len(back)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gmh materials', description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=['save', 'candidates', 'brief', 'propose', 'show', 'approve', 'reject',
                                    'reopen', 'bios', 'approve-bios', 'reject-bios', 'reopen-bios', 'fit'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--date', help="candidates, brief: only what that day's picks asked for (before their resumes are built)")
    ap.add_argument('--ids', nargs='+', help='candidates, brief: only what these roles asked for')
    ap.add_argument('--text')
    ap.add_argument('--id', dest='new_id')
    ap.add_argument('--reason', default='')
    ap.add_argument('--except', dest='except_refs', default='', help='approve-bios: numbers to leave for later')
    ap.add_argument('--reject', dest='reject_refs', default='', help='approve-bios: numbers to turn down in the same step')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--page', type=int, default=1, help='bios: which page of the list')
    ap.add_argument('--per', type=int, default=20, help='bios: bios per page')
    ap.add_argument('--out', help="brief: write the packet here (default <pipeline>/scratch/<today>/materials-brief-<key>.json; '-' prints it)")
    ap.add_argument('--rejected', action='store_true', help='bios: list the turned-down ones')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    a = ap.parse_args(argv)
    ws = os.path.abspath(os.path.expanduser(a.workspace))
    need = {'save': 2, 'propose': 1, 'approve': 1, 'reject': 1, 'reopen': 1, 'approve-bios': 1, 'reject-bios': 1,
            'reopen-bios': 1, 'fit': 2}.get(a.cmd, 0)
    if len(a.args) != need:
        ap.error(f'{a.cmd} takes {need} argument(s)')
    try:
        focus = (queued_ids(ws, a.date) if a.date else set()) | set(a.ids or []) if (a.date or a.ids) else None
        if a.cmd == 'save':
            rec = save(ws, a.args[0], a.args[1])
            print(f"saved {a.args[0]}: {len(rec['missing'])} missing, {len(rec['material_feedback'])} material notes")
        elif a.cmd == 'candidates':
            print('\n'.join(candidate_lines(*candidates(ws, a.days, focus=focus), sent=sent_bio_count(ws))))
        elif a.cmd == 'reopen':
            print(reopen(ws, a.args[0]))
        elif a.cmd == 'reopen-bios':
            print(f'{reopen_bios(ws, a.args[0])} turned-down bio(s) back on the list (gmh materials bios)')
        elif a.cmd == 'bios' and a.rejected:
            rej = rejected_bio_list(ws)
            print(f'{len(rej)} turned-down bio(s) (bring back with gmh materials reopen-bios all|"<exact bio>"):'
                  if rej else 'No turned-down bios.')
            for t in rej:
                print(f'  - {t}')
        elif a.cmd == 'bios':
            items = sent_bio_list(ws)
            print(f'{len(items)} bios used on built resumes, not approved yet (approve as written: '
                  'gmh materials approve-bios all|1,3,5-9 [--except 4,7] [--reject 2,8]; numbers are from this list)'
                  if items else 'No unapproved bios on built resumes.')
            rows, page, pages = bio_page(items, a.page, a.per)
            for n, t in rows:
                print(f'  {n:>3}. {t}')
            if items:
                print(f'page {page} of {pages}' + (f' (next: gmh materials bios --page {page + 1})' if page < pages else ''))
        elif a.cmd == 'approve-bios':
            texts, turned = approve_bios(ws, a.args[0], a.except_refs, a.reject_refs)
            print(f'{len(texts)} bio(s) approved (the resume tailor can use them from the next application on)'
                  + (f'; {len(turned)} turned down (not offered again)' if turned else '') + '.')
        elif a.cmd == 'reject-bios':
            print(f'{len(reject_bios(ws, a.args[0]))} bio(s) turned down; they will not be offered again.')
        elif a.cmd == 'brief':
            text = json.dumps(brief(ws, a.days, focus=focus), indent=1, ensure_ascii=False)
            if a.out == '-':
                print(text)
            else:
                path = os.path.abspath(a.out) if a.out else layout.scratch(ws, 'materials-brief', a.date or 'all')
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write(text + '\n')
                print(path)
        elif a.cmd == 'fit':
            before, after = fit(ws, a.args[0], a.args[1])
            print(f'fit {a.args[0]}\n  before: {before}\n  after:  {after}')
        elif a.cmd == 'propose':
            added, rejected = propose(ws, a.args[0])
            print(f"{len(added)} proposal(s) stored as pending: {', '.join(added) or '-'}")
            for i, cid, probs in rejected:
                print(f"  rejected #{i} ({cid or 'no candidate'}): " + '; '.join(probs))
        elif a.cmd == 'show':
            print('\n'.join(show_lines(ws, a.all)))
        elif a.cmd == 'approve':
            print(approve(ws, a.args[0], a.text, a.new_id))
        else:
            print(reject(ws, a.args[0], a.reason))
    except (MaterialError, specs_mod.SpecError) as e:
        sys.exit(f'gmh materials {a.cmd}: {e}')


if __name__ == '__main__':
    main()
