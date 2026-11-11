"""The review page's pick logic (section calls, own picks, the copied line), run in Node and read back
with gmh review picks' parser."""
import json, os, shutil, subprocess, unittest

from engine import runrecord

HAVE_NODE = shutil.which('node') is not None
BLOCK = ('// ---- pick logic', '// ---- end pick logic ----')

# Scored roles 1-6 (A: 1-3, B: 4-6), dropped roles d1-d4; role 2 has a pick saved in the run record.
SCENARIO = r"""
const CALLS = ['apply', 'hold', 'pass', 'manual'];
const ids = ['a1', 'a2', 'a3', 'b4', 'b5', 'b6', 'x1', 'x2', 'x3', 'x4'];
const byId = Object.fromEntries(ids.map((id, i) => [id, {id, ref: i < 6 ? i + 1 : 'd' + (i - 5)}]));
const order = r => typeof r.ref === 'number' ? r.ref : 100000 + Number(String(r.ref).slice(1));
const saved = {a2: {call: 'apply'}};
let picks = {a2: {call: 'apply', note: ''}}, sections = {};
__BLOCK__
const out = {};
const snap = k => { out[k] = pickText(); };
snap('saved only');
toggleSection('g-B', 'apply', ['b4', 'b5', 'b6']); snap('apply all B');
toggleRole('b5', 'pass'); snap('flip b5 to pass');
toggleSection('g-B', 'hold', ['b4', 'b5', 'b6']); snap('B to hold, b5 keeps pass');
toggleRole('b4', 'hold'); snap('take b4 out of the section call');
toggleRole('b4', 'hold'); snap('pick b4 back by hand');
toggleSection('g-drop-location', 'pass', ['x1', 'x2', 'x3', 'x4']); snap('pass all drops');
toggleSection('g-A', 'pass', ['a1', 'a2', 'a3']); snap('pass all A, saved a2 keeps apply');
toggleRole('a2', 'apply'); snap('take back saved a2');
picks.a3 = {call: 'pass', note: 'comp; too low'}; snap('note on a3');
toggleSection('g-A', 'pass', []); toggleSection('g-B', 'hold', []); snap('undo A and B section calls');
out.pickOf = {b5: pickOf('b5'), x2: pickOf('x2'), a1: pickOf('a1')};
out.compact = [compact([1, 2, 3, 5, 7, 8, 'd1', 'd2', 'd3', 'd9']), compact([4]), compact([4, 5])];
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(HAVE_NODE, 'node not installed')
class PickLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(runrecord.TEMPLATE, encoding='utf-8') as fh:
            page = fh.read()
        start, end = page.index(BLOCK[0]), page.index(BLOCK[1])
        js = SCENARIO.replace('__BLOCK__', page[start:end])
        cls.out = json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True, encoding='utf-8').stdout)

    def test_section_calls_and_own_picks(self):
        o = self.out
        self.assertEqual(o['saved only'], 'apply 2')
        self.assertEqual(o['apply all B'], 'apply 2 4-6')
        self.assertEqual(o['flip b5 to pass'], 'apply 2 4 6; pass 5')
        self.assertEqual(o['B to hold, b5 keeps pass'], 'apply 2; hold 4 6; pass 5')
        self.assertEqual(o['take b4 out of the section call'], 'apply 2; hold 6; pass 5')
        self.assertEqual(o['pick b4 back by hand'], 'apply 2; hold 4 6; pass 5')
        self.assertEqual(o['pass all drops'], 'apply 2; hold 4 6; pass 5 d1-4')
        self.assertEqual(o['pass all A, saved a2 keeps apply'], 'apply 2; hold 4 6; pass 1 3 5 d1-4')
        self.assertEqual(o['take back saved a2'], 'hold 4 6; pass 1 3 5 d1-4; clear 2')
        self.assertEqual(o['note on a3'], 'hold 4 6; pass 1 5 d1-4; clear 2; pass 3: comp, too low')
        self.assertEqual(o['undo A and B section calls'], 'hold 4; pass 5 d1-4; clear 2; pass 3: comp, too low')
        self.assertEqual(o['pickOf']['b5'], {'call': 'pass', 'note': '', 'inherited': False})
        self.assertEqual(o['pickOf']['x2'], {'call': 'pass', 'note': '', 'inherited': True})
        self.assertIsNone(o['pickOf']['a1'])

    def test_compact_ranges(self):
        self.assertEqual(self.out['compact'], ['1-3 5 7 8 d1-3 d9', '4', '4 5'])

    def test_copied_lines_parse(self):
        """Every line the page produced reads back into the same calls."""
        for k, line in self.out.items():
            if not isinstance(line, str):
                continue
            got = {(p['ref'], p['call']) for p in runrecord.parse_picks(line)}
            self.assertTrue(got, k)
        got = runrecord.parse_picks(self.out['note on a3'])
        self.assertIn(dict(ref=3, call='pass', note='comp too low'), got)  # the parser reads commas as spaces
        self.assertEqual([p['ref'] for p in got if p['call'] == 'pass' and not p['note']], [1, 5, 'd1', 'd2', 'd3', 'd4'])


class ConfirmFallbackTest(unittest.TestCase):
    """Confirm choices shows only where the artifact runtime serves db; a local file keeps Copy picks."""
    def test_page_without_runtime_keeps_copy(self):
        with open(runrecord.TEMPLATE, encoding='utf-8') as fh:
            page = fh.read()
        self.assertIn('<button class="btn" id="confirm" type="button" hidden>', page)
        self.assertIn("if (!DATA || !window.claude || !window.claude.use) return;", page)
        self.assertIn("if (!db) return;", page)
        self.assertIn('id="copy"', page)

GAP_SCENARIO = r"""
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
__BLOCK__
const rd = t => ({gap_type: t, top_gap: 'Needs 8 years of payments risk work', gap_quote: 'eight years in payments risk', strengths: []});
console.log(JSON.stringify({major: gapBlock(rd('major'), 'x')}));
"""


@unittest.skipUnless(HAVE_NODE, 'node not installed')
class GapBlockTest(unittest.TestCase):
    """A major or critical gap shows its text and posting quote beside the badge, not only in a hover title."""
    @classmethod
    def setUpClass(cls):
        with open(runrecord.TEMPLATE, encoding='utf-8') as fh:
            page = fh.read()
        cls.page = page

    def test_template_renders_gap_for_major_in_any_tier(self):
        i = self.page.index('function gapBlock')
        j = self.page.index('function roleHTML')
        block = self.page[i:j]
        src = GAP_SCENARIO.replace('__BLOCK__', block)
        out = json.loads(subprocess.run(['node', '-e', src], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
        self.assertIn('Needs 8 years of payments risk work', out['major'])
        self.assertIn('eight years in payments risk', out['major'])
        row = self.page[j:self.page.index('function controls')]
        self.assertIn("rd.gap_type === 'major' || rd.gap_type === 'critical'", row)
        self.assertIn('gapBlock(rd', row)


class GapSummaryTest(unittest.TestCase):
    def test_summary_lists_each_major_and_critical_gap(self):
        roles = [dict(tier='B', ref=4, company='Brightwater', title='Senior PM', new=True,
                      read=dict(gap_type='major', top_gap='Needs 8 years of payments risk work')),
                 dict(tier='gap', ref=5, company='Acme', title='Lead PM', new=False,
                      read=dict(gap_type='critical', top_gap='Needs a law degree')),
                 dict(tier='B', ref=6, company='Fabrikam', title='PM', new=False, read=dict(gap_type='minor', top_gap='x')),
                 dict(tier='B', ref=7, company='Contoso', title='PM', new=False)]
        lines = runrecord.summary(dict(date='2026-01-01', roles=roles, dropped=[]))
        text = '\n'.join(lines)
        self.assertIn('#4 Brightwater: Senior PM [B, major gap]: Needs 8 years of payments risk work', text)
        self.assertIn('#5 Acme: Lead PM [gap, critical gap]: Needs a law degree', text)
        self.assertNotIn('Fabrikam', text)
        self.assertNotIn('Contoso', text)


if __name__ == '__main__':
    unittest.main()
