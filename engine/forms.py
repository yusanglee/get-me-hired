#!/usr/bin/env python3
"""Stage 5a: fetch each Apply role's application form and normalize its questions.

Ported from the original pipeline's forms.py (Phase 7); reads and writes the workspace's pipeline folders.

Greenhouse: boards API (?questions=true) incl. compliance (EEO) questions.
Ashby: the public job-board GraphQL (ApiJobPosting.applicationForm).
Lever: the /apply page HTML (standard fields, custom question cards, EEO selects).

Writes <vault>/Pipeline/state/forms/<id>.json: [{label, required, type, options}]. Reads only public
job-board endpoints; never submits anything. Roles found on other boards (LinkedIn, Built In, Himalayas...)
are matched to the company's own Greenhouse, Lever or Ashby board during discovery when possible
(engine/boards.py); the rest have no fetchable form: apply to them by hand (gmh manual-notes prepares
their answers).

    python3 -m engine.forms --workspace <ws> [reviewed-<date>.csv]
"""
import argparse, csv, glob, html, json, os, re, sys, urllib.parse, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (get-me-hired; personal job search)'}


def get(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers=dict(UA, **({'Content-Type': 'application/json'} if data else {})))
    return urllib.request.urlopen(req, timeout=30).read().decode()


def clean(s):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).split())


def greenhouse(slug, jid):
    d = json.loads(get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}?questions=true'))
    qs = []
    groups = [('', d.get('questions') or [])] + [('eeo', c.get('questions') or []) for c in d.get('compliance') or []]
    groups += [('demographic', (d.get('demographic_questions') or {}).get('questions') or [])]
    for kind, items in groups:
        for q in items:
            f = q['fields'][0] if q.get('fields') else {}
            opts = [v['label'] for fld in q.get('fields', []) for v in fld.get('values', [])]
            qs.append(dict(label=clean(q.get('label')), required=bool(q.get('required')), type=f.get('type', ''),
                           options=opts or [a.get('label') for a in q.get('answer_options', []) or []], section=kind))
    if d.get('location_questions'):
        qs.append(dict(label='Location', required=True, type='input_text', options=[], section=''))
    return qs


def ashby(org, jid):
    q = ('query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { jobPosting('
         'organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { applicationForm {'
         ' sections { title fieldEntries { ... on FormFieldEntry { isRequired field descriptionHtml } } } } surveyForms { sections { title'
         ' fieldEntries { ... on FormFieldEntry { isRequired field } } } } } }')
    org = urllib.parse.unquote(org)  # board slugs can be URL-encoded (e.g. "Acme%20LLC")
    d = json.loads(get('https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting',
                       dict(operationName='ApiJobPosting', query=q,
                            variables=dict(organizationHostedJobsPageName=org, jobPostingId=jid))))
    jp = d['data']['jobPosting']
    qs = []
    for kind, form in [('', jp['applicationForm'])] + [('eeo', s) for s in jp.get('surveyForms') or []]:
        for s in form['sections']:
            for e in s['fieldEntries']:
                f = e['field']
                q = dict(label=clean(f.get('title')), required=e['isRequired'], type=f.get('type'),
                         options=[o.get('label') for o in f.get('selectableValues') or []], section=kind)
                if f.get('locationTypes'):  # e.g. ["Country"]: a location field that takes a country, not a city
                    q['location_types'] = f['locationTypes']
                if e.get('descriptionHtml'):
                    q['description'] = clean(re.sub(r'<[^>]+>', ' ', e['descriptionHtml']))
                qs.append(q)
    return qs


def lever(co, jid):
    """Standard fields come from the <li> blocks; custom cards and demographic surveys come from their
    hidden baseTemplate JSON (Lever writes value= before name=, so match the whole tag). Several surveys
    can exist per posting; Lever shows only the one for the candidate's location, so each keeps its id
    in `section` and the filler answers only the visible ones."""
    t = get(f'https://jobs.lever.co/{co}/{jid}/apply')
    qs = []
    # top-level question blocks only: split on the opening tag instead of a non-greedy </li> match,
    # which stopped at the first nested option <li> and kept one option per question
    for b in re.split(r'<li class="application-question', t)[1:]:
        b = b.split('<li class="application-question')[0]
        lab = re.search(r'class="application-label[^"]*">\s*(?:<div class="text">)?(.*?)</div>', b, re.S)
        if not lab:
            continue
        raw = lab.group(1)
        label = clean(raw).replace('✱', '').strip()
        typ = 'file' if 'type="file"' in b else 'select' if '<select' in b else 'textarea' if '<textarea' in b else \
            'radio' if 'type="radio"' in b else 'checkbox' if 'type="checkbox"' in b else 'text'
        opts = [clean(o) for o in re.findall(r'<option[^>]*>(.*?)</option>', b, re.S) if clean(o) and 'Select' not in clean(o)]
        opts += [html.unescape(v) for v in re.findall(r'type="(?:radio|checkbox)"[^>]*value="([^"]*)"', b)]
        qs.append(dict(label=label, required='✱' in raw or 'required' in b.split('</label>')[0][:3000], type=typ,
                       options=opts, section=''))
    for tag in re.findall(r'<input type="hidden"[^>]*name="(?:cards|surveysResponses)\[[^\]]+\]\[baseTemplate\]"[^>]*>', t):
        v = re.search(r'value="([^"]*)"', tag)
        if not v:
            continue
        card = json.loads(html.unescape(v.group(1)))
        sec = 'card' if card.get('type') != 'survey' else 'survey:' + card.get('id', '')[:8]
        for f in card.get('fields', []):
            qs.append(dict(label=clean(f.get('text')), required=bool(f.get('required')), type=f.get('type'),
                           options=[o.get('text') for o in f.get('options') or []], section=sec))
    for m in re.finditer(r'<select[^>]*name="(eeo\[[^\]]+\])"[^>]*>(.*?)</select>', t, re.S):
        qs.append(dict(label=m.group(1), required=False, type='select', section='eeo',
                       options=[clean(o) for o in re.findall(r'<option[^>]*>(.*?)</option>', m.group(2), re.S)
                                if clean(o) and not clean(o).startswith('Select')]))
    # card/survey fields are also rendered as <li>; keep the template version (full option list).
    # Key on label+section for surveys so the same question in two location surveys is kept per survey.
    tmpl = {q['label'] for q in qs if q['section']}
    qs = [q for q in qs if q['section'] or q['label'] not in tmpl]
    seen, out = set(), []
    for q in qs:
        k = (q['label'], q['section'])
        if k not in seen:
            seen.add(k); out.append(q)
    return out


def fetch(row):
    i, url = row['id'], row['url']
    kind, slug = i.split('-')[0], i.split('-')[1]
    m = re.match(r'(ab|lv)-(.+)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$', i)
    if m:  # slugs can contain hyphens (united-talent-agency), so split off the trailing UUID instead (Oct 20)
        return ashby(m.group(2), m.group(3)) if m.group(1) == 'ab' else lever(m.group(2), m.group(3))
    if kind == 'gh':
        jid = re.search(r'gh_jid=(\d+)|/jobs/(\d+)', url)
        return greenhouse(slug, jid.group(1) or jid.group(2))
    if kind == 'ab':
        return ashby(slug, i.split('-', 2)[2])
    if kind == 'lv':
        return lever(slug, i.split('-', 2)[2])
    raise ValueError(i)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.forms', description=__doc__.split('\n')[0])
    ap.add_argument('reviewed', nargs='?', help='reviewed CSV (default: the latest in the queue)')
    ap.add_argument('--workspace', default=os.environ.get('GMH_WORKSPACE'), required=not os.environ.get('GMH_WORKSPACE'))
    a = ap.parse_args(argv)
    from .profile import load_config
    ws = os.path.expanduser(a.workspace)
    from . import layout
    P = layout.pipeline(ws)
    src = a.reviewed or (sorted(glob.glob(os.path.join(P, 'queue', 'reviewed-*.csv'))) or [None])[-1]
    if not src:
        sys.exit('no reviewed-*.csv yet: make picks first (gmh review picks)')
    out = os.path.join(P, 'state', 'forms')
    os.makedirs(out, exist_ok=True)
    for r in csv.DictReader(open(src, encoding='utf-8', newline='')):
        if r['call'] != 'apply':
            continue
        if r['id'].split('-')[0] not in ('gh', 'ab', 'lv'):
            print(f"manual {r['company']:18} {r['title'][:50]}: not on Greenhouse/Ashby/Lever; apply by hand (gmh manual-notes)")
            continue
        try:
            qs = fetch(r)
            with open(os.path.join(out, r['id'] + '.json'), 'w', encoding='utf-8', newline='\n') as fh:
                json.dump(dict(id=r['id'], company=r['company'], title=r['title'], url=r['url'], questions=qs), fh,
                          indent=1, ensure_ascii=False)
            print(f"ok   {r['company']:18} {len(qs):3} questions  {r['title'][:50]}")
        except Exception as e:
            print(f"FAIL {r['company']:18} {r['title'][:50]}: {e}")


if __name__ == '__main__':
    main()
