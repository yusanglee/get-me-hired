"""The tracker dashboard (engine/dashboard.py): data embedding, escaping, empty trackers, computed flags."""
import json, os, re, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import dashboard, tracker


def row(**kw):
    base = {'date_applied': '2026-03-02', 'company': 'Brightwater', 'title': 'Senior Product Manager, Payments',
            'location': 'LA; NYC · Hybrid', 'id': 'gh-brightwater-1', 'status': 'applied', 'status_date': '2026-03-02',
            'source': 'pipeline', 'url': 'https://example.com/jobs/1', 'folder': ''}
    return {**base, **kw}


def embedded(page):
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    return json.loads(m.group(1))


class Dashboard(unittest.TestCase):
    def test_rows_are_embedded_with_fit_and_flags(self):
        rows = [row(), row(company='Cobalt Farms', title='Staff PM', id='gh-cobalt-2', status='interviewing',
                           status_date='2026-03-20', linkedin_interest='done 2026-03-03',
                           linkedin_connect='2026-03-03 sent: Ana Ruiz (u); 2026-03-04 sent: Sam Lee (u)')]
        page = dashboard.render(rows, today='2026-05-10', fits={'gh-brightwater-1': (82, 'A')})
        data = embedded(page)
        self.assertEqual(data['today'], '2026-05-10')
        a, b = data['rows']
        self.assertEqual((a['c'], a['l'], a['fit'], a['tier']), ('Brightwater', 'LA; NYC · Hybrid', 82, 'A'))
        self.assertTrue(a['stale'] and a['due'])          # 69 quiet days at applied
        self.assertFalse(b['stale'])                      # interviewing is never stale
        self.assertEqual((b['li'], b['lic'], b['fit']), ('done', 2, None))
        self.assertNotIn('http', page.split('<script type="application/json"')[0].split('</style>')[0])  # no CDN

    def test_markup_in_tracker_text_stays_text(self):
        evil = '</script><img src=x onerror=alert(1)> & "Co"'
        page = dashboard.render([row(company=evil, title='<b>PM</b>', notes='a b',
                                     url='javascript:alert(1)')], today='2026-03-03')
        self.assertNotIn('</script><img', page)
        self.assertNotIn('<b>PM</b>', page)
        data = embedded(page)
        self.assertEqual(data['rows'][0]['c'], evil)       # the text survives, as text
        self.assertEqual(data['rows'][0]['u'], '')         # only http(s) links become links
        self.assertIn('textContent', page)

    def test_empty_tracker(self):
        page = dashboard.render([], today='2026-03-03')
        self.assertEqual(embedded(page)['rows'], [])
        self.assertIn('No applications yet', page)

    def test_report_writes_the_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, 'Workflow', '03-Applied', 'Brightwater PM')
            os.makedirs(folder)
            out = tracker.report([row(folder='Workflow/03-Applied/Brightwater PM')], os.path.join(d, 'report.html'),
                                 vault=d, today='2026-03-03')
            data = embedded(open(out, encoding='utf-8').read())
            self.assertTrue(data['rows'][0]['f'].startswith('file://') and data['rows'][0]['f'].endswith('Brightwater%20PM'))

    def test_scores_prefer_scored_then_reviewed(self):
        with tempfile.TemporaryDirectory() as d:
            q = os.path.join(d, 'Pipeline', 'queue')
            os.makedirs(q)
            with open(os.path.join(q, 'scored-2026-03-01.csv'), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('tier,fit,id\nA,82,gh-a-1\n')
            with open(os.path.join(q, 'reviewed-2026-03-01.csv'), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('call,fit,id\napply,85,gh-b-2\napply,10,gh-a-1\n')
            self.assertEqual(dashboard.scores(d), {'gh-a-1': (82, 'A'), 'gh-b-2': (85, '')})


if __name__ == '__main__':
    unittest.main()
