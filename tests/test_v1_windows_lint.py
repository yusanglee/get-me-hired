"""Windows-portability lint: an AST scan of the Python sources.

Windows opens text files as cp1252 unless told otherwise, so every text-mode open must name its encoding,
every text-mode subprocess must name its encoding, and files read or written through csv need newline=''.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ['engine', 'dev', 'hooks', 'bin', 'tests']
SKIP_DIRS = {'node_modules', 'vendor', '__pycache__', '.git'}


def sources():
    for top in SCAN:
        for dp, dns, fns in os.walk(os.path.join(ROOT, top)):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                p = os.path.join(dp, fn)
                if not fn.endswith('.py'):
                    continue
                with open(p, encoding='utf-8', newline='') as f:
                    yield p, f.read()


def kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def const(node):
    return node.value if isinstance(node, ast.Constant) else None


def mode_arg(call, pos):
    m = kw(call, 'mode')
    if m is None and len(call.args) > pos:
        m = call.args[pos]
    return m


def is_text_mode(m):
    if m is None:
        return True
    v = const(m)
    return isinstance(v, str) and 'b' not in v


def has(call, name):
    return kw(call, name) is not None or any(k.arg is None for k in call.keywords)


def parents_of(tree):
    par = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            par[c] = n
    return par


def csv_fed(call, par):
    """True when this open() is handed to the csv module: directly, or through the name it is bound to."""
    p = par.get(call)
    if isinstance(p, ast.Call) and ast.unparse(p.func).startswith('csv.'):
        return True
    name, scope = None, None
    if isinstance(p, ast.withitem) and isinstance(p.optional_vars, ast.Name):
        name, scope = p.optional_vars.id, par.get(p)
    elif isinstance(p, ast.Assign) and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name):
        name, scope = p.targets[0].id, p
        while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            scope = par.get(scope)
    if name is None or scope is None:
        return False
    for c in ast.walk(scope):
        if isinstance(c, ast.Call) and ast.unparse(c.func).startswith('csv.'):
            args = list(c.args) + [k.value for k in c.keywords]
            if any(isinstance(a, ast.Name) and a.id == name for a in args):
                return True
    return False


def wanted(call, par):
    """The keyword arguments a text-mode open() is missing: [] when it is fine."""
    add = []
    if not has(call, 'encoding') and len(call.args) < 4:
        add.append("encoding='utf-8'")
    if csv_fed(call, par) and not has(call, 'newline') and len(call.args) < 5:
        add.append("newline=''")
    return add


def problems(path, txt):
    out = []
    rel = os.path.relpath(path, ROOT)
    tree = ast.parse(txt)
    par = parents_of(tree)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        dotted = ast.unparse(n.func)
        where = f'{rel}:{n.lineno}'
        if dotted in ('open', 'io.open'):
            if is_text_mode(mode_arg(n, 1)):
                out += [f'{where}: open() in text mode without {w.split("=")[0]}=' for w in wanted(n, par)]
        elif isinstance(n.func, ast.Attribute) and n.func.attr in ('read_text', 'write_text'):
            positional = 0 if n.func.attr == 'read_text' else 1
            if not has(n, 'encoding') and len(n.args) <= positional:
                out.append(f'{where}: {n.func.attr}() without encoding=')
        elif dotted in ('subprocess.run', 'subprocess.Popen', 'subprocess.check_output', 'subprocess.check_call',
                        'subprocess.call'):
            t = kw(n, 'text') or kw(n, 'universal_newlines')
            if t is not None and const(t) is not False and not has(n, 'encoding'):
                out.append(f'{where}: {dotted}(text=True) without encoding=')
    return out


class WindowsLint(unittest.TestCase):
    def test_text_io_names_its_encoding(self):
        bad = []
        for p, txt in sources():
            bad += problems(p, txt)
        self.assertEqual(bad, [], '\n' + '\n'.join(bad))

    def test_the_scan_sees_files(self):
        self.assertGreater(len(list(sources())), 20)


if __name__ == '__main__':
    unittest.main()
