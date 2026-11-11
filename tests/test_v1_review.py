"""v1.0 E3: `gmh review reads --briefs`, `--apply` with several files, `gmh fills show` as a table, and the
cross-platform opener. Fictional fixture run from test_discover_score; no network."""
import csv, json, os, sys, unittest
from io import StringIO
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from engine import fills, runrecord  # noqa: E402
import test_reads as TRD  # noqa: E402

DATE = TRD.DATE


class ReadsBriefsTest(TRD.ReadsBase):
    def test_briefs_split_by_per_and_are_self_contained(self):
        out = self.cli('reads', '--briefs', '--per', '1')
        paths = out.split()
        self.assertEqual(len(paths), 2)
        for p in paths:
            self.assertTrue(os.path.isabs(p) and os.path.exists(p))
            self.assertIn(os.path.join('scratch', DATE, 'reads-brief-'), p)
        b = [json.load(open(p, encoding='utf-8')) for p in paths]
        self.assertEqual([len(x['roles']) for x in b], [1, 1])
        self.assertEqual(sorted(x['roles'][0]['id'] for x in b), ['gh-acme-1', 'hm-initech-cos'])
        self.assertTrue(b[0]['resume_path'].endswith('master-resume.md') and os.path.exists(b[0]['resume_path']))
        self.assertTrue(b[0]['roles'][0]['jd'].endswith('.txt'))
        self.assertIn('"rows"', b[0]['reply_format'])
        self.assertIn('reads-reply-', b[0]['reply_path'])

    def test_default_per_puts_all_in_one_and_nothing_to_do_fails(self):
        paths = self.cli('reads', '--briefs').split()
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(json.load(open(paths[0], encoding='utf-8'))['roles']), 2)
        self.cache(TRD.row('gh-acme-1'), TRD.row('hm-initech-cos'))
        self.assertIn('no briefs written', self.cli('reads', '--briefs'))

    def test_ids_and_json(self):
        out = json.loads(self.cli('reads', '--briefs', '--ids', 'gh-acme-1', '--json'))
        self.assertEqual(len(out), 1)
        self.assertEqual([r['id'] for r in json.load(open(out[0], encoding='utf-8'))['roles']], ['gh-acme-1'])

    def test_existing_listing_unchanged(self):
        self.assertIn('gh-acme-1  Acme Robotics: ', self.cli('reads'))


class ApplyManyTest(TRD.ReadsBase):
    def setUp(self):
        super().setUp()
        self.score()

    def reply(self, name, *rows):
        p = os.path.join(self.ws, name)
        json.dump(dict(rows=list(rows)), open(p, 'w', encoding='utf-8', newline='\n'))
        return p

    def test_two_files_one_summary(self):
        a = self.reply('a.json', TRD.row('gh-acme-1'))
        b = self.reply('b.json', TRD.row('hm-initech-cos'))
        out = self.cli('reads', '--apply', a, b)
        self.assertIn('Cached 2 read(s)', out)
        self.assertEqual(out.count('Cached'), 1)
        self.assertEqual(self.cli('reads', '--json') and json.loads(self.cli('reads', '--json'))['roles'], [])

    def test_one_bad_file_saves_nothing(self):
        a = self.reply('a.json', TRD.row('gh-acme-1'))
        b = self.reply('b.json', TRD.row('gh-gone-9'))
        out = self.cli('reads', '--apply', a, b)
        self.assertIn('gh-gone-9', out)
        self.assertEqual(len(json.loads(self.cli('reads', '--json'))['roles']), 2)

    def test_same_role_in_two_files_is_refused(self):
        a = self.reply('a.json', TRD.row('gh-acme-1'))
        b = self.reply('b.json', TRD.row('gh-acme-1'))
        self.assertIn('is in both', self.cli('reads', '--apply', a, b))
        self.assertEqual(len(json.loads(self.cli('reads', '--json'))['roles']), 2)

    def test_single_file_still_works(self):
        self.assertIn('Cached 1 read(s)', self.cli('reads', '--apply', self.reply('a.json', TRD.row('gh-acme-1'))))


class FillsShowTest(TRD.ReadsBase):
    def show(self, *args):
        with mock.patch('sys.stdout', new=StringIO()) as so:
            fills.main([*args, '--workspace', self.ws])
        return so.getvalue()

    def test_table_has_company_title_status_and_left(self):
        self.score()
        rid = 'gh-acme-1'
        with open(os.path.join(self.ctx.queue, f'reviewed-{DATE}.csv'), 'w', encoding='utf-8', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['id', 'company', 'title'])
            w.writeheader()
            w.writerow(dict(id=rid, company='Acme Robotics', title='Chief of Staff'))
        fills.record(self.ws, rid, 'needs_user', ['captcha', 'upload cover'])
        fills.record(self.ws, 'gh-other-2', 'ready')
        lines = self.show('show', '--date', DATE).splitlines()
        self.assertEqual(lines[0], 'id | company | title | status | left')
        self.assertIn('gh-acme-1 | Acme Robotics | Chief of Staff | needs_user | captcha; upload cover', lines)
        self.assertIn('gh-other-2 |  |  | ready | ', lines)
        only = self.show('show', 'gh-acme-1', 'gh-nope-3').splitlines()
        self.assertEqual(len(only), 3)
        self.assertTrue(only[2].startswith('gh-nope-3 |') and 'no record' in only[2])

    def test_json_and_empty(self):
        self.assertIn('No fill records yet', self.show('show'))
        fills.record(self.ws, 'gh-x-1', 'blocked', note='needs an account')
        data = json.loads(self.show('show', '--json'))
        self.assertEqual((data[0]['id'], data[0]['status'], data[0]['left']), ('gh-x-1', 'blocked', 'needs an account'))


class OpenFileTest(unittest.TestCase):
    def test_per_platform(self):
        with mock.patch('sys.platform', 'darwin'), mock.patch('subprocess.run') as run:
            runrecord.open_file('/x/p.html')
        run.assert_called_once_with(['open', '/x/p.html'], check=False)
        with mock.patch('sys.platform', 'win32'), mock.patch.object(os, 'startfile', create=True) as sf:
            runrecord.open_file('C:\\x\\p.html')
        sf.assert_called_once_with('C:\\x\\p.html')
        with mock.patch('sys.platform', 'linux'), mock.patch('webbrowser.open') as wb:
            runrecord.open_file('/x/p.html')
        wb.assert_called_once_with('file:///x/p.html')


if __name__ == '__main__':
    unittest.main()
