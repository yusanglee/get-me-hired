"""A small YAML subset reader, so profile.yaml needs no third-party package.

Supported: nested mappings, block lists ("- x"), lists of mappings ("- key: v"),
inline lists ([a, b]), "#" comments, quoted strings, block scalars ("|" and ">"),
and the scalars true/false/null/ints/floats. Unlike YAML 1.1, yes/no stay strings. Not supported: anchors, tags,
multi-document files, inline mappings. A line it can't read raises ValueError
with the line number, rather than guessing.

The writer (dumps, render, fmt_scalar) emits only that subset, so loads(dumps(x)) == x.
"""
import re

_INT = re.compile(r'^[-+]?\d+$')
_FLOAT = re.compile(r'^[-+]?\d+\.\d+$')


def _strip_comment(line):
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == '#' and (i == 0 or line[i - 1] in ' \t'):
            break
        out.append(ch)
    return ''.join(out).rstrip()


def scalar(text):
    t = text.strip()
    if t == '' or t in ('~', 'null', 'Null', 'NULL'):
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in '"\'':
        body = t[1:-1]
        return body.replace("''", "'") if t[0] == "'" else bytes(body, 'utf-8').decode('unicode_escape') if '\\' in body else body
    if t in ('true', 'True'):  # yes/no stay strings: form answers are often literally "Yes" or "No"
        return True
    if t in ('false', 'False'):
        return False
    if _INT.match(t):
        return int(t)
    if _FLOAT.match(t):
        return float(t)
    if t.startswith('[') and t.endswith(']'):
        inner = t[1:-1].strip()
        return [scalar(x) for x in _split_inline(inner)] if inner else []
    return t


def _split_inline(s):
    parts, cur, quote = [], [], None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
            cur.append(ch)
        elif ch == ',':
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append(''.join(cur))
    return [p.strip() for p in parts]


def _key_value(text, lineno):
    m = re.match(r'^("[^"]*"|\'[^\']*\'|[^:]+?)\s*:(\s+(.*)|\s*)$', text)
    if not m:
        raise ValueError(f'line {lineno}: expected "key: value", got {text!r}')
    return scalar(m.group(1)) if m.group(1)[0] in '"\'' else m.group(1).strip(), (m.group(3) or '').strip()


def loads(text):
    lines = []
    raw = text.splitlines()
    i = 0
    while i < len(raw):
        line = raw[i]
        stripped = _strip_comment(line)
        if stripped.strip():
            lines.append((len(line) - len(line.lstrip(' ')), stripped.strip(), i + 1, i))
        i += 1
    pos = [0]

    def block_scalar(style, parent_indent, start_index):
        out, j = [], start_index + 1
        indent = None
        while j < len(raw):
            line = raw[j]
            if line.strip():
                ind = len(line) - len(line.lstrip(' '))
                if ind <= parent_indent:
                    break
                indent = ind if indent is None else indent
                out.append(line[indent:])
            else:
                out.append('')
            j += 1
        while out and not out[-1]:
            out.pop()
        while pos[0] < len(lines) and lines[pos[0]][3] < j:
            pos[0] += 1
        return '\n'.join(out) + '\n' if style == '|' else ' '.join(x for x in out if x) + '\n'

    def parse_value(rest, indent, lineno, raw_index):
        if rest in ('|', '>', '|-', '>-'):
            v = block_scalar(rest[0], indent, raw_index)
            return v.rstrip('\n') if rest.endswith('-') else v
        if rest:
            return scalar(rest)
        if pos[0] < len(lines) and lines[pos[0]][0] > indent:
            return parse_block(lines[pos[0]][0])
        if pos[0] < len(lines) and lines[pos[0]][0] == indent and lines[pos[0]][1].startswith('- '):
            return parse_block(indent)  # a list may sit at its key's indent
        return None

    def parse_block(indent):
        first = lines[pos[0]][1]
        if first == '-' or first.startswith('- '):
            out = []
            while pos[0] < len(lines) and lines[pos[0]][0] == indent and (lines[pos[0]][1] == '-' or lines[pos[0]][1].startswith('- ')):
                _, text, lineno, raw_index = lines[pos[0]]
                pos[0] += 1
                item = text[1:].strip()
                if not item:
                    out.append(parse_block(lines[pos[0]][0]) if pos[0] < len(lines) and lines[pos[0]][0] > indent else None)
                elif re.match(r'^("[^"]*"|\'[^\']*\'|[^\[\]{}"\':]+?)\s*:(\s|$)', item):
                    # a mapping that starts on the dash line; its other keys sit at dash indent + 2
                    child = indent + 2 + (len(text[1:]) - len(text[1:].lstrip(' ')) - 1)
                    k, rest = _key_value(item, lineno)
                    d = {k: parse_value(rest, child, lineno, raw_index)}
                    if pos[0] < len(lines) and lines[pos[0]][0] == child and not lines[pos[0]][1].startswith('- '):
                        d.update(parse_block(child))
                    out.append(d)
                else:
                    out.append(scalar(item))
            return out
        out = {}
        while pos[0] < len(lines) and lines[pos[0]][0] == indent:
            _, text, lineno, raw_index = lines[pos[0]]
            if text.startswith('- '):
                raise ValueError(f'line {lineno}: list item where a key was expected')
            pos[0] += 1
            k, rest = _key_value(text, lineno)
            out[k] = parse_value(rest, indent, lineno, raw_index)
        if pos[0] < len(lines) and lines[pos[0]][0] > indent:
            raise ValueError(f'line {lines[pos[0]][2]}: unexpected indent')
        return out

    if not lines:
        return {}
    result = parse_block(lines[0][0])
    if pos[0] < len(lines):
        raise ValueError(f'line {lines[pos[0]][2]}: unexpected dedent or indent')
    return result


def load(path):
    with open(path, encoding='utf-8') as fh:
        return loads(fh.read())


# ---- writer ----

_PLAIN_BAD = re.compile(r'^[\s\[\]{}"\'#&*!|>%@`,?:-]|: |:$| #|\s$')


def fmt_scalar(v):
    """One value as a single-line scalar that scalar() reads back as the same value (multi-line strings go through
    render() as block scalars)."""
    if v is None:
        return ''
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if isinstance(v, (int, float)):
        return repr(v)
    t = str(v)
    needs = (t == '' or t.strip() in ('~', 'null', 'Null', 'NULL', 'true', 'True', 'false', 'False')
             or _INT.match(t) or _FLOAT.match(t) or _PLAIN_BAD.search(t) or t != t.strip())
    if needs:
        return "'" + t.replace("'", "''") + "'"
    return t


def _key_text(k):
    k = str(k)
    return k if re.match(r'^[A-Za-z0-9_][A-Za-z0-9_ .\-/]*$', k) and not k.endswith(' ') else "'" + k.replace("'", "''") + "'"


def render(key, value, indent=0):
    """Lines for `key: value` at the given indent (key=None renders a bare list item's content, see _item)."""
    pad = ' ' * indent
    k = _key_text(key)
    if isinstance(value, dict):
        if not value:
            return [f'{pad}{k}:']
        out = [f'{pad}{k}:']
        for ck, cv in value.items():
            out += render(ck, cv, indent + 2)
        return out
    if isinstance(value, (list, tuple)):
        if not value:
            return [f'{pad}{k}: []']
        out = [f'{pad}{k}:']
        for item in value:
            out += render_item(item, indent + 2)
        return out
    if isinstance(value, str) and '\n' in value:
        body = value.rstrip('\n').split('\n')
        return [f'{pad}{k}: |' if value.endswith('\n') else f'{pad}{k}: |-'] + [(' ' * (indent + 2) + l) if l else '' for l in body]
    text = fmt_scalar(value)
    return [f'{pad}{k}: {text}' if text != '' else f'{pad}{k}:']


def render_item(item, indent=0):
    """Lines for one list item at the dash's indent."""
    pad = ' ' * indent
    if isinstance(item, dict) and item:
        lines = []
        for ck, cv in item.items():
            lines += render(ck, cv, indent + 2)
        lines[0] = pad + '- ' + lines[0][indent + 2:]
        return lines
    if isinstance(item, (list, tuple)) and item:
        out = [pad + '-']
        for sub in item:
            out += render_item(sub, indent + 2)
        return out
    if isinstance(item, dict) or isinstance(item, (list, tuple)):
        return [pad + '- []'] if isinstance(item, (list, tuple)) else [pad + '-']
    if isinstance(item, str) and '\n' in item:
        return [pad + '- ' + fmt_scalar(item.replace('\n', ' '))]
    text = fmt_scalar(item)
    return [f'{pad}- {text}' if text != '' else pad + '-']


def dumps(obj):
    """A mapping as YAML-subset text (comments are not kept: use render() to patch a file in place)."""
    out = []
    for k, v in obj.items():
        out += render(k, v, 0)
    return '\n'.join(out) + '\n'
