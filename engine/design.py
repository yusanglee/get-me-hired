"""Resume design tokens: <workspace>/design.json over the shipped templates/design.json.

Both Node builders (tools/resume.js, tools/cover_letter.js) take the merged tokens in their payload's
`design` key. The shipped defaults reproduce the original design byte for byte (checked by
rebuilding sent resumes: see docs/STATUS.md). The editor (`gmh design serve`, engine/design_editor.py)
writes the workspace file; earlier designs are kept under <workspace>/design-backups/.

    from engine.design import load_design, save_design, validate
"""
import copy, datetime, json, os, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(REPO, 'templates', 'design.json')
HEX = re.compile(r'^#?[0-9A-Fa-f]{6}$')

# (path, low, high) for every number the editor can change; validate() rejects anything outside.
RANGES = {
    'sizes_pt.name': (12, 28), 'sizes_pt.section': (8, 14), 'sizes_pt.role': (8, 14),
    'sizes_pt.body': (8, 12), 'sizes_pt.contact': (7, 12),
    'line_height': (1.0, 1.6), 'letter_spacing_pt.name': (0, 6), 'letter_spacing_pt.section': (0, 4),
    'section_rule.weight_pt': (0.25, 2), 'section_rule.gap_pt': (0, 8),
    'bullet.indent_in': (0.1, 0.5), 'bullet.hanging_in': (0.05, 0.4), 'dates.tab_pt': (400, 560),
    'page.width_in': (8.5, 8.5), 'page.height_in': (11, 11),
    'cover_letter.body_size_pt': (9, 13), 'cover_letter.line_height': (1.0, 1.8),
}
for k in ('top', 'right', 'bottom', 'left'):
    RANGES[f'page.margins_pt.{k}'] = (18, 72)
    RANGES[f'cover_letter.margins_pt.{k}'] = (36, 108)
BULLETS = ['•', '◦', '▪', '■', '-', '·']  # no en/em dash: verify fails any dash in the text layer
ALIGN = ('right', 'inline')


def default_design():
    with open(DEFAULT_PATH, encoding='utf-8') as f:
        return json.load(f)


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def get(d, path):
    for p in path.split('.'):
        d = d[p]
    return d


def validate(t):
    """Errors for a merged token set (empty list when it's usable)."""
    errs = []
    base = default_design()

    def walk(ref, cur, pre=''):
        for k, v in ref.items():
            if k.startswith('_'):
                continue
            path = pre + k
            if k not in cur:
                errs.append(f'{path} missing')
            elif isinstance(v, dict):
                if not isinstance(cur[k], dict):
                    errs.append(f'{path} must be an object')
                else:
                    walk(v, cur[k], path + '.')
            elif isinstance(v, bool) and not isinstance(cur[k], bool):
                errs.append(f'{path} must be true or false')
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and (isinstance(cur[k], bool) or not isinstance(cur[k], (int, float))):
                errs.append(f'{path} must be a number')
            elif isinstance(v, str) and not isinstance(cur[k], str):
                errs.append(f'{path} must be text')
    walk(base, t)
    typed = set(errs)

    def val(path):  # the value at path when walk() found it well-typed, else None
        try:
            v = get(t, path)
        except (KeyError, TypeError):
            return None
        return None if any(e.startswith(path + ' ') for e in typed) else v

    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    for path, (lo, hi) in RANGES.items():
        v = val(path)
        if num(v) and not lo <= v <= hi:
            errs.append(f'{path} = {v} is outside {lo}..{hi}')
    for grp in ('spacing_pt', 'cover_letter.spacing_pt'):
        for k, v in (val(grp) or {}).items():
            if num(v) and not 0 <= v <= 40:
                errs.append(f'{grp}.{k} = {v} is outside 0..40')
    for k, v in (val('colors') or {}).items():
        if not HEX.match(str(v)):
            errs.append(f'colors.{k} = {v!r} is not a 6-digit hex color')
    for k in ('heading', 'body'):
        v = val(f'fonts.{k}')
        if isinstance(v, str) and not re.fullmatch(r"[A-Za-z0-9 .'-]{2,40}", v):
            errs.append(f'fonts.{k} = {v!r} is not a font name')
    if val('bullet.glyph') is not None and t['bullet']['glyph'] not in BULLETS:
        errs.append(f'bullet.glyph must be one of {" ".join(BULLETS)}')
    if val('dates.align') is not None and t['dates']['align'] not in ALIGN:
        errs.append('dates.align must be right or inline')
    hang, ind = val('bullet.hanging_in'), val('bullet.indent_in')
    if num(hang) and num(ind) and hang > ind:
        errs.append('bullet.hanging_in must not exceed bullet.indent_in')
    sep = val('separator')
    if isinstance(sep, str) and not 0 < len(sep) <= 6:
        errs.append('separator must be 1 to 6 characters')
    return errs


def design_path(ws):
    return os.path.join(os.path.expanduser(ws), 'design.json')


def load_design(ws=None):
    """Shipped defaults, overridden by <ws>/design.json when it exists. Raises on invalid tokens."""
    t = default_design()
    p = design_path(ws) if ws else None
    if p and os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            t = merge(t, json.load(f))
    errs = validate(t)
    if errs:
        raise ValueError(f'{p or DEFAULT_PATH}: ' + '; '.join(errs))
    return t


def save_design(ws, tokens, now=None):
    """Write <ws>/design.json after backing up the current one. Returns (path, backup path or None)."""
    t = merge(default_design(), tokens)
    errs = validate(t)
    if errs:
        raise ValueError('; '.join(errs))
    p, backup = design_path(ws), None
    if os.path.exists(p):
        bdir = os.path.join(os.path.dirname(p), 'design-backups')
        os.makedirs(bdir, exist_ok=True)
        stamp = (now or datetime.datetime.now()).strftime('%Y%m%d-%H%M%S')
        backup = os.path.join(bdir, f'design-{stamp}.json')
        n = 1
        while os.path.exists(backup):
            n += 1
            backup = os.path.join(bdir, f'design-{stamp}-{n}.json')
        with open(p, 'rb') as src, open(backup, 'wb') as dst:
            dst.write(src.read())
    t['_about'] = default_design()['_about']
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(t, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, p)
    return p, backup


# ---------- fonts: only what the DOCX names and the PDF really embeds ----------
# Common ATS-safe faces (standard, readable, full Latin text layer). probe_fonts() decides which of them
# this machine's LibreOffice actually embeds; the editor offers only those.
CANDIDATES = ['Arial', 'Helvetica', 'Calibri', 'Carlito', 'Cambria', 'Caladea', 'Georgia', 'Garamond',
              'EB Garamond', 'Times New Roman', 'Liberation Sans', 'Liberation Serif', 'Verdana', 'Tahoma',
              'Trebuchet MS', 'Book Antiqua', 'Palatino', 'Gill Sans', 'Lato', 'Roboto', 'Open Sans',
              'Source Sans 3', 'Noto Sans', 'Noto Serif', 'DejaVu Sans', 'DejaVu Serif']
SERIF = {'Cambria', 'Caladea', 'Georgia', 'Garamond', 'EB Garamond', 'Times New Roman', 'Liberation Serif',
         'Book Antiqua', 'Palatino', 'Noto Serif', 'DejaVu Serif'}
# LibreOffice swaps these for metric-compatible twins: same widths, so line breaks match the DOCX in Word.
METRIC_TWIN = {'arial': 'liberationsans', 'helvetica': 'liberationsans', 'timesnewroman': 'liberationserif',
               'calibri': 'carlito', 'cambria': 'caladea', 'couriernew': 'liberationmono'}


def _norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def embedded_names(pdffonts_out):
    """Base font names from `pdffonts` output, subset prefix dropped ('BAAAAA+Caladea-Bold' -> 'Caladea-Bold')."""
    out = []
    for line in pdffonts_out.splitlines()[2:]:
        parts = line.split()
        if parts:
            out.append(parts[0].split('+', 1)[-1])
    return out


def font_matches(font, names):
    """'own' when the PDF embeds the font itself, 'twin' when it embeds its metric twin, else None."""
    want = _norm(font)
    base = [_norm(n.split('-')[0]) for n in names]
    if any(b.startswith(want) or (want.endswith('3') and b.startswith(want[:-1])) for b in base):
        return 'own'
    twin = METRIC_TWIN.get(want)
    if twin and any(b.startswith(twin) for b in base):
        return 'twin'
    return None


def probe_fonts(fonts, node_path, soffice, work):
    """Build one docx per font, convert them all in one LibreOffice run, read pdffonts.
    Returns {font: {status: own|twin|substituted|failed, embedded: [names], bold, italic}}."""
    import subprocess
    from .profile import soffice_pdf
    os.makedirs(work, exist_ok=True)
    subprocess.run(['node', os.path.join(REPO, 'tools', 'font_probe.js'), work, *fonts], check=True,
                   capture_output=True, env=dict(os.environ, NODE_PATH=node_path))
    docs = [os.path.join(work, f'{i}.docx') for i in range(len(fonts))]
    soffice_pdf(soffice, work, *docs)
    out = {}
    for i, font in enumerate(fonts):
        pdf = os.path.join(work, f'{i}.pdf')
        if not os.path.exists(pdf):
            out[font] = {'status': 'failed', 'embedded': []}
            continue
        names = embedded_names(subprocess.run(['pdffonts', pdf], capture_output=True, text=True, encoding='utf-8').stdout)
        text = subprocess.run(['pdftotext', pdf, '-'], capture_output=True, text=True, encoding='utf-8').stdout
        m = font_matches(font, names)
        readable = 'grew repeat purchases' in text and '(cid:' not in text
        out[font] = {'status': (m or 'substituted') if readable else 'unreadable', 'embedded': sorted(set(names)),
                     'bold': any('bold' in n.lower() for n in names), 'italic': any(('italic' in n.lower() or 'oblique' in n.lower()) for n in names),
                     'serif': font in SERIF}
    return out


def usable_fonts(probe):
    """Fonts the editor may offer: embedded as themselves, or as a metric twin."""
    return [f for f, r in probe.items() if r.get('status') in ('own', 'twin')]


# ---------- colour themes (custom colours are also allowed) ----------
THEMES = {
    'Classic': {'name': '212121', 'section': '6B6B6B', 'text': '212121', 'secondary': '6B6B6B', 'muted': '828282', 'rule': 'CCCCCC'},
    'Ink': {'name': '111111', 'section': '111111', 'text': '1A1A1A', 'secondary': '4A4A4A', 'muted': '6E6E6E', 'rule': '999999'},
    'Navy': {'name': '1F3A5F', 'section': '1F3A5F', 'text': '1E2329', 'secondary': '4E5A68', 'muted': '6F7A87', 'rule': 'B9C4D2'},
    'Forest': {'name': '24473C', 'section': '2F5D50', 'text': '1F2421', 'secondary': '4F5B55', 'muted': '707A74', 'rule': 'BCCBC4'},
    'Claret': {'name': '5E2236', 'section': '6D2E46', 'text': '241F21', 'secondary': '5A4F53', 'muted': '7A6F73', 'rule': 'D3C1C7'},
}
