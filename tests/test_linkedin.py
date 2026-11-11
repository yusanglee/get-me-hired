"""Phase 6: LinkedIn follow-through (engine/linkedin.py). Fictional people and companies only."""
import contextlib, csv, io, json, os, shutil, sys, tempfile, unittest, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import linkedin as L, tracker  # noqa: E402

MASTER = """# Jordan Rivera
## Experience
**Northwind**, Senior Product Manager (2019-2025)
- Led checkout and payments for 9 years across two startups
- Launched a new wallet, growing repeat purchases 40%
"""
POSTING = """# Senior Product Manager, Payments at Brightwater
About the role. You will report to Priya Natarajan, our Director of Product.
Your recruiter for this role is Dana Reyes. Morgan Lee, our Senior Talent Partner, also supports the team.
Questions? Reach out to Talent Acquisition. Please let your recruiter know about accommodations.
"""
HIRING_TEAM = """About the job
Meet the hiring team
Alex Kim
· 2nd
Head of Product, Payments
Message

Sam Ortiz
· 1st
Technical Recruiter
Job poster
"""


def put(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def docx(path, paragraphs):
    body = ''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', f'<w:document><w:body>{body}</w:body></w:document>')


def row(**kw):
    base = {'date_applied': '2026-03-02', 'company': 'Brightwater', 'title': 'Senior Product Manager, Payments',
            'id': 'gh-brightwater-1', 'job_key': 'brightwater_senior-product-manager-payments', 'status': 'applied',
            'status_date': '2026-03-02', 'source': 'pipeline', 'url': 'https://example.com/jobs/1',
            'folder': 'Workflow/03-Applied/2026-03-02 Brightwater - Senior PM Payments'}
    return {**base, **kw}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.vault = tempfile.mkdtemp()
        put(os.path.join(self.ws, 'config.json'), json.dumps({'paths': {'vault': self.vault}}))
        put(os.path.join(self.vault, 'master-resume.md'), MASTER)
        folder = os.path.join(self.vault, row()['folder'])
        os.makedirs(folder)
        put(os.path.join(folder, 'Senior Product Manager, Payments _ Brightwater.md'), POSTING)
        put(os.path.join(folder, 'application-notes.md'), 'Why Brightwater: wallet launch maps to their roadmap.')
        docx(os.path.join(folder, 'Jordan_Rivera_Cover_Letter_Brightwater.docx'),
             ['Dear Brightwater team,', 'At Northwind I launched a new wallet that grew repeat purchases 40%.'])
        self.rows = [row(),
                     row(date_applied='2026-03-05', company='Cobalt Farms', title='Product Manager, Growth',
                         id='gh-cobalt-2', job_key='cobalt-farms_product-manager-growth', folder=''),
                     row(date_applied='2026-03-01', company='Quill & Co', title='Staff PM', id='gh-quill-3',
                         job_key='quill_staff-product-manager', status='rejected', folder='')]
        # An older tracker file without the new columns must keep working.
        old = [c for c in tracker.COLUMNS if not c.startswith('linkedin_')]
        with open(tracker.path_of(self.ws), 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=old, extrasaction='ignore')
            w.writeheader()
            for r in self.rows:
                w.writerow(r)

    def tearDown(self):
        shutil.rmtree(self.ws)
        shutil.rmtree(self.vault)

    def run_cli(self, *args):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out):
            try:
                L.main(list(args) + ['--workspace', self.ws])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class InterestStep(Workspace):
    def test_queue_lists_open_applications_newest_first(self):
        code, out = self.run_cli('queue')
        self.assertEqual(code, 0)
        self.assertIn('2 compan(ies) still need', out)
        self.assertLess(out.index('Cobalt Farms'), out.index('Brightwater'))
        self.assertNotIn('Quill', out)  # rejected: closed
        self.assertIn('search/results/companies/?keywords=Brightwater', out)

    def test_confirmed_company_page_is_remembered(self):
        self.run_cli('company', 'gh-brightwater-1', 'https://www.linkedin.com/company/brightwater-pay/about/')
        code, out = self.run_cli('page', 'gh-brightwater-1')
        self.assertIn('Brightwater Jobs tab: https://www.linkedin.com/company/brightwater-pay/jobs/', out)
        self.assertIn('done, no button, or skip', out)

    def test_record_interest_keeps_tracker_compatible(self):
        code, out = self.run_cli('interest', 'gh-brightwater-1', 'done', '--date', '2026-03-03')
        self.assertEqual(code, 0)
        rows = tracker.read(tracker.path_of(self.ws))
        self.assertEqual(rows[0]['linkedin_interest'], 'done 2026-03-03')
        self.assertEqual(rows[1]['linkedin_interest'], '')
        self.assertEqual(rows[0]['status'], 'applied')  # nothing else changed
        _, q = self.run_cli('queue', '--date', '2026-03-03')
        self.assertIn('1 compan(ies) still need', q)
        self.assertIn('1 done today', q)

    def test_followup_scope_plugin_or_recent_gmail(self):
        # Plugin applications always qualify; Gmail imports only within gmail_followup_days.
        self.assertTrue(L.followup_eligible(row(date_applied='2025-01-01'), '2026-03-10'))
        self.assertTrue(L.followup_eligible(row(source='gmail', date_applied='2026-03-03'), '2026-03-10'))
        self.assertFalse(L.followup_eligible(row(source='gmail', date_applied='2026-03-02'), '2026-03-10'))
        self.assertFalse(L.followup_eligible(row(source='gmail', date_applied=''), '2026-03-10'))
        self.assertTrue(L.followup_eligible(row(source='gmail', date_applied='2026-01-02'), '2026-03-10', gmail_days=None))
        rows = [row(), row(company='Northwind', title='PM', id='gm-1', job_key='northwind_pm', source='gmail',
                           date_applied='2025-11-01', folder='')]
        q, total = L.interest_queue(rows, {}, today='2026-03-10')
        self.assertEqual((total, [r['company'] for r in q]), (1, ['Brightwater']))
        q, total = L.interest_queue(rows, {}, today='2026-03-10', gmail_days=200)
        self.assertEqual(total, 2)

    def test_old_gmail_import_is_refused_unless_included(self):
        rows = tracker.read(tracker.path_of(self.ws))
        rows.append(row(company='Northwind', title='PM', id='gm-1', job_key='northwind_pm', source='gmail',
                        date_applied='2026-01-05', folder=''))
        tracker.write(tracker.path_of(self.ws), rows)
        code, out = self.run_cli('queue', '--date', '2026-03-10')
        self.assertNotIn('gm-1', out)
        self.assertIn('1 Gmail-imported application(s)', out)
        code, _ = self.run_cli('page', 'gm-1', '--date', '2026-03-10')
        self.assertIn('more than 7 days ago', str(code))
        code, out = self.run_cli('page', 'gm-1', '--date', '2026-03-10', '--include-old')
        self.assertEqual(code, 0)
        put(os.path.join(self.ws, 'config.json'),
            json.dumps({'paths': {'vault': self.vault}, 'linkedin': {'gmail_followup_days': 90}}))
        code, out = self.run_cli('queue', '--date', '2026-03-10')
        self.assertIn('Northwind', out)

    def test_one_entry_and_one_record_per_company(self):
        rows = [dict(r) for r in self.rows] + [row(title='Product Manager, Risk', id='gh-brightwater-9',
                                                   job_key='brightwater_product-manager-risk', date_applied='2026-03-04')]
        q, total = L.interest_queue(rows, {})
        self.assertEqual(total, 2)
        # no scores: a company with more open roles first
        self.assertEqual([r['company'] for r in q], ['Brightwater', 'Cobalt Farms'])
        self.assertEqual([o['title'] for o in q[0]['other_roles']], ['Senior Product Manager, Payments'])
        changed, _ = L.record_interest(rows, 'gh-brightwater-1', 'not_offered', '2026-03-05')
        self.assertEqual(len(changed), 2)
        self.assertEqual(rows[3]['linkedin_interest'], 'not_offered 2026-03-05')
        self.assertNotIn('linkedin_interest', rows[1])  # Cobalt Farms untouched

    def test_queue_best_fit_first(self):
        os.makedirs(os.path.join(self.vault, 'Pipeline', 'queue'))
        put(os.path.join(self.vault, 'Pipeline', 'queue', 'scored-2026-03-01.csv'),
            'tier,fit,ats,company,title,locations,salary_max,gaps,flags,review,url,id\n'
            'B,61,80,Brightwater,"Senior Product Manager, Payments",NYC,,,,yes,,gh-brightwater-1\n'
            'A,78,90,Cobalt Farms,"Product Manager, Growth",NYC,,,,yes,,gh-cobalt-2\n')
        q, _ = L.interest_queue(self.rows, {}, fits=L.fit_scores(self.ws))
        self.assertEqual([(r['company'], r['fit'], r['tier']) for r in q], [('Cobalt Farms', 78, 'A'), ('Brightwater', 61, 'B')])
        _, out = self.run_cli('queue')
        self.assertLess(out.index('Cobalt Farms'), out.index('Brightwater'))
        self.assertIn('(fit 78 A)', out)

    def test_queue_falls_back_to_reviewed_fit(self):
        q_dir = os.path.join(self.vault, 'Pipeline', 'queue')
        os.makedirs(q_dir)
        put(os.path.join(q_dir, 'scored-2026-03-01.csv'),
            'tier,fit,ats,company,title,locations,salary_max,gaps,flags,review,url,id\n'
            'A,78,90,Cobalt Farms,"Product Manager, Growth",NYC,,,,yes,,gh-cobalt-2\n')
        put(os.path.join(q_dir, 'reviewed-2026-03-01.csv'),
            'call,gap_type,top_gap,company,title,locations,salary_max,fit,notes,url,id\n'
            'apply,,,Brightwater,"Senior Product Manager, Payments",NYC,,85,added by hand,,gh-brightwater-1\n'
            'apply,,,Cobalt Farms,"Product Manager, Growth",NYC,,99,,,gh-cobalt-2\n')
        fits = L.fit_scores(self.ws)
        self.assertEqual(fits['gh-brightwater-1'], (85, 'reviewed'))  # no scored fit: the reviewed one
        self.assertEqual(fits['gh-cobalt-2'], (78, 'A'))  # a scored fit always wins
        q, _ = L.interest_queue(self.rows, {}, fits=fits)
        self.assertEqual([r['company'] for r in q], ['Brightwater', 'Cobalt Farms'])

    def test_bad_outcome_rejected(self):
        with self.assertRaises(ValueError):
            L.record_interest(self.rows, 'gh-brightwater-1', 'clicked', '2026-03-03')

    def test_sent_appends_and_dedupes(self):
        rows = [dict(r) for r in self.rows]
        L.record_sent(rows, 'gh-brightwater-1', 'Dana Reyes', 'https://www.linkedin.com/in/dana-reyes-x', '2026-03-03')
        L.record_sent(rows, 'gh-brightwater-1', 'Dana Reyes', 'https://www.linkedin.com/in/dana-reyes-x', '2026-03-03')
        L.record_sent(rows, 'gh-brightwater-1', 'Alex Kim', '', '2026-03-04')
        self.assertEqual(rows[0]['linkedin_connect'],
                         '2026-03-03 sent: Dana Reyes (https://www.linkedin.com/in/dana-reyes-x); 2026-03-04 sent: Alex Kim')
        with self.assertRaises(ValueError):
            L.record_sent(rows, 'gh-brightwater-1', ' ', '', '2026-03-04')


class ConnectNote(Workspace):
    GOOD = ('Hi Dana! I recently applied for the Senior PM, Payments role at Brightwater. I have 9 years building '
            'checkout and payments, and at Northwind I launched a new wallet that grew repeat purchases 40%. '
            'Would love to connect!')

    def test_sources_read_submitted_materials(self):
        facts, mats, posting, files = L.sources(self.ws, self.rows[0])
        self.assertIn('Northwind', facts)
        self.assertIn('grew repeat purchases 40%', mats)  # from the .docx
        self.assertIn('wallet launch maps', mats)
        self.assertIn('Your recruiter for this role is Dana Reyes', posting)

    def test_good_note_passes(self):
        facts, mats, posting, _ = L.sources(self.ws, self.rows[0])
        res = L.check_note(self.GOOD, facts, mats, posting, 'Dana', 'Senior Product Manager, Payments', 'Brightwater')
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['warnings'], [])
        self.assertLessEqual(res['chars'], 300)

    def test_over_limit_dash_and_invented_number_fail(self):
        long = self.GOOD.replace('Would love', 'I also care deeply about merchants and their customers. ' * 2 + 'Would love')
        res = L.check_note(long, MASTER)
        self.assertFalse(res['ok'])
        self.assertTrue(any('over the 300 limit' in p for p in res['problems']))
        res = L.check_note('Hi Dana! I grew revenue 3x — fast. Would love to connect!', MASTER)
        self.assertTrue(any('dash' in p for p in res['problems']))
        self.assertTrue(any('3x' in p for p in res['problems']))

    def test_exact_300_passes_301_fails(self):
        base = 'Hi Dana! Would love to connect!'
        pad = 'a' * (300 - len(base))
        self.assertTrue(L.check_note(base[:9] + pad + base[9:])['ok'])
        self.assertFalse(L.check_note(base[:9] + pad + 'a' + base[9:])['ok'])

    def test_warnings_for_missing_pattern_parts(self):
        res = L.check_note('Hello there, I applied to your company.', MASTER, first='Dana',
                           title='Senior Product Manager, Payments', company='Brightwater')
        self.assertTrue(res['ok'])  # warnings never block
        self.assertEqual(len(res['warnings']), 4)

    def test_title_variants_accept_pm_shorthand(self):
        v = L.title_variants('Senior Product Manager, Growth')
        self.assertIn('senior pm, growth', v)
        self.assertIn('sr. pm, growth', v)

    def test_cli_check_note_exit_code(self):
        code, out = self.run_cli('check-note', 'gh-brightwater-1', '--first', 'Dana', '--text', self.GOOD)
        self.assertEqual(code, 0, out)
        code, out = self.run_cli('check-note', 'gh-brightwater-1', '--text', 'Hi Dana! I led 12 teams. Would love to connect!')
        self.assertEqual(code, 1)
        self.assertIn('12', out)

    def test_packet_has_rules_facts_and_people(self):
        code, out = self.run_cli('packet', 'gh-brightwater-1')
        self.assertTrue(os.path.isabs(out.strip()) and 'note-packet-gh-brightwater-1' in out)  # the path, not the packet
        p = json.load(open(out.strip(), encoding='utf-8'))
        self.assertEqual(p['role']['company'], 'Brightwater')
        self.assertIn('Northwind', p['facts'])
        self.assertEqual(p['people'][0]['name'], 'Dana Reyes')
        self.assertTrue(any('300' in r for r in p['rules']))
        self.assertGreater(p['claim_budget_without_name'], 100)


class PeopleTable(Workspace):
    NOTE = "Hi {first}! I recently applied for the Senior PM, Payments role at Brightwater. At Northwind I launched a new wallet that grew repeat purchases 40%. Would love to connect!"

    def test_table_addresses_each_person_and_checks_each_message(self):
        self.run_cli('people-add', 'gh-brightwater-1', '--name', 'Ciara P.', '--url', 'https://www.linkedin.com/in/ciara-example/',
                     '--signal', 'team_recruiter', '--source', 'web', '--title', 'Recruiter, Product')
        code, out = self.run_cli('table', 'gh-brightwater-1', '--note', self.NOTE)
        self.assertEqual(code, 0, out)
        self.assertIn('| # | Person | Why | Profile | Message (ready to paste) |', out)
        self.assertIn('Hi Ciara! I recently applied', out)  # "Ciara P." -> "Ciara"
        self.assertIn("Recruiter, Product · recruiter for the role's team · found by web search, check it's current", out)
        self.assertIn('https://www.linkedin.com/in/ciara-example/', out)
        self.assertIn('Hi Dana!', out)  # people named in the posting get their own message too

    def test_table_flags_a_failing_message(self):
        code, out = self.run_cli('table', 'gh-brightwater-1', '--note', self.NOTE.replace('40%', '75%'))
        self.assertEqual(code, 1)
        self.assertIn('FIX FIRST: number not in the resume or submitted materials: 75%', out)

    def test_table_needs_the_placeholder(self):
        code, _ = self.run_cli('table', 'gh-brightwater-1', '--note', 'Hi Sam! hello')
        self.assertNotEqual(code, 0)

    def test_first_name(self):
        self.assertEqual([L.first_name(n) for n in ('Ciara P.', 'Dr. Sam Lee', 'Jo', '')], ['Ciara', 'Sam', 'Jo', ''])


class People(Workspace):
    def test_posting_names_and_signals(self):
        got = {p['name']: p['signal'] for p in L.posting_people(POSTING)}
        self.assertEqual(got, {'Dana Reyes': 'posting_contact', 'Morgan Lee': 'posting_recruiter',
                               'Priya Natarajan': 'hiring_team'})

    def test_boilerplate_is_not_a_person(self):
        text = ('Please reach out to Talent Acquisition. Contact Human Resources. Your recruiter can share more. '
                'Legitimate Brightwater recruiters will never ask for money. Questions? Contact Us Today. '
                'For an accommodation, please contact Cobalt Farms Recruiting at 1-800-555-0100.')
        self.assertEqual(L.posting_people(text), [])

    def test_pasted_hiring_team_block(self):
        got = {p['name']: (p['signal'], p['degree'], p['title']) for p in L.posting_people(HIRING_TEAM)}
        self.assertEqual(got['Alex Kim'], ('hiring_team', 2, 'Head of Product, Payments'))
        self.assertEqual(got['Sam Ortiz'], ('posting_contact', 1, 'Technical Recruiter'))

    def test_in_network_line_is_a_connection_not_a_contact(self):
        text = '## People you can reach out to\n\nJo and others in your network\n\n## About the job\nReach out to us.'
        (p,) = L.posting_people(text)
        self.assertEqual((p['name'], p['signal'], p['degree']), ('Jo', 'other', None))  # not a reliable degree signal

    def test_rank_order_and_degree(self):
        ppl = [{'name': 'Recent Join', 'signal': 'recent_join'},
               {'name': 'Team Lead', 'signal': 'hiring_team'},
               {'name': 'Team Friend', 'signal': 'hiring_team', 'degree': 2},
               {'name': 'Named Recruiter', 'signal': 'posting_recruiter'},
               {'name': 'Team Recruiter', 'signal': 'team_recruiter'},
               {'name': 'Role Owner', 'signal': 'role_link'},
               {'name': 'Named Contact', 'signal': 'posting_contact'},
               {'name': 'Old Friend', 'signal': 'other', 'degree': 1},
               {'name': 'Extra Person', 'signal': 'other'}]
        names = [p['name'] for p in L.rank(ppl, limit=9)]
        # 1st-degree to the top; a direct role link beats recruiters; 2nd-degree jumps one group
        # (ahead of Named Recruiter), never past a 1st.
        self.assertEqual(names, ['Old Friend', 'Named Contact', 'Role Owner', 'Team Friend', 'Named Recruiter',
                                 'Team Recruiter', 'Team Lead', 'Recent Join', 'Extra Person'])
        two = [{'name': 'Second Contact', 'signal': 'posting_contact', 'degree': 2},
               {'name': 'First Other', 'signal': 'other', 'degree': 1},
               {'name': 'Plain Contact', 'signal': 'posting_contact'}]
        self.assertEqual([p['name'] for p in L.rank(two)], ['First Other', 'Second Contact', 'Plain Contact'])

    def test_merge_keeps_strongest_signal_and_degree(self):
        ppl = [{'name': 'Dana Reyes', 'signal': 'other', 'degree': 2, 'url': ''},
               {'name': 'Dana Reyes', 'signal': 'posting_contact', 'url': 'https://www.linkedin.com/in/dana-x'}]
        (p,) = L.rank(ppl)
        self.assertEqual((p['signal'], p['degree'], p['url']), ('posting_contact', 2, 'https://www.linkedin.com/in/dana-x'))
        self.assertIn('2nd-degree', p['why'])

    def test_cli_people_add_paste_and_links(self):
        paste = os.path.join(self.ws, 'paste.txt')
        put(paste, HIRING_TEAM)
        self.run_cli('people-paste', 'gh-brightwater-1', '--file', paste)
        self.run_cli('people-add', 'gh-brightwater-1', '--name', 'Riley Chen', '--signal', 'recent_join',
                     '--url', 'https://www.linkedin.com/in/riley-chen-x', '--degree', '1')
        code, out = self.run_cli('people', 'gh-brightwater-1')
        ppl = json.loads(out)
        # Sam and Riley are 1st-degree (top); Alex is 2nd-degree hiring team, so jumps ahead of Morgan.
        self.assertEqual([p['name'] for p in ppl], ['Sam Ortiz', 'Riley Chen', 'Dana Reyes', 'Alex Kim', 'Morgan Lee'])
        self.assertEqual(ppl[1]['profile'], 'https://www.linkedin.com/in/riley-chen-x')
        self.assertTrue(ppl[2]['profile'].startswith('https://www.linkedin.com/search/results/people/?keywords=Dana'))

    def test_slug_from(self):
        self.assertEqual(L.slug_from('https://www.linkedin.com/company/cobalt-farms/life/'), 'cobalt-farms')
        self.assertEqual(L.slug_from('cobalt-farms'), 'cobalt-farms')
        with self.assertRaises(ValueError):
            L.slug_from('not a slug at all')


if __name__ == '__main__':
    unittest.main()
