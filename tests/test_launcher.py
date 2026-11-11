"""One launcher for every OS: engine/__main__.py holds the command table that bin/gmh (bash), bin/gmh.cmd (Windows)
and bin/gmh.py call, and it maps each command to the same module the old bash table did."""
import importlib.util, os, subprocess, sys, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from engine.__main__ import COMMANDS  # noqa: E402

# The 0.26 bash launcher's table, kept here so a refactor can't silently re-route a command.
OLD = {'setup': 'engine.setup', 'discover': 'engine.discover', 'score': 'engine.score', 'review': 'engine.runrecord',
       'gmail': 'engine.gmail_import', 'tracker': 'engine.tracker', 'redline': 'engine.redline',
       'linkedin': 'engine.linkedin', 'forms': 'engine.forms', 'applied': 'engine.applied',
       'design': 'engine.design_editor', 'home': 'engine.home', 'today': 'engine.today', 'fills': 'engine.fills',
       'materials': 'engine.materials', **{s: 'engine.stages' for s in
                                           ('answers', 'specs', 'tailor', 'notes', 'manual-notes', 'fillplan')}}
NOT_BUILT_YET = set()  # registered for v1.0; its module lands with its work package


def gmh(*args):
    return subprocess.run([sys.executable, os.path.join(REPO, 'bin', 'gmh.py'), *args],
                          capture_output=True, text=True, encoding='utf-8')


class Launcher(unittest.TestCase):
    def test_old_commands_reach_the_same_module(self):
        for cmd, mod in OLD.items():
            self.assertEqual(COMMANDS[cmd][0], mod, cmd)
            self.assertEqual(COMMANDS[cmd][1], mod == 'engine.stages', cmd)

    def test_every_module_exists(self):
        for cmd, (mod, _, _) in COMMANDS.items():
            if cmd not in NOT_BUILT_YET:
                self.assertIsNotNone(importlib.util.find_spec(mod), cmd)

    def test_help_lists_every_command(self):
        p = gmh('--help')
        self.assertEqual(p.returncode, 0)
        for cmd in COMMANDS:
            self.assertIn(f'  {cmd} ', p.stdout)

    def test_runs_a_module_and_passes_exit_codes(self):
        self.assertEqual(gmh('tracker', '--help').returncode, 0)
        p = gmh('specs', '--help')
        self.assertEqual(p.returncode, 0)
        self.assertIn('fillplan', p.stdout)
        self.assertEqual(gmh('no-such-command').returncode, 2)

    def test_wrappers_call_the_python_launcher(self):
        with open(os.path.join(REPO, 'bin', 'gmh'), encoding='utf-8') as fh:
            self.assertIn('gmh.py', fh.read())
        with open(os.path.join(REPO, 'bin', 'gmh.cmd'), 'rb') as fh:
            cmd = fh.read()
        self.assertIn(b'gmh.py', cmd)
        self.assertIn(b'\r\n', cmd)  # cmd.exe needs CRLF


if __name__ == '__main__':
    unittest.main()
