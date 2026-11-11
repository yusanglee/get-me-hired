"""Resume checks for one built PDF (+ its .docx), driven by profile and config instead of one person's layout.

Checks: contact details and section headings extract as text; no tables, text boxes, drawings,
columns, headers or footers in the .docx; no em/en dashes; no stale figures (profile
resume.stale_numbers); bullets within resume.max_bullet_lines and the summary within
resume.max_summary_lines; the v1 layout rules (each off unless its key is set: max_pages,
max_scope_lines, min_last_line_words, skills_lines, max_page1_free_pt); page count and page-break rules (resume.page_breaks); the body font
is embedded (resume.font); skills terms are all approved (bank skills). JD keyword coverage is
reported, never enforced.

ATS checks (Phase 5, after ai-job-search's ATS rules, MIT): the PDF text layer has no "(cid:N)",
replacement or private-use glyphs; date ranges use a plain ASCII hyphen (Workday's import misreads
others); and, given the approved facts, a keyword table: covered / synonym / have-it (true per the
facts but not on this resume) / gap. The table is advice for choosing approved bullets, never a
reason to add words the facts don't support.

    from engine.verify import verify
    fails, notes = verify(pdf, doc, prof, cfg, bank, jd_text=None, jd_terms=None)
"""
import re, subprocess, zipfile
from .resume import page_break_failures, stale_failures


def _run(*a):
    return subprocess.run(a, capture_output=True, text=True, encoding='utf-8').stdout


def bullet_blocks(lines, glyph='•'):
    blocks, cur = [], None
    for ln in lines:
        if ln.strip().startswith(glyph):
            cur = [ln]
            blocks.append(cur)
        elif cur is not None and ln.startswith('  ') and ln.strip():
            cur.append(ln)
        else:
            cur = None
    return blocks


def _plain(text):
    """Paragraph text as it reads in the PDF: **bold** marks gone, compatibility forms folded, no spaces."""
    import unicodedata
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text.replace('**', '')))


def paragraph_lines(lines, text, glyph='•'):
    """The layout lines (stripped, bullet glyph removed) one paragraph occupies, found by matching its text
    against consecutive lines. None when it can't be located."""
    target = _plain(text)
    rows = [l.replace('\f', '').strip() for l in lines]
    rows = [r[len(glyph):].strip() if r.startswith(glyph) else r for r in rows]
    for s in range(len(rows)):
        acc, got = '', []
        for r in rows[s:]:
            if not r:
                break
            acc += _plain(r)
            got.append(r)
            if acc == target:
                return got
            if not target.startswith(acc):
                break
    return None


def layout_rule_failures(lines, doc, rules, glyph='•'):
    """The v1 layout rules (all off when their config key is missing): max_scope_lines, min_last_line_words,
    skills_lines. Returns (failures, notes); a paragraph that can't be found in the text is noted, not failed."""
    fails, notes, lost = [], [], 0
    scope_max, runt, skills_n = rules.get('max_scope_lines'), rules.get('min_last_line_words'), rules.get('skills_lines')
    if not (scope_max or runt or skills_n):
        return fails, notes
    paras = [('summary', doc.get('summary', ''), False)]
    for x in doc.get('experience', []):
        if x.get('scope'):
            paras.append(('scope', x['scope'], False))
        paras += [('bullet', b, True) for b in x.get('bullets', [])]
    paras.append(('skills', doc.get('skills', ''), False))
    long_scope, runts, skills_bad = [], [], None
    for kind, text, is_bullet in paras:
        if not text.strip():
            continue
        got = paragraph_lines(lines, text, glyph if is_bullet else '\0')
        if got is None:
            lost += 1
            continue
        if kind == 'scope' and scope_max and len(got) > scope_max:
            long_scope.append(f'{len(got)} lines: {got[0][:40]}')
        if kind == 'skills' and skills_n and len(got) != skills_n:
            skills_bad = len(got)
        if runt and len(got) > 1 and len(got[-1].split()) < runt:
            runts.append(f'{kind} "{" ".join(_plain_words(text)[:6])}" ends on "{got[-1]}"')
    if long_scope:
        fails.append(f'{len(long_scope)} scope line(s) over {scope_max} lines: ' + ' | '.join(long_scope))
    if skills_bad is not None:
        fails.append(f'skills are {skills_bad} lines (want {skills_n})')
    if runts:
        fails.append(f'{len(runts)} paragraph(s) end on a last line under {runt} words: ' + ' | '.join(runts))
    if lost:
        notes.append(f'layout rules: {lost} paragraph(s) not found in the PDF text, not checked')
    return fails, notes


def _plain_words(text):
    return text.replace('**', '').split()


def skills_approved(skills, approved):
    ok = {t.lower() for t in approved}

    def good(t):
        t = t.strip().lower()
        if t in ok:
            return True
        m = re.fullmatch(r'(.+?)\s*\((.+)\)', t)  # "Mobile Apps (iOS, Android)": base and each inner term approved
        return bool(m) and m.group(1) in ok and all(x.strip() in ok for x in m.group(2).split(','))
    return [t.strip() for t in skills.split('|') if t.strip() and not good(t)]


GARBLED_RE = re.compile(r'\(cid:\d+\)|[\ufffd\ue000-\uf8ff]')
MONTH = r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?'
DATE = rf'(?:{MONTH}\s+)?(?:19|20)\d\d|\d{{1,2}}/(?:19|20)\d\d'
RANGE_RE = re.compile(rf'({DATE})(\s*)([^\sA-Za-z0-9])(\s*)({DATE}|present|current|now)\b', re.I)
# Common JD-term synonyms; a pack can add its own under "synonyms": {"term": ["alt", ...]}
SYNONYMS = {'a/b testing': ['experimentation', 'experiments', 'a/b tests'], 'experimentation': ['a/b testing', 'a/b tests'],
            'go-to-market': ['gtm', 'launch'], 'gtm': ['go-to-market'], 'roadmap': ['roadmaps', 'product strategy'],
            'machine learning': ['ml', 'ai'], 'ml': ['machine learning'], 'ai': ['machine learning', 'llm', 'genai'],
            'monetization': ['revenue', 'subscriptions', 'payments'], 'retention': ['churn', 'engagement'],
            'stakeholder management': ['cross-functional', 'stakeholders'], 'sql': ['bigquery', 'queries']}


def text_layer_failures(text):
    """Glyphs an ATS can't read: '(cid:N)' from unmapped fonts, U+FFFD, private-use characters."""
    bad = GARBLED_RE.findall(text)
    out = [f'text layer has {len(bad)} unreadable glyph(s) ({", ".join(sorted(set(bad))[:3])})'] if bad else []
    if not re.search(r'[A-Za-z]{3}', text):
        out.append('no extractable text (image-only PDF?)')
    return out


def date_range_failures(text):
    """Date ranges must read 'Jan 2021 - Mar 2024' with an ASCII hyphen, not a dash, minus or other symbol."""
    bad = sorted({m.group(0).strip() for m in RANGE_RE.finditer(text) if m.group(3) != '-'})
    return [f'{len(bad)} date range(s) without a plain hyphen: ' + ' | '.join(bad[:4])] if bad else []


def keyword_coverage(jd_text, jd_terms, resume_text, facts, synonyms=None):
    """{term: 'covered' | 'synonym' | 'have-it' | 'gap'} for each vocabulary term the JD uses.
    have-it: absent from this resume but present in the approved facts (pick a bullet that shows it)."""
    syn = {**SYNONYMS, **{k.lower(): v for k, v in (synonyms or {}).items()}}
    res, fac = resume_text.lower(), (facts or '').lower()
    has = lambda t, hay: re.search(r'(?<!\w)' + re.escape(t) + r'(?:s|es)?(?!\w)', hay) is not None  # plurals count
    out = {}
    for t in sorted({t.lower() for t in jd_terms.findall(jd_text)}):
        if has(t, res):
            out[t] = 'covered'
        elif any(has(a.lower(), res) for a in syn.get(t, [])):
            out[t] = 'synonym'
        elif has(t, fac):
            out[t] = 'have-it'
        else:
            out[t] = 'gap'
    return out


def coverage_note(cov):
    by = {}
    for t, k in cov.items():
        by.setdefault(k, []).append(t)
    parts = [f"{k} {len(by[k])}" + (f" ({', '.join(by[k])})" if k in ('have-it', 'gap') else '')
             for k in ('covered', 'synonym', 'have-it', 'gap') if by.get(k)]
    return 'coverage: ' + '; '.join(parts) if parts else 'coverage: no JD terms'


def font_failures(pdffonts_out, design):
    """Each design font must be embedded under its own name, or (DOCX keeps the name) its metric twin."""
    from .design import embedded_names, font_matches
    names = embedded_names(pdffonts_out)
    return [f'{f} not embedded' for f in dict.fromkeys([design['fonts']['heading'], design['fonts']['body']])
            if not font_matches(f, names)]


def verify(pdf, doc, prof, cfg, bank=None, jd_text=None, jd_terms=None, facts=None, synonyms=None, design=None):
    """design: the token set the resume was built with (engine.design). With it, the bullet glyph and both
    design fonts are checked; without it, config resume.font is."""
    rules = cfg.get('resume', {})
    fails, notes = [], []
    pages = _run('pdftotext', '-layout', pdf, '-').split('\f')
    text = '\n'.join(pages)
    flat = re.sub(r'\s+', ' ', text)
    for need in [prof.get('identity.email'), prof.get('identity.phone')] + list(rules.get('sections') or []):
        if need and need not in flat:
            fails.append(f'missing "{need}"')

    docx = pdf[:-4] + '.docx'
    z = zipfile.ZipFile(docx)
    xml = z.read('word/document.xml').decode()
    for tag in ['<w:tbl>', '<w:txbxContent', '<w:drawing', '<w:cols ']:
        if tag in xml:
            fails.append(f'docx contains {tag}')
    if any(n.startswith(('word/header', 'word/footer')) for n in z.namelist()):
        fails.append('docx has header/footer part')

    dashes = len(re.findall('[–—]', text))
    if dashes:
        fails.append(f'{dashes} em/en dashes')
    fails += stale_failures(text, prof.get('resume.stale_numbers', []))
    fails += text_layer_failures(text)
    fails += date_range_failures(text)

    lines = text.splitlines()
    limit = rules.get('max_bullet_lines', 2)
    long = [b[0].strip()[2:60] for b in bullet_blocks(lines, design['bullet']['glyph'] if design else '•') if len(b) > limit]
    if long:
        fails.append(f'{len(long)} bullet(s) over {limit} lines: ' + ' | '.join(long))
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == 'EXECUTIVE SUMMARY')
        j = next(k for k, l in enumerate(lines) if l.strip() == 'PROFESSIONAL EXPERIENCE')
        n = len([l for l in lines[i + 1:j] if l.strip()])
        if n > rules.get('max_summary_lines', 4):
            fails.append(f'summary is {n} lines')
    except StopIteration:
        pass

    glyph = design['bullet']['glyph'] if design else '•'
    lf, ln = layout_rule_failures(lines, doc, rules, glyph)
    fails += lf
    notes += ln
    fails += page_break_failures(pages, doc, dict(rules.get('page_breaks') or {}, pages=rules.get('pages'),
                                                  max_pages=rules.get('max_pages'), glyph=glyph))
    bbox = _run('pdftotext', '-bbox', '-f', '1', '-l', '1', pdf, '-')
    ys = [float(y) for y in re.findall(r'yMax="([\d.]+)"', bbox)]
    if ys:  # free space under the last line of page 1 (page height minus bottom margin, in points)
        free = round(792 - rules.get('bottom_margin_pt', 28) - max(ys), 1)
        notes.append(f'page-1 free {free}pt')
        multi_page = len([p for p in pages if p.strip()]) > 1  # a one-page resume may end wherever it ends
        if rules.get('max_page1_free_pt') is not None and multi_page and free > rules['max_page1_free_pt']:
            fails.append(f"page 1 has {free}pt free (max {rules['max_page1_free_pt']}pt)")
    if design:
        fails += font_failures(_run('pdffonts', pdf), design)
    elif rules.get('font') and rules['font'] not in _run('pdffonts', pdf):
        fails.append(f"{rules['font']} not embedded")
    if bank is not None:
        bad = skills_approved(doc['skills'], bank.get('skills', []))
        if bad:
            fails.append('skills not approved: ' + ', '.join(bad))
    if jd_text and jd_terms is not None:
        terms = sorted({t.lower() for t in jd_terms.findall(jd_text)})
        miss = [t for t in terms if t not in flat.lower()]
        notes.append(f'JD terms {len(terms) - len(miss)}/{len(terms)}' + (f' (missing: {", ".join(miss)})' if miss else ''))
        if facts:
            notes.append(coverage_note(keyword_coverage(jd_text, jd_terms, flat, facts, synonyms)))
    return fails, notes
