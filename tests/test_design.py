"""Phase 8: design tokens, the builders reading them, font checks, save with backup, and the editor server.
All fixtures are fictional. Golden XML in tests/fixtures/design was written by the builders as they were
before tokens existed, so the default tokens must reproduce it byte for byte."""
import copy, datetime, http.client, json, os, shutil, subprocess, tempfile, threading, unittest, zipfile

from engine import design, design_editor, resume
from engine.verify import bullet_blocks, font_failures

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, 'fixtures', 'design')
PROFILE = os.path.join(ROOT, 'templates', 'profile.example.yaml')
CONFIG = os.path.join(ROOT, 'templates', 'config.example.json')
NODE = resume.node_modules()
HAVE_NODE = shutil.which('node') and os.path.isdir(os.path.join(NODE, 'docx'))

PDFFONTS = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
BAAAAA+Caladea-Bold                  TrueType          WinAnsi          yes yes yes    150  0
DAAAAA+LiberationSans                TrueType          WinAnsi          yes yes yes    180  0
GAAAAA+LiberationSans-Bold           TrueType          WinAnsi          yes yes yes    160  0
"""


def build_xml(tool, payload, tmp, parts=('document', 'numbering')):
    src, out = os.path.join(tmp, 'in.json'), os.path.join(tmp, 'out.docx')
    json.dump(payload, open(src, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False)
    subprocess.run(['node', os.path.join(ROOT, 'tools', tool), src, out], check=True, capture_output=True,
                   env=dict(os.environ, NODE_PATH=NODE))
    z = zipfile.ZipFile(out)
    return {p: z.read(f'word/{p}.xml') for p in parts}


@unittest.skipUnless(HAVE_NODE, 'needs Node and the docx package (npm install --prefix tools)')
class BuilderTokens(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.resume = json.load(open(os.path.join(FIX, 'resume_payload.json'), encoding='utf-8'))
        self.cover = json.load(open(os.path.join(FIX, 'cover_payload.json'), encoding='utf-8'))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def golden(self, name, part):
        return open(os.path.join(FIX, f'{name}_{part}.xml'), 'rb').read()

    def test_default_tokens_reproduce_the_old_resume(self):
        for payload in (self.resume, dict(self.resume, design=design.load_design())):  # no design key, and full defaults
            got = build_xml('resume.js', payload, self.tmp)
            self.assertEqual(got['document'], self.golden('resume', 'document'))
            self.assertEqual(got['numbering'], self.golden('resume', 'numbering'))

    def test_default_tokens_reproduce_the_old_cover_letter(self):
        for payload in (self.cover, dict(self.cover, design=design.load_design())):
            got = build_xml('cover_letter.js', payload, self.tmp)
            self.assertEqual(got['document'], self.golden('cover', 'document'))

    def test_tokens_change_the_resume(self):
        t = design.load_design()
        t['fonts'] = {'heading': 'Noto Serif', 'body': 'Carlito'}
        t['colors']['section'] = '1F3A5F'
        t['bullet']['glyph'] = '▪'
        t['dates']['align'] = 'inline'
        t['bold']['inline'] = False
        t['section_rule']['show'] = False
        t['sizes_pt']['body'] = 10
        got = build_xml('resume.js', dict(self.resume, design=t), self.tmp)
        doc, num = got['document'].decode(), got['numbering'].decode()
        self.assertIn('w:ascii="Carlito"', doc)
        self.assertIn('w:ascii="Noto Serif"', doc)
        self.assertNotIn('Arial', doc)
        self.assertNotIn('Caladea', doc)
        self.assertIn('1F3A5F', doc)
        self.assertIn('w:val="▪"', num)
        self.assertNotIn('<w:tab/>', doc)                 # dates follow the title, no tab stop
        self.assertIn('Jan 2022 - Present', doc)
        self.assertNotIn('<w:pBdr>', doc)                 # no rule under headings
        self.assertIn('<w:sz w:val="20"/>', doc)          # 10 pt body
        # content is unchanged: every word of the payload is still there
        for x in self.resume['experience']:
            for b in x['bullets']:
                for word in b.replace('**', '').split():
                    self.assertIn(word.replace('&', '&amp;'), doc)

    def test_cover_letter_follows_resume_fonts(self):
        t = design.load_design()
        t['fonts'] = {'heading': 'Noto Serif', 'body': 'DejaVu Sans'}
        doc = build_xml('cover_letter.js', dict(self.cover, design=t), self.tmp, ('document',))['document'].decode()
        self.assertIn('Noto Serif', doc)
        self.assertIn('DejaVu Sans', doc)
        self.assertNotIn('Arial', doc)


class Tokens(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.ws)

    def test_defaults_are_valid_and_mapped_to_the_old_values(self):
        t = design.load_design()
        self.assertEqual(design.validate(t), [])
        # the locked Oct 10 system, in Word units
        self.assertEqual(round(t['sizes_pt']['body'] * 2), 19)
        self.assertEqual(round(t['spacing_pt']['section_before'] * 20), 230)
        self.assertEqual(round(t['line_height'] * 240), 276)
        self.assertEqual(round(t['dates']['tab_pt'] * 20), 10800)
        self.assertEqual({k: round(v * 20) for k, v in t['page']['margins_pt'].items()},
                         {'top': 600, 'right': 700, 'bottom': 560, 'left': 700})

    def test_workspace_file_overrides_part_of_the_defaults(self):
        json.dump({'fonts': {'body': 'Carlito'}, 'colors': {'name': '1F3A5F'}}, open(os.path.join(self.ws, 'design.json'), 'w', encoding='utf-8', newline='\n'))
        t = design.load_design(self.ws)
        self.assertEqual(t['fonts'], {'heading': 'Caladea', 'body': 'Carlito'})
        self.assertEqual(t['colors']['name'], '1F3A5F')
        self.assertEqual(t['colors']['text'], '212121')

    def test_invalid_tokens_are_refused(self):
        bad = design.default_design()
        bad['sizes_pt']['body'] = 30
        bad['colors']['text'] = 'red'
        bad['bullet']['glyph'] = '—'
        bad['dates']['align'] = 'left'
        bad['bold']['name'] = 'yes'
        errs = ' | '.join(design.validate(bad))
        for frag in ('sizes_pt.body', 'colors.text', 'bullet.glyph', 'dates.align', 'bold.name'):
            self.assertIn(frag, errs)
        json.dump({'line_height': 3}, open(os.path.join(self.ws, 'design.json'), 'w', encoding='utf-8', newline='\n'))
        with self.assertRaises(ValueError):
            design.load_design(self.ws)

    def test_save_backs_up_the_previous_design(self):
        p, backup = design.save_design(self.ws, {'fonts': {'body': 'Carlito'}})
        self.assertIsNone(backup)
        first = open(p, encoding='utf-8').read()
        p2, backup = design.save_design(self.ws, {'fonts': {'body': 'Noto Sans'}}, now=datetime.datetime(2026, 10, 21, 9, 0, 0))
        self.assertEqual(open(backup, encoding='utf-8').read(), first)
        self.assertTrue(backup.replace(os.sep, '/').endswith('design-backups/design-20261021-090000.json'))
        _, backup2 = design.save_design(self.ws, {'fonts': {'body': 'Carlito'}}, now=datetime.datetime(2026, 10, 21, 9, 0, 0))
        self.assertNotEqual(backup, backup2)                 # same second: a new name, nothing overwritten
        self.assertEqual(design.load_design(self.ws)['fonts']['body'], 'Carlito')
        with self.assertRaises(ValueError):
            design.save_design(self.ws, {'sizes_pt': {'body': 2}})
        self.assertEqual(design.load_design(self.ws)['fonts']['body'], 'Carlito')  # a refused save changes nothing


class Fonts(unittest.TestCase):
    def test_pdffonts_parsing_and_twins(self):
        names = design.embedded_names(PDFFONTS)
        self.assertEqual(names, ['Caladea-Bold', 'LiberationSans', 'LiberationSans-Bold'])
        self.assertEqual(design.font_matches('Caladea', names), 'own')
        self.assertEqual(design.font_matches('Arial', names), 'twin')       # LibreOffice's metric twin
        self.assertEqual(design.font_matches('Cambria', names), 'twin')
        self.assertIsNone(design.font_matches('Georgia', names))
        self.assertEqual(design.font_matches('Liberation Sans', names), 'own')

    def test_usable_fonts_only_embedded_or_twin(self):
        probe = {'Arial': {'status': 'twin'}, 'Georgia': {'status': 'substituted'}, 'Caladea': {'status': 'own'},
                 'Odd': {'status': 'unreadable'}}
        self.assertEqual(design.usable_fonts(probe), ['Arial', 'Caladea'])

    def test_verify_font_and_bullet_checks(self):
        t = design.load_design()
        self.assertEqual(font_failures(PDFFONTS, t), [])
        t['fonts']['body'] = 'Georgia'
        self.assertEqual(font_failures(PDFFONTS, t), ['Georgia not embedded'])
        lines = ['▪ First bullet that wraps', '  onto a second line', 'Company', '▪ Another']
        self.assertEqual([len(b) for b in bullet_blocks(lines, '▪')], [2, 1])
        self.assertEqual(bullet_blocks(lines), [])

    def test_face_files(self):
        d = tempfile.mkdtemp()
        try:
            for f in ('Carlito-Regular.ttf', 'Carlito-Bold.ttf', 'Carlito-Italic.ttf', 'Carlito-BoldItalic.ttf',
                      'DejaVuSans.ttf', 'DejaVuSans-Oblique.ttf', 'DejaVuSansMono.ttf'):
                open(os.path.join(d, f), 'w', encoding='utf-8', newline='\n').close()
            self.assertEqual(sorted(design_editor.face_files('Carlito', [d])), ['bold', 'bolditalic', 'italic', 'regular'])
            dv = design_editor.face_files('DejaVuSans', [d])
            self.assertEqual(sorted(dv), ['italic', 'regular'])
            self.assertTrue(dv['regular'].endswith('DejaVuSans.ttf'))
        finally:
            shutil.rmtree(d)


class StagesUseTheWorkspaceDesign(unittest.TestCase):
    def test_ctx_and_payload(self):
        from engine import stages
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, 'vault', 'Pipeline'))
            ws = os.path.join(tmp, 'ws')
            os.makedirs(ws)
            shutil.copy(PROFILE, os.path.join(ws, 'profile.yaml'))
            cfg = json.load(open(CONFIG, encoding='utf-8'))
            cfg['paths'] = {'vault': os.path.join(tmp, 'vault')}
            json.dump(cfg, open(os.path.join(ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
            self.assertEqual(stages.Ctx(ws).design, design.load_design())
            design.save_design(ws, {'fonts': {'body': 'Carlito'}})
            ctx = stages.Ctx(ws)
            self.assertEqual(ctx.design['fonts']['body'], 'Carlito')
            doc = json.load(open(os.path.join(HERE, 'fixtures', 'workspace', 'resume', 'templates', 'Ops.json'), encoding='utf-8'))
            self.assertEqual(resume.render_payload(doc, ctx.prof, ctx.design)['design']['fonts']['body'], 'Carlito')
            self.assertEqual(resume.render_payload(doc, ctx.prof)['design'], design.load_design())
        finally:
            shutil.rmtree(tmp)


class EditorServer(unittest.TestCase):
    """The HTTP layer with the font probe and PDF build stubbed out: local-only, token-gated POSTs, check-before-save."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, 'ws')
        shutil.copytree(os.path.join(HERE, 'fixtures', 'workspace', 'resume'), os.path.join(self.ws, 'resume'))
        shutil.copy(PROFILE, os.path.join(self.ws, 'profile.yaml'))
        json.dump(json.load(open(CONFIG, encoding='utf-8')), open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        app = design_editor.Editor(self.ws)
        app.catalog = lambda refresh=False: [{'name': 'Arial', 'status': 'twin', 'pdf_family': 'LiberationSans', 'serif': False, 'files': {}},
                                             {'name': 'Caladea', 'status': 'own', 'pdf_family': 'Caladea', 'serif': True, 'files': {}},
                                             {'name': 'Carlito', 'status': 'own', 'pdf_family': 'Carlito', 'serif': False, 'files': {}}]
        self.app = app
        self.srv = design_editor.http.server.ThreadingHTTPServer(('127.0.0.1', 0), design_editor.make_handler(app))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp)
        shutil.rmtree(self.app.work, ignore_errors=True)

    def req(self, method, path, body=None, token=True, host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'Content-Type': 'application/json'}
        if token:
            h['X-GMH-Token'] = self.app.token
        if host:
            h['Host'] = host
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        return r.status, (json.loads(data) if r.getheader('Content-Type', '').startswith('application/json') else data)

    def test_page_state_and_sources(self):
        code, page = self.req('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(self.app.token.encode(), page)
        code, st = self.req('GET', '/api/state')
        self.assertEqual(code, 200)
        self.assertEqual([s['label'] for s in st['sources']], ['Template: Ops'])
        self.assertEqual(st['tokens'], design.load_design())
        self.assertIn('Georgia', st['unavailable'])
        code, r = self.req('GET', '/api/resume?id=' + st['sources'][0]['id'].replace(' ', '%20'))
        self.assertEqual(code, 200)
        self.assertIn('experience', r)
        self.assertNotIn('design', r)

    def test_local_only_and_token(self):
        self.assertEqual(self.req('GET', '/api/state', host='evil.example')[0], 403)
        self.assertEqual(self.req('POST', '/api/save', {'tokens': {}}, token=False)[0], 403)
        self.assertEqual(self.req('GET', '/check/../../etc/passwd')[0], 404)

    def test_save_needs_a_check_of_the_same_tokens(self):
        t = design.load_design()
        t['fonts']['body'] = 'Carlito'
        code, r = self.req('POST', '/api/save', {'tokens': t, 'check_id': 'nope'})
        self.assertFalse(r['ok'])
        self.assertFalse(os.path.exists(design.design_path(self.ws)))
        # a passed check for these tokens
        self.app.checks['abc123abc123'] = {'hash': design_editor.tokens_hash(t), 'dir': self.tmp, 'fails': [], 'pdf': ''}
        t2 = copy.deepcopy(t)
        t2['sizes_pt']['body'] = 10
        self.assertFalse(self.req('POST', '/api/save', {'tokens': t2, 'check_id': 'abc123abc123'})[1]['ok'])  # changed since
        code, r = self.req('POST', '/api/save', {'tokens': t, 'check_id': 'abc123abc123'})
        self.assertTrue(r['ok'], r)
        self.assertEqual(design.load_design(self.ws)['fonts']['body'], 'Carlito')
        # a failed check saves only when the user confirms
        t3 = copy.deepcopy(t)
        t3['fonts']['body'] = 'Arial'
        self.app.checks['def456def456'] = {'hash': design_editor.tokens_hash(t3), 'dir': self.tmp, 'fails': ['3 pages (want 2)'], 'pdf': ''}
        self.assertFalse(self.req('POST', '/api/save', {'tokens': t3, 'check_id': 'def456def456'})[1]['ok'])
        r = self.req('POST', '/api/save', {'tokens': t3, 'check_id': 'def456def456', 'accept_fails': True})[1]
        self.assertTrue(r['ok'])
        self.assertTrue(os.path.exists(r['backup']))

    def test_check_refuses_bad_tokens_and_unembeddable_fonts(self):
        src = self.req('GET', '/api/state')[1]['sources'][0]['id']
        t = design.load_design()
        t['fonts']['body'] = 'Georgia'
        r = self.req('POST', '/api/check', {'tokens': t, 'source': src})[1]
        self.assertFalse(r['ok'])
        self.assertIn('Georgia', r['errors'][0])
        t['fonts']['body'] = 'Arial'
        t['margins'] = None
        t['line_height'] = 9
        self.assertFalse(self.req('POST', '/api/check', {'tokens': t, 'source': src})[1]['ok'])


if __name__ == '__main__':
    unittest.main()
