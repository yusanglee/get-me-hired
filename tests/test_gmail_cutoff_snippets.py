"""Application mail whose snippet stops before the verdict goes to unsure, never dropped as 'other'."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import gmail_import as gi  # noqa: E402


def msg(mid, subject, sender, snippet, body=None):
    m = {'id': mid, 'thread_id': 't' + mid, 'subject': subject, 'sender': sender,
         'date': '2026-11-09T10:00:00Z', 'snippet': snippet}
    if body:
        m['body'] = body
    return m


OPEN_MOVE = msg('a1', 'Brightwater Staff Product Manager, Platform Application', 'Brightwater <no-reply@brightwater.example>',
                'Hi Jordan, Thank you for your interest in Brightwater and the time you spent applying. '
                "After reviewing your background, we've decided to move forward")
CUT_INTEREST = msg('a2', 'Thank You for Your Interest in Northwind', 'Northwind <no-reply@northwind.example>',
                   'Hi Jordan, Thank you for applying. We appreciate you considering us as a potential next step in your')
INTEREST_ROLE = msg('a3', 'Following up', 'Quarry Talent <talent@quarry.example>',
                    'Thanks for your interest in the Senior Product Manager role. We wanted to share an update.')
WORKDAY = msg('a4', 'Regarding Your Application with Pellucid Inc.', 'Pellucid <pellucid@myworkday.com>',
              'Dear Jordan, Thank you for the time you invested in the process.')


class CutOffSnippetTest(unittest.TestCase):
    def assertUnsure(self, m):
        c = gi.classify(m)
        self.assertEqual(c['confidence'], 'low', c)
        recs, _ = gi.records([m])
        self.assertEqual([r['id'] for r in recs], [m['id']])
        self.assertFalse(gi.settled(recs[0]))
        return c

    def test_open_move_forward_is_unsure(self):
        c = self.assertUnsure(OPEN_MOVE)
        self.assertIn('move forward', c['reason'])

    def test_snippet_cut_mid_sentence_is_unsure(self):
        self.assertUnsure(CUT_INTEREST)
        bare = dict(CUT_INTEREST, id='a5', snippet='Hi Jordan, We appreciate you considering us as a potential next step in your')
        self.assertIn('cut off', self.assertUnsure(bare)['reason'])

    def test_interest_in_role_is_unsure(self):
        self.assertUnsure(INTEREST_ROLE)

    def test_regarding_your_application_reads_as_status_update(self):
        c = self.assertUnsure(WORKDAY)
        self.assertIn('status update', c['reason'])

    def test_end_to_end_unsure_list(self):
        rows, unsure = gi.group(gi.records([OPEN_MOVE, CUT_INTEREST])[0], [])
        self.assertEqual(rows, [])
        self.assertEqual(sorted(u['id'] for u in unsure), ['a1', 'a2'])

    def test_object_after_move_forward_still_a_rejection(self):
        m = msg('b1', 'Your Brightwater application', 'Brightwater <no-reply@brightwater.example>',
                "We've decided to move forward with other candidates.")
        self.assertEqual(gi.classify(m)['kind'], 'rejection')

    def test_body_settles_it(self):
        m = msg('b2', 'Brightwater Product Manager Application', 'Brightwater <no-reply@brightwater.example>',
                "we've decided to move forward", body="we've decided to move forward with other candidates.")
        c = gi.classify(m)
        self.assertEqual((c['kind'], c['confidence']), ('rejection', 'high'))

    def test_unrelated_mail_still_dropped(self):
        for m in (msg('c1', 'Weekend sale', 'Shop <news@shop.example>', 'Our biggest sale of the season starts now and'),
                  msg('c2', 'Your mobile app update', 'Bank <no-reply@bank.example>', 'The new version of our app is ready.')):
            self.assertEqual(gi.classify(m)['confidence'], 'high', m['id'])
            self.assertEqual(gi.records([m])[0], [])

    def test_interest_subject_with_received_stays_a_confirmation(self):
        m = msg('c4', 'Thank you for your interest in Brightwater', 'Brightwater <no-reply@brightwater.example>',
                'Thank you for applying. We have received your application and our team will review it and')
        self.assertEqual(gi.classify(m)['confidence'], 'high')

    def test_confirmation_unchanged(self):
        m = msg('c3', 'Thank you for applying to Brightwater', 'Brightwater <no-reply@brightwater.example>',
                'We received your application for the Product Manager role and will review it and')
        self.assertEqual(gi.classify(m)['kind'], 'confirmation')


if __name__ == '__main__':
    unittest.main()
