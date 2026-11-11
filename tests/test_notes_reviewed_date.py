"""gmh notes reads the reviewed CSV of the drafts file's day, so a queue spanning two days refreshes the older
day's notes with that day's drafts (it read only the latest reviewed CSV before). --date overrides."""
import os, tempfile, unittest
from types import SimpleNamespace

from engine import stages


class ReviewedPath(unittest.TestCase):
    def setUp(self):
        self.P = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.P, 'queue'))
        for d in ('2026-01-05', '2026-01-06'):
            open(os.path.join(self.P, 'queue', f'reviewed-{d}.csv'), 'w', encoding='utf-8', newline='\n').write('id,call\n')
        self.ctx = SimpleNamespace(P=self.P, latest=stages.Ctx.latest.__get__(SimpleNamespace(P=self.P)))

    def name(self, d):
        return os.path.join(self.P, 'queue', f'reviewed-{d}.csv')

    def test_latest_by_default(self):
        self.assertEqual(stages.reviewed_path(self.ctx), self.name('2026-01-06'))
        self.assertEqual(stages.reviewed_path(self.ctx, drafts_path='/d/my-drafts.json'), self.name('2026-01-06'))

    def test_drafts_file_day(self):
        self.assertEqual(stages.reviewed_path(self.ctx, drafts_path='/d/drafts-2026-01-05.json'), self.name('2026-01-05'))
        # a drafts day with no reviewed CSV falls back to the latest
        self.assertEqual(stages.reviewed_path(self.ctx, drafts_path='/d/drafts-2026-01-02.json'), self.name('2026-01-06'))

    def test_date_wins_and_must_exist(self):
        self.assertEqual(stages.reviewed_path(self.ctx, '2026-01-05', '/d/drafts-2026-01-06.json'), self.name('2026-01-05'))
        with self.assertRaises(SystemExit):
            stages.reviewed_path(self.ctx, '2026-01-01')


if __name__ == '__main__':
    unittest.main()
