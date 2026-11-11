"""get-me-hired launcher: `gmh <command> [args]` on every OS (bin/gmh, bin/gmh.cmd and bin/gmh.py call main()).

    python -m engine <command> [args]      (from the plugin folder)
"""
import importlib.util, os, runpy, sys

# command -> (module, pass the command name on as argv[1], help line)
COMMANDS = {
    'setup':        ('engine.setup', False, 'workspace setup, checks, profile/config edits, role packs'),
    'discover':     ('engine.discover', False, 'find roles on the watchlist and job boards'),
    'score':        ('engine.score', False, 'triage-score the latest discovered roles'),
    'review':       ('engine.runrecord', False, 'run summary, review page, reads and picks -> reviewed CSV'),
    'gmail':        ('engine.gmail_import', False, 'email history import and status sync'),
    'tracker':      ('engine.tracker', False, 'tracker.csv: status, find, prep, report'),
    'redline':      ('engine.redline', False, 'reviewer packet, edit apply and fact checks for drafts'),
    'linkedin':     ('engine.linkedin', False, '"I\'m interested" queue, connect-note packet and checks'),
    'forms':        ('engine.forms', False, 'fetch the application forms of apply picks'),
    'applied':      ('engine.applied', False, 'record a confirmed application in the tracker'),
    'design':       ('engine.design_editor', False, 'resume design editor on a local page, or the usable-font list'),
    'today':        ('engine.today', False, 'where today stands and the next step'),
    'home':         ('engine.home', False, 'HOME.md (status and links), and the summaries sessions leave'),
    'fills':        ('engine.fills', False, 'where each application form stands after filling'),
    'materials':    ('engine.materials', False, 'proposed bullets, bios, summaries and template versions'),
    'check-text':   ('engine.checktext', False, 'check a follow-up, thank-you or other draft against your facts'),
    'reply':        ('engine.agent_reply', False, "save a helper agent's JSON reply from its output file"),
    'answers':      ('engine.stages', True, 'application stage: form answers'),
    'specs':        ('engine.stages', True, 'application stage: resume specs'),
    'tailor':       ('engine.stages', True, 'application stage: build tailored resumes'),
    'notes':        ('engine.stages', True, 'application stage: application notes'),
    'manual-notes': ('engine.stages', True, 'application stage: notes for hand-applied roles'),
    'fillplan':     ('engine.stages', True, 'application stage: form-fill plan'),
}


def usage():
    w = max(map(len, COMMANDS))
    lines = ['get-me-hired: gmh <command> [args]   (gmh <command> --help for details)', '']
    lines += [f'  {name.ljust(w)}  {help_}' for name, (_, _, help_) in COMMANDS.items()]
    lines += ['', 'The workspace comes from --workspace or $GMH_WORKSPACE where a command needs one.']
    return '\n'.join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"gmh: unknown command '{cmd}' (try gmh --help)", file=sys.stderr)
        return 2
    mod, pass_name, _ = COMMANDS[cmd]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    if importlib.util.find_spec(mod) is None:
        print(f"gmh: '{cmd}' is not available in this version", file=sys.stderr)
        return 2
    sys.argv = [mod] + ([cmd] if pass_name else []) + rest
    runpy.run_module(mod, run_name='__main__', alter_sys=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
