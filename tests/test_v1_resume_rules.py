"""E7: the v1 resume layout rules (config resume.*, each off when its key is missing), the fixed page-break check,
and the education line in tools/resume.js. All fixtures are fictional (tests/fixtures/resume_rules)."""
import json, os, re, shutil, subprocess, tempfile, unittest, zipfile

from engine import design, resume
from engine.verify import layout_rule_failures, paragraph_lines

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, 'fixtures', 'resume_rules')
NODE = resume.node_modules()
HAVE_NODE = shutil.which('node') and os.path.isdir(os.path.join(NODE, 'docx'))


def txt(name):
    return open(os.path.join(FIX, name), encoding='utf-8').read()


DOC = {
    'summary': 'Product leader who grew Brightwater to 700 sites and led consumer growth work across marketplaces and subscriptions.',
    'skills': 'Roadmapping  |  SQL  |  Experimentation  |  Pricing  |  Retention  |  Mobile Apps  |  Stakeholder Management',
    'experience': [
        {'id': 'bright', 'role': 'Senior Product Manager', 'company': 'Brightwater', 'scope':
         'Consumer marketplace for local services across four product teams and two mobile platforms.',
         'bullets': ['Grew repeat bookings by 40% through a new onboarding flow and a faster checkout.',
                     'Launched pricing tests across 12 markets.']},
        {'id': 'harbor', 'role': 'Product Manager', 'company': 'Harbor Labs', 'scope': '',
         'bullets': ['Shipped a loyalty program that lifted retention.',
                     'Ran the quarterly roadmap with design and engineering partners across the whole company.']},
        {'id': 'north', 'role': 'Associate Product Manager', 'company': 'Northwind', 'scope': '',
         'bullets': ['Owned the support tooling backlog.']},
    ],
}


class PageBreaks(unittest.TestCase):
    def pages(self, p2):
        return [txt('page1.txt'), txt(p2)]

    def test_summary_naming_the_company_is_not_a_false_positive(self):
        # the summary names Brightwater; the rule says Northwind-side role 3 starts page 2 and role 2 ends page 1
        rules = {'pages': 2, 'last_on_page_1': 'harbor', 'first_on_page_2': 'north'}
        self.assertEqual(resume.page_break_failures(self.pages('page2_good.txt'), DOC, rules), [])
        # old behaviour: a summary-only mention counted as "on page 1"
        rules = {'first_on_page_2': 'bright'}
        p1 = txt('page1.txt').replace('Brightwater  ·  Chicago, IL', 'Other Co  ·  Chicago, IL').replace('Senior Product Manager', 'Lead')
        p2 = 'Senior Product Manager        Jan 2022 - Present\nBrightwater  ·  Chicago, IL\n'
        self.assertEqual(resume.page_break_failures([p1, p2], DOC, rules), [])

    def test_company_inside_experience_on_page_1_still_fails(self):
        fails = resume.page_break_failures(self.pages('page2_good.txt'), DOC, {'first_on_page_2': 'bright'})
        self.assertTrue(any('top of page 2' in f for f in fails))

    def test_first_on_page_2_must_be_the_role_line(self):
        rules = {'first_on_page_2': 'north'}
        self.assertEqual(resume.page_break_failures(self.pages('page2_good.txt'), DOC, rules), [])
        fails = resume.page_break_failures(self.pages('page2_orphan.txt'), DOC, rules)
        self.assertTrue(any('not the Northwind role line' in f for f in fails), fails)

    def test_no_page_starts_with_a_carried_over_bullet(self):
        rules = {'pages': 2}
        self.assertEqual(resume.page_break_failures(self.pages('page2_good.txt'), DOC, rules), [])
        for name in ('page2_orphan.txt', 'page2_bullet.txt'):
            fails = resume.page_break_failures(self.pages(name), DOC, rules)
            self.assertTrue(any('carried-over bullet' in f for f in fails), (name, fails))
        # same with max_pages alone, and off for a one-page resume
        self.assertTrue(resume.page_break_failures(self.pages('page2_bullet.txt'), DOC, {'max_pages': 2}))
        self.assertEqual(resume.page_break_failures([txt('page1.txt')], DOC, {'pages': 1}), [])
        self.assertEqual(resume.page_break_failures(self.pages('page2_bullet.txt'), DOC, {}), [])

    def test_max_pages(self):
        three = self.pages('page2_good.txt') + ['SKILLS\nmore\n']
        self.assertEqual(resume.page_break_failures(three[:2], DOC, {'max_pages': 2}), [])
        self.assertEqual(resume.page_break_failures(three, DOC, {'max_pages': 2}), ['3 pages (max 2)'])
        self.assertEqual(resume.page_break_failures(three, DOC, {'pages': 2}), ['3 pages (want 2)'])


class LayoutRules(unittest.TestCase):
    lines = (txt('page1.txt') + '\n' + txt('page2_good.txt')).splitlines()

    def run_rules(self, rules, doc=DOC):
        return layout_rule_failures(self.lines, doc, rules)

    def test_off_without_keys(self):
        self.assertEqual(self.run_rules({}), ([], []))
        self.assertEqual(self.run_rules({'max_bullet_lines': 2, 'pages': 2}), ([], []))

    def test_paragraph_lines_finds_wrapped_text(self):
        got = paragraph_lines(self.lines, DOC['experience'][0]['bullets'][0])
        self.assertEqual(len(got), 2)
        self.assertEqual(got[-1], 'checkout.')
        self.assertIsNone(paragraph_lines(self.lines, 'Not in the resume at all.'))

    def test_scope_lines(self):
        self.assertEqual(self.run_rules({'max_scope_lines': 2}), ([], []))
        fails, _ = self.run_rules({'max_scope_lines': 1})
        self.assertEqual(len(fails), 1)
        self.assertIn('scope', fails[0])

    def test_runt_last_lines(self):
        fails, _ = self.run_rules({'min_last_line_words': 3})
        self.assertEqual(len(fails), 1)
        self.assertIn('4 paragraph(s)', fails[0])
        self.assertIn('bullet "Grew repeat bookings by 40% through" ends on "checkout."', fails[0])
        self.assertIn('scope "Consumer marketplace', fails[0])
        self.assertIn('skills "Roadmapping', fails[0])
        self.assertNotIn('Launched pricing', fails[0])        # one-line paragraphs are not wrapped
        fails, _ = self.run_rules({'min_last_line_words': 2})
        self.assertEqual(len(fails), 1)                       # only "checkout." is a single word
        self.assertIn('1 paragraph(s)', fails[0])

    def test_skills_lines(self):
        self.assertEqual(self.run_rules({'skills_lines': 2}), ([], []))
        fails, _ = self.run_rules({'skills_lines': 3})
        self.assertEqual(fails, ['skills are 2 lines (want 3)'])

    def test_unfound_paragraph_is_a_note_not_a_failure(self):
        doc = dict(DOC, summary='A summary that is not in this PDF text at all.')
        fails, notes = self.run_rules({'max_scope_lines': 2}, doc)
        self.assertEqual(fails, [])
        self.assertTrue(any('not found' in n for n in notes))

    def test_bold_marks_and_wide_characters_do_not_break_matching(self):
        doc = dict(DOC, summary='Product leader who grew **Brightwater** to 700 sites and led consumer growth work '
                                'across marketplaces and subscriptions.')
        self.assertEqual(self.run_rules({'max_scope_lines': 2}, doc), ([], []))


@unittest.skipUnless(HAVE_NODE, 'needs Node and the docx package (npm ci --prefix tools)')
class Builder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.payload = json.load(open(os.path.join(HERE, 'fixtures', 'design', 'resume_payload.json'), encoding='utf-8'))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, payload):
        src, out = os.path.join(self.tmp, 'in.json'), os.path.join(self.tmp, 'out.docx')
        json.dump(payload, open(src, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False)
        subprocess.run(['node', os.path.join(ROOT, 'tools', 'resume.js'), src, out], check=True, capture_output=True,
                       env=dict(os.environ, NODE_PATH=NODE))
        return zipfile.ZipFile(out).read('word/document.xml').decode('utf-8')

    def test_fitting_education_is_unchanged(self):
        golden = open(os.path.join(HERE, 'fixtures', 'design', 'resume_document.xml'), 'rb').read().decode('utf-8')
        self.assertEqual(self.build(self.payload), golden)

    def test_long_education_goes_on_two_lines(self):
        long = {'school': 'The Very Long Named Institute of Technology and Applied Sciences',
                'degree': 'Master of Science, Management of Technology and Innovation (Product)', 'years': '2010 - 2014'}
        short = {'school': 'State University', 'degree': 'B.A., Economics', 'years': '2008 - 2010'}
        xml = self.build(dict(self.payload, education=[long, short]))
        edu = xml[xml.index('EDUCATION'):]
        paras = [p for p in re.findall(r'<w:p>.*?</w:p>', edu, re.S)[0:3]]   # long = 2 paragraphs, short = 1
        self.assertEqual(len(re.findall(r'State University', edu)), 1)
        self.assertIn(long['school'], paras[0])
        self.assertIn('2010 - 2014', paras[0])
        self.assertNotIn(long['degree'], paras[0])
        self.assertIn(long['degree'], paras[1])
        self.assertNotIn('<w:tab/>', paras[1])
        self.assertIn('State University', paras[2])
        self.assertIn('B.A., Economics', paras[2])           # short entry keeps its one line

    def test_inline_dates_never_split(self):
        t = design.load_design()
        t['dates']['align'] = 'inline'
        long = {'school': 'The Very Long Named Institute of Technology and Applied Sciences',
                'degree': 'Master of Science, Management of Technology and Innovation (Product)', 'years': '2010 - 2014'}
        xml = self.build(dict(self.payload, education=[long], design=t))
        edu = xml[xml.index('EDUCATION'):]
        self.assertEqual(len(re.findall(r'Institute of Technology', edu)), 1)
        self.assertIn('Institute of Technology and Applied Sciences</w:t>', edu)

    def test_body_paragraphs_are_never_justified(self):
        xml = self.build(self.payload)
        self.assertNotRegex(xml, r'<w:jc w:val="(both|distribute|justify|thaiDistribute)"')
        for m in re.finditer(r'<w:jc w:val="(\w+)"', xml):
            self.assertEqual(m.group(1), 'center')           # only the name, bio and contact lines are centred
        self.assertNotIn('w:jc', re.search(r'EXECUTIVE SUMMARY.*', xml, re.S).group(0))


if __name__ == '__main__':
    unittest.main()
