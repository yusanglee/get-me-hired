"""The application stages (5b answers, 3 specs + tailor, 5c notes, manual notes, 5d fill plans), run from a workspace.

These replace the original pipeline's answers.py, make_specs_<date>.py, tailor.py, notes.py,
manual_notes.py and fillplan.py. They read and write the same vault files in the same formats
(Pipeline/state/answers, state/notes, state/fillplans, specs/, Workflow/02-Ready to Apply), so the
old scripts can pick up any stage's output if you switch back. Nothing here deletes a file.

    python3 -m engine.stages --workspace <ws> answers
    python3 -m engine.stages --workspace <ws> specs <batch.yaml>
    python3 -m engine.stages --workspace <ws> specs brief <id> [--date D]      (resume-tailor packet, JSON)
    python3 -m engine.stages --workspace <ws> specs check-entry <entry.json>   (prints problems or "ok")
    python3 -m engine.stages --workspace <ws> tailor <spec.json> [...]
    python3 -m engine.stages --workspace <ws> notes <drafts.json>
    python3 -m engine.stages --workspace <ws> manual-notes [<drafts.json>]   (default: drafts/drafts[-manual]-<date>.json)
    python3 -m engine.stages --workspace <ws> fillplan <id> [...]

The workspace's config.json gives paths.vault (the folder holding Pipeline/ and Workflow/), else the workspace
itself. Each stage first checks what it needs (setup.stage_problems) and stops before writing anything.
Before the first stage that writes into the vault, its state folders and specs are copied to
Pipeline/state/pre-v2-snapshot/ (once), so the old pipeline's last outputs are always recoverable.
"""
import argparse, csv, datetime, glob, html, importlib.util, json, os, re, shutil, subprocess, sys, tempfile
from .profile import load_profile, load_config, full_name, salary_ask, find_soffice, soffice_pdf, filename_prefix
from .answers import Answerer, load_answer_bank, load_stage5_answers, load_stage5_role_answers, choose_option, ai_attestation
from .locations import office_answer, relocation_assistance
from .resume import apply_overrides, build, contact_lines, node_modules
from .design import load_design
from .pay import pairs as pay_pairs
from . import layout, specs as specs_mod
from .verify import verify

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIRS = ('state/answers', 'state/notes', 'state/fillplans', 'specs')


def long_date(d):
    """'November 9, 2026' (strftime's %-d is not available on Windows)."""
    return f'{d:%B} {d.day}, {d.year}'


class Ctx:
    def __init__(self, workspace, today=None):
        self.ws = os.path.expanduser(workspace)
        self.prof = load_profile(os.path.join(self.ws, 'profile.yaml'))
        self.cfg = load_config(os.path.join(self.ws, 'config.json'))
        self.vault = layout.vault(self.ws, self.cfg)  # config paths.vault, else the workspace
        self.P = layout.pipeline(self.ws, self.cfg)
        self.ready = layout.ready(self.ws, self.cfg)
        self.today = today or datetime.date.today()
        self.node_path = node_modules(self.cfg, self.vault)
        self.first = self.prof.get('identity.first_name')
        self.design = load_design(self.ws)  # <workspace>/design.json over the shipped defaults

    def answerer(self):
        bank = os.path.join(self.ws, 'answer-bank.md')
        rules, exact = load_answer_bank(bank) if os.path.exists(bank) else ([], {})
        stage5 = os.path.join(self.P, 'queue', 'stage5-questions-*.md')
        exact = {**load_stage5_answers(stage5), **exact}
        return Answerer(self.prof, rules, exact, today=self.today, cfg=self.cfg, role_exact=load_stage5_role_answers(stage5))

    def snapshot(self):
        """Copy the vault's stage outputs once, before v2 first writes over them."""
        dest = os.path.join(self.P, 'state', 'pre-v2-snapshot')
        if os.path.exists(dest):
            return
        copied = []
        for d in SNAPSHOT_DIRS:
            src = os.path.join(self.P, d)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dest, d))
                copied.append(d)
        # Written even on a fresh vault: the folder is the "done" marker, so a later run never snapshots v2's own outputs.
        os.makedirs(dest, exist_ok=True)
        when = f'{datetime.datetime.now():%Y-%m-%d %H:%M}'
        open(os.path.join(dest, 'README.txt'), 'w', encoding='utf-8', newline='\n').write(
            f'Outputs of the original pipeline as of {when}, copied before the first\n'
            'get-me-hired v2 stage wrote into this vault. Copy a folder back to restore it.\n' if copied else
            f'As of {when} this vault had no original-pipeline stage outputs ({", ".join(SNAPSHOT_DIRS)}),\n'
            'so there was nothing to copy. Everything in those folders was written by get-me-hired v2.\n')

    def latest(self, pattern):
        hits = sorted(glob.glob(os.path.join(self.P, pattern)))
        return hits[-1] if hits else None


# ---------- 5b: answers ----------
def stage_answers(ctx, out_root=None):
    out_root = out_root or ctx.P
    a = ctx.answerer()
    os.makedirs(os.path.join(out_root, 'state', 'answers'), exist_ok=True)
    asks, consents = {}, {}
    for f in sorted(glob.glob(os.path.join(ctx.P, 'state', 'forms', '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        rid = os.path.basename(f)[:-5]
        out = []
        for q in d['questions']:
            r = a.answer(q['label'], q['required'], role=rid)
            kind = 'user' if r['source'] in ('user: exact label', 'user: approved for this role') else r['kind']
            out.append(dict(q, kind=kind, answer=r['answer']))
            if kind in ('ask', 'consent'):
                bucket = asks if kind == 'ask' else consents
                label = re.sub(r'\s+', ' ', q['label'].strip())
                # an AI attestation is listed once per role, with its id, so an answer approves that role only
                key = (label, rid) if ai_attestation(q['label']) else (label, '')
                who = f"{rid}: {d['company']}: {d['title']}" if key[1] else f"{d['company']}: {d['title']}"
                bucket.setdefault(key, dict(options=q['options'][:8], roles=[]))['roles'].append(who)
        json.dump(dict(d, questions=out), open(os.path.join(out_root, 'state', 'answers', os.path.basename(f)), 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=False)
    lines = [f'# Stage 5: questions for {ctx.first} ({ctx.today})', '',
             f'Required form questions the answer bank does not cover. Answer each once; Claude adds the answer to the answer bank and reuses it.',
             'An AI-use attestation is listed once per role (with its id): an answer there approves that role only.', '']
    for title, bucket in [('## Required questions with no answer', asks), ('## Consent and acknowledgement checkboxes', consents)]:
        lines += [title, '']
        for i, (k, v) in enumerate(sorted(bucket.items(), key=lambda x: (-len(x[1]['roles']), x[0])), 1):
            opts = f"  \n   Options: {' / '.join(o for o in v['options'] if o)}" if v['options'] else ''
            lines.append(f"{i}. **{k[0]}** ({len(v['roles'])} role{'s' if len(v['roles']) > 1 else ''}: {'; '.join(sorted(set(v['roles'])))}){opts}  \n   ANSWER:")
        lines.append('')
    os.makedirs(os.path.join(out_root, 'queue'), exist_ok=True)
    p = os.path.join(out_root, 'queue', f'stage5-questions-{ctx.today}-open.md')
    open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    print(f'{len(asks)} uncovered required questions, {len(consents)} consent items -> {p}')
    by_label = lambda b: {k[0]: dict(options=v['options'], roles=[r for (l, _), w in b.items() if l == k[0] for r in w['roles']])
                          for k, v in b.items()}
    return by_label(asks), by_label(consents)


# ---------- 3: specs and tailor ----------
def stage_specs(ctx, batch, out_dir=None):
    skipped = []
    specs = specs_mod.run(batch, ctx.ws, out_dir=out_dir or os.path.join(ctx.P, 'specs'), legacy_shape=True, cfg=ctx.cfg,
                          skipped=skipped)
    for line in skipped:
        print(line)
    print(f'{len(specs)} specs -> {out_dir or os.path.join(ctx.P, "specs")}')
    return specs


def _templates(ctx):
    return specs_mod.load_templates(ctx.ws)


def _term_re(ctx):
    """The JD keyword vocabulary for the coverage report: workspace terms.txt, else the vault's score.py TERM_RE."""
    p = os.path.join(ctx.ws, 'terms.txt')
    if os.path.exists(p):
        terms = [t.strip() for t in open(p, encoding='utf-8') if t.strip() and not t.startswith('#')]
        return re.compile(r'\b(' + '|'.join(re.escape(t) for t in terms) + r')\b', re.I)
    src = os.path.join(ctx.P, 'score.py')
    m = re.search(r"TERM_RE = re\.compile\((r'.*?)\)\n", open(src, encoding='utf-8').read(), re.S) if os.path.exists(src) else None
    return eval('re.compile(' + m.group(1) + ')', {'re': re}) if m else None


def stage_tailor(ctx, spec_paths, ready_dir=None):
    ready_dir = ready_dir or ctx.ready
    templates, bank, terms = _templates(ctx), specs_mod.load_bank(ctx.ws), _term_re(ctx)
    facts = next((open(p, encoding='utf-8').read() for p in (os.path.join(ctx.ws, 'master-resume.md'),
                  os.path.join(ctx.vault, 'master-resume.md')) if os.path.exists(p)), None)
    ok = []
    for sp in spec_paths:
        spec = json.load(open(sp, encoding='utf-8'))
        if spec.get('prebuilt'):
            print(f"skip {spec['slug']}: prebuilt resume")
            ok.append(True)
            continue
        doc = specs_mod.apply_spec(templates[spec['template']], spec.get('overrides', {}))
        folder = os.path.join(ready_dir, spec['folder'])
        os.makedirs(folder, exist_ok=True)
        json.dump(dict(doc, _built_from=f"template {spec['template']} + {os.path.basename(sp)}",
                       _template_version=spec.get('template_version') or specs_mod.template_version(templates[spec['template']])),
                  open(os.path.join(folder, f"resume_{spec['slug']}.json"), 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=False)
        jd_src = os.path.join(ctx.P, 'state', 'jd', spec['id'] + '.txt')
        jd_dst = os.path.join(folder, f"{spec['company']} - {spec['title']}.md".replace('/', '-'))
        if os.path.exists(jd_src) and not os.path.exists(jd_dst):
            shutil.copy(jd_src, jd_dst)
        out = build(doc, ctx.prof, folder, spec['slug'], ctx.cfg, node_path=ctx.node_path, design=ctx.design)
        jd = open(jd_src, encoding='utf-8').read() if os.path.exists(jd_src) else None
        fails, notes = verify(out['pdf'], doc, ctx.prof, ctx.cfg, bank, jd, terms, facts=facts, design=ctx.design)
        print(f"{'FAIL' if fails else 'PASS'}  {spec['company']}  ({spec['template']})  {os.path.basename(out['pdf'])}  "
              + '; '.join(notes)
              + ('' if not fails else '\n    - ' + '\n    - '.join(fails)))
        ok.append(not fails)
    print(f'\n{sum(ok)}/{len(ok)} passed')
    return ok


# ---------- 5c: notes and cover letters ----------
def _bottom(jd_text, top):
    if not top:
        return None
    ps = pay_pairs(html.unescape(html.unescape(jd_text)))
    return int(min([lo for lo, hi, _, _ in ps if abs(hi - top) < 1] or [0])) or None


def _cover(ctx, company, date, paragraphs, folder, slug):
    tmp = os.path.join(tempfile.gettempdir(), f'cl_{slug}.json')
    json.dump(dict(name=full_name(ctx.prof).upper(), signoff=full_name(ctx.prof), contact=contact_lines(ctx.prof),
                   company=company, date=date, paragraphs=paragraphs, design=ctx.design), open(tmp, 'w', encoding='utf-8', newline='\n'))
    docx = os.path.join(folder, f'{filename_prefix(ctx.prof)}Cover_Letter_{slug}.docx')
    subprocess.run(['node', os.path.join(REPO, 'tools', 'cover_letter.js'), tmp, docx], check=True,
                   env=dict(os.environ, NODE_PATH=ctx.node_path))
    soffice_pdf(find_soffice(ctx.cfg), folder, docx)
    pdf = docx[:-5] + '.pdf'
    text = subprocess.run(['pdftotext', pdf, '-'], capture_output=True, text=True, encoding='utf-8').stdout
    pages = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', pdf], capture_output=True, text=True, encoding='utf-8').stdout).group(1))
    assert pages == 1 and not re.search('[–—]', text), f'{slug}: cover letter check failed'
    return pdf


def note_rows(ctx, form, spec, reviewed_row, drafts_for_role, top, bottom, cover_pdf):
    sal = salary_ask(ctx.prof, top, bottom)
    floor = ctx.prof.get('salary.floor')
    rows, prefix = [], filename_prefix(ctx.prof)
    for q in form['questions']:
        ans, src = q['answer'], q['kind']
        drafted = [v for k, v in drafts_for_role.get('answers', {}).items() if k and q['label'].startswith(k[:60])]
        if drafted and src in ('ask', 'skip') and not q.get('options') and q.get('type') not in ('input_file', 'File', 'file'):
            ans, src = drafted[0], 'draft'  # an approved draft answers an essay no rule covers (Oct 22: Greenhouse textareas)
        elif ans == 'SALARY':
            ans = sal if q['required'] else (ctx.prof.get('preferences.optional_salary') or 'Open, based on total compensation')
            src = (f"rule: max(top x {ctx.prof.get('salary.top_factor', 0.75)}, range bottom, {floor}), top {top}, bottom {bottom}"
                   if q['required'] else 'answer bank: optional field')
        elif ans in ('RELOCATION', 'OFFICE'):
            ans = office_answer(q['label'], reviewed_row['locations'], ctx.prof, ctx.cfg) or '[CONFIRM: office/relocation]'
            src = 'answer bank (role-specific)'
        elif ans == 'RELOCATION_ASSIST':
            ans = relocation_assistance(reviewed_row['locations'], ctx.prof, ctx.cfg) or '[CONFIRM: relocation assistance]'
            src = 'rule: role location'
        elif ans == 'APPLIED_BEFORE':
            ans, src = 'No (check tracker)', 'rule: tracker'
        elif ans.startswith('FILE: tailored'):
            ans = f"{prefix}Resume_{spec['slug']}.pdf"
        elif ans.startswith('FILE: cover'):
            ans = os.path.basename(cover_pdf) if cover_pdf else '(none: leave blank)'
        elif src == 'draft':
            if drafted:
                ans = drafted[0]
            elif ans.startswith('YEARS') and q.get('options'):
                ans = f"{ctx.prof.get('employment.years_experience')} [pick the matching option]"
            elif ans.startswith('YEARS'):  # a text box ("Do you have 5+ years of ...?"): written by hand or drafted
                ans = f"[NEEDS DRAFT: {ctx.prof.get('employment.years_experience')}]"
            else:
                ans, src = ('(optional: leave blank)', 'skip') if not q['required'] else ('[NEEDS DRAFT]', 'draft')
        elif src == 'consent':
            ans = f'{ctx.first} approved (answer bank)'
        elif src == 'skip':
            ans = '(leave blank)'
        elif src == 'ask' and ans:
            ans, src = f'LEAVE FOR {ctx.first.upper()}: {ans}', 'user'
        rows.append((q['label'], q['required'], ans, src))
    return rows, sal


def reviewed_path(ctx, date=None, drafts_path=None):
    """The reviewed CSV a stage reads: --date if given; else the day in the drafts file's name (drafts-<date>.json),
    so a queue spanning days pairs each day's roles with that day's drafts; else the latest."""
    if not date and drafts_path:
        m = re.search(r'drafts-(\d{4}-\d{2}-\d{2})', os.path.basename(drafts_path))
        if m and os.path.exists(os.path.join(ctx.P, 'queue', f'reviewed-{m.group(1)}.csv')):
            date = m.group(1)
    if date:
        p = os.path.join(ctx.P, 'queue', f'reviewed-{date}.csv')
        if not os.path.exists(p):
            raise SystemExit(f'no queue/reviewed-{date}.csv')
        return p
    p = ctx.latest('queue/reviewed-*.csv')
    if not p:
        raise SystemExit('no queue/reviewed-*.csv: run gmh review picks first')
    return p


def stage_notes(ctx, drafts_path, ready_dir=None, state_root=None, date=None):
    ready_dir, state_root = ready_dir or ctx.ready, state_root or ctx.P
    drafts = json.load(open(drafts_path, encoding='utf-8'))
    src = reviewed_path(ctx, date, drafts_path)
    print(f'roles from {os.path.relpath(src, ctx.P)}')
    reviewed = {r['id']: r for r in csv.DictReader(open(src, encoding='utf-8', newline=''))}
    date = long_date(ctx.today)
    applied_p = os.path.join(ctx.P, 'state', 'applied.csv')
    applied = {r['id'] for r in csv.DictReader(open(applied_p, encoding='utf-8', newline=''))} if os.path.exists(applied_p) else set()
    prefix = filename_prefix(ctx.prof)
    done = []
    for sp in sorted(glob.glob(os.path.join(ctx.P, 'specs', '*.json'))):
        spec = json.load(open(sp, encoding='utf-8'))
        slug = spec['slug']
        if spec['id'] in applied or spec['id'] not in reviewed:
            continue
        folder = os.path.join(ready_dir, spec['folder'])
        ans_p = os.path.join(state_root, 'state', 'answers', spec['id'] + '.json')
        if not os.path.isdir(folder) or not os.path.exists(ans_p):
            continue  # passed (folder moved) or manual-submit role (no form fetched)
        form = json.load(open(ans_p, encoding='utf-8'))
        d = drafts.get(slug, {})
        jd = open(os.path.join(ctx.P, 'state', 'jd', spec['id'] + '.txt'), encoding='utf-8').read()
        top = int(float(reviewed[spec['id']]['salary_max'] or 0)) or None
        bottom = _bottom(jd, top)
        cover_pdf = _cover(ctx, spec['company'], date, d['cover'], folder, slug) if d.get('cover') else None
        rows, sal = note_rows(ctx, form, spec, reviewed[spec['id']], d, top, bottom, cover_pdf)
        os.makedirs(os.path.join(state_root, 'state', 'notes'), exist_ok=True)
        json.dump(dict(id=spec['id'], slug=slug, folder=folder, url=form['url'], cover=cover_pdf,
                       resume=os.path.join(folder, f'{prefix}Resume_{slug}.pdf'),
                       rows=[dict(label=l, required=r, answer=a, source=s) for l, r, a, s in rows]),
                  open(os.path.join(state_root, 'state', 'notes', spec['id'] + '.json'), 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=False)
        md = [f"# Application notes: {spec['company']}, {spec['title']}", '',
              f"**Apply:** {form['url']}  ", f"**Resume:** {prefix}Resume_{slug}.pdf  ",
              f"**Cover letter:** {os.path.basename(cover_pdf) if cover_pdf else 'none (form has no cover letter field)'}  ",
              f"**Salary (if a number is required):** {sal}  ",
              f"**Prepared:** {date}. Claude fills every field, then stops at Submit for {ctx.first}'s OK.", '',
              '| # | Question | Req | Answer | Source |', '|---|---|---|---|---|']
        for i, (lab, req, ans, src) in enumerate(rows, 1):
            md.append(f"| {i} | {lab[:160].replace('|', '/')} | {'yes' if req else ''} | {str(ans).replace('|', '/')} | {src} |")
        if d.get('cover'):
            md += ['', '## Cover letter text', ''] + [x + '\n' for x in d['cover']]
        open(os.path.join(folder, 'application-notes.md'), 'w', encoding='utf-8', newline='\n').write('\n'.join(md))
        flags = [r for r in rows if 'NEEDS DRAFT' in str(r[2]) or 'CONFIRM' in str(r[2])]
        print(f"{slug:30} cover={'yes' if cover_pdf else 'no ':3} salary={str(sal or 'ask'):7} flags={len(flags)}"
              + ''.join(f'\n    - {f[0][:90]}: {f[2]}' for f in flags))
        done.append(spec['id'])
    return done


def standard_answers(ctx):
    """The answer sheet for manual-submit roles, from the profile (replaces manual_notes.py STANDARD)."""
    p, a = ctx.prof, ctx.answerer()
    start = a.tokens()['start_date']
    edu = p.get('education.0', {}) or {}
    mr = p.get('employment.most_recent', {}) or {}
    g = lambda k, d='ASK': p.get(k) or d
    rows = [
        ('Legal name', full_name(p)),
        ('Preferred name', f"leave blank unless required (then {p.get('identity.preferred_name') or p.get('identity.first_name')} / {p.get('identity.last_name')})"),
        ('Email', g('identity.email')), ('Phone', g('identity.phone')),
        ('Address / city', f"{a.tokens()['home']} (home address: ask {ctx.first})"),
        ('LinkedIn', g('identity.linkedin')), ('Website', g('identity.website')),
        ('Authorized to work in the U.S.?', g('work_authorization.authorized_us')),
        ('Require sponsorship (now or future), OPT, H-1B?', g('work_authorization.visa_detail')),
        ('At least 18?', g('attestations.over_18')), ('Non-compete / non-solicit?', g('attestations.non_compete')),
        ('Previously employed by this company?', g('attestations.previously_employed')),
        ('How did you hear?', g('preferences.how_heard') + (f" (else {', '.join(p.get('preferences.how_heard_fallback'))})" if p.get('preferences.how_heard_fallback') else '')),
        ('Current company', p.get('employment.current_employer') or 'N/A (not currently employed)'),
        ('Current or most recent company / title', f"{mr.get('company')}, {mr.get('title')}, {mr.get('start')} to {mr.get('end')}"),
        ('Education', f"{edu.get('school')}; {edu.get('degree')}; {edu.get('field')}; {edu.get('start')} to {edu.get('end')}"),
        ('Start date', start), ('Willing to travel?', g('preferences.travel')),
        ('Gender', g('eeo.gender')), ('Transgender?', g('eeo.transgender')), ('Sexual orientation', g('eeo.sexual_orientation')),
        ('Race / ethnicity', f"{g('eeo.race')}; Hispanic or Latino: {g('eeo.hispanic')}"),
        ('Veteran', g('eeo.veteran')), ('Disability', g('eeo.disability')),
        ('Privacy notice, truthfulness certification', 'Agree (approved)'),
        ('Optional marketing or data-retention consent', 'Leave unticked'),
        ('Pronouns (optional)', g('identity.pronouns', '(leave blank)')),
    ]
    over = p.get('manual_answers', {}) or {}  # profile wording for this sheet wins, question by question
    return [(q, over.get(q, a)) for q, a in rows]


def manual_drafts(ctx, src, drafts_path=None):
    """The drafts a manual role's cover comes from: drafts_path if given; else every drafts/drafts-<date>.json and
    drafts-manual-<date>.json (never a .pre-review backup), the reviewed CSV's own day first, then newest first,
    a day's manual file before its main one. Returns {slug: draft}, the first file holding a slug winning."""
    if drafts_path:
        return json.load(open(drafts_path, encoding='utf-8'))
    day = re.search(r'reviewed-(\d{4}-\d{2}-\d{2})', os.path.basename(src))
    day = day.group(1) if day else None
    found = []
    for p in glob.glob(os.path.join(ctx.P, 'drafts', 'drafts-*.json')):
        m = re.fullmatch(r'drafts-(manual-)?(\d{4}-\d{2}-\d{2})\.json', os.path.basename(p))
        if m:
            found.append(((m.group(2) == day, m.group(2), bool(m.group(1))), p))
    paths = [p for _, p in sorted(found, reverse=True)]
    out = {}
    for p in paths:
        for slug, d in json.load(open(p, encoding='utf-8')).items():
            if isinstance(d, dict) and d.get('cover') and slug not in out:
                out[slug] = d
    return out


def manual_apply_table(items):
    """The table shown after manual prep (templates/manual-apply.md): one row per hand-applied role, with the posting
    link, a file:// link to its application-notes.md and to its cover letter if there is one."""
    import pathlib
    with open(os.path.join(REPO, 'templates', 'manual-apply.md'), encoding='utf-8') as fh:
        lines = fh.read().splitlines()
    row_t = next(l[4:].strip() for l in lines if l.startswith('ROW:'))
    body = '\n'.join(l for l in lines if not l.startswith('ROW:'))
    cell = lambda t: str(t).replace('|', '/').replace('\n', ' ')
    rows = [row_t.format(company=cell(i['company']), title=cell(i['title']), url=i['url'],
                         notes=pathlib.Path(i['notes']).resolve().as_uri(),
                         cover=(f"[{cell(os.path.basename(i['cover']))}]({pathlib.Path(i['cover']).resolve().as_uri()})"
                                if i.get('cover') else 'none')) for i in items]
    return body.replace('{rows}', '\n'.join(rows)).strip()


def stage_manual_notes(ctx, ready_dir=None, date=None, drafts_path=None):
    """Answer sheets for manual-submit roles. An approved cover letter in the drafts file becomes the role's
    cover letter docx and PDF here, as gmh notes does for form roles (Nov 4: hand-apply covers had no file)."""
    ready_dir = ready_dir or ctx.ready
    src = reviewed_path(ctx, date, drafts_path)
    drafts = manual_drafts(ctx, src, drafts_path)
    applied = {r['id'] for r in csv.DictReader(open(os.path.join(ctx.P, 'state', 'applied.csv'), encoding='utf-8', newline=''))}
    specs = {}
    for p in glob.glob(os.path.join(ctx.P, 'specs', '*.json')):
        s = json.load(open(p, encoding='utf-8'))
        specs[s['id']] = s
    standard, prefix = standard_answers(ctx), filename_prefix(ctx.prof)
    a_home = ctx.answerer().tokens()['home']
    floor = ctx.prof.get('salary.floor')
    rows = [r for r in csv.DictReader(open(src, encoding='utf-8', newline='')) if r['call'] == 'manual' and r['id'] not in applied and r['id'] in specs]
    if any(drafts.get(specs[r['id']]['slug'], {}).get('cover') for r in rows):
        from .setup import tools_problems  # building a cover needs Node and LibreOffice; stop before writing anything
        probs = tools_problems(ctx.cfg, ctx.vault)
        if probs:
            raise SystemExit('gmh manual-notes: a cover letter needs the resume tools:\n  - ' + '\n  - '.join(probs))
    done = []
    for r in rows:
        spec = specs[r['id']]
        folder = os.path.join(ready_dir, spec['folder'])
        if not os.path.isdir(folder):
            continue
        top = int(float(r['salary_max'] or 0)) or None
        bottom = _bottom(open(os.path.join(ctx.P, 'state', 'jd', r['id'] + '.txt'), encoding='utf-8').read(), top)
        sal = salary_ask(ctx.prof, top, bottom)
        loc = (f"Remote from {a_home}." if r['locations'].split('/')[0] == 'Remote'
               else office_answer('Where will you work from?', r['locations'], ctx.prof, ctx.cfg))
        d = drafts.get(spec['slug'], {})
        cover_pdf = _cover(ctx, spec['company'], f'{long_date(ctx.today)}', d['cover'], folder, spec['slug']) if d.get('cover') else None
        md = [f"# Application notes: {r['company']}, {r['title']}", '',
              f"**Apply (manual):** {r['url']}  ",
              f"**Resume:** {prefix}Resume_{spec['slug']}.pdf (in this folder)  ",
              (f"**Cover letter:** {os.path.basename(cover_pdf)} (in this folder; .docx beside it)  " if cover_pdf else
               '**Cover letter:** none prepared. Ask Claude for one if the form has a cover letter field.  '),
              f"**Salary, if a number is required:** {sal} (rule: max(top x {ctx.prof.get('salary.top_factor', 0.75)}, range bottom, {floor}), top {top}, bottom {bottom}). If optional: Open, based on total compensation.  ",
              f"**Location / office questions:** {loc}  ",
              f"**Why manual:** {r['notes'].split('Oct 19. ', 1)[-1]}  ",
              f"**Prepared:** {long_date(ctx.today)}. Tell Claude when it's submitted so it's logged in applied.csv and the tracker.", '',
              '## Standard answers (profile.yaml)', '', '| Question | Answer |', '|---|---|']
        md += [f'| {q} | {a} |' for q, a in standard]
        md += ['', '## Gaps to expect in screening', '', f"- {r['top_gap']}", '']
        if d.get('cover'):
            md += ['## Cover letter text', ''] + [x + '\n' for x in d['cover']]
        open(os.path.join(folder, 'application-notes.md'), 'w', encoding='utf-8', newline='\n').write('\n'.join(md))
        print(f"{spec['slug']:28} cover={'yes' if cover_pdf else 'no ':3} salary={sal:7} {r['url'][:70]}")
        done.append(dict(company=r['company'], title=r['title'], url=r['url'],
                         notes=os.path.join(folder, 'application-notes.md'), cover=cover_pdf))
    if done:
        print('\n' + manual_apply_table(done))
    return done


# ---------- 5d: fill plans ----------
def _js(v):
    """A JS literal in the fillers' own style: single-quoted strings, ['a', 'b'] lists."""
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_js(x) for x in v) + ']'
    return "'" + str(v).replace('\\', '\\\\').replace("'", "\\'") + "'"


def _degree_loose(option):
    """A fallback for forms that spell the profile's degree level differently: "^Bachelor's Degree$" also takes
    "Bachelors", "Bachelor's" or "Bachelor Degree". Only the level word; never Bachelor of Arts for Science."""
    m = re.search(r'\b(bachelor|master|associate|doctor)', option or '', re.I)
    return f"^{m.group(1)}'?\u2019?s?( degree)?$" if m else '(?!)'


def filler_source(ctx, ats):
    """A form filler with the profile's form values substituted (tools/fillers/fill_<ats>.js)."""
    src = open(os.path.join(REPO, 'tools', 'fillers', f'fill_{ats}.js'), encoding='utf-8').read()
    f = ctx.prof.get('forms', {}) or {}
    edu, emp = f.get('education') or {}, f.get('employment') or {}
    mr = ctx.prof.get('employment.most_recent', {}) or {}
    city = f.get('city_typed') or ctx.prof.get('home.city') or ''
    subs = {
        '__CITY_TYPED__': _js(city), '__CITY_RE__': f.get('city_option') or '^' + re.escape(city),
        '__GH_LOCATION_RE__': f.get('greenhouse_location_option') or '^' + re.escape(city),
        '__LEVER_SCHOOL_RE__': edu.get('lever_school_option') or '(?!)',
        '__EDU_ON__': 'true' if edu.get('school_typed') else 'false',
        '__SCHOOL_TYPED__': _js(edu.get('school_typed', '')), '__SCHOOL_RE__': edu.get('school_option') or '(?!)',
        '__DEGREE_RE__': edu.get('degree_option') or '(?!)', '__DEGREE_LOOSE_RE__': _degree_loose(edu.get('degree_option')),
        '__DISC_TYPED__': _js(edu.get('discipline_typed', '')), '__DISC_RE__': edu.get('discipline_option') or '(?!)',
        '__EDU_START_MONTH__': _js(edu.get('start_month', [])), '__EDU_START_YEAR__': _js(edu.get('start_year', [])),
        '__EDU_END_MONTH__': _js(edu.get('end_month', [])), '__EDU_END_YEAR__': _js(edu.get('end_year', [])),
        '__EMP_ON__': 'true' if emp and mr.get('company') else 'false',
        '__EMP_COMPANY__': _js(mr.get('company', '')), '__EMP_TITLE__': _js(mr.get('title', '')),
        '__EMP_START_MONTH__': _js(emp.get('start_month', '')), '__EMP_START_YEAR__': _js(str(emp.get('start_year', ''))),
        '__EMP_END_MONTH__': _js(emp.get('end_month', '')), '__EMP_END_YEAR__': _js(str(emp.get('end_year', ''))),
        '__EMP_SUMMARY__': _js(emp.get('summary', '')),
    }
    for k, v in subs.items():
        src = src.replace(k, v)
    if ats == 'greenhouse':
        check = re.sub(r'^//.*$', '', open(os.path.join(REPO, 'tools', 'fillers', 'form_check.js'), encoding='utf-8').read(), flags=re.M).strip()
        src = src.replace('__CHECK__', check)
    return src


def build_fillplan(ctx, qid, state_root=None):
    state_root = state_root or ctx.P
    notes = json.load(open(os.path.join(state_root, 'state', 'notes', qid + '.json'), encoding='utf-8'))
    form = {q['label']: q for q in json.load(open(os.path.join(state_root, 'state', 'answers', qid + '.json'), encoding='utf-8'))['questions']}
    city = (ctx.prof.get('home.city') or '').lower()
    leave = f'LEAVE FOR {ctx.first.upper()}'
    plan, review = [], []
    for r in notes['rows']:
        q = form.get(r['label'], {})
        typ, opts, ans = q.get('type', ''), q.get('options') or [], str(r['answer'])
        if typ == 'Boolean' and re.match(rf'i live in {re.escape(city)} and can work from|yes\b', ans.lower()):
            ans = 'Yes'  # Ashby Yes/No buttons have no options list, so an office sentence becomes Yes
        if r['source'] in ('skip',) or ans.startswith('(') or ans in ('', 'DRAFT'):
            continue
        if 'CONFIRM' in ans or 'NEEDS DRAFT' in ans or leave in ans or r['source'] == 'ask' or ('[pick the matching option]' in ans and not opts):
            review.append(f"{r['label'][:90]}: {ans[:90]}")
            continue
        if typ in ('input_file', 'File', 'file'):
            lab = r['label'].strip().lower()
            path = (notes['resume'] if re.match(r'(resume|cv|resume/cv)\b', lab)
                    else notes['cover'] if lab.startswith('cover letter') else None)
            if not path and r['required']:
                review.append(f"{r['label'][:90]}: required upload that is not a resume or cover letter")
            if path:
                plan.append(dict(label=r['label'], kind='file', value=path))
            continue
        if r['source'] == 'consent':
            choice = choose_option(opts, r['label'], 'Yes', ctx.prof) or (opts[0] if len(opts) == 1 else None)
            plan.append(dict(label=r['label'], kind='choice', value=[choice] if choice else [], consent=True))
            if not choice:
                review.append(f"{r['label'][:90]}: consent box, check manually")
            continue
        if opts:
            if typ == 'multi_value_multi_select' and ';' in ans:
                vals = [choose_option(opts, r['label'], part.strip(), ctx.prof) for part in ans.split(';') if part.strip()]
            else:
                vals = [choose_option(opts, r['label'], ans, ctx.prof)]
            if not all(vals):
                review.append(f"{r['label'][:90]}: no option matches '{ans[:60]}' (options: {' / '.join(opts[:6])})")
                continue
            f = dict(label=r['label'], kind='choice', value=vals)
            if qid.startswith('gh-') and q.get('section') == 'eeo' and r['label'] == 'Race':
                # Greenhouse asks "Are you Hispanic/Latino?" first and shows the race box only after "No";
                # the API lists just "Race", so the filler answers the Hispanic box from the profile first
                hisp = 'Yes' if re.search(r'hispanic|latin', vals[0], re.I) else None
                if not hisp:
                    h = ctx.answerer().classify('Are you Hispanic/Latino?')
                    hisp = choose_option(['Yes', 'No', 'Decline To Self Identify'], 'Hispanic/Latino', h['answer'] or '')
                if hisp:
                    f['hispanic'] = hisp
                else:
                    review.append('Are you Hispanic/Latino? (shown before Race): no answer in the profile, set it by hand')
            plan.append(f)
        elif r['label'].strip().lower() == 'location' and (q.get('location_types') == ['Country']
                                                            or re.search(r'\bcountry\b', q.get('description', ''), re.I)):
            # a location field that asks for the country ("Country you're currently residing in"): type the country
            country = re.sub(r'\s+of america$', '', str(ctx.prof.get('home.country') or ''), flags=re.I)
            if country:
                plan.append(dict(label=r['label'], kind='location', value=country, typed=country, re='^' + re.escape(country)))
            else:
                review.append(f"{r['label']}: asks for the country; the profile has no home.country")
        elif r['label'].strip().lower() in ('location', 'location (city)'):
            plan.append(dict(label='Location (City)', kind='location', value=ctx.prof.get('forms.city_typed') or ctx.prof.get('home.city')))
        else:
            plan.append(dict(label=r['label'], kind='text', value=ans))
    if qid.startswith('lv-'):
        for f in plan:
            q = form.get(f['label'], {})
            f['required'], f['section'] = bool(q.get('required')), q.get('section', '')
    ats = 'greenhouse' if qid.startswith('gh-') else 'ashby' if qid.startswith('ab-') else 'lever'
    os.makedirs(os.path.join(state_root, 'state', 'fillplans'), exist_ok=True)
    out = os.path.join(state_root, 'state', 'fillplans', qid + '.js')
    open(out, 'w', encoding='utf-8', newline='\n').write(filler_source(ctx, ats).replace('__PLAN__', json.dumps(plan, ensure_ascii=False)))
    return out, plan, review


def ats_of(qid):
    return 'greenhouse' if qid.startswith('gh-') else 'ashby' if qid.startswith('ab-') else 'lever'


def apply_url(ctx, qid, state_root=None):
    """The URL the form-filler opens: Ashby is the posting URL plus /application; Greenhouse and Lever, the form's own URL."""
    with open(os.path.join(state_root or ctx.P, 'state', 'notes', qid + '.json'), encoding='utf-8') as fh:
        url = json.load(fh)['url']
    if ats_of(qid) == 'ashby' and not url.rstrip('/').endswith('/application'):
        return url.split('#')[0].split('?')[0].rstrip('/') + '/application'
    return url


def submit_script(qid):
    """The absolute path of the submit script for this role's ATS (tools/submit/submit_<ats>.js)."""
    return os.path.join(REPO, 'tools', 'submit', f'submit_{ats_of(qid)}.js')


def resume_problems(ctx, qid, state_root=None):
    """Why this role's tailored resume must not go into a form: its PDF is missing or fails engine.verify, run on the
    resume JSON gmh tailor saved beside it (the same call as gmh tailor). A prebuilt resume has no JSON and is not re-checked."""
    with open(os.path.join(state_root or ctx.P, 'state', 'notes', qid + '.json'), encoding='utf-8') as fh:
        notes = json.load(fh)
    pdf = notes['resume']
    if not os.path.exists(pdf):
        return [f'resume PDF not found: {pdf}']
    spec = None
    for sp in glob.glob(os.path.join(ctx.P, 'specs', '*.json')):
        with open(sp, encoding='utf-8') as fh:
            d = json.load(fh)
        if d.get('id') == qid:
            spec = d
            break
    doc_p = os.path.join(notes['folder'], f"resume_{spec['slug']}.json") if spec else None
    if not doc_p or not os.path.exists(doc_p):
        return []
    with open(doc_p, encoding='utf-8') as fh:
        doc = {k: v for k, v in json.load(fh).items() if not k.startswith('_')}
    jd_p = os.path.join(ctx.P, 'state', 'jd', qid + '.txt')
    jd = open(jd_p, encoding='utf-8').read() if os.path.exists(jd_p) else None
    facts = next((open(p, encoding='utf-8').read() for p in (os.path.join(ctx.ws, 'master-resume.md'),
                  os.path.join(ctx.vault, 'master-resume.md')) if os.path.exists(p)), None)
    fails, _ = verify(pdf, doc, ctx.prof, ctx.cfg, specs_mod.load_bank(ctx.ws), jd, _term_re(ctx), facts=facts, design=ctx.design)
    return fails


def main(argv=None):
    ap = argparse.ArgumentParser(description='get-me-hired application stages (v2).')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('stage', choices=['answers', 'specs', 'tailor', 'notes', 'manual-notes', 'fillplan'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--date', help='notes, manual-notes: the reviewed-<date>.csv to read (default: the date in the '
                                   'drafts file name, else the latest)')
    ap.add_argument('--out', help='specs brief: where to write the packet (default: the scratch path; - for stdout)')
    ap.add_argument('--spec', help='specs coverage: the spec or tailor reply to measure (default: the scratch spec)')
    a = ap.parse_args(argv)
    if not a.workspace:
        sys.exit('--workspace (or $GMH_WORKSPACE) is required')
    from .setup import stage_problems
    probs = stage_problems(a.workspace, a.stage)
    if probs:
        sys.exit(f'gmh {a.stage}: not ready, nothing was changed. Still needed:\n  - ' + '\n  - '.join(probs)
                 + f'\n(gmh setup check --workspace {a.workspace} lists everything the workspace still needs)')
    ctx = Ctx(a.workspace)
    if not (a.stage == 'specs' and a.args[:1] in (['brief'], ['check-entry'], ['coverage'])):  # these only read
        ctx.snapshot()
    if a.stage == 'answers':
        stage_answers(ctx)
    elif a.stage == 'specs' and a.args[:1] == ['brief'] and len(a.args) == 2 and a.out == '-':
        try:
            print(json.dumps(specs_mod.brief(ctx.ws, ctx.P, a.args[1], a.date, ctx.cfg), indent=1, ensure_ascii=False))
        except specs_mod.SpecError as e:
            sys.exit(f'spec error: {e}')
    elif a.stage == 'specs' and a.args[:1] in (['brief'], ['accept'], ['coverage']):
        code, text = specs_mod.run_command(ctx.ws, a.args, out=a.out, date=a.date, spec=a.spec, cfg=ctx.cfg)
        print(text, file=sys.stderr if code == 2 else sys.stdout)
        sys.exit(code)
    elif a.stage == 'specs' and a.args[:1] == ['check-entry'] and len(a.args) == 2:
        probs = specs_mod.check_entry(json.load(open(a.args[1], encoding='utf-8')), _templates(ctx),
                                      specs_mod.load_bank(ctx.ws), ctx.cfg)
        print('\n'.join(probs) or 'ok')
        sys.exit(1 if probs else 0)
    elif a.stage == 'specs':
        stage_specs(ctx, a.args[0])
    elif a.stage == 'tailor':
        ok = stage_tailor(ctx, a.args)
        sys.exit(0 if all(ok) else 1)
    elif a.stage == 'notes':
        stage_notes(ctx, a.args[0], date=a.date)
    elif a.stage == 'manual-notes':
        stage_manual_notes(ctx, date=a.date, drafts_path=a.args[0] if a.args else None)
    elif a.stage == 'fillplan':
        refused = 0
        for qid in a.args:
            probs = resume_problems(ctx, qid)
            if probs:
                refused += 1
                print(f"{qid}: not planned, the tailored resume fails its checks (fix it with gmh tailor):\n    - "
                      + '\n    - '.join(probs))
                continue
            out, plan, review = build_fillplan(ctx, qid)
            print(f"{qid}: {len(plan)} fields planned -> {os.path.relpath(out, ctx.P)}")
            print(f'   apply_url: {apply_url(ctx, qid)}')
            print(f'   submit_script: {submit_script(qid)}')
            for r in review:
                print('   REVIEW', r)
        sys.exit(1 if refused else 0)


if __name__ == '__main__':
    main()
