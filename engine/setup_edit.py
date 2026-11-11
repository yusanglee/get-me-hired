"""The edit commands of `gmh setup`: profile.yaml values, config.json blocks, the companies list, resume titles and
the Node tools install. Contract: dev/v1-cli.md (E1). engine/setup.py wires them in (add_parsers / run).

    gmh setup profile set <dotted.path> <value> [--add] [--json-value]
    gmh setup profile show [<path>]
    gmh setup config locations --home <metro> [--remote-countries US,CA] [--metro NAME[:pattern]]...
    gmh setup config top <metro|Remote>... [--bonus N]
    gmh setup config salary --floor <N> [--currency USD|CAD] [--no-range include|exclude|include_if_level_fits]
    gmh setup config resume <key> <value>
    gmh setup companies add "<Company>" [--slug s] [--ats greenhouse|lever|ashby]
    gmh setup tools
    gmh setup resumes <file|folder>... [--titles]

Every command takes --workspace (default $GMH_WORKSPACE). Exit codes: 0 ok, 1 nothing to do or a check failed,
2 bad usage.
"""
import argparse, collections, copy, json, os, re, shutil, subprocess, sys

from . import yamlish

COMMANDS = ('profile', 'config', 'companies', 'tools')

RESUME_KEYS = ('pages', 'page_breaks', 'max_bullet_lines', 'max_summary_lines', 'max_extra_bullets', 'font', 'sections',
               'bottom_margin_pt', 'max_pages', 'max_scope_lines', 'min_last_line_words', 'skills_lines',
               'max_page1_free_pt')
NUMERIC_RESUME_KEYS = ('pages', 'max_bullet_lines', 'max_summary_lines', 'max_extra_bullets', 'bottom_margin_pt',
                       'max_pages', 'max_scope_lines', 'min_last_line_words', 'skills_lines', 'max_page1_free_pt')
NO_RANGE = ('include', 'exclude', 'include_if_level_fits')
ATS_NAMES = ('greenhouse', 'lever', 'ashby')


class Usage(Exception):
    """Bad usage: exit 2."""


class Nothing(Exception):
    """Nothing to do, or a check failed: exit 1."""


def _ws(a):
    ws = getattr(a, 'workspace', None) or os.environ.get('GMH_WORKSPACE')
    if not ws:
        raise Usage('give the workspace: --workspace <folder> or set GMH_WORKSPACE')
    return os.path.abspath(os.path.expanduser(ws))


def _write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


# ---- profile.yaml: in-place edits that keep comments and order ----

def profile_keys():
    """Top-level keys profile.yaml may have: those of templates/profile.example.yaml."""
    from .setup import TEMPLATES
    return list((yamlish.load(os.path.join(TEMPLATES, 'profile.example.yaml')) or {}).keys())


def _content(line):
    s = line.strip()
    return bool(s) and not s.startswith('#')


def _indent(line):
    return len(line) - len(line.lstrip(' '))


_KEY = re.compile(r'''^(?P<ind>\s*)(?P<dash>- )?(?P<key>"[^"]*"|'[^']*'|[^\s:#'"\-\[{][^:#]*?)\s*:(?P<rest>(?:\s.*)?)$''')


def _parse(line):
    """(effective key indent, key, rest, prefix) for a `key: value` line (a dash counts as 2 columns), else None."""
    m = _KEY.match(line.rstrip())
    if not m:
        return None
    key = m['key']
    if key[0] in '"\'':
        key = key[1:-1]
    eff = len(m['ind']) + (2 if m['dash'] else 0)
    return eff, key, m['rest'], m['ind'] + (m['dash'] or '')


def _is_dash(line):
    s = line.lstrip(' ')
    return s == '-' or s.startswith('- ')


def _block_end(lines, i, k):
    """One past the last content line of the block that belongs to the key on line i (effective indent k)."""
    j, last = i + 1, i
    while j < len(lines):
        if _content(lines[j]):
            ind = _indent(lines[j])
            if ind < k or (ind == k and not _is_dash(lines[j])):
                break
            last = j
        j += 1
    return last + 1


def _find_key(lines, lo, hi, k, name):
    for i in range(lo, hi):
        if _content(lines[i]):
            p = _parse(lines[i])
            if p and p[0] == k and p[1] == name:
                return i
    return None


def _items(lines, lo, hi, d):
    """[(start, end)] of the list items whose dashes sit at indent d inside lines[lo:hi]."""
    starts = [i for i in range(lo, hi) if _content(lines[i]) and _indent(lines[i]) == d and _is_dash(lines[i])]
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else hi
        while e > s + 1 and not _content(lines[e - 1]):
            e -= 1
        out.append((s, e))
    return out


def _build(parts, value):
    if not parts:
        return value
    if parts[0].isdigit():
        if int(parts[0]) != 0:
            raise Usage(f'cannot create list item {parts[0]}: add them in order starting at 0')
        return [_build(parts[1:], value)]
    return {parts[0]: _build(parts[1:], value)}


def _lookup(data, parts):
    node = data
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        elif isinstance(node, list) and p.isdigit() and int(p) < len(node):
            node = node[int(p)]
        else:
            return None, False
    return node, True


def _apply(data, parts, value, add):
    """The expected parsed result of an edit, to check the text edit against."""
    data = copy.deepcopy(data)
    node = data
    for n, p in enumerate(parts):
        last = n == len(parts) - 1
        if isinstance(node, dict):
            if last:
                if add:
                    cur = node.get(p)
                    node[p] = (list(cur) if isinstance(cur, list) else []) + [value]
                else:
                    node[p] = value
            else:
                if not isinstance(node.get(p), (dict, list)):
                    node[p] = _build(parts[n + 1:], [value] if add else value)
                    return data
                node = node[p]
        elif isinstance(node, list) and p.isdigit():
            i = int(p)
            if i < len(node):
                if last:
                    if add:
                        raise Usage(f'{".".join(parts)} is a list item; --add works on a list')
                    node[i] = value
                else:
                    if not isinstance(node[i], (dict, list)):
                        node[i] = _build(parts[n + 1:], [value] if add else value)
                        return data
                    node = node[i]
            elif i == len(node):
                node.append(_build(parts[n + 1:], [value] if add else value))
                return data
            else:
                raise Usage(f'{".".join(parts[:n + 1])}: only {len(node)} items; add the next one as {len(node)}')
        else:
            raise Usage(f'{".".join(parts[:n])} is not a {"list" if p.isdigit() else "mapping"}')
    return data


def _with_prefix(new_lines, prefix, k):
    """new_lines were rendered at indent k; give the first one the original line prefix (indent and dash)."""
    new_lines = list(new_lines)
    new_lines[0] = prefix + new_lines[0][k:]
    return new_lines


def edit_text(text, parts, value, add=False):
    """Set (or with add, append to a list at) the dotted path in profile.yaml text, keeping comments, order and
    every other line. Returns the new text; raises Usage when the path doesn't fit the file's shape."""
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    n_lines = len(lines)
    first = next((i for i, l in enumerate(lines) if _content(l)), None)
    lo, hi = 0, n_lines
    k = _indent(lines[first]) if first is not None else 0
    state = 'map'      # what lines[lo:hi] holds: 'map' (keys at k) or 'list' (dashes at k)
    parent_key = None  # (i, k, prefix) of the key that owns the container, if any
    for n, p in enumerate(parts):
        last = n == len(parts) - 1
        rest_parts = parts[n + 1:]
        if state == 'map':
            i = _find_key(lines, lo, hi, k, p)
            if i is None:  # a new key at the end of this mapping
                new = _build(rest_parts, [value] if add and last else value) if not last else ([value] if add else value)
                new_lines = yamlish.render(p, new, k)
                at = hi
                while at > lo and not _content(lines[at - 1]):
                    at -= 1
                if first is None:
                    at = n_lines
                lines[at:at] = new_lines
                break
            _, key, rest, prefix = _parse(lines[i])
            e = _block_end(lines, i, k)
            body = [j for j in range(i + 1, e) if _content(lines[j])]
            value_raw = yamlish._strip_comment(rest).strip()
            comment = rest[len(yamlish._strip_comment(rest)):]
            if last:
                if add:
                    if body and _is_dash(lines[body[0]]):  # a block list: add one line, touch nothing else
                        d = _indent(lines[body[0]])
                        lines[e:e] = yamlish.render_item(value, d)
                        break
                    if value_raw not in ('', '[]', '~', 'null') and not value_raw.startswith('['):
                        raise Usage(f'{".".join(parts)} is not a list (it holds a single value)')
                    cur = yamlish.scalar(value_raw) if value_raw else None
                    new = (cur if isinstance(cur, list) else []) + [value]
                else:
                    new = value
                new_lines = _with_prefix(yamlish.render(key, new, k), prefix, k)
                if not isinstance(new, (dict, list)) and not (isinstance(new, str) and '\n' in new) and comment.strip():
                    new_lines[0] += comment
                lines[i:e] = new_lines
                break
            # descend
            if not body:
                if value_raw not in ('', '[]', '~', 'null'):
                    raise Usage(f'{".".join(parts[:n + 1])} holds a single value, not a mapping or list')
                new = _build(rest_parts, [value] if add and not rest_parts else value) if rest_parts else value
                lines[i:e] = _with_prefix(yamlish.render(key, _build(rest_parts, [value] if add else value), k), prefix, k)
                break
            c = _indent(lines[body[0]])
            lo, hi = i + 1, e
            if _is_dash(lines[body[0]]):
                state, k = 'list', c
            else:
                state, k = 'map', c
        else:  # list
            if not p.isdigit():
                raise Usage(f'{".".join(parts[:n])} is a list: use an item number, like {".".join(parts[:n])}.0')
            items = _items(lines, lo, hi, k)
            idx = int(p)
            if idx >= len(items):
                if idx != len(items):
                    raise Usage(f'{".".join(parts[:n])}: only {len(items)} items; add the next one as {len(items)}')
                item = _build(rest_parts, [value] if add and not rest_parts else value) if rest_parts else ([value] if add else value)
                at = hi
                while at > lo and not _content(lines[at - 1]):
                    at -= 1
                lines[at:at] = yamlish.render_item(item, k)
                break
            s, e = items[idx]
            if last:
                if add:
                    raise Usage(f'{".".join(parts)} is a list item; --add works on a list')
                lines[s:e] = yamlish.render_item(value, k)
                break
            head = lines[s].lstrip(' ')[1:].strip()
            if head and not _parse(lines[s]):
                raise Usage(f'{".".join(parts[:n + 1])} holds a single value, not a mapping')
            lo, hi, state, k = s, e, 'map', k + 2
            if not head:  # "-" alone, keys on the following lines
                nxt = next((j for j in range(s + 1, e) if _content(lines[j])), None)
                if nxt is None:
                    raise Usage(f'{".".join(parts[:n + 1])} is empty')
                lo, k = s + 1, _indent(lines[nxt])
    return '\n'.join(lines) + '\n'


def parse_value(text, as_json=False):
    if as_json:
        try:
            return json.loads(text)
        except ValueError as e:
            raise Usage(f'--json-value: not valid JSON ({e})')
    t = text.strip()
    if re.match(r'^[-+]?0\d+$', t) or re.match(r'^[-+]?\d{16,}$', t):
        return t  # zip codes and long ids keep their leading zeros and digits
    return yamlish.scalar(text)


def _show(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _blank(x):
    if isinstance(x, dict):
        return all(_blank(v) for v in x.values())
    return x in (None, '', [])


def profile_set(ws, path, text, add=False, as_json=False):
    pp = os.path.join(ws, 'profile.yaml')
    if not os.path.exists(pp):
        raise Nothing(f'no profile.yaml in {ws} (run gmh setup init)')
    parts = [p for p in path.split('.') if p]
    if not parts:
        raise Usage('give a path like identity.email')
    allowed = profile_keys()
    if parts[0] not in allowed:
        raise Usage(f'unknown profile section {parts[0]!r}; the sections are: {", ".join(allowed)}')
    value = parse_value(text, as_json)
    with open(pp, encoding='utf-8') as fh:
        old = fh.read()
    data = yamlish.loads(old) or {}
    cur, ok = _lookup(data, parts)
    if add and ok and isinstance(cur, list) and cur and all(_blank(x) for x in cur):
        old = edit_text(old, parts, [], False)  # the template's empty example entry makes way for the first real one
        data = yamlish.loads(old) or {}
    want = _apply(data, parts, value, add)
    new = edit_text(old, parts, value, add)
    try:
        got = yamlish.loads(new)
    except ValueError as e:
        raise Nothing(f'profile.yaml not changed: the edit would not read back ({e})')
    if got != want:
        raise Nothing('profile.yaml not changed: the edit would not read back as the same values '
                      f'(path {path}); edit the file by hand')
    if new != old:
        _write(pp, new)
    return value


def profile_show(ws, path=None):
    pp = os.path.join(ws, 'profile.yaml')
    if not os.path.exists(pp):
        raise Nothing(f'no profile.yaml in {ws}')
    if not path:
        with open(pp, encoding='utf-8') as fh:
            return fh.read().rstrip('\n')
    data = yamlish.load(pp) or {}
    v, ok = _lookup(data, [p for p in path.split('.') if p])
    if not ok:
        raise Nothing(f'{path}: not in profile.yaml')
    if isinstance(v, (dict, list)):
        return yamlish.dumps({path.split('.')[-1]: v}).rstrip('\n')
    return '' if v is None else (str(v).rstrip('\n') if isinstance(v, str) else json.dumps(v))


# ---- config.json ----

def _config_path(ws):
    p = os.path.join(ws, 'config.json')
    if not os.path.exists(p):
        raise Nothing(f'no config.json in {ws} (run gmh setup init)')
    return p


def load_raw_config(ws):
    with open(_config_path(ws), encoding='utf-8') as fh:
        return json.load(fh, object_pairs_hook=collections.OrderedDict)


def save_config(ws, cfg):
    _write(os.path.join(ws, 'config.json'), json.dumps(cfg, indent=2, ensure_ascii=False) + '\n')


def _block(cfg, name):
    if not isinstance(cfg.get(name), dict):
        cfg[name] = collections.OrderedDict()
    return cfg[name]


def _check_locations(loc):
    """The same rules the engine applies when it reads the block (profile.normalize_locations); Usage on a bad one."""
    from .profile import normalize_locations
    probe = copy.deepcopy(dict(loc))
    if probe.get('remote_countries'):
        probe['remote_us'] = True  # the engine's remote_countries reading (E6) makes 'Remote' a valid top choice
    try:
        normalize_locations(probe)
    except ValueError as e:
        raise Usage(str(e))


def config_locations(ws, home=None, remote_countries=None, metros=()):
    from .profile import KNOWN_METROS
    cfg = load_raw_config(ws)
    loc = _block(cfg, 'locations')
    if remote_countries is not None:
        codes = []
        for c in re.split(r'[,\s]+', remote_countries):
            c = c.strip().upper()
            if c and c not in codes:
                codes.append(c)
        if not all(re.fullmatch(r'[A-Z]{2}', c) for c in codes):
            raise Usage('--remote-countries takes two-letter country codes, like US,CA')
        loc['remote_countries'] = codes
        loc['remote_us'] = 'US' in codes  # the engine of today still reads remote_us
    if metros:
        out = []
        for m in metros:
            name, _, pat = m.partition(':')
            name = name.strip()
            if not name:
                raise Usage(f'--metro {m!r}: give a metro name, like NYC or "Portland:portland|pdx"')
            entry = collections.OrderedDict(name=name, policy='any')
            if pat.strip():
                entry['pattern'] = pat.strip()
            out.append(entry)
        loc['metros'] = out
    if home:
        loc['home'] = home
        names = [m.get('name') for m in loc.get('metros') or []]
        if home not in names and home in KNOWN_METROS:
            loc.setdefault('metros', []).append(collections.OrderedDict(name=home, policy='any'))
    if home is None and remote_countries is None and not metros:
        raise Usage('give --home, --remote-countries or --metro')
    _check_locations(loc)
    save_config(ws, cfg)
    return loc


def config_top(ws, names, bonus=None):
    cfg = load_raw_config(ws)
    loc = _block(cfg, 'locations')
    have = {m.get('name') for m in loc.get('metros') or []}
    remote_ok = bool(loc.get('remote_us') or loc.get('remote_countries'))
    for n in names:
        if n != 'Remote' and n not in have:
            raise Usage(f"{n!r} is not a configured metro ({', '.join(sorted(have)) or 'none yet'}); "
                        'add it with gmh setup config locations --metro first')
        if n == 'Remote' and not remote_ok:
            raise Usage("'Remote' needs remote countries: gmh setup config locations --remote-countries US")
    loc['top'] = list(names)
    if bonus is not None:
        loc['top_bonus'] = bonus
    elif names and 'top_bonus' not in loc:
        loc['top_bonus'] = 5
    _check_locations(loc)
    save_config(ws, cfg)
    return loc


def config_salary(ws, floor=None, currency='USD', no_range=None):
    if floor is None and no_range is None:
        raise Usage('give --floor and/or --no-range')
    cur = currency.upper()
    if cur not in ('USD', 'CAD'):
        raise Usage('--currency is USD or CAD')
    if no_range is not None and no_range not in NO_RANGE:
        raise Usage(f'--no-range is one of {", ".join(NO_RANGE)}')
    if floor is not None and floor < 0:
        raise Usage('--floor must be a positive number')
    cfg = load_raw_config(ws)
    sal = _block(cfg, 'salary')
    if floor is not None:
        sal['floor_' + cur.lower()] = floor
    if no_range is not None:
        sal['no_range_policy'] = no_range
    save_config(ws, cfg)
    return sal


def config_resume(ws, key, text):
    if key not in RESUME_KEYS:
        raise Usage(f'unknown resume key {key!r}; the keys are: {", ".join(RESUME_KEYS)}')
    t = text.strip()
    try:
        value = json.loads(t)
    except ValueError:
        value = None if t.lower() in ('none', 'null', '') else t
    if key in NUMERIC_RESUME_KEYS and not (value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))):
        raise Usage(f'resume.{key} takes a number (or none to turn it off)')
    if key == 'page_breaks' and not (value is None or isinstance(value, dict)):
        raise Usage('resume.page_breaks takes a JSON object, like \'{"first_on_page_2": "experience[2]"}\'')
    if key in ('sections',) and value is not None and not isinstance(value, (list, dict)):
        raise Usage('resume.sections takes JSON (a list or object)')
    cfg = load_raw_config(ws)
    block = _block(cfg, 'resume')
    block[key] = {} if key == 'page_breaks' and value is None else value
    save_config(ws, cfg)
    return block


# ---- companies.txt ----

def _guess_slug(name):
    return re.sub(r'[^a-z0-9]+', '', name.lower())


def companies_add(ws, name, slug=None, ats=None):
    """Append `Company | slug` to companies.txt unless a line already names the company (case-insensitive).
    --ats pins the board in Pipeline/state/ats_cache.json, so the company isn't probed. Returns 'added' or 'already there'."""
    from .setup import COMPANIES_HEADER, _companies
    name = re.sub(r'\s+', ' ', name).strip()
    if not name or '|' in name:
        raise Usage('give the company name (without a | in it)')
    path = os.path.join(ws, 'companies.txt')
    have = {n.lower() for n, _ in _companies(ws)}
    if name.lower() in have:
        return 'already there'
    text = ''
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    else:
        text = COMPANIES_HEADER
    if text and not text.endswith('\n'):
        text += '\n'
    slug = (slug or '').strip() or _guess_slug(name)
    _write(path, text + f'{name} | {slug}\n')
    if ats:
        state = os.path.join(ws, 'Pipeline', 'state')
        os.makedirs(state, exist_ok=True)
        cp = os.path.join(state, 'ats_cache.json')
        cache = {}
        if os.path.exists(cp):
            with open(cp, encoding='utf-8') as fh:
                cache = json.load(fh)
        cache[name] = [ats, slug]
        _write(cp, json.dumps(cache, indent=1, sort_keys=True) + '\n')
    return 'added'


# ---- Node tools ----

def tools_install(ws, tools_dir=None, run=None, which=None):
    """Install the plugin's Node dependency (docx, at the version in tools/package.json) into <ws>/.gmh/node_modules
    and record paths.node_modules in config.json. Returns the node_modules path."""
    from .resume import INSTALL_HINT
    from .setup import REPO
    run, which = run or subprocess.run, which or shutil.which
    with open(os.path.join(tools_dir or os.path.join(REPO, 'tools'), 'package.json'), encoding='utf-8') as fh:
        pkg = json.load(fh)
    deps = pkg.get('dependencies') or {}
    npm, node = which('npm'), which('node')
    if not (npm and node):
        raise Nothing(f"{'Node.js' if not node else 'npm'} not found: install Node.js from https://nodejs.org (it includes npm), "
                      f'then run gmh setup tools again, or: {INSTALL_HINT}')
    prefix = os.path.join(ws, '.gmh')
    os.makedirs(prefix, exist_ok=True)
    _write(os.path.join(prefix, 'package.json'), json.dumps({'name': 'gmh-workspace-tools', 'private': True,
                                                             'dependencies': deps}, indent=2) + '\n')
    lock = os.path.join(tools_dir or os.path.join(REPO, 'tools'), 'package-lock.json')
    if os.path.exists(lock):
        shutil.copyfile(lock, os.path.join(prefix, 'package-lock.json'))
        cmd = [npm, 'ci', '--prefix', prefix, '--no-audit', '--no-fund']
    else:
        cmd = [npm, 'install', '--prefix', prefix, '--no-audit', '--no-fund']
    r = run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode and cmd[1] == 'ci':  # a lockfile that doesn't fit: fall back to a plain install
        cmd = [npm, 'install', '--prefix', prefix, '--no-audit', '--no-fund']
        r = run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise Nothing(f'npm failed ({" ".join(cmd[:2])}): {(r.stderr or r.stdout or "").strip()[-400:]}')
    modules = os.path.join(prefix, 'node_modules')
    if not os.path.isdir(os.path.join(modules, 'docx')):
        raise Nothing(f'npm finished but {os.path.join(modules, "docx")} is not there')
    cfg = load_raw_config(ws)
    _block(cfg, 'paths')['node_modules'] = modules
    save_config(ws, cfg)
    return modules


# ---- resume job titles ----

TITLE_WORDS = ('manager', 'director', 'lead', 'head', 'vp', 'vice president', 'president', 'chief', 'officer', 'founder',
               'co-founder', 'cofounder', 'engineer', 'designer', 'analyst', 'researcher', 'scientist', 'strategist',
               'consultant', 'specialist', 'coordinator', 'associate', 'architect', 'developer', 'producer', 'recruiter',
               'partner', 'owner', 'principal', 'administrator', 'executive', 'intern', 'advisor', 'adviser', 'editor',
               'writer', 'planner', 'generalist', 'controller', 'accountant', 'representative', 'assistant', 'fellow',
               'attorney', 'counsel', 'teacher', 'professor', 'manager,')
DEPT_WORDS = ('product', 'engineering', 'design', 'marketing', 'operations', 'strategy', 'growth', 'data', 'sales',
              'finance', 'research', 'platform', 'technology', 'business', 'customer', 'people', 'hr', 'legal', 'ux',
              'content', 'brand', 'partnerships', 'analytics', 'programs', 'program', 'project', 'software', 'ai',
              'machine', 'learning', 'security', 'infrastructure', 'consumer', 'revenue', 'communications', 'talent')
_TITLE_RE = re.compile(r'\b(?:' + '|'.join(re.escape(w) for w in TITLE_WORDS if not w.endswith(',')) + r')\b', re.I)
_DEPT_RE = re.compile(r'\b(?:' + '|'.join(DEPT_WORDS) + r')\b', re.I)
_MONTH = r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?'
_DATE_RE = re.compile(r'(?:\(?\b' + _MONTH + r'\s+)?\b(?:19|20)\d{2}\b(?:\s*[-–—]\s*(?:(?:' + _MONTH + r'\s+)?(?:(?:19|20)\d{2}|present|current|now)))?\)?|\bpresent\b|\bcurrent\b', re.I)
_SPLIT_RE = re.compile(r'\s+[|–—·@]\s+|\s+-\s+|\s+at\s+|\t+|\s{3,}|\|', re.I)


def titles_in(text):
    """Job titles that look like titles in one resume's text: short lines (or the first piece of a 'Title | Company |
    dates' line) with a role word, in capitalized words. A heuristic: Claude reads the list before using it."""
    found = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in '•*●▪-–—·' or len(line) > 140:
            continue
        line = _DATE_RE.sub(' ', line).strip(' ,;|–—-·')
        for part in _SPLIT_RE.split(line):
            part = part.strip(' ,;:()')
            if not part:
                continue
            head, comma, tail = part.partition(',')
            if comma and not (_TITLE_RE.search(tail) or _DEPT_RE.search(tail)):
                part = head.strip()  # "Senior Product Manager, Acme Corp": the company after the comma goes
            words = part.split()
            if not 1 <= len(words) <= 8 or part.endswith('.') or not _TITLE_RE.search(part):
                continue
            small = {'of', 'and', 'the', 'for', 'in', 'to', 'a', 'an', '&', 'at', 'on'}
            caps = [w for w in words if w.lower() not in small]
            if not caps or sum(1 for w in caps if w[:1].isupper() or w[:1].isdigit()) < max(1, int(len(caps) * 0.75 + 0.5)):
                continue
            if len(words) > 1 and words[0].lower() in ('responsible', 'managed', 'led', 'built', 'worked', 'owned'):
                continue
            found.append(part)
            break
    return found


def title_table(versions):
    """[(count, title, [version names])], most common first. versions: [(name, text)]. Counts the versions that
    show a title (case and spacing ignored), not repeats inside one."""
    seen = collections.OrderedDict()
    for name, text in versions:
        for t in titles_in(text):
            key = re.sub(r'\s+', ' ', t.lower().replace('&', 'and')).strip()
            e = seen.setdefault(key, {'forms': collections.Counter(), 'files': []})
            e['forms'][t] += 1
            if name not in e['files']:
                e['files'].append(name)
    rows = [(len(e['files']), e['forms'].most_common(1)[0][0], e['files']) for e in seen.values()]
    return sorted(rows, key=lambda r: (-r[0], r[1].lower()))


def format_titles(rows):
    if not rows:
        return 'no job titles found in the resume versions'
    w = max(len(str(r[0])) for r in rows)
    return '\n'.join(f'{str(c).rjust(w)}  {t}  ({", ".join(f)})' for c, t, f in rows)


def resolve_resume_args(paths, workspace=None):
    """`resumes` took <workspace> <files>...; v1 takes <files>... with --workspace or $GMH_WORKSPACE. A first path
    that is a workspace folder (it holds profile.yaml or config.json) is still read as the workspace.
    Returns (workspace or None, [file])."""
    paths = list(paths)
    if workspace:
        return workspace, paths
    if paths:
        p = os.path.expanduser(paths[0])
        if os.path.isdir(p) and (os.path.exists(os.path.join(p, 'profile.yaml')) or os.path.exists(os.path.join(p, 'config.json'))):
            return paths[0], paths[1:]
    env = os.environ.get('GMH_WORKSPACE')
    if env:
        return env, paths
    if paths:
        return paths[0], paths[1:]
    return None, []


def expand_resume_files(files):
    """Folders become the .txt, .md, .docx and .pdf files directly inside them."""
    out = []
    for f in files:
        f = os.path.expanduser(f)
        if os.path.isdir(f):
            out += [os.path.join(f, n) for n in sorted(os.listdir(f)) if n.lower().endswith(('.txt', '.md', '.docx', '.pdf'))]
        else:
            out.append(f)
    return out


def pdf_text(path, run=None, which=None):
    run, which = run or subprocess.run, which or shutil.which
    exe = which('pdftotext')
    if not exe:
        raise SystemExit(f'{path}: reading a PDF needs pdftotext, which is not installed '
                         '(brew install poppler, or apt install poppler-utils, or poppler for Windows); '
                         'or save the PDF text as a .txt file and add that')
    r = run([exe, '-layout', path, '-'], capture_output=True)
    if r.returncode:
        raise SystemExit(f'{path}: pdftotext failed: {(r.stderr or b"").decode("utf-8", "replace").strip()[-200:]}')
    return r.stdout.decode('utf-8', 'replace')


# ---- argparse wiring ----

def _ws_arg(s):
    s.add_argument('--workspace', help='the workspace folder (default: $GMH_WORKSPACE)')


def add_parsers(sub):
    s = sub.add_parser('profile', help='set or show a profile.yaml value')
    ps = s.add_subparsers(dest='sub', required=True)
    p = ps.add_parser('set', help='set one value (a dotted path like identity.email)')
    p.add_argument('path')
    p.add_argument('value')
    p.add_argument('--add', action='store_true', help='append to a list instead of replacing')
    p.add_argument('--json-value', action='store_true', help='read the value as JSON (lists, mappings, exact strings)')
    _ws_arg(p)
    p = ps.add_parser('show', help='print the profile or one value')
    p.add_argument('path', nargs='?')
    _ws_arg(p)

    s = sub.add_parser('config', help='write config.json settings')
    cs = s.add_subparsers(dest='sub', required=True)
    p = cs.add_parser('locations')
    p.add_argument('--home', help='home metro')
    p.add_argument('--remote-countries', help='countries remote roles may be in, like US,CA')
    p.add_argument('--metro', action='append', default=[], metavar='NAME[:pattern]',
                   help='a metro to search (repeat); replaces the list. Unknown names need a :pattern regex')
    _ws_arg(p)
    p = cs.add_parser('top')
    p.add_argument('names', nargs='*', metavar='metro|Remote')
    p.add_argument('--bonus', type=int)
    _ws_arg(p)
    p = cs.add_parser('salary')
    p.add_argument('--floor', type=int)
    p.add_argument('--currency', default='USD', type=str.upper, choices=['USD', 'CAD'])
    p.add_argument('--no-range', choices=list(NO_RANGE))
    _ws_arg(p)
    p = cs.add_parser('resume')
    p.add_argument('key', choices=list(RESUME_KEYS))
    p.add_argument('value')
    _ws_arg(p)

    s = sub.add_parser('companies', help='edit the target-company list')
    ks = s.add_subparsers(dest='sub', required=True)
    p = ks.add_parser('add')
    p.add_argument('company')
    p.add_argument('--slug')
    p.add_argument('--ats', choices=list(ATS_NAMES))
    _ws_arg(p)

    s = sub.add_parser('tools', help='install the Node tools (docx) into the workspace')
    _ws_arg(s)


def run(a):
    """Run one of COMMANDS; returns the exit code."""
    try:
        ws = _ws(a)
        if a.cmd == 'profile':
            if a.sub == 'set':
                v = profile_set(ws, a.path, a.value, a.add, a.json_value)
                print(f'{"added to" if a.add else "set"} {a.path}{" +=" if a.add else " ="} {_show(v)}')
            else:
                print(profile_show(ws, a.path))
        elif a.cmd == 'config':
            if a.sub == 'locations':
                out = config_locations(ws, a.home, a.remote_countries, a.metro)
            elif a.sub == 'top':
                out = config_top(ws, a.names, a.bonus)
            elif a.sub == 'salary':
                out = config_salary(ws, a.floor, a.currency, a.no_range)
            else:
                out = config_resume(ws, a.key, a.value)
            print(json.dumps({a.sub if a.sub != 'top' else 'locations': out}, indent=2, ensure_ascii=False))
        elif a.cmd == 'companies':
            what = companies_add(ws, a.company, a.slug, a.ats)
            print(what)
        else:
            modules = tools_install(ws)
            print(f'installed the Node tools in {modules}\nrecorded paths.node_modules in {os.path.join(ws, "config.json")}')
        return 0
    except Usage as e:
        print(f'gmh setup {a.cmd}: {e}', file=sys.stderr)
        return 2
    except Nothing as e:
        print(f'gmh setup {a.cmd}: {e}', file=sys.stderr)
        return 1
