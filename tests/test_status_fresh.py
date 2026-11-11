"""docs/STATUS.md must not contradict git or plugin.json, and the repo-only reminder hook stays out of the export."""
import json, os, re, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = os.path.join(ROOT, 'docs', 'STATUS.md')
HOOK = os.path.join(ROOT, '.claude', 'hooks', 'status_reminder.py')
sys.path.insert(0, os.path.join(ROOT, '.claude', 'hooks'))

CLAIM = re.compile(r'not (?:yet )?(?:merged|shared)', re.I)
TICKED = re.compile(r'`([^`\s]+)`')


def stale_claims(text, merged):
    """Lines that say something is "not merged" or "not shared" about a `ref` that merged(ref) says is in HEAD.
    merged(ref) returns True, False, or None when ref isn't a ref here (then the line is left alone)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if CLAIM.search(line):
            out += [(n, ref, line.strip()) for ref in TICKED.findall(line) if merged(ref)]
    return out


def in_head(ref):
    """Is ref (a local branch, else its origin/ copy) an ancestor of HEAD? None when neither exists here."""
    def git(*a):
        return subprocess.run(['git', '-C', ROOT, *a], capture_output=True)
    for cand in (ref, 'origin/' + ref):
        if git('rev-parse', '--verify', '--quiet', cand + '^{commit}').returncode == 0:
            return git('merge-base', '--is-ancestor', cand, 'HEAD').returncode == 0
    return None


class Parser(unittest.TestCase):
    TEXT = ('## Branch `feature/x` (1.2.0, not merged, not shared)\n'
            'Ran `bin/gmh` fine.\n'
            '## Branch `feature/y` (1.3.0, not merged)\n'
            'Branch `feature/x` is merged and shared.\n')

    def test_flags_only_refs_already_in_head(self):
        got = stale_claims(self.TEXT, lambda r: r == 'feature/x')
        self.assertEqual([(n, ref) for n, ref, _ in got], [(1, 'feature/x')])

    def test_unknown_refs_and_clean_text_pass(self):
        self.assertEqual(stale_claims(self.TEXT, lambda r: None), [])
        self.assertEqual(stale_claims('Everything is merged.', lambda r: True), [])


@unittest.skipUnless(os.path.exists(STATUS), 'STATUS.md is not shipped in the shared copy')
class StatusFresh(unittest.TestCase):
    def setUp(self):
        with open(STATUS, encoding='utf-8') as fh:
            self.text = fh.read()

    def test_names_the_current_version(self):
        with open(os.path.join(ROOT, '.claude-plugin', 'plugin.json'), encoding='utf-8') as fh:
            version = json.load(fh)['version']
        self.assertIn(version, self.text, f'docs/STATUS.md never mentions the current version {version}')

    def test_no_not_merged_claim_about_a_merged_branch(self):
        bad = stale_claims(self.text, in_head)
        self.assertEqual(bad, [], 'docs/STATUS.md says these are not merged/shared, but they are in HEAD: ' +
                         '; '.join(f'line {n} `{ref}`' for n, ref, _ in bad))


@unittest.skipUnless(os.path.exists(HOOK), 'the repo-only reminder hook is not shipped in the shared copy')
class ReminderHook(unittest.TestCase):
    def setUp(self):
        import status_reminder
        self.g = status_reminder.reminder

    def bash(self, cmd):
        return self.g({'tool_name': 'Bash', 'tool_input': {'command': cmd}})

    def test_fires_on_merge_push_and_export(self):
        for cmd in ('git merge --ff-only verify-0.21', 'git push origin main', 'git -C ~/x push',
                    'dev/export-share ~/claude/out', 'git checkout main && git merge feature', 'cd x; ./dev/export-share out'):
            self.assertIn('docs/STATUS.md', self.bash(cmd) or '', cmd)

    def test_quiet_otherwise(self):
        for cmd in ('git status', 'git log --oneline', 'python3 -m unittest discover tests', 'ls docs',
                    'cat dev/export-share', 'grep -rn export-share .', 'grep -rn "git push" docs'):
            self.assertIsNone(self.bash(cmd), cmd)
        self.assertIsNone(self.g({'tool_name': 'Read', 'tool_input': {'file_path': 'git push'}}))

    def test_script_prints_hook_json(self):
        p = subprocess.run([sys.executable, HOOK], capture_output=True,
                           text=True, input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'git push'}}), encoding='utf-8')
        out = json.loads(p.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PostToolUse')
        quiet = subprocess.run([sys.executable, HOOK],
                               capture_output=True, text=True, input='not json', encoding='utf-8')
        self.assertEqual((quiet.returncode, quiet.stdout), (0, ''))

    def test_every_dev_hook_lives_where_the_export_removes_it(self):
        with open(os.path.join(ROOT, '.claude', 'settings.json'), encoding='utf-8') as fh:
            post = json.load(fh)['hooks'].get('PostToolUse', [])
        cmds = [h['command'] for e in post for h in e['hooks']]
        self.assertTrue(cmds)
        for c in cmds:
            self.assertIn('/.claude/hooks/', c, c)


if __name__ == '__main__':
    unittest.main()
