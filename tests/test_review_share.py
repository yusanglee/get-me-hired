"""Sharing the review page: the standing Run Review artifact is created once and its link saved;
the page opens dark; the instructions never default to an external browser or the run JSON. Fictional workspace."""
import io, json, os, re, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from engine import runrecord, setup  # noqa: E402


class ArtifactUrl(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.join(tempfile.mkdtemp(prefix='gmh-share-'), 'Jordan Rivera search')
        self.addCleanup(shutil.rmtree, os.path.dirname(self.ws), True)
        setup.init(self.ws, name='Jordan Rivera')

    def cfg(self):
        with open(os.path.join(self.ws, 'config.json'), encoding='utf-8') as fh:
            return json.load(fh)

    def test_save_keeps_the_rest_of_config_and_validates(self):
        before = self.cfg()
        with self.assertRaises(runrecord.PickError):
            runrecord.save_artifact_url(self.ws, 'https://example.com/artifact/abc12345')
        self.assertEqual(runrecord.save_artifact_url(self.ws, 'https://claude.ai/code/artifact/0a1b2c3d-4e5f/'), '')
        after = self.cfg()
        self.assertEqual(after['review']['artifact_url'], 'https://claude.ai/code/artifact/0a1b2c3d-4e5f')
        after['review'].pop('artifact_url')
        if not after['review']:
            after.pop('review')
        before.get('review', {}).pop('artifact_url', None)
        if 'review' in before and not before['review']:
            before.pop('review')
        self.assertEqual(after, before)
        self.assertEqual(runrecord.save_artifact_url(self.ws, 'https://claude.ai/artifact/99999999'),
                         'https://claude.ai/code/artifact/0a1b2c3d-4e5f')

    def test_cli_without_runs(self):
        out = io.StringIO()
        with redirect_stdout(out):
            runrecord.main(['artifact-url', '--workspace', self.ws])
        self.assertIn('none yet', out.getvalue())


class Page(unittest.TestCase):
    def test_dark_by_default(self):
        with open(os.path.join(REPO, 'engine', 'review_page.html'), encoding='utf-8') as fh:
            html = fh.read()
        root = re.search(r':root \{(.*?)\}', html, re.S).group(1)
        self.assertIn('--bg: #11151d', root)
        self.assertIn('color-scheme: dark', root)
        self.assertIn(':root[data-theme="light"]', html)
        self.assertNotIn('prefers-color-scheme', html)

    def test_review_run_publishes_the_artifact_and_creates_it_once(self):
        with open(os.path.join(REPO, 'skills', 'review-run', 'references', 'review-page.md'), encoding='utf-8') as fh:
            t = fh.read()
        step = t[t.index('## Show the page'):t.index('## Confirm choices')]
        self.assertIn('gmh review artifact-url <link>', step)
        self.assertIn('never link or open `run-<date>.json`', step)
        self.assertIn('Only open it in the default browser', step)
        self.assertIn('"comments": {}', step)
        self.assertIn('Read the whole file before each publish', step)
        self.assertIn('Never give, open or link the local file instead, for any reason: not\nits size', step)
        self.assertIn('read it in parts', step)
        self.assertIn('Only in a tool with no artifact tool at all', step)
        with open(os.path.join(REPO, 'references', 'platforms.md'), encoding='utf-8') as fh:
            plat = fh.read()
        sec = plat[plat.index('## The review page'):plat.index('## Gmail')]
        self.assertIn('Never the local\n  file, whatever the page', sec)
        self.assertNotIn('Anywhere else', sec)


if __name__ == '__main__':
    unittest.main()
