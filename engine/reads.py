"""Gap and strength reads: a posting-reader's verdict on one posting against the master resume, cached so
scoring can use it (engine/triage.py apply_read) and picks can copy it into the reviewed row.

Cache: <vault>/Pipeline/state/reads/<safe id>.json, the reply row plus jd_sha (sha1 of the saved JD text),
resume_sha (sha1 of the resume text score.evidence returns) and read_at. A read counts only while both hashes
still match: a changed posting or resume makes it stale, and `gmh review reads` lists the role again.

A reply is {"rows": [{id, gap_type, top_gap, gap_quote, strengths: [{label, level, resume, posting}], needs,
concerns, pay}]}. validate() rejects the whole reply, listing every problem, so nothing half-valid is cached.

pay (optional, Nov 11): the annual base range the posting states, {min, max, currency, quote}, or null. Score uses it
only when the pay parser found no range (score.read_pay). It must be checkable: the quote is in the saved posting,
the max is one of the quote's figures and the min one of the posting's, so a read can't invent pay.
"""
import datetime, hashlib, html, json, os, re
from . import runrecord

GAP_TYPES = ('none', 'minor', 'major', 'critical')
LEVELS = ('excellent', 'strong')
MAX_STRENGTHS, MAX_NEEDS = 3, 5
PRIVATE = ('concerns', 'jd_sha', 'resume_sha')  # kept in the cache, not copied into the run record
CURRENCIES = ('USD', 'CAD')
PAY_MIN, PAY_MAX = 50_000, 1_500_000  # same plausible annual band as pay.pairs
FIGURE = re.compile(r'(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?([kK]\b)?')


class ReadError(ValueError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__('read reply rejected, nothing saved:\n' + '\n'.join('  - ' + p for p in problems))


def sha(text):
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()


def path_of(state, rid):
    return os.path.join(state, 'reads', re.sub(r'[^\w.-]', '_', rid) + '.json')


def _text(p):
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def known_ids(queue, date):
    """Ids a reply may cover: the run record's roles and dropped postings, and the date's reviewed rows."""
    rec = runrecord.load(queue, date)
    ids = {e['id'] for e in rec.get('roles', []) + rec.get('dropped', []) if e.get('id')}
    ids |= {r['id'] for r in runrecord._read_reviewed(queue, date)[2] if r.get('id')}
    return ids


def _str(v):
    return v.strip() if isinstance(v, str) else None


def _flat(text):
    return re.sub(r'\s+', ' ', html.unescape(html.unescape(text or ''))).strip().lower()


def figures(text):
    """Every amount written in the text, as numbers: '$111,974' -> 111974, '$150K' -> 150000, '172,826.00' -> 172826."""
    out = set()
    for m in FIGURE.finditer(text or ''):
        n = float(m.group(1).replace(',', '') + (m.group(2) or ''))
        out.add(round(n * 1000 if m.group(3) else n))
    return out


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check_pay(pay, jd):
    """(pay normalized or None, problems). None/{} is no pay. Checks the figures against the quote and the posting."""
    if pay in (None, {}):
        return None, []
    if not isinstance(pay, dict):
        return None, ['pay must be an object {min, max, currency, quote} or null']
    lo, hi, cur, quote = _num(pay.get('min')), _num(pay.get('max')), pay.get('currency') or 'USD', _str(pay.get('quote'))
    bad = []
    if hi is None or not PAY_MIN <= hi <= PAY_MAX:
        bad.append(f"pay max {pay.get('max')!r} must be an annual figure between {PAY_MIN:,} and {PAY_MAX:,}")
    if pay.get('min') is not None and (lo is None or hi is None or not PAY_MIN <= lo <= hi):
        bad.append(f"pay min {pay.get('min')!r} must be a number from {PAY_MIN:,} up to the max, or null")
    if cur not in CURRENCIES:
        bad.append(f"pay currency {cur!r} is not one of {', '.join(CURRENCIES)}")
    if not quote:
        bad.append('pay quote missing: give the posting text the figures come from')
    elif jd is not None and _flat(quote) not in _flat(jd):
        bad.append(f'pay quote is not in the saved posting: {quote[:80]!r}')
    elif hi is not None and round(hi) not in figures(quote):
        bad.append(f'pay max {hi:,.0f} is not a figure in the quote')
    if lo is not None and jd is not None and round(lo) not in figures(html.unescape(jd)):
        bad.append(f'pay min {lo:,.0f} is not a figure in the posting')
    if bad:
        return None, bad
    return dict(min=round(lo) if lo is not None else None, max=round(hi), currency=cur, quote=quote), []


def validate(reply, ids, state):
    """The rows of a posting-reader reply, normalized. Raises ReadError listing every problem (unknown id,
    unknown gap_type or level, more than 3 strengths or 5 needs, no saved posting, wrong types, pay that can't be
    checked against the posting)."""
    rows = reply.get('rows') if isinstance(reply, dict) else reply
    if not isinstance(rows, list):
        raise ReadError(['expected {"rows": [...]}'])
    out, bad, seen = [], [], set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            bad.append(f'row {i}: not an object')
            continue
        rid = _str(r.get('id')) or ''
        who = f'row {i} ({rid or "no id"})'
        if not rid:
            bad.append(f'{who}: id missing')
        elif rid not in ids:
            bad.append(f'{who}: id is not a role or dropped posting of this run, or a reviewed row')
        elif rid in seen:
            bad.append(f'{who}: id appears twice')
        elif not runrecord.jd_path(state, rid):
            bad.append(f'{who}: no saved posting to read it against')
        seen.add(rid)
        if r.get('gap_type') not in GAP_TYPES:
            bad.append(f"{who}: gap_type {r.get('gap_type')!r} is not one of {', '.join(GAP_TYPES)}")
        row = dict(id=rid, gap_type=r.get('gap_type'))
        for k in ('top_gap', 'gap_quote', 'concerns'):
            row[k] = _str(r.get(k, ''))
            if row[k] is None:
                bad.append(f'{who}: {k} must be text')
        st = r.get('strengths', [])
        if not isinstance(st, list) or len(st) > MAX_STRENGTHS:
            bad.append(f'{who}: strengths must be a list of at most {MAX_STRENGTHS}')
            st = []
        row['strengths'] = []
        for s in st:
            if not (isinstance(s, dict) and _str(s.get('label'))):
                bad.append(f'{who}: each strength needs a label')
            elif s.get('level') not in LEVELS:
                bad.append(f"{who}: strength {s['label']!r} level {s.get('level')!r} is not one of {', '.join(LEVELS)}")
            else:
                row['strengths'].append(dict(label=s['label'].strip(), level=s['level'],
                                             resume=_str(s.get('resume', '')) or '', posting=_str(s.get('posting', '')) or ''))
        nd = r.get('needs', [])
        if not isinstance(nd, list) or len(nd) > MAX_NEEDS or not all(isinstance(x, str) for x in nd):
            bad.append(f'{who}: needs must be a list of at most {MAX_NEEDS} texts')
            nd = []
        row['needs'] = [x.strip() for x in nd if x.strip()]
        jp = runrecord.jd_path(state, rid) if rid else None
        pay, probs = check_pay(r.get('pay'), _text(jp) if jp else None)
        bad += [f'{who}: {x}' for x in probs]
        if pay:
            row['pay'] = pay
        out.append(row)
    if not out and not bad:
        bad.append('no rows')
    if bad:
        raise ReadError(bad)
    return out


def save(state, rows, resume, now=None):
    """Cache validated rows against their saved posting and the resume text. Returns the ids saved."""
    os.makedirs(os.path.join(state, 'reads'), exist_ok=True)
    stamp = now or datetime.datetime.now().isoformat(timespec='seconds')
    for r in rows:
        body = dict(r, jd_sha=sha(_text(runrecord.jd_path(state, r['id']))), resume_sha=sha(resume), read_at=stamp)
        with open(path_of(state, r['id']), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(body, fh, indent=1, ensure_ascii=False)
    return [r['id'] for r in rows]


def valid(state, rid, resume, jd=None):
    """The cached read for `rid` while it matches the posting (`jd` text, else the saved file) and the resume text; else None."""
    p = path_of(state, rid)
    if not rid or not os.path.exists(p):
        return None
    try:
        rd = json.loads(_text(p))
        if jd is None:
            jp = runrecord.jd_path(state, rid)
            jd = _text(jp) if jp else None
        if jd is None or rd.get('gap_type') not in GAP_TYPES:
            return None
    except (OSError, ValueError, AttributeError):
        return None
    return rd if rd.get('jd_sha') == sha(jd) and rd.get('resume_sha') == sha(resume) else None


def public(rd):
    """The read as the run record keeps it: no concerns, no hashes."""
    return {k: v for k, v in rd.items() if k not in PRIVATE}


class Reader:
    """Valid reads for one workspace; the resume text is read once, when first needed."""

    def __init__(self, ctx):
        self.ctx, self.state, self._resume = ctx, ctx.state, None

    @property
    def resume(self):
        if self._resume is None:
            from .score import evidence
            self._resume = evidence(self.ctx)
        return self._resume

    def __call__(self, rid):
        return valid(self.state, rid, self.resume)
