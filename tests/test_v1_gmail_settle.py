"""gmh gmail settle: unsure mail is settled by a command (u<n> or a decisions file), never by hand-editing or ad-hoc
code on the proposed file. Fictional companies only."""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_v1_gmail import Base, run  # noqa: E402
from engine import gmail_import as gi  # noqa: E402


class SettleTest(Base):
    def proposed(self):
        prop = gi.propose(self.msgs, self.ws)
        path = os.path.join(self.tmp, 'proposed.json')
        gi._save(path, prop)
        return prop, path

    def test_table_numbers_unsure_mail(self):
        prop, _ = self.proposed()
        text = gi.table(prop)
        for i in range(1, len(prop['unsure']) + 1):
            self.assertIn(f'- u{i} ', text)
        self.assertIn('gmh gmail settle', text)

    def test_one_by_label_moves_it_into_the_table(self):
        prop, path = self.proposed()
        n = len(prop['unsure'])
        code, out, err = run('settle', path, 'u1', '--kind', 'rejection', '--company', 'Larkspur', '--role',
                             'Chief of Staff', '--workspace', self.ws)
        self.assertEqual(code, 0, err)
        after = gi._load(path)
        self.assertEqual(len(after['unsure']), n - 1)
        row = next(r for r in after['rows'] if r['company'] == 'Larkspur')
        self.assertEqual((row['title'], row['status']), ('Chief of Staff', 'rejected'))
        self.assertIn('Larkspur', out)

    def test_file_of_decisions_and_dismiss(self):
        prop, path = self.proposed()
        ids = [u['id'] for u in prop['unsure']]
        dec = self.write('dec.json', [{'u': 'u1', 'dismiss': True},
                                      {'u': ids[1], 'kind': 'interview', 'company': 'Corvid', 'role': 'Ops Lead'},
                                      {'u': 3, 'kind': 'other'}])
        code, out, err = run('settle', path, '--file', dec, '--workspace', self.ws)
        self.assertEqual(code, 0, err)
        after = gi._load(path)
        self.assertEqual(after['unsure'], [])
        self.assertEqual({d['id'] for d in after['dismissed']}, {ids[0], ids[2]})
        self.assertTrue(any(r['company'] == 'Corvid' and r['status'] == 'interviewing' for r in after['rows']))

    def test_any_problem_changes_nothing(self):
        prop, path = self.proposed()
        before = open(path, encoding='utf-8').read()
        dec = self.write('dec.json', [{'u': 'u1', 'kind': 'rejection', 'company': 'Larkspur'},
                                      {'u': 'u99', 'kind': 'rejection', 'company': 'X'},
                                      {'u': 'u2', 'kind': 'hired', 'company': 'Y'},
                                      {'u': 'u3', 'dismiss': True, 'kind': 'offer'}])
        code, _, err = run('settle', path, '--file', dec, '--workspace', self.ws)
        self.assertNotEqual(code, 0)
        for bit in ('u99', "unknown kind 'hired'", 'dismiss stands alone'):
            self.assertIn(bit, err)
        self.assertEqual(open(path, encoding='utf-8').read(), before)

    def test_a_status_needs_a_company(self):
        prop, path = self.proposed()
        blank = next((i for i, u in enumerate(prop['unsure'], 1) if not u.get('company')), None)
        if blank is None:
            prop['unsure'][0]['company'] = ''
            gi._save(path, prop)
            blank = 1
        code, _, err = run('settle', path, f'u{blank}', '--kind', 'rejection', '--workspace', self.ws)
        self.assertNotEqual(code, 0)
        self.assertIn('needs a company', err)

    def test_gmail_reference_uses_settle_not_hand_edits(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        text = open(os.path.join(root, 'references', 'gmail.md'), encoding='utf-8').read()
        self.assertIn('gmh gmail settle', text)
        self.assertNotIn('"decided": true', text)


if __name__ == '__main__':
    unittest.main()
