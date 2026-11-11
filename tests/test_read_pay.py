"""Pay from a posting read (reads.check_pay, score.read_pay): used only when the pay parser found no range, and
only when every figure can be found in the saved posting. Fictional fixture run from test_runrecord."""
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from engine import reads, runrecord, score  # noqa: E402
import test_reads as TRd  # noqa: E402

DATE = TRd.DATE
LINE = 'Salary band for this role: 150,000 – 170,000 per year, plus equity.'  # no $, so the parser misses it


def pay(lo=150000, hi=170000, cur='USD', quote='150,000 – 170,000 per year'):
    return dict(min=lo, max=hi, currency=cur, quote=quote)


class ReadPayTest(TRd.ReadsBase):
    def setUp(self):
        super().setUp()
        self.jd = os.path.join(self.ctx.state, 'jd', 'gh-acme-6.txt')
        with open(self.jd, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\n' + LINE + '\n')

    def read(self, p, rid='gh-acme-6'):
        return dict(TRd.row(rid), pay=p)

    def rejects(self, p, fragment):
        with self.assertRaises(reads.ReadError) as cm:
            reads.validate(dict(rows=[self.read(p)]), {'gh-acme-6'}, self.ctx.state)
        self.assertIn(fragment, str(cm.exception))

    def test_valid_pay_is_kept_and_cached(self):
        rows = reads.validate(dict(rows=[self.read(pay())]), {'gh-acme-6'}, self.ctx.state)
        self.assertEqual(rows[0]['pay'], pay())
        self.cache(self.read(pay()))
        self.assertEqual(reads.public(self.reader('gh-acme-6'))['pay']['max'], 170000)
        self.assertNotIn('pay', reads.validate(dict(rows=[self.read(None)]), {'gh-acme-6'}, self.ctx.state)[0])
        self.assertNotIn('pay', reads.validate(dict(rows=[TRd.row('gh-acme-6')]), {'gh-acme-6'}, self.ctx.state)[0])

    def test_pay_that_cannot_be_checked_is_rejected(self):
        self.rejects(pay(quote='$150,000 - $170,000'), 'not in the saved posting')
        self.rejects(pay(hi=175000, quote='150,000 – 170,000'), 'not a figure in the quote')
        self.rejects(pay(lo=140000), 'min 140,000 is not a figure in the posting')
        self.rejects(pay(cur='EUR'), "currency 'EUR'")
        self.rejects(pay(hi=17), 'annual figure')
        self.rejects(pay(lo=190000), 'up to the max')
        self.rejects(pay(quote=''), 'quote missing')
        self.rejects('150k', 'must be an object')

    def test_figures(self):
        self.assertEqual(reads.figures('US$ 111,974 to US$ 172,826.00 or $150K'), {111974, 172826, 150000})

    def test_score_drops_a_read_range_under_the_floor(self):
        self.assertIn('no posted range', self.score()['gh-acme-6']['flags'])
        self.cache(self.read(pay()))
        roles = self.score()
        self.assertNotIn('gh-acme-6', roles)
        d = next(d for d in runrecord.load(self.ctx.queue, DATE)['dropped'] if d['id'] == 'gh-acme-6')
        self.assertEqual((d['stage'], d['reason'], d['salary_max']), ('score', 'salary', 170000))
        self.assertIn('posting read', d['detail'])

    def test_score_keeps_a_read_range_over_the_floor(self):
        with open(self.jd, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('Senior level: 190,000 – 230,000.\n')
        self.cache(self.read(pay(lo=150000, hi=230000, quote='190,000 – 230,000')))
        r = self.score()['gh-acme-6']
        self.assertEqual((r['salary_min'], r['salary_max'], r['salary_source']), (150000, 230000, 'read'))
        self.assertNotIn('no posted range', r['flags'])

    def test_parser_range_wins(self):
        jd = os.path.join(self.ctx.state, 'jd', 'gh-acme-1.txt')
        with open(jd, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('\nOther band: 100,000 - 120,000\n')
        self.cache(self.read(pay(lo=100000, hi=120000, quote='100,000 - 120,000'), rid='gh-acme-1'))
        r = self.score()['gh-acme-1']
        self.assertEqual((r['salary_max'], r['salary_source']), (260000, 'jd_text'))

    def test_cad_read_with_no_cad_floor_is_kept(self):
        self.cache(self.read(pay(cur='CAD')))
        r = self.score()['gh-acme-6']
        self.assertEqual((r['salary_max'], r['salary_source']), (170000, 'read CAD'))

    def test_reviewed_row_takes_pay_only_when_empty(self):
        rd = dict(gap_type='none', top_gap='', pay=pay())
        row = dict(gap_type='', top_gap='', salary_max='')
        self.assertTrue(runrecord.gap_from_read(row, rd, only_empty=True))
        self.assertEqual(row['salary_max'], '170000')
        row = dict(gap_type='minor', top_gap='x', salary_max='200000')
        self.assertFalse(runrecord.gap_from_read(row, rd, only_empty=True))
        self.assertEqual(row['salary_max'], '200000')

    def test_page_marks_read_pay(self):
        page = open(os.path.join(os.path.dirname(HERE), 'engine', 'review_page.html'), encoding='utf-8').read()
        self.assertIn('(from the posting read)', page)


if __name__ == '__main__':
    unittest.main()
