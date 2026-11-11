"""Resume design editor: a local page (controls left, live preview right) that edits <workspace>/design.json.

    python3 -m engine.design_editor --workspace <ws> [--port 8765] [--open]     (bin/gmh design ...)
    python3 -m engine.design_editor --workspace <ws> fonts [--refresh]        probe and list usable fonts

The preview is HTML drawn from the user's own resume: the newest resume_<slug>.json the tailor stage
wrote under Workflow/, else an approved template. It is an approximation; "Check" builds the real
DOCX and PDF with the tokens, runs engine.verify (page count, line limits, page-break rules, fonts,
ATS text layer) and shows the PDF pages. "Save" is allowed only for tokens that were checked; it backs
up the current design.json first. Saved tokens apply to resumes built from then on; resumes already
built are never rebuilt or touched.

Fonts: only fonts this machine's LibreOffice really embeds (engine.design.probe_fonts) are offered,
and the preview loads those same font files, so it can't show a face the PDF won't have.

The server listens on 127.0.0.1 only. Every POST needs the per-run token embedded in the page.
"""
import argparse, base64, glob, hashlib, http.server, json, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, webbrowser
from urllib.parse import urlparse, parse_qs, unquote

from .profile import load_profile, load_config, find_soffice
from .resume import build, render_payload, validate as validate_doc, node_modules
from .design import (CANDIDATES, THEMES, BULLETS, RANGES, default_design, load_design, merge, probe_fonts,
                     save_design, usable_fonts, validate as validate_tokens, design_path)
from .verify import verify

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'design_editor.html')
FONT_EXT = ('.ttf', '.otf')


# ---------- resume sources ----------
def resume_sources(ws, cfg, limit=12):
    """[(id, label, path)] newest built resume documents first, then approved templates."""
    out = []
    from . import layout
    vault = layout.vault(ws, cfg)
    if os.path.isdir(os.path.join(vault, 'Workflow')):
        built = glob.glob(os.path.join(vault, 'Workflow', '*', '*', 'resume_*.json'))
        if os.path.exists(os.path.join(vault, 'Pipeline', 'tools', 'content.js')):  # the original pipeline's build scripts
            built += glob.glob(os.path.join(vault, 'Workflow', '*', '*', 'build_resume_*.js'))
        built.sort(key=os.path.getmtime, reverse=True)
        for p in built[:limit]:
            folder = os.path.basename(os.path.dirname(p))
            out.append(('b:' + p, f'Built: {folder}', p))
    for p in sorted(glob.glob(os.path.join(ws, 'resume', 'templates', '*.json'))):
        out.append(('t:' + p, f'Template: {os.path.basename(p)[:-5]}', p))
    return out


def load_doc(path):
    if path.endswith('.js'):
        from .migrate import content_of
        from .resume import from_build_script
        tools = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path)))), 'Pipeline', 'tools')
        return from_build_script(open(path, encoding='utf-8').read(), content_of(path, tools))
    doc = json.load(open(path, encoding='utf-8'))
    return validate_doc({k: v for k, v in doc.items() if not k.startswith('_')})


# ---------- font files the preview can load (the same files LibreOffice embeds) ----------
def font_dirs(soffice):
    dirs = []
    if soffice:
        real = os.path.realpath(soffice)
        dirs += [os.path.join(os.path.dirname(real), '..', 'Resources', 'fonts', 'truetype'),
                 os.path.join(os.path.dirname(real), '..', 'share', 'fonts', 'truetype')]
    dirs += ['/Applications/LibreOffice.app/Contents/Resources/fonts/truetype', '/usr/lib/libreoffice/share/fonts/truetype',
             '/opt/libreoffice/share/fonts/truetype', os.path.expanduser('~/Library/Fonts'), '/Library/Fonts',
             os.path.expanduser('~/.local/share/fonts'), '/usr/share/fonts/truetype']
    return [os.path.normpath(d) for d in dirs if os.path.isdir(d)]


def face_files(family, dirs):
    """{'regular'|'bold'|'italic'|'bolditalic': path} for an embedded family name such as 'LiberationSans'."""
    want = re.sub(r'[^a-z0-9]', '', family.lower())
    styles = {}
    for d in dirs:
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(FONT_EXT):
                continue
            stem = f.rsplit('.', 1)[0]
            base, _, style = stem.partition('-')
            if re.sub(r'[^a-z0-9]', '', base.lower()) != want:
                continue
            s = style.lower().replace('oblique', 'italic')
            key = {'': 'regular', 'regular': 'regular', 'bold': 'bold', 'italic': 'italic', 'bolditalic': 'bolditalic'}.get(s)
            if key and key not in styles:
                styles[key] = os.path.join(d, f)
    return styles


def font_catalog(probe, dirs):
    """Usable fonts with the family the PDF embeds and the files the preview loads."""
    cat = []
    for font in usable_fonts(probe):
        r = probe[font]
        fam = sorted({n.split('-')[0] for n in r['embedded']}, key=len)[0]
        cat.append({'name': font, 'status': r['status'], 'pdf_family': fam, 'serif': r.get('serif', False),
                    'files': face_files(fam, dirs)})
    return cat


# ---------- the app ----------
class Editor:
    def __init__(self, ws):
        self.ws = os.path.expanduser(ws)
        self.prof = load_profile(os.path.join(self.ws, 'profile.yaml'))
        self.cfg = load_config(os.path.join(self.ws, 'config.json'))
        self.soffice = find_soffice(self.cfg)
        from . import layout
        self.node_path = node_modules(self.cfg, layout.vault(self.ws, self.cfg))
        self.token = secrets.token_urlsafe(18)
        self.lock = threading.Lock()
        self.checks = {}  # id -> {hash, dir, fails, notes, pages}
        self.work = tempfile.mkdtemp(prefix='gmh-design-')
        self.bank = None
        try:
            from .specs import load_bank
            self.bank = load_bank(self.ws)
        except Exception:
            pass

    # fonts are probed once and cached in the workspace (a probe is one LibreOffice run, a few seconds)
    def fonts(self, refresh=False):
        cache = os.path.join(self.ws, 'state', 'design-fonts.json')
        if not refresh and os.path.exists(cache):
            data = json.load(open(cache, encoding='utf-8'))
            if set(data.get('probe', {})) >= set(CANDIDATES):
                return data
        if not self.soffice:
            raise RuntimeError('LibreOffice not found: it decides which fonts the PDF can embed')
        probe = probe_fonts(CANDIDATES, self.node_path, self.soffice, os.path.join(self.work, 'probe'))
        data = {'probed': time.strftime('%Y-%m-%d %H:%M'), 'probe': probe}
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(data, open(cache, 'w', encoding='utf-8', newline='\n'), indent=1)
        return data

    def catalog(self, refresh=False):
        return font_catalog(self.fonts(refresh)['probe'], font_dirs(self.soffice))

    def state(self):
        saved_path = design_path(self.ws)
        srcs = resume_sources(self.ws, self.cfg)
        docs = []
        for sid, label, p in srcs:
            try:
                load_doc(p)
                docs.append({'id': sid, 'label': label})
            except Exception:
                continue
        cat = self.catalog()
        return {
            'token': self.token, 'tokens': load_design(self.ws), 'defaults': default_design(),
            'saved_exists': os.path.exists(saved_path), 'saved_path': saved_path,
            'themes': THEMES, 'bullets': BULLETS, 'ranges': RANGES,
            'fonts': [dict(f, files={k: os.path.basename(v) for k, v in f['files'].items()}) for f in cat],
            'unavailable': sorted(set(CANDIDATES) - {f['name'] for f in cat}),
            'sources': docs, 'rules': self.cfg.get('resume', {}),
        }

    def payload(self, source_id, tokens=None):
        path = next((p for sid, _, p in resume_sources(self.ws, self.cfg) if sid == source_id), None)
        if not path:
            raise KeyError('unknown resume source')
        return render_payload(load_doc(path), self.prof, tokens), load_doc(path)

    def font_file(self, name):
        for f in self.catalog():
            for style, p in f['files'].items():
                if os.path.basename(p) == name:
                    return p
        return None

    def check(self, tokens, source_id):
        t = merge(default_design(), tokens)
        errs = validate_tokens(t)
        if errs:
            return {'ok': False, 'errors': errs}
        usable = {f['name'] for f in self.catalog()}
        bad = [f for f in (t['fonts']['heading'], t['fonts']['body']) if f not in usable]
        if bad:
            return {'ok': False, 'errors': [f'{f} is not embeddable on this machine' for f in bad]}
        _, doc = self.payload(source_id)
        cid = secrets.token_hex(6)
        out_dir = os.path.join(self.work, cid)
        with self.lock:
            out = build(doc, self.prof, out_dir, 'design-check', self.cfg, node_path=self.node_path, design=t)
            fails, notes = verify(out['pdf'], doc, self.prof, self.cfg, self.bank, design=t)
            subprocess.run(['pdftoppm', '-r', '110', '-png', out['pdf'], os.path.join(out_dir, 'page')], check=True, capture_output=True)
        pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(out_dir, 'page-*.png')))
        self.checks[cid] = {'hash': tokens_hash(t), 'dir': out_dir, 'fails': fails, 'pdf': out['pdf']}
        return {'ok': True, 'check_id': cid, 'fails': fails, 'notes': notes, 'pages': [f'/check/{cid}/{p}' for p in pages],
                'pdf': f'/check/{cid}/resume.pdf'}

    def save(self, tokens, check_id, accept_fails=False):
        t = merge(default_design(), tokens)
        c = self.checks.get(check_id)
        if not c or c['hash'] != tokens_hash(t):
            return {'ok': False, 'errors': ['Check this design before saving (the settings changed since the last check).']}
        if c['fails'] and not accept_fails:
            return {'ok': False, 'errors': ['The check failed; confirm to save anyway.']}
        path, backup = save_design(self.ws, t)
        return {'ok': True, 'path': path, 'backup': backup}


def tokens_hash(t):
    return hashlib.sha256(json.dumps({k: v for k, v in t.items() if not k.startswith('_')}, sort_keys=True).encode()).hexdigest()


def make_handler(app):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype='application/json', extra=None):
            data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == 'application/json' else body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _local(self):
            host = (self.headers.get('Host') or '').split(':')[0]
            return host in ('127.0.0.1', 'localhost')

        def do_GET(self):
            if not self._local():
                return self._send(403, {'error': 'local only'})
            u = urlparse(self.path)
            try:
                if u.path == '/':
                    html = open(PAGE, encoding='utf-8').read().replace('__TOKEN__', app.token)
                    return self._send(200, html, 'text/html; charset=utf-8',
                                      {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; font-src 'self'"})
                if u.path == '/api/state':
                    return self._send(200, app.state())
                if u.path == '/api/resume':
                    p, _ = app.payload(parse_qs(u.query).get('id', [''])[0])
                    p.pop('design', None)
                    return self._send(200, p)
                if u.path.startswith('/fonts/'):
                    f = app.font_file(unquote(u.path[7:]))
                    if not f:
                        return self._send(404, {'error': 'no such font'})
                    return self._send(200, open(f, 'rb').read(), 'font/otf' if f.endswith('.otf') else 'font/ttf')
                m = re.fullmatch(r'/check/([0-9a-f]{12})/(page-\d+\.png|resume\.pdf)', u.path)
                if m and m.group(1) in app.checks:
                    c = app.checks[m.group(1)]
                    f = c['pdf'] if m.group(2) == 'resume.pdf' else os.path.join(c['dir'], m.group(2))
                    if os.path.exists(f):
                        return self._send(200, open(f, 'rb').read(), 'application/pdf' if f.endswith('.pdf') else 'image/png')
                return self._send(404, {'error': 'not found'})
            except Exception as e:
                return self._send(500, {'error': str(e)})

        def do_POST(self):
            if not self._local() or self.headers.get('X-GMH-Token') != app.token:
                return self._send(403, {'error': 'forbidden'})
            try:
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n) or b'{}')
                if self.path == '/api/check':
                    return self._send(200, app.check(body.get('tokens') or {}, body.get('source') or ''))
                if self.path == '/api/save':
                    return self._send(200, app.save(body.get('tokens') or {}, body.get('check_id') or '', bool(body.get('accept_fails'))))
                if self.path == '/api/fonts/refresh':
                    app.catalog(refresh=True)
                    return self._send(200, app.state())
                return self._send(404, {'error': 'not found'})
            except Exception as e:
                return self._send(500, {'ok': False, 'errors': [f'{type(e).__name__}: {e}']})
    return H


def serve(ws, port=8765, open_browser=False):
    app = Editor(ws)
    app.catalog()  # probe fonts before the page asks
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    url = f'http://127.0.0.1:{srv.server_address[1]}/'
    print(f'design editor: {url}  (Ctrl+C to stop)', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(app.work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Resume design editor (local page) and font probe.')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'))
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--open', action='store_true', help='open the page in the default browser')
    ap.add_argument('cmd', nargs='?', default='serve', choices=['serve', 'fonts'])
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args(argv)
    if not a.workspace:
        sys.exit('set GMH_WORKSPACE or pass --workspace')
    if a.cmd == 'fonts':
        app = Editor(a.workspace)
        probe = app.fonts(a.refresh)['probe']
        for f, r in probe.items():
            tag = {'own': 'embedded', 'twin': 'metric twin'}.get(r['status'], 'NOT OFFERED')
            print(f"{f:18} {tag:12} PDF embeds: {', '.join(r['embedded']) or '-'}")
        return
    serve(a.workspace, a.port, a.open)


if __name__ == '__main__':
    main()
