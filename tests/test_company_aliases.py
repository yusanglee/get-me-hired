"""Company aliases in the applied-check and dedup: one employer hiring under several names (a parent and its
brands). Fictional companies only: Northwind (parent), Tailspin and Northwind Pay (its brands), Brightwater."""
import csv, os, shutil, tempfile, unittest

from engine import runrecord, tracker, triage
from engine.job_key import alias_keys, company_names, make_key

GROUPS = [['Northwind', 'Tailspin', 'Northwind Pay']]
TITLE = 'Staff Product Manager, Post-Checkout Experience'
DATE = '2026-11-10'


class Names(unittest.TestCase):
    def test_parenthetical_and_groups(self):
        self.assertEqual(company_names('Northwind (Tailspin)'), {'northwind', 'tailspin'})
        self.assertEqual(company_names('Northwind Pay', GROUPS), {'northwind', 'tailspin', 'northwind-pay'})
        self.assertEqual(company_names('Brightwater', GROUPS), {'brightwater'})

    def test_keys_include_the_plain_key(self):
        self.assertIn(make_key('Northwind (Tailspin)', TITLE), alias_keys('Northwind (Tailspin)', TITLE))
        self.assertIn(make_key('Tailspin', TITLE), alias_keys('Northwind (Tailspin)', TITLE))


class AppliedCheck(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws)
        rows = []
        tracker.upsert(rows, {'company': 'Northwind (Tailspin)', 'title': TITLE, 'id': 'gh-northwind-5001',
                              'date_applied': '2026-10-19', 'status': 'applied'})
        tracker.write(tracker.path_of(self.ws), rows)
        self.queue = os.path.join(self.ws, 'queue')
        os.makedirs(self.queue)
        with open(os.path.join(self.queue, f'reviewed-{DATE}.csv'), 'w', encoding='utf-8', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['id', 'company', 'title', 'call'])
            w.writerow(['bi-7001', 'Northwind Pay', TITLE, 'apply'])        # sibling brand, same job
            w.writerow(['li-7002', 'Tailspin', TITLE, 'apply'])             # the name in parentheses
            w.writerow(['gh-brightwater-7003', 'Brightwater', TITLE, 'apply'])  # another employer, same title
            w.writerow(['bi-7004', 'Northwind Pay', 'Senior Product Manager, Payouts', 'apply'])  # sibling, other job

    def hits(self, aliases):
        return [r['id'] for r in runrecord.queued_applied(self.queue, DATE, tracker.known_keys(self.ws, (), aliases))]

    def test_alias_group_catches_the_sibling_brand(self):
        self.assertEqual(self.hits(GROUPS), ['bi-7001', 'li-7002'])

    def test_without_a_group_only_the_parenthetical_matches(self):
        self.assertEqual(self.hits(()), ['li-7002'])

    def test_already_applied_by_the_role_own_parenthetical(self):
        index = tracker.known_keys(self.ws, (), ())
        self.assertTrue(triage.already_applied('Tailspin (Northwind)', TITLE, 'x', index))
        self.assertFalse(triage.already_applied('Brightwater', TITLE, 'x', index))


if __name__ == '__main__':
    unittest.main()
