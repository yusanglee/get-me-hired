"""The generic resume document, and building it to .docx/.pdf.

A resume document (JSON) is the same for every user:

    {
      "bio": "Product Leader  ·  Consumer Apps",          # line under the name
      "summary": "...",
      "experience": [                                      # newest first
        {"id": "acme", "role": "Senior PM", "dates": "Jan 2022 - Present",
         "company": "Acme", "location": "Chicago, IL", "scope": "One line on the company.",
         "bullets": ["Grew **X** by ...", "..."]}
      ],
      "skills": "Term  |  Term  |  Term",
      "education": [{"school": "State University", "degree": "B.A., Economics", "years": "2010 - 2014"}],
      "extra_sections": [{"heading": "INTERESTS", "text": "..."}]
    }

Name and contact lines come from profile.yaml, so one template serves every role.
A template is a resume document the user approved; a spec tailors it by overriding
bio, summary, skills, extra_sections, or `experience[i]` bullet lists (an
experience can also be addressed by its id: `experience.acme`). Overrides can
only use approved text; `engine.specs` enforces that.
"""
import copy, json, os, re, subprocess, shutil
from .profile import full_name, home_display, filename_prefix, find_soffice, soffice_pdf
from .design import load_design

TOP_KEYS = ('bio', 'summary', 'skills', 'extra_sections')
EXP_KEY = re.compile(r'^experience(?:\[(\d+)\]|\.([\w-]+))$')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def validate(doc):
    errs = []
    for k in ('summary', 'skills', 'experience', 'education'):
        if not doc.get(k):
            errs.append(f'missing {k}')
    for i, x in enumerate(doc.get('experience') or []):
        for k in ('role', 'dates', 'company', 'location'):
            if not x.get(k):
                errs.append(f'experience[{i}] missing {k}')
        if not isinstance(x.get('bullets'), list):
            errs.append(f'experience[{i}].bullets must be a list')
    ids = [x.get('id') for x in doc.get('experience') or [] if x.get('id')]
    if len(ids) != len(set(ids)):
        errs.append('duplicate experience ids')
    if errs:
        raise ValueError('resume document: ' + '; '.join(errs))
    return doc


def exp_index(doc, key):
    """'experience[2]' or 'experience.acme' (or a bare legacy id like 'acme') -> 2, else None."""
    m = EXP_KEY.match(key)
    if m and m.group(1) is not None:
        i = int(m.group(1))
        return i if i < len(doc['experience']) else None
    want = m.group(2) if m else key
    return next((i for i, x in enumerate(doc['experience']) if x.get('id') == want), None)


def apply_overrides(doc, overrides):
    """A copy of `doc` with spec overrides applied. Unknown keys raise, so a typo never ships silently."""
    out = copy.deepcopy(doc)
    for key, val in (overrides or {}).items():
        if key in TOP_KEYS:
            out[key] = val
            continue
        i = exp_index(out, key)
        if i is None:
            raise KeyError(f'unknown override {key!r}')
        out['experience'][i]['bullets'] = [val] if isinstance(val, str) else list(val)
    return validate(out)


def contact_lines(prof):
    custom = prof.get('resume.contact_lines')
    if custom:
        return list(custom)
    line1 = [home_display(prof), prof.get('identity.phone'), prof.get('identity.email')]
    line2 = [prof.get('identity.linkedin'), prof.get('identity.website')]
    return ['  ·  '.join(x for x in line if x) for line in (line1, line2) if any(line)]


def render_payload(doc, prof, design=None):
    """The builder's input. `design` is a merged token set (engine.design); None means the shipped defaults."""
    p = dict(name=prof.get('resume.name') or full_name(prof).upper(), contact=contact_lines(prof),
             bio=doc.get('bio', ''), summary=doc['summary'], skills=doc['skills'],
             experience=[{k: x.get(k, '') for k in ('role', 'dates', 'company', 'location', 'scope', 'bullets')} for x in doc['experience']],
             education=doc['education'], extra_sections=doc.get('extra_sections') or [])
    p['design'] = design or load_design()
    return p


def output_name(prof, slug, kind='Resume', ext='docx'):
    return f'{filename_prefix(prof)}{kind}_{slug}.{ext}'


TOOLS_MODULES = os.path.join(REPO, 'tools', 'node_modules')
INSTALL_HINT = f'install the Node tools once: npm install --prefix "{os.path.join(REPO, "tools")}"'


def node_modules(cfg=None, vault=None):
    """Where the Node tools find `docx`: config paths.node_modules, else the plugin's tools/node_modules,
    else a vault's Pipeline/tools/node_modules (the original pipeline's install)."""
    explicit = ((cfg or {}).get('paths') or {}).get('node_modules')
    cands = [explicit, TOOLS_MODULES] + ([os.path.join(vault, 'Pipeline', 'tools', 'node_modules')] if vault else [])
    return next((c for c in cands if c and os.path.isdir(os.path.join(os.path.expanduser(c), 'docx'))), explicit or TOOLS_MODULES)


def build(doc, prof, out_dir, slug, cfg=None, node_path=None, design=None, pdf=True):
    """Render doc -> <prefix>Resume_<slug>.docx (and .pdf via LibreOffice). Returns the paths."""
    os.makedirs(out_dir, exist_ok=True)
    payload = os.path.join(out_dir, f'.resume_{slug}.json')
    json.dump(render_payload(doc, prof, design), open(payload, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    docx = os.path.join(out_dir, output_name(prof, slug))
    env = dict(os.environ, NODE_PATH=node_path or os.environ.get('NODE_PATH', ''))
    if not shutil.which('node'):
        raise RuntimeError('Node.js not found: install it (https://nodejs.org), then ' + INSTALL_HINT)
    r = subprocess.run(['node', os.path.join(REPO, 'tools', 'resume.js'), payload, docx], env=env, capture_output=True, text=True, encoding='utf-8')
    if r.returncode:
        hint = INSTALL_HINT if "Cannot find module 'docx'" in r.stderr else 'see the error above'
        raise RuntimeError(f'resume build failed for {slug}: {r.stderr.strip()[-400:]}\n  fix: {hint}')
    os.remove(payload)
    out = {'docx': docx}
    if pdf:
        soffice = find_soffice(cfg)
        if not soffice:
            raise RuntimeError('LibreOffice not found (it turns the .docx into a PDF): install it from libreoffice.org '
                               'or `brew install --cask libreoffice`, or set paths.soffice in config.json')
        soffice_pdf(soffice, out_dir, docx)
        out['pdf'] = docx[:-5] + '.pdf'
    return out


# ---------- page and content rules (config resume.*, profile resume.stale_numbers) ----------
def _is_heading(line):
    t = line.strip()
    return len(t) >= 5 and t.isupper() and not re.search(r'\d|·', t)


def experience_section(page):
    """The PROFESSIONAL EXPERIENCE part of one page's text (to the next section heading). A page without that
    heading (page 2, or synthetic text) is returned whole."""
    lines = page.splitlines()
    start = next((k for k, l in enumerate(lines) if l.strip() == 'PROFESSIONAL EXPERIENCE'), None)
    if start is None:
        return page
    end = next((k for k in range(start + 1, len(lines)) if _is_heading(lines[k])), len(lines))
    return '\n'.join(lines[start + 1:end])


def _squash(s):
    return re.sub(r'\s+', ' ', s).strip()


def _first_line(page):
    return next((l for l in page.splitlines() if l.strip()), '')


def carried_over_start(page, glyph='•'):
    """True when the page's first non-empty line is a bullet or a bullet's continuation line (indented past the
    page's left edge): the previous page's text spilled over."""
    lines = [l for l in page.splitlines() if l.strip()]
    if not lines:
        return False
    first = lines[0]
    if first.strip().startswith(glyph):
        return True
    indent = lambda l: len(l) - len(l.lstrip())
    return indent(first) >= min(indent(l) for l in lines) + 2


def page_break_failures(pages, doc, rules):
    """rules: {"pages": 2, "max_pages": 2, "last_on_page_1": "experience[2]", "first_on_page_2": "experience[3]"}.
    `pages` is the PDF text split on form feeds. Names are matched by company, and only inside page 1's
    PROFESSIONAL EXPERIENCE section (a summary naming the company does not count). first_on_page_2 needs page
    2's first line to be that role's title line. When more than one page is wanted, no page may start with a
    carried-over bullet (`glyph` in rules, default the bullet dot)."""
    fails = []
    pages = [p for p in pages if p.strip()]
    want = rules.get('pages')
    if want and len(pages) != want:
        fails.append(f'{len(pages)} pages (want {want})')
    cap = rules.get('max_pages')
    if cap and len(pages) > cap:
        fails.append(f'{len(pages)} pages (max {cap})')
    exp1 = experience_section(pages[0]) if pages else ''
    for key, page_no in (('last_on_page_1', 0), ('first_on_page_2', 1)):
        ref = rules.get(key)
        if not ref:
            continue
        i = exp_index(doc, ref)
        if i is None:
            fails.append(f'page rule {key}: unknown {ref}')
            continue
        company = doc['experience'][i]['company']
        if key == 'last_on_page_1':
            if not pages or company not in exp1:
                fails.append(f'page boundary: {company} not on page 1')
            nxt = doc['experience'][i + 1]['company'] if i + 1 < len(doc['experience']) else None
            if nxt and pages and nxt in exp1:
                fails.append(f'page boundary: {nxt} rose onto page 1')
        elif len(pages) < 2 or company in exp1 or company not in pages[1]:
            fails.append(f'page boundary: {company} is not at the top of page 2')
        else:
            role = _squash(doc['experience'][i].get('role', ''))
            first = _squash(_first_line(pages[1]))
            # a real layout contains the role title somewhere; then the top line must be this role's title line
            if role and any(role in _squash(p) for p in pages) and role not in first:
                fails.append(f'page boundary: page 2 starts with "{first[:40]}", not the {company} role line')
    if max(want or 0, cap or 0) > 1:
        glyph = rules.get('glyph') or '•'
        for n, pg in enumerate(pages[1:], 2):
            if carried_over_start(pg, glyph):
                fails.append(f'page {n} starts with a carried-over bullet: "{_squash(_first_line(pg))[:40]}"')
    return fails


def stale_failures(text, patterns):
    flat = re.sub(r'\s+', ' ', text)
    return [f'stale figure {s}' for s in patterns or [] if re.search(s, flat)]


# ---------- migration helper: read an approved build_resume_*.js into a document ----------
_S = r"'((?:[^'\\]|\\.)*)'"


def _js(s):
    return s.replace("\\'", "'").replace('\\\\', '\\')


def from_build_script(js, content):
    """Turn one of the original pipeline's build_resume_<Name>.js scripts plus its CONTENT
    (as JSON, from tools/content.js) into a generic document. Experience ids are the old
    CONTENT keys (one per job), so old specs still address them."""
    exp_part = js.split("sectionHeading('PROFESSIONAL EXPERIENCE')", 1)[1].split("sectionHeading('SKILLS')", 1)[0]
    experience, cur = [], None
    for m in re.finditer(r"roleLine\(" + _S + r",\s*" + _S + r"\)|companyLine\(" + _S + r",\s*" + _S + r"\)|scopeLine\(" + _S + r"\)"
                         r"|CONTENT\.(\w+)\.forEach|bullet\(CONTENT\.(\w+)\)", exp_part):
        if m.group(1) is not None:
            cur = {'id': None, 'role': _js(m.group(1)), 'dates': _js(m.group(2)), 'company': '', 'location': '', 'scope': '', 'bullets': []}
            experience.append(cur)
        elif m.group(3) is not None:
            cur['company'], cur['location'] = _js(m.group(3)), _js(m.group(4))
        elif m.group(5) is not None:
            cur['scope'] = _js(m.group(5))
        else:
            key = m.group(6) or m.group(7)
            cur['id'] = key
            v = content[key]
            cur['bullets'] = [v] if isinstance(v, str) else list(v)
            if isinstance(v, str):
                cur['single'] = True  # the old CONTENT held one string, not a list
    edu = re.search(r"\[(\[" + _S + r",\s*" + _S + r",\s*" + _S + r"\](?:,\s*\[[^\]]*\])*)\]\.forEach\(\(\[u, d, y\]", js)
    education = [{'school': _js(a), 'degree': _js(b), 'years': _js(c)}
                 for a, b, c in re.findall(r"\[" + _S + r",\s*" + _S + r",\s*" + _S + r"\]", edu.group(1))] if edu else []
    extra = [{'heading': _js(h), 'text': _js(t)} for h, t in
             re.findall(r"sectionHeading\(" + _S + r"\)\);\s*\nc\.push\(new Paragraph\(\{[^\n]*?rich\(" + _S + r"\)", js.split("sectionHeading('EDUCATION')", 1)[1])]
    doc = {'bio': content.get('bio', ''), 'summary': content['summary'], 'skills': content['skills'],
           'experience': experience, 'education': education, 'extra_sections': extra}
    return validate(doc)


def to_legacy(doc):
    """The old CONTENT object (keys by experience id), for the original pipeline's tailor.py."""
    out = {k: doc[k] for k in ('bio', 'summary', 'skills') if k in doc}
    for x in doc['experience']:
        if x.get('id'):
            out[x['id']] = x['bullets'][0] if x.get('single') else x['bullets']
    return out
