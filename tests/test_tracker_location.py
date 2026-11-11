"""Tracker location column: one short form for where a role is based (engine/locfmt.py)."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import tracker
from engine.locfmt import format_location, role_location


class FormatLocation(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(format_location('San Francisco, CA; Seattle, WA; New York, NY'), 'SF; Seattle; NYC')
        self.assertEqual(format_location('Remote - United States'), 'Remote (US)')
        self.assertEqual(format_location('United States', remote=True), 'Remote (US)')
        self.assertEqual(format_location('New York / Remote'), 'NYC · Remote')
        self.assertEqual(format_location('Los Angeles, CA', hint='LA (hybrid Tue/Thu)'), 'LA · Hybrid')
        self.assertEqual(format_location('', hint='El Segundo, on-site'), 'El Segundo · On-site')
        self.assertEqual(format_location('', hint='SF/NYC/Seattle (25% in office)'), 'SF; NYC; Seattle · Hybrid')

    def test_unknown_stays_blank(self):
        self.assertEqual(format_location('source: "https://www.linkedin.com/jobs/view/1/"'), '')
        self.assertEqual(format_location('Springfield'), '')  # not a known city: blank, not a guess


class TrackerColumn(unittest.TestCase):
    def test_new_rows_and_backfill(self):
        with tempfile.TemporaryDirectory() as d:
            pipe = os.path.join(d, 'Pipeline')
            os.makedirs(os.path.join(pipe, 'state', 'jd'))
            with open(os.path.join(pipe, 'state', 'jd', 'gh-acme-1.txt'), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('Staff PM\nAcme\nLos Angeles, CA; Remote\nhttps://x\n\nBody')
            self.assertEqual(role_location(pipe, 'gh-acme-1', {}), 'LA · Remote')
            rows = [{'company': 'Acme', 'title': 'Staff PM', 'id': 'gh-acme-1'},
                    {'company': 'Brightwater', 'title': 'PM', 'id': ''}]
            hints = os.path.join(d, 'hints.csv')
            with open(hints, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write('company,title,location\nBrightwater,PM,"Chicago, hybrid"\n')
            filled, missing = tracker.fill_locations(rows, pipe, hints)
            self.assertEqual([r['location'] for r in rows], ['LA · Remote', 'Chicago · Hybrid'])
            self.assertEqual(missing, [])
            self.assertIn('location', tracker.COLUMNS)


if __name__ == '__main__':
    unittest.main()
