"""Structure of the skills, shared references and subagents: sizes, frontmatter, tables of contents, links that
resolve, no plugin-root variable outside platforms.md, no stale or author-history words, every `gmh ...` named in a
skill is a real command, and the agents table matches the subagent files. The helpers here (bundle, links) are also
used by test_commands.py."""
import functools, glob, os, re, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from engine.__main__ import COMMANDS  # noqa: E402

LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')
NAME_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
FORBIDDEN = [r'<vault>', r'user #' + '1', r'\bY' + r'usang\b', r'\bNov 3\b', r'\b349\b']


def text(p):
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def frontmatter(p):
    """key: value lines of the leading --- block, quotes stripped."""
    m = re.match(r'---\n(.*?)\n---', text(p), re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(':')
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        out[k.strip()] = v
    return out


def rel(p):
    return os.path.relpath(p, REPO)


def skills():
    return sorted(glob.glob(os.path.join(REPO, 'skills', '*', 'SKILL.md')))


def references():
    return sorted(glob.glob(os.path.join(REPO, 'references', '*.md'))
                  + glob.glob(os.path.join(REPO, 'skills', '*', 'references', '*.md')))


# Agents with no tools line, so they inherit the session's tools: gmail-reader needs the user's Gmail connector, whose
# tool names carry a per-user id (mcp__<id>__search_threads) that no tools line can name. Every other agent lists its tools.
INHERITS_TOOLS = {'gmail-reader'}


def subagents():
    return sorted(glob.glob(os.path.join(REPO, 'subagents', '*.md')))


def skill_docs():
    """Every file a skill can send Claude to: skills, their references, the shared references, the subagents."""
    return skills() + references() + subagents()


def resolve(src, target):
    """The file a relative link points to, or None. Until the remaining commands become skills, a link to
    skills/<name>/SKILL.md resolves to commands/<name>.md when only that exists."""
    path = os.path.normpath(os.path.join(os.path.dirname(src), target.split('#')[0]))
    if os.path.exists(path):
        return path
    m = re.match(re.escape(os.path.join(REPO, 'skills')) + r'[\\/]([a-z-]+)[\\/]SKILL\.md$', path)
    if m:
        cmd = os.path.join(REPO, 'commands', m.group(1) + '.md')
        if os.path.exists(cmd):
            return cmd
    return None


def links(p):
    """(target as written, resolved path or None) for every relative link in p."""
    out = []
    for t in LINK_RE.findall(text(p)):
        if re.match(r'[a-z]+:', t) or t.startswith('#') or '{' in t:  # a URL, an anchor, a template placeholder
            continue
        out.append((t, resolve(p, t)))
    return out


def bundle(name, depth=2):
    """A skill's SKILL.md plus the .md files it links to, and theirs (depth levels), as one text. A skill not yet
    converted is its commands/<name>.md and what that links to."""
    start = os.path.join(REPO, 'skills', name, 'SKILL.md')
    if not os.path.exists(start):
        start = os.path.join(REPO, 'commands', name + '.md')
    seen, frontier = [start], [start]
    for _ in range(depth):
        nxt = []
        for p in frontier:
            for _, q in links(p):
                if q and q.endswith('.md') and q not in seen:
                    seen.append(q)
                    nxt.append(q)
        frontier = nxt
    return '\n'.join(text(p) for p in seen)


def slug(heading):
    """The anchor a Markdown renderer gives a heading."""
    s = re.sub(r'[^\w\- ]', '', heading.strip().lower())
    return s.replace(' ', '-')


@functools.lru_cache(maxsize=None)
def help_choices(*argv):
    """The first {a,b,c} choice list in `gmh <argv> --help`, as a set (empty when there is none)."""
    out = subprocess.run([sys.executable, '-m', 'engine', *argv, '--help'], cwd=REPO, capture_output=True, text=True,
                         timeout=60, env={**os.environ, 'GMH_WORKSPACE': os.environ.get('GMH_WORKSPACE', REPO)}, encoding='utf-8')
    for m in re.finditer(r'(\S*)\s*\{([a-z0-9,_-]+)\}', out.stdout.split('\n\n')[0]):
        before = m.group(1)  # "[--source" before {user,web} is an option's values; "[-h]" or "[--open]" is not
        if not (before.lstrip('[').startswith('-') and not before.endswith(']')):
            return set(m.group(2).split(','))
    return set()


class Skills(unittest.TestCase):
    def test_there_are_skills(self):
        names = {os.path.basename(os.path.dirname(p)) for p in skills()}
        self.assertTrue({'today', 'setup'} <= names, names)

    def test_skill_size_and_frontmatter(self):
        for p in skills():
            fm = frontmatter(p)
            folder = os.path.basename(os.path.dirname(p))
            self.assertLess(len(text(p).splitlines()), 200, rel(p))
            self.assertEqual(fm.get('name'), folder, rel(p))
            self.assertRegex(folder, NAME_RE)
            self.assertTrue(fm.get('description'), rel(p))
            self.assertLessEqual(len(fm['description']), 1024, rel(p))
            self.assertLessEqual(len(fm['description']), 300, rel(p))
            if 'model' in fm:
                self.assertIn(fm['model'], ('haiku', 'sonnet', 'opus'), rel(p))

    def test_references_have_frontmatter(self):
        for p in references():
            fm = frontmatter(p)
            self.assertEqual(fm.get('name'), os.path.basename(p)[:-3], rel(p))
            self.assertTrue(fm.get('description'), rel(p))

    def test_long_references_have_a_matching_contents(self):
        for p in references():
            t = text(p)
            if len(t.splitlines()) <= 100:
                continue
            heads = [h for h in re.findall(r'^## (.+)$', t, re.M) if h.strip() != 'Contents']
            self.assertIn('\n## Contents\n', t, rel(p))
            toc = t[t.index('\n## Contents\n'):].split('\n## ', 2)[1]
            anchors = re.findall(r'\]\(#([^)]+)\)', toc)
            self.assertEqual(anchors, [slug(h) for h in heads], rel(p))

    def test_subagent_frontmatter(self):
        self.assertTrue(subagents())
        for p in subagents():
            fm = frontmatter(p)
            self.assertEqual(fm.get('name'), os.path.basename(p)[:-3], p)
            self.assertLessEqual(len(fm.get('description', '')), 250, rel(p))
            self.assertNotIn('never', fm['description'].lower(), rel(p) + ': the safety clause belongs in the body')
            if fm['name'] in INHERITS_TOOLS:
                self.assertNotIn('tools', fm, rel(p))
            else:
                self.assertTrue(fm.get('tools'), rel(p))
            self.assertIn(fm.get('model'), ('haiku', 'sonnet', 'opus'), rel(p))

    def test_manifest_lists_every_subagent(self):
        import json
        with open(os.path.join(REPO, '.claude-plugin', 'plugin.json'), encoding='utf-8') as fh:
            listed = json.load(fh)['agents']
        self.assertEqual(sorted(listed), ['./subagents/' + os.path.basename(p) for p in subagents()])
        self.assertFalse(os.path.exists(os.path.join(REPO, 'agents')))


class Links(unittest.TestCase):
    def test_every_relative_link_resolves(self):
        for p in skill_docs() + glob.glob(os.path.join(REPO, 'templates', '*.md')):
            for t, q in links(p):
                self.assertIsNotNone(q, f'{rel(p)}: link to {t} does not resolve')

    def test_plugin_root_only_in_platforms(self):
        for p in skill_docs():
            if rel(p) == os.path.join('references', 'platforms.md'):
                continue
            self.assertNotIn('CLAUDE_PLUGIN_ROOT', text(p), rel(p))

    def test_no_stale_or_author_words(self):
        for p in skill_docs():
            for pat in FORBIDDEN:
                self.assertIsNone(re.search(pat, text(p)), f'{rel(p)}: {pat}')

    def test_no_repo_paths_to_commands_or_old_agents(self):
        for p in skill_docs():
            t = re.sub(r'<!--.*?-->', '', text(p), flags=re.S)  # credits name the upstream files
            self.assertNotRegex(t, r'(?<![\w/.])agents/[a-z-]+\.md', rel(p))
            self.assertNotRegex(t, r'(?<![\w/.])commands/[a-z-]+\.md', rel(p))

    def test_resolve_falls_back_to_unconverted_commands(self):
        src = os.path.join(REPO, 'skills', 'today', 'SKILL.md')
        for name in [os.path.basename(c)[:-3] for c in glob.glob(os.path.join(REPO, 'commands', '*.md'))]:
            self.assertIsNotNone(resolve(src, f'../{name}/SKILL.md'), name)
        self.assertIsNone(resolve(src, '../no-such-skill/SKILL.md'))


class GmhCommands(unittest.TestCase):
    def test_every_gmh_command_in_the_skills_exists(self):
        found = 0
        for p in skills() + references():
            for span in re.findall(r'`([^`\n]+)`', text(p)):
                toks = span.split()
                if len(toks) < 2 or toks[0] != 'gmh' or toks[1].startswith('-'):
                    continue
                found += 1
                self.assertIn(toks[1], COMMANDS, f'{rel(p)}: `{span}`')
                if COMMANDS[toks[1]][1]:  # a stage command: its words are stage arguments, not subcommands
                    continue
                path, before = [toks[1]], None
                for tok in toks[2:4]:
                    choices = help_choices(*path)
                    if not re.match(r'^[a-z][a-z-]*$', tok) or not choices or choices == before:
                        break  # not a word, or no (new) subcommand list at this level
                    self.assertIn(tok, choices, f'{rel(p)}: `{span}`')
                    path.append(tok)
                    before = choices
        self.assertGreater(found, 40)

    def test_agents_table_matches_subagents(self):
        t = text(os.path.join(REPO, 'references', 'agents.md'))
        rows = dict(re.findall(r'^\| `([a-z-]+)` \| (haiku|sonnet|opus) \|', t, re.M))
        files = {os.path.basename(p)[:-3]: frontmatter(p)['model'] for p in subagents()}
        self.assertEqual(rows, files)


if __name__ == '__main__':
    unittest.main()
