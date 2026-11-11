"""gmh manual-notes builds the cover letter for a hand-applied role whenever the drafts file holds an approved cover
for its slug (Nov 4: approved covers for manual roles had no file; only form roles got one from gmh notes)."""
import csv, datetime, json, os, tempfile, unittest
from types import SimpleNamespace
from unittest import mock

from engine import stages

FIELDS = ['id', 'call', 'company', 'title', 'url', 'salary_max', 'locations', 'notes', 'top_gap']


class Prof(dict):
    def get(self, k, d=None):
        return super().get(k, d)

    def require(self, k):
        return self[k]


class ManualNotesCover(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.P = os.path.join(self.ws, 'Pipeline')
        self.ready = os.path.join(self.ws, 'Workflow', 'ready')
        for d in ('queue', 'specs', 'state/jd', 'drafts'):
            os.makedirs(os.path.join(self.P, d))
        open(os.path.join(self.P, 'state', 'applied.csv'), 'w', encoding='utf-8', newline='\n').write('id\n')
        rows = [('r1', 'manual', 'Brightwater', 'Senior PM', 'https://example.com/brightwater'),
                ('r2', 'manual', 'Northwind', 'Staff PM', 'https://example.com/northwind'),
                ('r3', 'apply', 'Lumen', 'PM', 'https://example.com/lumen')]
        with open(os.path.join(self.P, 'queue', 'reviewed-2026-01-05.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            for rid, call, co, title, url in rows:
                w.writerow(dict(id=rid, call=call, company=co, title=title, url=url, salary_max='',
                                locations='Remote', notes='LinkedIn posting', top_gap='none'))
                slug = co.lower()
                json.dump(dict(id=rid, slug=slug, company=co, folder=slug),
                          open(os.path.join(self.P, 'specs', f'{slug}.json'), 'w', encoding='utf-8', newline='\n'))
                os.makedirs(os.path.join(self.ready, slug))
                open(os.path.join(self.P, 'state', 'jd', f'{rid}.txt'), 'w', encoding='utf-8', newline='\n').write('A role.')
        self.ctx = SimpleNamespace(
            P=self.P, ws=self.ws, vault=self.ws, ready=self.ready, cfg={}, today=datetime.date(2026, 1, 5),
            prof=Prof({'identity.first_name': 'Jordan', 'identity.last_name': 'Rivera', 'salary.floor': 150000}),
            answerer=lambda: SimpleNamespace(tokens=lambda: {'home': 'Springfield'}),
            latest=stages.Ctx.latest.__get__(SimpleNamespace(P=self.P)))
        self.built = []

    def fake_cover(self, ctx, company, date, paragraphs, folder, slug):
        self.built.append((company, slug, paragraphs, folder))
        return os.path.join(folder, f'Jordan_Rivera_Cover_Letter_{slug}.pdf')

    def drafts(self, day, data):
        p = os.path.join(self.P, 'drafts', f'drafts-{day}.json')
        json.dump(data, open(p, 'w', encoding='utf-8', newline='\n'))
        return p

    def run_stage(self, **kw):
        with mock.patch.object(stages, '_cover', self.fake_cover), \
             mock.patch.object(stages, 'standard_answers', lambda ctx: [('Email', 'jordan@example.com')]), \
             mock.patch('engine.setup.tools_problems', lambda cfg, ws: []):
            stages.stage_manual_notes(self.ctx, **kw)

    def notes(self, slug):
        return open(os.path.join(self.ready, slug, 'application-notes.md'), encoding='utf-8').read()

    def test_approved_cover_becomes_a_document_and_is_named_in_the_notes(self):
        self.drafts('2026-01-05', {'brightwater': {'cover': ['Dear Brightwater team,', 'Thank you.']},
                                   'lumen': {'cover': ['Not a manual role.']}})
        self.run_stage()
        self.assertEqual([(c, s) for c, s, _, _ in self.built], [('Brightwater', 'brightwater')])
        self.assertEqual(self.built[0][2], ['Dear Brightwater team,', 'Thank you.'])
        self.assertEqual(self.built[0][3], os.path.join(self.ready, 'brightwater'))
        md = self.notes('brightwater')
        self.assertIn('**Cover letter:** Jordan_Rivera_Cover_Letter_brightwater.pdf', md)
        self.assertNotIn('none prepared', md)
        self.assertIn('## Cover letter text', md)
        self.assertIn('Dear Brightwater team,', md)
        # no draft for this manual role: unchanged wording, nothing built
        self.assertIn('none prepared', self.notes('northwind'))
        self.assertFalse(os.path.exists(os.path.join(self.ready, 'lumen', 'application-notes.md')))

    def test_cover_found_in_another_days_drafts_file(self):
        self.drafts('2026-01-04', {'northwind': {'cover': ['Older draft.']}})
        self.drafts('2026-01-05', {'brightwater': {'answers': {'Why us?': 'Because.'}}})
        self.run_stage()
        self.assertEqual([s for _, s, _, _ in self.built], ['northwind'])
        self.assertIn('none prepared', self.notes('brightwater'))

    def test_reviewed_day_wins_over_a_newer_file(self):
        self.drafts('2026-01-05', {'brightwater': {'cover': ['Same day.']}})
        self.drafts('2026-01-06', {'brightwater': {'cover': ['Next day.']}})
        self.run_stage(date='2026-01-05')
        self.assertEqual(self.built[0][2], ['Same day.'])

    def test_manual_drafts_file_and_no_pre_review_backup(self):
        self.drafts('2026-01-05', {'northwind': {'cover': ['Main file.']}})
        self.drafts('manual-2026-01-05', {'northwind': {'cover': ['Manual file.']}})
        self.drafts('2026-01-05.pre-review', {'brightwater': {'cover': ['Before review.']}})
        self.run_stage()
        self.assertEqual([(s, para) for _, s, para, _ in self.built], [('northwind', ['Manual file.'])])
        self.assertIn('none prepared', self.notes('brightwater'))

    def test_explicit_drafts_path(self):
        p = self.drafts('2026-01-05', {'northwind': {'cover': ['Given file.']}})
        self.drafts('2026-01-04', {'brightwater': {'cover': ['Ignored.']}})
        self.run_stage(drafts_path=p)
        self.assertEqual([(s, para) for _, s, para, _ in self.built], [('northwind', ['Given file.'])])

    def test_missing_tools_stop_before_writing(self):
        self.drafts('2026-01-05', {'brightwater': {'cover': ['Dear Brightwater team,']}})
        with mock.patch.object(stages, '_cover', self.fake_cover), \
             mock.patch.object(stages, 'standard_answers', lambda ctx: []), \
             mock.patch('engine.setup.tools_problems', lambda cfg, ws: ['node not found']):
            with self.assertRaises(SystemExit) as e:
                stages.stage_manual_notes(self.ctx)
        self.assertIn('node not found', str(e.exception))
        self.assertEqual(self.built, [])
        self.assertFalse(os.path.exists(os.path.join(self.ready, 'northwind', 'application-notes.md')))


if __name__ == '__main__':
    unittest.main()
