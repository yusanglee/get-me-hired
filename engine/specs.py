"""Write tailoring specs for a batch of roles, picking approved bullets by ID.

Replaces the one-off make_specs_<date>.py scripts. You write a short batch file; this
module looks every bullet, summary and skills term up in approved text, checks the
layout rules, and writes one spec per role. It never writes new resume content.

Workspace inputs:
  resume/templates/<Name>.json   approved resume documents (see engine.resume)
  resume/bank.json               {"bullets": {"MV": {"text": "...", "experience": "acme"}, ...},
                                  "skills": ["approved term", ...],
                                  "skill_sets": {"growth": ["term", ...]},
                                  "bio_prefix": "Product Leader  ·  ",
                                  "bios": ["Consumer Growth & Marketplaces", ...],   # optional, added by gmh materials
                                  "summaries": {"platform": "..."}}                  # optional, added by gmh materials

Batch file (YAML or JSON):
  date: 2026-10-21
  reviewed: queue/reviewed-2026-10-21.csv      # optional; gives company/title; roles no longer apply/manual are skipped
  roles:
    - id: gh-acme-123
      slug: Acme-Growth
      short: Senior PM Growth                  # folder: "<date> <company> - <short>"
      template: Marketplace
      bio: Consumer Growth & Marketplaces       # bio_prefix is added unless the text has "·"
      summary: template:Creator                 # optional: another template's approved summary, or bank:<name>
      skills: ['@growth', Mobile Apps]          # @name expands a skill set
      experience:
        acme: [MV, SL, WB]                      # by experience id or experience[0]
      extra_sections: none                      # optional: drop the template's extra sections
      drop_oldest: 1                            # optional: drop the 1 oldest job (the last in the template); the only way to drop a job

Template experience fields (set by hand in the template): max_bullets (cap on that job's bullets) and
no_extra: true (never add the extra bullet beyond the template's count).

Usage: python3 -m engine.specs <batch.yaml> --workspace <dir> [--out <dir>] [--legacy]
--legacy writes the original pipeline's spec shape (CONTENT keys named after each job), for its tailor.py.

For the resume-tailor agent (bin/gmh specs ...; ROLE_ENTRY below is the role entry's format and example):
  gmh specs brief <id> [--date D] --workspace <ws>    JSON packet for one role: templates, bank, read, materials, rules
  gmh specs check-entry <entry.json> --workspace <ws> checks one role entry (as the agent returns it); prints problems or ok
  gmh specs accept <id> <reply.json> [--date D]       checks the tailor's reply, saves its notes, fills the reviewed-row labels, adds the entry to the day's batch file
  gmh specs coverage <id> [--spec <file>]             posting key-term coverage: template default vs the spec
"""
import argparse, csv, glob, json, os, re, sys
from . import yamlish
from .resume import apply_overrides, exp_index, to_legacy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY_KEYS = ('id', 'slug', 'short', 'template', 'bio', 'summary', 'skills', 'experience', 'extra_sections',
              'drop_oldest', 'company', 'title')


class SpecError(ValueError):
    pass


ROLE_ENTRY = {
    'format': 'One role entry of the batch file (JSON here, YAML in the file). Required: id, slug, template. '
              'short: folder name part. bio: an approved bio (the packet\'s bios), as the text after the bio_prefix. '
              'summary: "template:<Name>" or "bank:<name>" (the packet\'s summaries). skills: approved terms; "@name" expands a skill set. experience: '
              '{experience id: [bullet ids]} in the order to print. drop_oldest: N drops the N oldest jobs (the last N of the template), the only way to drop a job. '
              'Do not use extra_sections (gmh specs writes the legacy shape, which has no form for it).',
    'example': {'id': 'gh-brightwater-123', 'slug': 'Brightwater-Ops', 'short': 'Chief of Staff', 'template': 'Ops',
                'bio': 'Operating Cadence & Strategy', 'summary': 'template:Ops', 'skills': ['@core', 'Board Prep'],
                'experience': {'acme': ['MNA', 'PLAN']}},
}


def load_templates(workspace):
    out = {}
    for p in glob.glob(os.path.join(workspace, 'resume', 'templates', '*.json')):
        out[os.path.basename(p)[:-5]] = json.load(open(p, encoding='utf-8'))
    if not out:
        raise SpecError(f'no templates in {workspace}/resume/templates')
    return out


def load_bank(workspace):
    """bank.json, plus resume/skill_sets.json (hand-kept named skill lists) when present."""
    bank = json.load(open(os.path.join(workspace, 'resume', 'bank.json'), encoding='utf-8'))
    extra = os.path.join(workspace, 'resume', 'skill_sets.json')
    if os.path.exists(extra):
        bank['skill_sets'] = {**bank.get('skill_sets', {}), **json.load(open(extra, encoding='utf-8'))}
    return bank


def bank_from_templates(templates, skills=None):
    """The bullet bank from approved templates: every bullet gets an id <experience id>-NNN.
    Approved skills are the templates' skills lines plus any extra approved terms."""
    bullets, owner = {}, {}
    for doc in templates.values():
        for x in doc['experience']:
            for b in x['bullets']:
                owner.setdefault(b, x['id'])
    for i, (text, exp) in enumerate(sorted(owner.items(), key=lambda kv: (kv[1], kv[0]))):
        bullets[f'{exp}-{i:03d}'] = {'text': text, 'experience': exp}
    bios = {d['bio'] for d in templates.values()}
    prefix = os.path.commonprefix(sorted(bios))
    prefix = prefix[:prefix.rfind('·') + 3] if '·' in prefix else ''
    terms = set(skills or [])
    for doc in templates.values():
        terms |= {t.strip() for t in doc['skills'].split('|') if t.strip()}
    seen, out = set(), []
    for t in sorted(terms):
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return {'bio_prefix': prefix, 'bullets': bullets, 'skills': out, 'skill_sets': {}}


def template_version(doc):
    """'v<version>-<8 hex>': the template's own version number (absent = 1) and a hash of its content, so a built
    resume says exactly which approved template it came from."""
    import hashlib
    body = json.dumps({k: v for k, v in doc.items() if k != 'version'}, sort_keys=True, ensure_ascii=False)
    return f"v{doc.get('version', 1)}-{hashlib.sha1(body.encode('utf-8')).hexdigest()[:8]}"


def approved_bios(templates, bank):
    """Every approved bio line in full (prefix included): each template's own, plus the bank's `bios`."""
    prefix = bank.get('bio_prefix', '')
    out = {d.get('bio', '') for d in templates.values() if d.get('bio')}
    out |= {b if '·' in b else prefix + b for b in bank.get('bios', [])}
    return out


def _load(path):
    return yamlish.load(path) if path.endswith(('.yaml', '.yml')) else json.load(open(path, encoding='utf-8'))


def skills_line(items, bank):
    approved = {t.lower() for t in bank.get('skills', [])}
    terms = []
    for it in items:
        if isinstance(it, str) and it.startswith('@'):
            name = it[1:]
            if name not in bank.get('skill_sets', {}):
                raise SpecError(f'unknown skill set {it}')
            terms += bank['skill_sets'][name]
        else:
            terms.append(it)
    bad = [t for t in terms if t.lower() not in approved]
    if bad:
        raise SpecError('skills not approved: ' + ', '.join(bad))
    if len({t.lower() for t in terms}) != len(terms):
        raise SpecError('duplicate skills term')
    return '  |  '.join(terms)


def apply_spec(tpl, overrides):
    """The resume document for a template plus spec overrides, including `drop_oldest` (the N oldest jobs go; the
    template lists jobs newest first, so they are the last N). Use this, not resume.apply_overrides, for specs."""
    ov = dict(overrides or {})
    n = ov.pop('drop_oldest', 0) or 0
    doc = apply_overrides(tpl, ov)
    if n:
        if not isinstance(n, int) or isinstance(n, bool) or not 0 < n < len(doc['experience']):
            raise SpecError(f'drop_oldest must be a whole number from 1 to {len(doc["experience"]) - 1}')
        doc['experience'] = doc['experience'][:-n]
    return doc


def make_spec(role, templates, bank, cfg=None, date=None, row=None):
    """One role's spec: {slug, id, company, title, template, folder, overrides}. Raises SpecError."""
    cfg = cfg or {}
    max_extra = ((cfg.get('resume') or {}).get('max_extra_bullets', 1))
    tname = role.get('template')
    if tname not in templates:
        raise SpecError(f"{role.get('slug')}: unknown template {tname!r}")
    tpl = templates[tname]
    ov = {}
    if role.get('bio'):
        b = role['bio']
        ov['bio'] = b if '·' in b else bank.get('bio_prefix', '') + b
    if role.get('summary'):
        s = role['summary']
        if isinstance(s, str) and s.startswith('template:') and s[9:] in templates:
            ov['summary'] = templates[s[9:]]['summary']
        elif isinstance(s, str) and s.startswith('bank:') and s[5:] in (bank.get('summaries') or {}):
            ov['summary'] = bank['summaries'][s[5:]]
        else:
            raise SpecError(f"{role['slug']}: summary must be 'template:<Name>' or 'bank:<name>' (approved text only)")
    if role.get('skills'):
        ov['skills'] = skills_line(role['skills'], bank)
    if role.get('extra_sections') == 'none':
        ov['extra_sections'] = []
    kept = len(tpl['experience'])
    if role.get('drop_oldest') not in (None, 0):
        n = role['drop_oldest']
        if not isinstance(n, int) or isinstance(n, bool) or not 0 < n < kept:
            raise SpecError(f"{role['slug']}: drop_oldest must be a whole number from 1 to {kept - 1} "
                            "(it drops the oldest jobs; a job cannot be dropped any other way)")
        ov['drop_oldest'] = n
        kept -= n
    for key, ids in (role.get('experience') or {}).items():
        i = exp_index(tpl, key)
        if i is None:
            raise SpecError(f"{role['slug']}: template {tname} has no experience {key!r}")
        if i >= kept:
            raise SpecError(f"{role['slug']}: experience {key!r} is dropped by drop_oldest: {role['drop_oldest']}")
        exp = tpl['experience'][i]
        texts = []
        for bid in ids:
            b = bank['bullets'].get(bid)
            if not b:
                raise SpecError(f"{role['slug']}: unknown bullet id {bid!r}")
            if b.get('experience') and exp.get('id') and b['experience'] != exp['id']:
                raise SpecError(f"{role['slug']}: bullet {bid} belongs to {b['experience']}, not {exp['id']}")
            texts.append(b['text'])
        if len(set(texts)) != len(texts):
            raise SpecError(f"{role['slug']}: duplicate bullet in {key}")
        delta = len(texts) - len(exp['bullets'])
        extra = 0 if exp.get('no_extra') else max_extra
        if not 0 <= delta <= extra:
            raise SpecError(f"{role['slug']}: {key} has {len(texts)} bullets; template {tname} has {len(exp['bullets'])} "
                            + ('(this job takes no extra bullet: no_extra)' if exp.get('no_extra') else
                               f"(allowed: same, or up to {max_extra} more, so the page break holds)"))
        cap = exp.get('max_bullets')
        if cap and len(texts) > cap:
            raise SpecError(f"{role['slug']}: {key} has {len(texts)} bullets; this job allows at most {cap} (max_bullets)")
        ov[f'experience[{i}]'] = texts
    apply_spec(tpl, ov)  # raises on anything the renderer couldn't use
    company = role.get('company') or (row or {}).get('company')
    title = role.get('title') or (row or {}).get('title')
    if not (company and title):
        raise SpecError(f"{role['slug']}: company and title needed (from the batch or the reviewed CSV)")
    return dict(slug=role['slug'], id=role['id'], company=company, title=title.strip(), template=tname,
                template_version=template_version(tpl),
                folder=f"{date} {company} - {role.get('short') or title}".replace('/', '-'), overrides=ov)


def check_entry(role, templates, bank, cfg=None):
    """Problems with one batch role entry (a list; empty when it passes). Same checks as make_spec."""
    if not isinstance(role, dict):
        return ['entry must be an object']
    unknown = sorted(set(role) - set(ENTRY_KEYS))
    if unknown:
        return ['unknown field(s): ' + ', '.join(map(str, unknown)) + ' (a job is dropped only with drop_oldest)']
    miss = [k for k in ('id', 'slug', 'template') if not role.get(k)]
    if miss:
        return ['missing ' + ', '.join(miss)]
    try:
        spec = make_spec(role, templates, bank, cfg, 'check', {'company': 'x', 'title': 'x'})
    except SpecError as e:
        return [str(e)]
    # The tailor's path only: a bio must be approved text. (`gmh specs <batch>` still builds older batches.)
    bio = spec['overrides'].get('bio')
    if bio and bio not in approved_bios(templates, bank):
        return [f"{role['slug']}: bio {role['bio']!r} is not an approved bio (use one from the packet's bios; "
                "new bios are proposed and approved with gmh materials)"]
    return []


def safe_id(rid):
    return re.sub(r'[^\w.-]', '_', rid)


def _reviewed_found(pipeline, rid, date=None):
    """(path, date, row) for rid: reviewed-<date>.csv, else the newest reviewed-*.csv containing it."""
    files = [os.path.join(pipeline, 'queue', f'reviewed-{date}.csv')] if date else \
        sorted(glob.glob(os.path.join(pipeline, 'queue', 'reviewed-*.csv')), reverse=True)
    for f in files:
        if os.path.exists(f):
            for r in csv.DictReader(open(f, encoding='utf-8', newline='')):
                if r.get('id') == rid:
                    return f, os.path.basename(f)[len('reviewed-'):-len('.csv')], r
    raise SpecError(f'no reviewed row for {rid}' + (f' in reviewed-{date}.csv' if date else ''))


def _reviewed(pipeline, rid, date=None):
    return _reviewed_found(pipeline, rid, date)[2]


def layout_rules(cfg):
    """One plain sentence per layout rule set in config `resume.*` (only the keys present)."""
    r = (cfg or {}).get('resume') or {}
    n = lambda k: r.get(k) is not None and not isinstance(r.get(k), bool)
    plural = lambda v, w: f'{v} {w}' + ('' if v == 1 else 's')
    out = []
    if n('max_bullet_lines'):
        out.append(f"Layout: every bullet fits on {plural(r['max_bullet_lines'], 'line')} or fewer.")
    if n('max_summary_lines'):
        out.append(f"Layout: the summary fits on {plural(r['max_summary_lines'], 'line')} or fewer.")
    if n('max_scope_lines'):
        out.append(f"Layout: a job's scope line fits on {plural(r['max_scope_lines'], 'line')} or fewer.")
    if n('min_last_line_words'):
        out.append(f"Layout: the last line of a bullet has at least {plural(r['min_last_line_words'], 'word')}.")
    if n('skills_lines'):
        out.append(f"Layout: the skills section fits on {plural(r['skills_lines'], 'line')} or fewer.")
    if n('max_pages'):
        out.append(f"Layout: the resume is {plural(r['max_pages'], 'page')} or fewer.")
    pb = r.get('page_breaks')
    if isinstance(pb, dict) and pb:
        out.append('Layout: page break: ' + '; '.join(f"{k.replace('_', ' ')} = {v}" for k, v in pb.items())
                   + ' (adding or cutting bullets there can move it).')
    if n('max_page1_free_pt'):
        out.append(f"Layout: when the resume runs to a second page, page 1 leaves at most {r['max_page1_free_pt']} pt "
                   "of empty space at the bottom.")
    return out


def brief(workspace, pipeline, rid, date=None, cfg=None):
    """What the resume tailor sees for one role. Never a gap field: only the read's needs and strengths."""
    row = _reviewed(pipeline, rid, date)
    templates, bank = load_templates(workspace), load_bank(workspace)
    jd = next((p for p in (os.path.join(pipeline, 'state', 'jd', n + '.txt') for n in (rid, safe_id(rid)))
               if os.path.exists(p)), os.path.join(pipeline, 'state', 'jd', rid + '.txt'))
    rp = os.path.join(pipeline, 'state', 'reads', safe_id(rid) + '.json')
    read = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else {}
    extra = ((cfg or {}).get('resume') or {}).get('max_extra_bullets', 1)
    prefix = bank.get('bio_prefix', '')
    facts = next((p for p in (os.path.join(workspace, 'master-resume.md'),
                              os.path.join(os.path.dirname(pipeline), 'master-resume.md')) if os.path.exists(p)), '')
    return {
        'role': {'id': rid, 'company': row.get('company', ''), 'title': (row.get('title') or '').strip()},
        'posting_path': jd,
        'read': {'needs': read.get('needs', []), 'strengths': read.get('strengths', [])},
        'templates': {n: {'summary': t['summary'], 'bio': t.get('bio', ''), 'skills': t.get('skills', ''),
                          'experience': [{k: x.get(k, '') for k in ('id', 'company', 'role')} | {'bullets': x['bullets']}
                                         | {k: x[k] for k in ('max_bullets', 'no_extra') if k in x}
                                         for x in t['experience']]} for n, t in sorted(templates.items())},
        'bank': {k: bank[k] for k in ('bullets', 'skills', 'skill_sets', 'bio_prefix') if k in bank},
        'materials': {k: row.get(k, '') for k in ('summary_variant', 'template_script', 'lead_material')},
        'bios': sorted(b[len(prefix):] if prefix and b.startswith(prefix) else b for b in approved_bios(templates, bank)),
        'summaries': {f'template:{n}': t['summary'] for n, t in sorted(templates.items())}
                     | {f'bank:{n}': s for n, s in sorted((bank.get('summaries') or {}).items())},
        'facts_path': facts,
        'batch_format': ROLE_ENTRY,
        'rules': [
            'Use only ids, templates, skills and skill sets present in this packet.',
            'Never write new resume text: summary is "template:<Name>", bullets are bank ids.',
            'Lead with what the posting stresses (read.needs); strengths show what the resume already matches.',
            f'Layout: each experience keeps its template bullet count or adds at most {extra} (the page break holds); '
            'a bullet belongs to its own experience; no duplicate bullets or skills terms.',
            *(['Experiences with max_bullets take at most that many bullets; no_extra: true means never add the extra '
               'bullet beyond the template count.']
              if any(k in x for t in templates.values() for x in t['experience'] for k in ('max_bullets', 'no_extra')) else []),
            *layout_rules(cfg),
            "drop_oldest: N (in the spec entry) drops the N oldest jobs, the last N of the template's experience list; "
            'it is the only way to drop a job. Use it only to meet a layout rule.',
            'Pick the approved summary, bio, skills terms and bullets that cover the most posting key terms (the engine '
            'measures coverage and fills the reviewed-row labels after you; do not report them).',
            'Read the full posting at posting_path if the needs are not enough.',
            'bio: one of bios; summary: one of the summaries keys.',
            'missing: true strengths the posting asks for that the master resume (facts_path) states but no bank '
            'bullet does; quote the master-resume line exactly. material_feedback: a bio, summary, skills line or '
            'template that fits this role badly, with why. Both are notes for later review, never resume text.'],
        'return_format': {'spec': ROLE_ENTRY['example'], 'notes': '',
                          'missing': [{'experience': 'acme', 'fact': 'short phrase', 'resume_line': 'exact master-resume line'}],
                          'material_feedback': [{'kind': 'bio|summary|skills|template', 'template': 'Ops',
                                                 'issue': 'why it fits this role badly', 'suggest': 'an idea, not resume text'}]}}


# ---------- brief to a file, accept, coverage, the resume-choice approval ----------

LABELS = ('summary_variant', 'template_script', 'lead_material')


def _pipeline(ws, cfg):
    from . import layout
    return layout.pipeline(ws, cfg)


def write_brief(ws, rid, out=None, date=None, cfg=None):
    """gmh specs brief: write the packet to `out` (default <pipeline>/scratch/<today>/tailor-brief-<id>.json). Returns the path."""
    from . import layout
    path = os.path.abspath(out) if out else layout.scratch(ws, 'tailor-brief', rid, cfg=cfg)
    pkt = brief(ws, _pipeline(ws, cfg), rid, date, cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(pkt, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return path


def batch_path(ws, date, cfg=None):
    """The day's batch file: <pipeline>/queue/batch-<date>.json (what `gmh specs <batch>` reads), where it has always
    lived."""
    return os.path.join(_pipeline(ws, cfg), 'queue', f'batch-{date}.json')


def default_labels(entry, templates, bank):
    """The reviewed row's material labels for a checked spec entry: summary_variant is the summary's source
    ("template:<T>" unless the entry picks another), template_script the template name, lead_material the first
    bullet's bank id (the entry's first listed bullet, else the template's first bullet, else "template:<T>")."""
    tname = entry['template']
    lead = next((ids[0] for ids in (entry.get('experience') or {}).values() if ids), None)
    if not lead:
        first = next((b for x in templates[tname]['experience'] for b in x['bullets']), None)
        lead = next((bid for bid, b in bank.get('bullets', {}).items() if first and b.get('text') == first), None)
    return {'summary_variant': entry.get('summary') or f'template:{tname}', 'template_script': tname,
            'lead_material': lead or f'template:{tname}'}


def accept(ws, rid, reply_path, date=None, cfg=None):
    """Take the resume-tailor's reply for one role: check its spec entry, write the reviewed row's labels, add the
    entry to the day's batch file and save the reply's notes (missing, material_feedback). The labels come from the
    reply when it gives them, else from the entry (default_labels). Everything is checked first;
    on any problem SpecError lists them all and nothing is written. Returns the batch file's path."""
    from . import materials, runrecord
    pipeline = _pipeline(ws, cfg)
    try:
        reply = json.load(open(reply_path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise SpecError(f'{reply_path}: not a JSON tailor reply ({e})')
    if not isinstance(reply, dict) or not isinstance(reply.get('spec'), dict):
        raise SpecError('the tailor reply must be a JSON object with a "spec" entry')
    entry, problems = reply['spec'], []
    if entry.get('id') != rid:
        problems.append(f"the spec entry is for {entry.get('id')!r}, not {rid!r}")
    problems += check_entry(entry, load_templates(ws), load_bank(ws), cfg)
    labels = {}
    if not problems:
        defaults = default_labels(entry, load_templates(ws), load_bank(ws))
        for k in LABELS:  # a label the reply gives wins; otherwise the engine fills it from the spec entry
            v = reply.get(k)
            labels[k] = v.strip() if isinstance(v, str) and v.strip() else defaults[k]
    try:
        rpath, day, row = _reviewed_found(pipeline, rid, date)
        if row.get('call') not in ('apply', 'manual'):
            problems.append(f"{rid} is call={row.get('call')!r} in reviewed-{day}.csv, not apply or manual")
    except SpecError as e:
        problems.append(str(e))
        day = row = None
    bpath = batch_path(ws, day, cfg) if day else None
    batch = {'date': day, 'reviewed': f'queue/reviewed-{day}.csv', 'roles': []}
    if bpath and os.path.exists(bpath):
        try:
            batch = json.load(open(bpath, encoding='utf-8'))
            batch['roles'] = list(batch.get('roles') or [])
        except (OSError, ValueError) as e:
            problems.append(f'{bpath}: unreadable ({e})')
        else:
            clash = next((r['id'] for r in batch['roles'] if r.get('slug') == entry.get('slug') and r.get('id') != rid), None)
            if clash:
                problems.append(f"slug {entry.get('slug')!r} is already used by {clash} in the batch file")
    if problems:
        raise SpecError('\n'.join(problems))
    batch['roles'] = [r for r in batch['roles'] if r.get('id') != rid] + [entry]
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    with open(bpath, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(batch, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    runrecord.fill(os.path.join(pipeline, 'queue'), day, rid, labels)
    materials.save(ws, rid, reply_path)
    return bpath


def doc_text(doc):
    """The resume's words as one string (bold marks removed), for matching against posting terms."""
    parts = [doc.get('bio', ''), doc.get('summary', ''), doc.get('skills', '')]
    for x in doc.get('experience', []):
        parts += [x.get('role', ''), x.get('company', ''), x.get('scope', ''), *x.get('bullets', [])]
    for e in doc.get('education', []):
        parts += [e.get('school', ''), e.get('degree', '')]
    for sec in doc.get('extra_sections') or []:
        parts += [sec.get('heading', ''), sec.get('text', '')]
    return '\n'.join(parts).replace('**', '')


def _spec_overrides(obj, templates, bank, cfg):
    """(template name, overrides) from a tailor reply, a role entry or a built spec."""
    if isinstance(obj.get('spec'), dict):
        obj = obj['spec']
    if 'overrides' in obj and obj.get('template'):
        return obj['template'], obj['overrides']
    probs = check_entry(obj, templates, bank, cfg)
    if probs:
        raise SpecError('; '.join(probs))
    spec = make_spec(obj, templates, bank, cfg, 'check', {'company': 'x', 'title': 'x'})
    return spec['template'], spec['overrides']


def coverage(ws, rid, spec_path=None, date=None, cfg=None):
    """Posting key terms found in the template as it is (before) and in the resume the spec makes (after).
    Returns {'terms': N, 'before': X, 'after': Y, 'missed': [terms the spec still lacks]}."""
    import types
    from . import layout, stages, verify
    pipeline = _pipeline(ws, cfg)
    pkt_post = brief(ws, pipeline, rid, date, cfg)['posting_path']
    if not os.path.exists(pkt_post):
        raise SpecError(f'no saved posting for {rid} ({pkt_post})')
    jd = open(pkt_post, encoding='utf-8').read()
    terms = stages._term_re(types.SimpleNamespace(ws=ws, P=pipeline))
    if terms is None:
        raise SpecError('no keyword vocabulary: put one term per line in <workspace>/terms.txt')
    path = spec_path or layout.scratch(ws, 'spec', rid, date=date, cfg=cfg)
    if not os.path.exists(path):
        raise SpecError(f'no spec file at {path} (pass --spec <file>)')
    templates, bank = load_templates(ws), load_bank(ws)
    try:
        obj = _load(path)
    except (OSError, ValueError) as e:
        raise SpecError(f'{path}: unreadable ({e})')
    tname, ov = _spec_overrides(obj, templates, bank, cfg)
    done = lambda cov: {t for t, k in cov.items() if k in ('covered', 'synonym')}
    before = verify.keyword_coverage(jd, terms, doc_text(templates[tname]), None)
    after = verify.keyword_coverage(jd, terms, doc_text(apply_spec(templates[tname], ov)), None)
    return {'terms': len(after), 'before': len(done(before)), 'after': len(done(after)),
            'missed': sorted(set(after) - done(after))}


def coverage_line(c):
    return f"before {c['before']}/{c['terms']}, after {c['after']}/{c['terms']}; missed: " + (', '.join(c['missed']) or 'none')


CHOICE_TEMPLATE = os.path.join(REPO, 'templates', 'resume-choice.md')


def render_choice(ws, rid, reply_path, date=None, cfg=None):
    """The resume-choice approval text for one role, from templates/resume-choice.md and the tailor's reply
    (an accepted spec). Bullets are shown by bank id with their text."""
    reply = json.load(open(reply_path, encoding='utf-8'))
    entry = reply.get('spec', reply)
    pipeline = _pipeline(ws, cfg)
    templates, bank = load_templates(ws), load_bank(ws)
    row = _reviewed(pipeline, rid, date)
    tname, ov = _spec_overrides(entry, templates, bank, cfg)
    tpl, doc = templates[tname], apply_spec(templates[tname], ov)
    by_text = {}
    for bid, b in bank.get('bullets', {}).items():
        by_text.setdefault(b['text'], bid)
    lines = []
    for x in doc['experience']:
        lines.append(f"{x.get('company', '')}, {x.get('role', '')}:")
        for b in x['bullets']:
            lines.append(f"  - {by_text.get(b, 'template')}  {b.replace('**', '')}")
    summary_src = entry.get('summary') or f'template:{tname}'
    notes = []
    if ov.get('drop_oldest'):
        gone = tpl['experience'][-ov['drop_oldest']:]
        notes.append('Dropped the oldest job(s): ' + ', '.join(x.get('company', '') for x in gone) + '.')
    for x in tpl['experience']:
        if x.get('no_extra') or x.get('max_bullets'):
            notes.append(f"{x.get('company', '')}: " + ', '.join(
                s for s in (f"at most {x['max_bullets']} bullets" if x.get('max_bullets') else '',
                            'no extra bullet' if x.get('no_extra') else '') if s) + '.')
    notes += layout_rules(cfg)
    if reply.get('notes'):
        notes.append('Tailor: ' + str(reply['notes']))
    try:
        cov = coverage_line(coverage(ws, rid, reply_path, date, cfg))
    except SpecError as e:
        cov = f'not available ({e})'
    values = {'role': f"{row.get('company', '')}: {(row.get('title') or '').strip()}", 'id': rid, 'template': tname,
              'summary': doc['summary'], 'summary_source': summary_src, 'bio': doc.get('bio', ''),
              'bullets': '\n'.join(lines), 'skills': doc['skills'], 'coverage': cov,
              'layout_notes': '\n'.join(f'- {n}' for n in notes) or '- none'}
    text = open(CHOICE_TEMPLATE, encoding='utf-8').read()
    for k, v in values.items():
        text = text.replace('{' + k + '}', v)
    return text


def run_command(ws, args, out=None, date=None, spec=None, cfg=None):
    """The `gmh specs brief|accept|coverage` subcommands. Returns (exit code, text to print).
    args: ['brief', id] | ['accept', id, reply.json] | ['coverage', id]."""
    try:
        if args[:1] == ['brief'] and len(args) == 2:
            return 0, write_brief(ws, args[1], out, date, cfg)
        if args[:1] == ['accept'] and len(args) == 3:
            accept(ws, args[1], args[2], date, cfg)
            return 0, f'accepted {args[1]}'
        if args[:1] == ['coverage'] and len(args) == 2:
            return 0, coverage_line(coverage(ws, args[1], spec, date, cfg))
    except ValueError as e:  # SpecError, MaterialError, PickError
        return 1, str(e)
    return 2, 'usage: gmh specs brief <id> [--out F] | accept <id> <reply.json> [--date D] | coverage <id> [--spec F]'


def legacy(spec, templates):
    """The original pipeline's spec shape: overrides keyed by CONTENT names (one key per job)."""
    tpl = templates[spec['template']]
    doc = apply_spec(tpl, spec['overrides'])
    content, base = to_legacy(doc), to_legacy(tpl)
    ov = {k: v for k, v in content.items() if base.get(k) != v}
    if spec['overrides'].get('drop_oldest'):
        ov['drop_oldest'] = spec['overrides']['drop_oldest']
    if spec['overrides'].get('extra_sections') is not None:
        raise SpecError(f"{spec['slug']}: extra_sections overrides have no legacy form")
    return dict(spec, overrides=ov)


def run(batch_path, workspace, out_dir=None, legacy_shape=False, cfg=None, skipped=None):
    """One spec per batch role. A role the reviewed CSV no longer marks apply or manual (passed after its resume
    choice was accepted) is left out, with a line in `skipped`; a role missing from the CSV is an error."""
    batch = _load(batch_path)
    templates, bank = load_templates(workspace), load_bank(workspace)
    rows = {}
    if batch.get('reviewed'):
        rp = batch['reviewed']
        if not os.path.isabs(rp):  # relative to the workspace, else to its pipeline folder (where runs write queue/)
            from . import layout
            rp = next((c for c in (os.path.join(workspace, rp), os.path.join(layout.pipeline(workspace, cfg or {}), rp)) if os.path.exists(c)),
                      os.path.join(workspace, rp))
        rows = {r['id']: r for r in csv.DictReader(open(rp, encoding='utf-8', newline=''))}
        absent = [r['id'] for r in batch['roles'] if r['id'] not in rows]
        if absent:
            raise SpecError('not in the reviewed CSV: ' + ', '.join(absent))
        keep = []
        for r in batch['roles']:
            call = rows[r['id']].get('call')
            if call in ('apply', 'manual'):
                keep.append(r)
            elif skipped is not None:
                skipped.append(f"skipped {r['id']}: call={call or 'blank'} in the reviewed CSV (no spec written)")
        batch = dict(batch, roles=keep)
    slugs = [r['slug'] for r in batch['roles']]
    if len(set(slugs)) != len(slugs):
        raise SpecError('duplicate slug in batch')
    specs = [make_spec(r, templates, bank, cfg, str(batch.get('date')), rows.get(r['id'])) for r in batch['roles']]
    if legacy_shape:
        specs = [legacy(s, templates) for s in specs]
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for s in specs:
            json.dump(s, open(os.path.join(out_dir, s['slug'] + '.json'), 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=False)
    return specs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('batch')
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--out')
    ap.add_argument('--legacy', action='store_true')
    a = ap.parse_args(argv)
    try:
        skipped = []
        specs = run(a.batch, os.path.expanduser(a.workspace), a.out, a.legacy, skipped=skipped)
    except SpecError as e:
        sys.exit(f'spec error: {e}')
    for line in skipped:
        print(line)
    print(f"{len(specs)} specs" + (f' written to {a.out}' if a.out else ' (dry run: no --out)'))


if __name__ == '__main__':
    main()
