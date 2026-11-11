"""Migrate an original-pipeline vault (the layout get-me-hired grew out of) into a workspace, and
check that the generic renderer reproduces resumes that were already sent.

Reads only; writes only under the target workspace. Never touches the source vault.

    python3 -m engine.migrate --vault <vault> --workspace <dir> [--page-breaks last_id,first_id] [--regress slug1,slug2,...]

Writes into the workspace:
  config.json                 the vault's Pipeline/config.json, locations converted to metros, plus resume rules
  resume/templates/<Name>.json one per approved build_resume_<Name>.js (the Oct 17 templates)
  resume/bank.json            bullet ids (from the make_specs scripts' PREFIX tables), every approved
                              bullet under an auto id, approved skills, skill sets
profile.yaml and answer-bank.md are NOT generated: they hold personal facts and are written by the
user (or /setup) from the vault's answer-bank.md.

--regress rebuilds the named shipped resumes (role-folder build_resume_<slug>.js) through the
generic renderer and compares word/document.xml and the PDF text with what was shipped.
"""
import argparse, ast, glob, json, os, re, subprocess, sys, zipfile
from .profile import load_config, load_profile, filename_prefix
from .resume import from_build_script, build
from .design import load_design
from .specs import bank_from_templates


def content_of(script, node_tools):
    out = subprocess.run(['node', os.path.join(node_tools, 'content.js'), script], capture_output=True, text=True, check=True, encoding='utf-8').stdout
    return json.loads(out)


def template_scripts(vault):
    return sorted(glob.glob(os.path.join(vault, 'Workflow', '*', '2026-10-17 *', 'build_resume_*.js')))


def prefix_tables(vault):
    """Merge the PREFIX dicts of every specs/make_specs_*.py (parsed, never executed)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(vault, 'Pipeline', 'specs', 'make_specs_*.py'))):
        m = re.search(r'^PREFIX = (\{.*?^\})', open(p, encoding='utf-8').read(), re.M | re.S)
        if m:
            for k, v in ast.literal_eval(m.group(1)).items():
                if out.get(k, v) != v:
                    raise ValueError(f'bullet id {k} means two different things across make_specs scripts')
                out[k] = v
    return out


def approved_skills(vault):
    """Extra approved terms from the master resume's KEYWORD BANK."""
    terms = set()
    master = open(os.path.join(vault, 'master-resume.md'), encoding='utf-8').read()
    if '## KEYWORD BANK' in master:
        for line in master.split('## KEYWORD BANK')[1].split('\n---')[0].splitlines():
            if line.startswith('**'):
                terms |= {t.strip() for t in line.split(':**', 1)[-1].split('·') if t.strip()}
    return terms


def build_bank(vault, templates):
    bank = bank_from_templates(templates, approved_skills(vault))
    owner = {b['text']: b['experience'] for b in bank['bullets'].values()}
    for bid, prefix in prefix_tables(vault).items():
        hits = sorted({t for t in owner if t.startswith(prefix)})
        if len(hits) != 1:
            raise ValueError(f'bullet id {bid}: {len(hits)} approved bullets start with {prefix!r}')
        bank['bullets'][bid] = {'text': hits[0], 'experience': owner[hits[0]]}
    return bank


def migrate(vault, workspace, page_breaks=None):
    node_tools = os.path.join(vault, 'Pipeline', 'tools')
    os.makedirs(os.path.join(workspace, 'resume', 'templates'), exist_ok=True)
    templates = {}
    for s in template_scripts(vault):
        name = os.path.basename(s)[len('build_resume_'):-3]
        templates[name] = from_build_script(open(s, encoding='utf-8').read(), content_of(s, node_tools))
        json.dump(templates[name], open(os.path.join(workspace, 'resume', 'templates', name + '.json'), 'w', encoding='utf-8', newline='\n'),
                  indent=1, ensure_ascii=False)
    bank = build_bank(vault, templates)
    json.dump(bank, open(os.path.join(workspace, 'resume', 'bank.json'), 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=False)
    raw = json.load(open(os.path.join(vault, 'Pipeline', 'config.json'), encoding='utf-8'))
    raw.setdefault('resume', {}).update({'pages': 2, 'font': 'Caladea', 'max_bullet_lines': 2, 'max_summary_lines': 4,
                                         'max_extra_bullets': 1})
    if page_breaks:  # experience ids: the last job on page 1, the first on page 2
        raw['resume']['page_breaks'] = {'last_on_page_1': f'experience.{page_breaks[0]}', 'first_on_page_2': f'experience.{page_breaks[1]}'}
    raw.setdefault('salary', {}).setdefault('down_level_below', 260000)
    raw.setdefault('paths', {})['vault'] = vault  # engine.stages reads and writes the vault's Pipeline/ and Workflow/
    cfg = load_config(raw)
    json.dump(cfg, open(os.path.join(workspace, 'config.json'), 'w', encoding='utf-8', newline='\n'), indent=1, ensure_ascii=False)
    return templates, bank


def _pdf_text(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, encoding='utf-8').stdout


def regress(vault, workspace, slugs, out_dir):
    """Rebuild shipped resumes through the generic renderer; compare with the shipped files."""
    prof = load_profile(os.path.join(workspace, 'profile.yaml'))
    cfg = load_config(json.load(open(os.path.join(workspace, 'config.json'), encoding='utf-8')))
    node_tools = os.path.join(vault, 'Pipeline', 'tools')
    design = load_design(workspace)
    results = []
    for slug in slugs:
        hits = glob.glob(os.path.join(vault, 'Workflow', '*', '*', f'build_resume_{slug}.js'))
        if len(hits) != 1:
            results.append((slug, 'SKIP', f'{len(hits)} build scripts found'))
            continue
        script = hits[0]
        shipped_docx = os.path.join(os.path.dirname(script), f'{filename_prefix(prof)}Resume_{slug}.docx')
        doc = from_build_script(open(script, encoding='utf-8').read(), content_of(script, node_tools))
        out = build(doc, prof, out_dir, slug, cfg, node_path=os.path.join(node_tools, 'node_modules'), design=design)
        new_xml = zipfile.ZipFile(out['docx']).read('word/document.xml')
        old_xml = zipfile.ZipFile(shipped_docx).read('word/document.xml')
        new_txt, old_txt = _pdf_text(out['pdf']), _pdf_text(shipped_docx[:-5] + '.pdf')
        xml_ok, txt_ok = new_xml == old_xml, new_txt == old_txt
        detail = []
        if not txt_ok:
            import difflib
            diff = [l for l in difflib.unified_diff(old_txt.splitlines(), new_txt.splitlines(), lineterm='', n=0)
                    if l[:1] in '+-' and not l.startswith(('+++', '---'))]
            detail = diff[:6]
        results.append((slug, 'PASS' if xml_ok and txt_ok else 'DIFF',
                        f'document.xml {"identical" if xml_ok else "differs"}; PDF text {"identical" if txt_ok else "differs"}'
                        + ''.join('\n      ' + d[:160] for d in detail)))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description='Migrate an original-pipeline vault into a get-me-hired workspace (read-only on the vault).')
    ap.add_argument('--vault', required=True)
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--regress', default='')
    ap.add_argument('--page-breaks', default='', help='experience ids: last on page 1, first on page 2 (e.g. acme,beta)')
    a = ap.parse_args(argv)
    vault, ws = os.path.expanduser(a.vault), os.path.expanduser(a.workspace)
    templates, bank = migrate(vault, ws, a.page_breaks.split(',') if a.page_breaks else None)
    print(f'{len(templates)} templates, {len(bank["bullets"])} bullet ids, {len(bank["skills"])} approved skills -> {ws}')
    if a.regress:
        if not os.path.exists(os.path.join(ws, 'profile.yaml')):
            sys.exit('regression needs profile.yaml in the workspace')
        fails = 0
        for slug, status, detail in regress(vault, ws, a.regress.split(','), os.path.join(ws, 'regression')):
            print(f'{status:5} {slug}: {detail}')
            fails += status != 'PASS'
        sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
