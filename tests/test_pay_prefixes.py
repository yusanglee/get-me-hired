"""US currency prefixes on pay ranges (bug found Nov 11: 'US$ 111,974 to US$ 172,826' read as no range)."""
import unittest
from engine import pay

CA_CFG = {'locations': {'remote_countries': ['US', 'CA'], 'metros': []}, 'salary': {'floor_usd': 200000}}
US_CFG = {'locations': {'metros': []}, 'salary': {'floor_usd': 200000}}


class TestUsPrefixes(unittest.TestCase):
    PARSED = [
        ('Brightwater pays US$ 111,974 to US$ 172,826 per year.', 111974, 172826),
        ('Brightwater pays US$111,974 to US$172,826 per year.', 111974, 172826),
        ('Range: US $150,000 - US $180,000', 150000, 180000),
        ('Range: U.S. $150,000 to U.S. $190,000', 150000, 190000),
        ('Range: USD 150,000 - USD 200,000', 150000, 200000),
        ('Range: USD 150,000 – 200,000', 150000, 200000),
        ('Range: USD $150k to USD $180k', 150000, 180000),
        ('Range: $150K–$200K USD', 150000, 200000),
        ('Range: $150,000 - 200,000', 150000, 200000),
        ('Range: $111,974 to $172,826', 111974, 172826),
    ]

    def test_parsed_without_canada(self):
        for text, lo, hi in self.PARSED:
            self.assertEqual(pay.salary_full(text, cfg=US_CFG), (lo, hi, 'jd_text', 'USD'), text)
            self.assertEqual(pay.salary_full(text), (lo, hi, 'jd_text', 'USD'), text)

    def test_parsed_with_canada(self):
        for text, lo, hi in self.PARSED:
            self.assertEqual(pay.salary_full(text, hits=['Remote'], cfg=CA_CFG), (lo, hi, 'jd_text', 'USD'), text)

    def test_discover_lookup_regex_sees_prefixed_range(self):
        self.assertTrue(pay.PAIR_RE.search('US$111,974 to US$172,826'))

    def test_below_floor_after_fix(self):
        lo, hi, _, cur = pay.salary_full('US$ 111,974 to US$ 172,826', cfg=US_CFG)
        self.assertTrue(pay.below_floor(hi, cur, US_CFG))

    def test_not_a_range(self):
        for text in ['Brightwater has 150,000 - 200,000 users', '$150k and 200k users',
                     'Founded 2015, 150,000 users and 200,000 visits', 'Northwind: 150,000 - $200,000 in grants']:
            self.assertEqual(pay.salary_full(text, cfg=US_CFG)[:3], (None, None, 'none'), text)

    def test_cad_unchanged(self):
        full = lambda t, h=('Toronto',): pay.salary_full(t, hits=list(h), cfg=CA_CFG)
        self.assertEqual(full('CA$120,000 - CA$150,000'), (120000, 150000, 'jd_text', 'CAD'))
        self.assertEqual(full('CAD 120,000 - CAD 150,000'), (120000, 150000, 'jd_text', 'CAD'))
        self.assertEqual(full('CA$120,000 - 150,000'), (120000, 150000, 'jd_text', 'CAD'))
        self.assertEqual(full('$120k-$150k CAD', ('Remote',)), (120000, 150000, 'jd_text', 'CAD'))
        self.assertEqual(full('US$150,000 - US$180,000')[3], 'USD')


if __name__ == '__main__':
    unittest.main()
