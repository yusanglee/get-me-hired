"""resume.max_page1_free_pt holds only when the resume runs to a second page: a one-page resume may end wherever it
ends (found in the v1.0 smoke test: a short one-page resume failed the rule and fillplan refused it)."""
import os, sys, tempfile, unittest, zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import verify  # noqa: E402

DOC = {'experience': [], 'skills': '', 'summary': ''}


class PageOneFill(unittest.TestCase):
    def run_verify(self, pages, last_y):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, 'r.pdf')
            with zipfile.ZipFile(pdf[:-4] + '.docx', 'w') as z:
                z.writestr('word/document.xml', '<w:document/>')

            def fake_run(*a):
                if '-bbox' in a:
                    return f'<word yMin="{last_y - 10}" yMax="{last_y}">x</word>'
                if a[0] == 'pdftotext':
                    return '\f'.join(pages)
                return ''
            with mock.patch.object(verify, '_run', side_effect=fake_run):
                fails, _ = verify.verify(pdf, DOC, {}, {'resume': {'max_page1_free_pt': 40}})
        return [f for f in fails if 'page 1 has' in f]

    def test_one_page_resume_is_not_held_to_it(self):
        self.assertEqual(self.run_verify(['Jordan Rivera\nSome text\n'], 500), [])

    def test_two_page_resume_with_a_short_page_one_fails(self):
        self.assertEqual(len(self.run_verify(['Jordan Rivera\nPage one\n', 'Page two\n'], 500)), 1)

    def test_two_page_resume_with_a_full_page_one_passes(self):
        self.assertEqual(self.run_verify(['Jordan Rivera\nPage one\n', 'Page two\n'], 740), [])


if __name__ == '__main__':
    unittest.main()
