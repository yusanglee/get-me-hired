"""Phase 7: new-user path fixes (record an application, reviewed CSV lookup, Node tools lookup) and a guard that
keeps the owner's personal data out of the repo. Fictional people and companies only."""
import re, csv, json, os, subprocess, sys, tempfile, shutil, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from engine import applied, resume, specs, tracker  # noqa: E402


class MarkApplied(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        json.dump({'paths': {'vault': self.ws}}, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))
        P = os.path.join(self.ws, 'Pipeline')
        for d in ('specs', 'queue'):
            os.makedirs(os.path.join(P, d))
        json.dump({'id': 'gh-brightwater-1', 'slug': 'Brightwater-CoS', 'company': 'Brightwater', 'title': 'Chief of Staff',
                   'folder': '2026-10-21 Brightwater - Chief of Staff'}, open(os.path.join(P, 'specs', 'Brightwater-CoS.json'), 'w', encoding='utf-8', newline='\n'))
        with open(os.path.join(P, 'queue', 'reviewed-2026-10-21.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['call', 'company', 'title', 'url', 'id'])
            w.writerow(['apply', 'Brightwater', 'Chief of Staff', 'https://job-boards.greenhouse.io/brightwater/jobs/1', 'gh-brightwater-1'])
        os.makedirs(os.path.join(self.ws, 'Workflow', '02-Ready to Apply', '2026-10-21 Brightwater - Chief of Staff'))

    def tearDown(self):
        shutil.rmtree(self.ws)

    def test_mark_moves_folder_and_writes_tracker_once(self):
        out = applied.mark(self.ws, ['gh-brightwater-1', 'gh-missing-9'], '2026-10-21')
        self.assertEqual(out, ['applied: Brightwater | Chief of Staff', 'gh-missing-9: no spec found (was it tailored?); nothing recorded'])
        self.assertTrue(os.path.isdir(os.path.join(self.ws, 'Workflow', '03-Applied', '2026-10-21 Brightwater - Chief of Staff')))
        rows = tracker.read(tracker.path_of(self.ws))
        self.assertEqual([(r['company'], r['status'], r['url'], r['folder']) for r in rows],
                         [('Brightwater', 'applied', 'https://job-boards.greenhouse.io/brightwater/jobs/1',
                           'Workflow/03-Applied/2026-10-21 Brightwater - Chief of Staff')])
        self.assertEqual(applied.mark(self.ws, ['gh-brightwater-1'], '2026-10-22'), ['already recorded: Brightwater | Chief of Staff'])
        self.assertEqual(len(tracker.read(tracker.path_of(self.ws))), 1)

    def test_queue_status_suggests_followup_only_when_the_day_is_done(self):
        P = os.path.join(self.ws, 'Pipeline')
        json.dump({'id': 'ab-corvid-2', 'slug': 'Corvid-PM', 'company': 'Corvid', 'title': 'Product Manager',
                   'folder': '2026-10-21 Corvid - PM'}, open(os.path.join(P, 'specs', 'Corvid-PM.json'), 'w', encoding='utf-8', newline='\n'))
        with open(os.path.join(P, 'queue', 'reviewed-2026-10-21.csv'), 'a', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['manual', 'Corvid', 'Product Manager', '', 'ab-corvid-2'])
            w.writerow(['pass', 'Larkspur', 'Senior PM', '', 'gh-larkspur-3'])  # passed roles don't hold the queue open
        applied.mark(self.ws, ['gh-brightwater-1'], '2026-10-21')
        self.assertEqual(applied.queue_status(self.ws, ['gh-brightwater-1']),
                         ['2026-10-21 queue: 1 of 2 marked applied, 1 to go. LinkedIn follow-up is suggested once all are in '
                          '(mark a closed or dropped role pass with gmh review picks).'])
        applied.mark(self.ws, ['ab-corvid-2'], '2026-10-21')
        self.assertTrue(applied.queue_status(self.ws, ['ab-corvid-2'])[0].startswith('All 2 roles queued on 2026-10-21 are marked applied.'))
        self.assertEqual(applied.queue_status(self.ws, ['gh-elsewhere-9']), [])  # not queued in any reviewed file: nothing to say


class NewUserPaths(unittest.TestCase):
    def test_node_modules_lookup(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, 'Pipeline', 'tools', 'node_modules', 'docx'))
            explicit = os.path.join(d, 'mine')
            os.makedirs(os.path.join(explicit, 'docx'))
            self.assertEqual(resume.node_modules({'paths': {'node_modules': explicit}}, d), explicit)
            got = resume.node_modules({}, d)
            self.assertIn(got, (resume.TOOLS_MODULES, os.path.join(d, 'Pipeline', 'tools', 'node_modules')))
            self.assertTrue(os.path.isdir(os.path.join(got, 'docx')))
        finally:
            shutil.rmtree(d)


# What dev/export-share leaves out; the scan of this repo itself skips the same paths.
NOT_SHIPPED = ['CLAUDE.md', 'dev', '.claude', 'workspace', 'docs/STATUS.md', 'docs/PLAN.md', 'docs/audits']


class NoPersonalDataInRepo(unittest.TestCase):
    """The shipped tree is free of the workspace owner's identity values, names and tracker companies. Runs
    dev/privacy_check.py where a private workspace exists (GMH_PRIVATE_WORKSPACE, else the one under workspace/).
    GMH_PRIVACY_REPO points it at another tree, e.g. a share export (dev/export-share runs the checker itself)."""

    def test_shipped_files(self):
        checker = os.path.join(REPO, 'dev', 'privacy_check.py')
        if not os.path.exists(checker):
            self.skipTest('dev/privacy_check.py is not part of the shared copy')
        sys.path.insert(0, HERE)
        from private_workspace import private_workspace
        ws = private_workspace()
        if not ws or not os.path.exists(os.path.join(ws, 'profile.yaml')):
            self.skipTest('no private workspace on this machine')
        root = os.environ.get('GMH_PRIVACY_REPO') or REPO
        cmd = [sys.executable, checker, root, '--workspace', ws]
        if root == REPO:
            # Only committed files can ship: skip local untracked and ignored files (fill plans, tool caches).
            local = subprocess.run(['git', '-C', REPO, 'ls-files', '--others', '--directory'], capture_output=True,
                                   text=True, encoding='utf-8').stdout.split('\n')
            for e in NOT_SHIPPED + [x for x in local if x.strip()]:
                cmd += ['--exclude', e]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(out.returncode, 0, 'personal data in shipped files (file:line:kind):\n' + out.stdout)


if __name__ == '__main__':
    unittest.main()
