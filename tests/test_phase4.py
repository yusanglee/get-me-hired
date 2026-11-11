"""Phase 4: role packs, workspace setup, the tracker, and email history import."""
import csv, datetime, json, os, re, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import gmail_import as gi, packs, setup, tracker  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'gmail', 'incoming.jsonl')

RESUME = {
    'bio': 'Operator  ·  Strategy and Execution',
    'summary': 'Chief of Staff who ran the operating cadence, board materials and annual planning for a Series C startup.',
    'experience': [
        {'company': 'Example Health', 'role': 'Chief of Staff to the CEO', 'dates': 'Mar 2021 - Jun 2026', 'location': 'Chicago, IL',
         'bullets': ['Ran the OKR and planning cycle for 400 people across 9 teams.',
                     'Prepared quarterly board materials and led fundraising diligence for a $60M Series C.']},
        {'company': 'Consultancy Co', 'role': 'Senior Associate', 'dates': 'Jul 2016 - Feb 2021', 'location': 'Chicago, IL',
         'bullets': ['Built financial models for 12 M&A integration projects.']},
    ],
    'skills': 'Strategic Planning  |  OKRs  |  Financial Modeling',
    'education': [{'school': 'State University', 'degree': 'B.A., Economics', 'years': '2008 - 2012'}],
}


class PackTest(unittest.TestCase):
    def test_base_packs_valid(self):
        self.assertEqual(packs.base_packs(), ['chief-of-staff', 'product-management'])
        for n in packs.base_packs():
            packs.load(n)

    def test_bad_regex_rejected(self):
        with self.assertRaises(packs.PackError):
            packs.validate({'titles': {'include': '(unclosed'}})

    def test_pm_titles(self):
        p = packs.load('product-management')
        self.assertTrue(packs.title_ok(p, 'Senior Product Manager, Growth'))
        self.assertTrue(packs.title_ok(p, 'Senior Product Manager, Design Systems'))  # design guard overridden
        self.assertFalse(packs.title_ok(p, 'Product Designer'))
        self.assertFalse(packs.title_ok(p, 'Associate Product Manager'))
        self.assertFalse(packs.title_ok(p, 'Product Marketing Manager'))

    def test_cos_titles(self):
        p = packs.load('chief-of-staff')
        for t in ('Chief of Staff to the CEO', 'Chief of Staff, Engineering', 'Strategy & Operations Lead', 'Head of Strategy'):
            self.assertTrue(packs.title_ok(p, t), t)
        for t in ('Executive Assistant to the Chief of Staff', 'Sales Operations Manager', 'Medical Staff Coordinator',
                  'Senior Software Engineer, Business Operations'):
            self.assertFalse(packs.title_ok(p, t), t)

    def test_draft_uses_resume_evidence(self):
        p = packs.draft(packs.load('chief-of-staff'), json.dumps(RESUME).lower())
        pats = {s['pattern'] for s in p['strengths']}
        labels = {g['label'] for g in p['gaps']}
        self.assertTrue(any('board' in x for x in pats))
        self.assertTrue(any('fundrais' in x for x in pats))
        self.assertIn('consulting or banking background', labels)
        self.assertFalse(p['approved'])
        self.assertNotIn('strength_catalog', p)

    def test_score_formula(self):
        p = packs.draft(packs.load('chief-of-staff'), json.dumps(RESUME).lower())
        jd = ('About the role: Chief of Staff to the CEO. Requirements: 6+ years in strategy; own the operating cadence and '
              'OKRs; prepare board materials; an investment banking background is required. Benefits: health.')
        r = packs.score(p, 'Chief of Staff to the CEO', jd, json.dumps(RESUME), 240000)
        self.assertIn('consulting or banking background', r['gaps'])
        self.assertGreater(r['strengths'], 0)
        self.assertEqual(r['flags'], '')
        r2 = packs.score(p, 'Chief of Staff', jd.replace('an investment banking background is required',
                                                          'an investment banking background is a plus'),
                         json.dumps(RESUME), None)
        self.assertNotIn('consulting or banking background', r2['gaps'])  # "a plus" never costs points
        self.assertIn('no posted range', r2['flags'])


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, 'JobSearch')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_blank_profile_has_no_example_values(self):
        text = setup.blank_profile(open(os.path.join(setup.TEMPLATES, 'profile.example.yaml'), encoding='utf-8').read())
        for leak in ('Jordan', 'Rivera', 'Northwestern', 'Chicago', 'example.com', '555-'):
            self.assertNotIn(leak, text)
        self.assertIn('top_factor: 0.75', text)

    def test_full_flow(self):
        made = setup.init(self.ws, 'chief-of-staff')
        self.assertTrue(any(m.endswith('profile.yaml') for m in made))
        for d in ('Workflow/02-Ready to Apply', 'Pipeline/state/forms', 'resume/draft', 'state/gmail'):
            self.assertTrue(os.path.isdir(os.path.join(self.ws, d)), d)
        cfg = json.load(open(os.path.join(self.ws, 'config.json'), encoding='utf-8'))
        self.assertNotIn('vault', cfg['paths'])  # the workspace is its own vault
        from engine import layout
        self.assertEqual(layout.vault(self.ws), self.ws)
        rep = setup.check(self.ws)
        self.assertFalse(rep['ready'])
        self.assertIn('identity.first_name', rep['profile_missing_required'])
        self.assertEqual(setup.init(self.ws, 'chief-of-staff'), [])  # re-run never overwrites

        prof = open(os.path.join(self.ws, 'profile.yaml'), encoding='utf-8').read()
        prof = prof.replace('  first_name:\n', '  first_name: Sam\n', 1).replace('  last_name:\n', '  last_name: Park\n', 1) \
                   .replace('  email:\n', '  email: sam@example.org\n', 1)
        open(os.path.join(self.ws, 'profile.yaml'), 'w', encoding='utf-8', newline='\n').write(prof)
        cfg['salary']['floor_usd'] = 180000
        cfg['locations'] = {'home': 'Chicago', 'remote_us': True, 'metros': [{'name': 'Chicago', 'policy': 'any'}]}
        json.dump(cfg, open(os.path.join(self.ws, 'config.json'), 'w', encoding='utf-8', newline='\n'))

        draft = os.path.join(self.tmp, 'draft.json')
        json.dump(RESUME, open(draft, 'w', encoding='utf-8', newline='\n'))
        setup.resume_draft(self.ws, draft)
        self.assertIn('[unapproved]', open(os.path.join(self.ws, 'master-resume.md'), encoding='utf-8').read())
        with self.assertRaises(SystemExit):
            setup.pack_approve(self.ws)  # nothing drafted yet
        dest, n = setup.resume_approve(self.ws)
        self.assertEqual(n, 3)
        bank = json.load(open(os.path.join(self.ws, 'resume', 'bank.json'), encoding='utf-8'))
        self.assertIn('OKRs', bank['skills'])
        self.assertNotIn('[unapproved]', open(os.path.join(self.ws, 'master-resume.md'), encoding='utf-8').read())
        pack = setup.pack_draft(self.ws)
        self.assertEqual(pack['drafted_from'], 'chief-of-staff')
        setup.pack_approve(self.ws)
        with self.assertRaises(SystemExit):
            setup.pack_draft(self.ws)  # approved packs are edited by hand
        rep = setup.check(self.ws)
        self.assertTrue(rep['ready'], setup.format_check(rep))

    def test_privacy_check_flags_unignored_repo_folder(self):
        import subprocess
        repo = os.path.join(self.tmp, 'repo')
        os.makedirs(repo)
        subprocess.run(['git', 'init', '-q', repo], check=True)
        with self.assertRaises(SystemExit):
            setup.init(os.path.join(repo, 'ws'))
        open(os.path.join(repo, '.gitignore'), 'w', encoding='utf-8', newline='\n').write('ws/\n')
        setup.init(os.path.join(repo, 'ws'))

    def test_resolve_companies_uses_cache(self):
        setup.init(self.ws)
        with open(os.path.join(self.ws, 'companies.txt'), 'a', encoding='utf-8', newline='\n') as fh:
            fh.write('Acme Corp | acme\nZeta\n')
        calls = []

        def fake(guesses, name):
            calls.append((name, guesses))
            return ['greenhouse', 'acme'] if name == 'Acme Corp' else None
        cache = setup.resolve_companies(self.ws, fetch=fake)
        self.assertEqual(cache, {'Acme Corp': ['greenhouse', 'acme'], 'Zeta': None})
        self.assertEqual(calls[0][1], ['acme', 'acmecorp', 'acme-corp'])
        setup.resolve_companies(self.ws, fetch=fake)
        self.assertEqual(len(calls), 2)  # cached


class TrackerTest(unittest.TestCase):
    def test_status_moves_forward_and_closes(self):
        self.assertTrue(tracker.advance('applied', '2026-07-01', 'interviewing', '2026-07-10'))
        self.assertFalse(tracker.advance('interviewing', '2026-07-10', 'applied', '2026-07-12'))
        self.assertTrue(tracker.advance('interviewing', '2026-07-10', 'rejected', '2026-07-20'))
        self.assertFalse(tracker.advance('rejected', '2026-07-20', 'interviewing', '2026-07-10'))  # older event
        self.assertTrue(tracker.advance('rejected', '2026-07-20', 'interviewing', '2026-08-01'))  # re-engaged later

    def test_upsert_and_csv_quoting(self):
        rows = []
        self.assertEqual(tracker.upsert(rows, {'company': 'Acme, Inc.', 'title': 'Chief of Staff', 'status': 'applied',
                                               'date_applied': '2026-07-01', 'notes': 'comma, "quoted"'}), 'added')
        self.assertEqual(tracker.upsert(rows, {'company': 'Acme', 'title': 'Chief of Staff', 'status': 'interviewing',
                                               'status_date': '2026-07-09', 'gmail_ids': 'm2'}), 'updated')
        self.assertEqual(tracker.upsert(rows, {'company': 'ACME', 'title': 'Chief of Staff', 'gmail_ids': 'm2'}), 'unchanged')
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'tracker.csv')
            tracker.write(p, rows)
            back = tracker.read(p)
            self.assertEqual(back[0]['notes'], 'comma, "quoted"')
            self.assertEqual(back[0]['status'], 'interviewing')
            out = tracker.report(back, os.path.join(d, 'report.html'))
            self.assertIn('Acme, Inc.', open(out, encoding='utf-8').read())


class SeedLegacyTest(unittest.TestCase):
    def test_seed_from_applied_csv(self):
        with tempfile.TemporaryDirectory() as d:
            vault, ws = os.path.join(d, 'vault'), os.path.join(d, 'ws')
            os.makedirs(os.path.join(vault, 'Pipeline', 'state'))
            with open(os.path.join(vault, 'Pipeline', 'state', 'applied.csv'), 'w', newline='', encoding='utf-8') as fh:
                w = csv.writer(fh)
                w.writerow(['date_applied', 'company', 'title', 'id', 'folder', 'url'])
                w.writerow(['2026-10-19', 'Kestrel', 'Chief of Staff, Product', 'gh-kestrel-1', 'Workflow/03-Applied/x', 'https://x'])
            setup.init(ws)
            cfg = {'paths': {'vault': vault}}
            self.assertEqual(tracker.seed_legacy(ws, cfg)['added'], 1)
            self.assertEqual(tracker.seed_legacy(ws, cfg)['unchanged'], 1)  # re-run is a no-op
            r = tracker.read(tracker.path_of(ws))[0]
            self.assertEqual((r['source'], r['status'], r['id']), ('pipeline', 'applied', 'gh-kestrel-1'))


class GmailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, 'ws')
        setup.init(self.ws, 'chief-of-staff')
        self.msgs = gi.read_incoming(FIX)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def by_id(self, mid):
        return next(m for m in self.msgs if m['id'] == mid)

    def test_classify(self):
        expect = {'m01': 'confirmation', 'm02': 'interview', 'm03': 'confirmation', 'm04': 'rejection',
                  'm05': 'confirmation', 'm06': 'confirmation', 'm08': 'offer', 'm10': 'assessment'}
        for mid, kind in expect.items():
            self.assertEqual(gi.classify(self.by_id(mid))['kind'], kind, mid)
        self.assertEqual(gi.classify(self.by_id('m07'))['confidence'], 'low')  # "unfortunately" in a sale email
        self.assertEqual(gi.classify(self.by_id('m09'))['confidence'], 'low')  # verdict is in the body

    def test_confirmation_boilerplate_is_not_an_interview(self):
        self.assertEqual(gi.classify(self.by_id('m01'))['kind'], 'confirmation')

    def test_extract(self):
        self.assertEqual(gi.extract_company(self.by_id('m01'))[0], 'Brightwater')
        self.assertEqual(gi.extract_company(self.by_id('m03'))[0], 'Northwind')
        self.assertEqual(gi.extract_company(self.by_id('m05'))[0], 'Kestrel')
        self.assertEqual(gi.extract_company(self.by_id('m06'))[0], 'Pellucid')
        self.assertEqual(gi.extract_company(self.by_id('m09'))[0], '')
        self.assertEqual(gi.extract_role(self.by_id('m01')), 'Chief of Staff to the CEO')
        self.assertEqual(gi.extract_role(self.by_id('m03')), 'Strategy & Operations Lead')
        self.assertEqual(gi.extract_role(self.by_id('m05')), 'Head of Business Operations')

    def test_propose_regroup_apply_idempotent(self):
        prop = gi.propose(self.msgs, self.ws)
        rows = {r['company']: r for r in prop['rows']}
        self.assertEqual(rows['Brightwater']['status'], 'offer')
        self.assertEqual(rows['Brightwater']['date_applied'], '2026-07-02')
        self.assertEqual(len(rows['Brightwater']['messages']), 3)
        self.assertEqual(rows['Northwind']['status'], 'rejected')
        self.assertEqual(rows['Pellucid']['title'], '')  # LinkedIn mail: role unknown until the user says
        self.assertEqual({u['id'] for u in prop['unsure']}, {'m07', 'm09', 'm10'})
        # Claude settles the unsure ones
        for u in prop['unsure']:
            if u['id'] == 'm07':
                u['dismissed'] = True
            if u['id'] == 'm09':
                u.update(decided=True, kind='rejection', company='Kestrel', role='Head of Business Operations')
            if u['id'] == 'm10':  # a case study from a non-ATS sender: low confidence until read
                u.update(decided=True, kind='assessment', company='Quarry', role='Chief of Staff, Operations')
        for r in prop['rows']:
            if r['company'] == 'Pellucid':
                r['title'] = 'Chief of Staff'
        prop = gi.regroup(prop, self.ws)
        rows = {r['company']: r for r in prop['rows']}
        self.assertEqual(rows['Kestrel']['status'], 'rejected')
        self.assertEqual(rows['Pellucid']['title'], 'Chief of Staff')
        self.assertFalse([u for u in prop['unsure'] if u['id'] in ('m07', 'm09')])
        quarry = rows['Quarry']['n']
        approve = ','.join(str(r['n']) for r in prop['rows'] if r['company'] != 'Quarry')
        res = gi.apply(prop, self.ws, approve, dismiss_spec=str(quarry))
        self.assertEqual(res['added'], 4)
        tr = {r['company']: r for r in tracker.read(tracker.path_of(self.ws))}
        self.assertEqual(tr['Brightwater']['status'], 'offer')
        self.assertEqual(tr['Brightwater']['source'], 'gmail')
        self.assertNotIn('Quarry', tr)
        for r in tr.values():  # no email text stored in the tracker
            self.assertNotIn('Unfortunately', json.dumps(r))
        self.assertEqual(gi.last_run(self.ws).isoformat(), prop['scanned_at'])  # nothing left open
        lr = gi.last_run(self.ws)
        self.assertRegex(gi.after_query(self.ws), r'^\d{4}/\d{2}/\d{2}$')  # never epoch seconds
        self.assertLessEqual(datetime.datetime.strptime(gi.after_query(self.ws), '%Y/%m/%d').date(),
                             (lr - datetime.timedelta(hours=24)).date() - datetime.timedelta(days=1))
        again = gi.propose(self.msgs, self.ws)
        self.assertEqual(again['rows'], [])  # every processed message is skipped
        self.assertEqual(again['skipped_seen'], 10)  # every message: applied, dismissed, or part of a dismissed row

    def test_open_rows_hold_back_the_next_scan(self):
        prop = gi.propose(self.msgs, self.ws)
        prop['scanned_at'] = '2026-10-20T18:00:00+00:00'
        north = next(r for r in prop['rows'] if r['company'] == 'Northwind')
        others = ','.join(str(r['n']) for r in prop['rows'] if r is not north and r['title'])
        for u in prop['unsure']:
            u['dismissed'] = True
        prop = {**prop, 'dismissed': prop['unsure'], 'unsure': []}
        gi.apply(prop, self.ws, others)
        # Northwind was neither approved nor dismissed: the next scan reaches back to its oldest mail
        self.assertEqual(gi.last_run(self.ws).date().isoformat(), min(m['date'] for m in north['messages']))
        untitled = ','.join(str(r['n']) for r in prop['rows'] if not r['title'])
        gi.apply(prop, self.ws, str(north['n']), dismiss_spec=untitled)  # everything decided now
        self.assertEqual(gi.last_run(self.ws).isoformat(), '2026-10-20T18:00:00+00:00')

    def _set_last_run(self, v):
        os.makedirs(os.path.join(self.ws, 'state', 'gmail'), exist_ok=True)
        json.dump({'last_run': v}, open(os.path.join(self.ws, 'state', 'gmail', 'sync.json'), 'w', encoding='utf-8', newline='\n'))

    def test_after_query_is_a_date_with_boundary_slack(self):
        self._set_last_run('2026-10-21T00:30:00+00:00')  # just past UTC midnight
        self.assertEqual(gi.after_query(self.ws), '2026/10/19')
        self._set_last_run('2026-10-21T23:30:00+00:00')  # just before it
        self.assertEqual(gi.after_query(self.ws), '2026/10/19')
        self._set_last_run('2026-10-21T23:30:00-08:00')  # aware non-UTC value is normalised to UTC first
        self.assertEqual(gi.after_query(self.ws), '2026/10/20')
        self._set_last_run('2026-03-01')  # month boundary
        self.assertEqual(gi.after_query(self.ws), '2026/02/27')

    def test_queries_use_date_form(self):
        self._set_last_run('2026-10-21T08:00:00+00:00')
        qs = gi.queries(after=gi.after_query(self.ws))
        self.assertTrue(all(q.startswith('after:2026/10/19 ') for q in qs))
        self.assertEqual(gi.after_query(os.path.join(self.ws, 'nowhere')), None)

    def test_unapplied_proposal_stays_in_the_next_window(self):
        prop = gi.propose(self.msgs, self.ws)  # proposed, never applied
        self.assertIsNone(gi.last_run(self.ws))  # nothing recorded, so the next sync is a full history import
        self.assertEqual(len(gi.propose(self.msgs, self.ws)['rows']), len(prop['rows']))  # nothing marked seen
        self._set_last_run('2026-10-10T00:00:00+00:00')  # an earlier sync; the unapplied proposal changes nothing
        self.assertEqual(gi.last_run(self.ws).isoformat(), '2026-10-10T00:00:00+00:00')

    def test_legacy_date_only_sync_file(self):
        os.makedirs(os.path.join(self.ws, 'state', 'gmail'), exist_ok=True)
        json.dump({'last_run': '2026-10-01'}, open(os.path.join(self.ws, 'state', 'gmail', 'sync.json'), 'w', encoding='utf-8', newline='\n'))
        self.assertEqual(gi.last_run(self.ws).isoformat(), '2026-10-01T00:00:00+00:00')

    def test_matches_existing_tracker_row(self):
        rows = []
        tracker.upsert(rows, {'company': 'Northwind', 'title': 'Strategy & Operations Lead', 'status': 'applied',
                              'date_applied': '2026-07-05', 'source': 'pipeline'})
        tracker.write(tracker.path_of(self.ws), rows)
        prop = gi.propose([self.by_id('m04')], self.ws)
        self.assertEqual(prop['rows'][0]['action'], 'update')
        self.assertEqual(prop['rows'][0]['status'], 'rejected')

    def test_real_world_formats(self):
        """Shapes seen in a real inbox (Oct 2026), with fictional companies."""
        G = 'no-reply@us.greenhouse-mail.io'
        cases = [  # sender, subject, snippet -> kind, company, role
            (G, 'Jordan, thank you for applying to Brightwater!',
             "Hi Jordan, Thanks for applying to our Senior Manager, Strategy position at Brightwater - we're excited",
             'confirmation', 'Brightwater', 'Senior Manager, Strategy'),
            ('no-reply@hire.lever.co', 'Thanks for applying to Chief of Staff, Operations',
             "Hi Jordan, We're excited to have your application for Chief of Staff, Operations! You can manage your data",
             'confirmation', '', 'Chief of Staff, Operations'),
            (G, 'Northwind | We\'ve Received Your Application',
             'Hello Jordan, Thank you for your interest in Northwind and for applying to the Sr. Operations Lead opportunity with us!',
             'confirmation', 'Northwind', 'Sr. Operations Lead'),
            ('no-reply@kestrel.example', 'Thank you for applying to Kestrel',
             'Hi Jordan, Thank you for applying to Kestrel! We have received your application for Head of Strategy, Growth role and',
             'confirmation', 'Kestrel', 'Head of Strategy, Growth'),
            ('careers@jobs.pellucid.example', 'Jordan, we have received your application for Chief of Staff (L6)',
             'Dear Jordan, Thank you for applying for the role of Chief of Staff (L6) at Pellucid! It is exciting',
             'confirmation', 'Pellucid', 'Chief of Staff (L6)'),
            ('quarry@myworkday.com', 'Application Received for Director, Business Operations',
             'Dear Jordan, Thank you for applying for the role of Director, Business Operations . We are processing it',
             'confirmation', 'Quarry', 'Director, Business Operations'),
            ('noreply@mail.bigco.jobs', 'Thank you for Applying to BigCo!',
             "Hi Jordan, We've received your application for the Chief of Staff, Devices (ID: 1234567) position.",
             'confirmation', 'BigCo', 'Chief of Staff, Devices'),
        ]
        for snd, subj, snip, kind, co, role in cases:
            m = {'id': 'x', 'sender': snd, 'subject': subj, 'snippet': snip}
            self.assertEqual(gi.classify(m)['kind'], kind, subj)
            self.assertEqual(gi.extract_company(m)[0], co, subj)
            self.assertEqual(gi.extract_role(m), role, subj)

    def test_noise_is_dropped(self):
        for snd, subj in [('no-reply@us.greenhouse-mail.io', 'Security code for your application to Brightwater'),
                          ('jobs-noreply@linkedin.com', 'Brightwater is hiring for a Strategy role'),
                          ('jobs-noreply@linkedin.com', "Jordan, apply now to 'Chief of Staff at Northwind'"),
                          ('jobs-noreply@linkedin.com', 'New jobs similar to Chief of Staff at Kestrel'),
                          ('noreply@mail.bigco.jobs', 'Keep track of your application')]:
            c = gi.classify({'sender': snd, 'subject': subj, 'snippet': 'Thank you for your interest in the role'})
            self.assertEqual((c['kind'], c['confidence']), ('other', 'high'), subj)

    def test_follow_up_subject_needs_the_body(self):
        m = {'sender': 'recruiter@bigco.example', 'subject': 'Following up on your recent application to BigCo',
             'snippet': 'Thanks so much for applying with us. We carefully reviewed'}
        self.assertEqual(gi.classify(m)['confidence'], 'low')
        m['body'] = m['snippet'] + ' your background and decided not to proceed with your application at this time.'
        self.assertEqual(gi.classify(m)['kind'], 'rejection')

    def test_status_update_subject_is_not_dropped(self):
        """'Update on your X application' from a company-hosted Workday tenant, verdict past the snippet."""
        m = {'id': 'u1', 'sender': 'noreply@workday.harborgroup.example', 'subject': 'Update on your Brightwater application',
             'snippet': 'Hi Jordan, Thank you for your interest in Brightwater. After careful consideration, we'}
        c = gi.classify(m)
        self.assertEqual((c['kind'], c['confidence']), ('rejection', 'low'))
        self.assertEqual(gi.extract_company(m)[0], 'Brightwater')
        recs, _ = gi.records([m])
        self.assertEqual(len(recs), 1)
        self.assertFalse(gi.settled(recs[0]))  # goes to unsure for Claude to read
        m2 = {'id': 'u2', 'sender': 'noreply@workday.harborgroup.example', 'subject': 'Update on your Brightwater application',
              'snippet': 'Hi Jordan, We wanted to let you know'}
        c = gi.classify(m2)
        self.assertEqual(c['confidence'], 'low')
        self.assertEqual(len(gi.records([m2])[0]), 1)
        # a plain confirmation stays a confirmation
        m3 = {'sender': 'noreply@workday.harborgroup.example', 'subject': 'Thank you for applying to Brightwater',
              'snippet': 'Hi Jordan, Thank you for applying. We have received your application and will review it carefully.'}
        self.assertEqual(gi.classify(m3), {'kind': 'confirmation', 'confidence': 'high', 'reason': 'Thank you for applying'})

    def test_shared_ats_hosts_give_no_company(self):
        """appreview.gem.com and similar hosts are the ATS, not the employer: the company comes from the subject."""
        for snd in ['no-reply@appreview.gem.com', 'no-reply@ats.rippling.com', 'notifications@candidates.workablemail.com',
                    'no-reply@fa.us2.oraclecloud.com', 'no-reply@email.smartrecruiters.com']:
            m = {'sender': snd, 'subject': 'Update on your Kestrel Application', 'snippet': 'Hi Jordan, thank you for'}
            self.assertEqual(gi.extract_company(m), ('Kestrel', 'subject'), snd)
            m = {'sender': snd, 'subject': 'Your application', 'snippet': 'Hi Jordan, thank you for'}
            self.assertEqual(gi.extract_company(m), ('', ''), snd)
        # tenant subdomains still name the employer
        self.assertEqual(gi.extract_company({'sender': 'no-reply@kestrel.bamboohr.com', 'subject': 'Your application'})[0], 'Kestrel')

    def test_recruiter_scheduled_interviews(self):
        P = 'Pat Kim <pat@{}.example>'
        cases = [  # sender, subject, snippet -> kind, confidence, company
            (P.format('northwind'), 'Northwind | Let’s chat | Jordan Rivera',
             'Hi Jordan, After going over your application for the Senior Manager, Strategy position, your',
             'interview', 'high', 'Northwind'),
            (P.format('pellucid'), 'Pellucid Inc. Interview Confirmation',
             'Hi Jordan, You are confirmed for your video interview with Pat Kim on Tuesday',
             'interview', 'high', 'Pellucid Inc'),
            (P.format('quarry'), 'Jordan Rivera | Quarry Recruiter Screen Confirmation & Preparation Information',
             'Hi Jordan, Looking forward to our phone call to chat about the position',
             'interview', 'high', 'Quarry'),
            (P.format('kestrel'), 'Your application to Kestrel',
             "Hi Jordan, Thanks for applying. I'd love to set up a phone call to chat about the position.",
             'interview', 'high', 'Kestrel'),
        ]
        for snd, subj, snip, kind, conf, co in cases:
            m = {'sender': snd, 'subject': subj, 'snippet': snip}
            c = gi.classify(m)
            self.assertEqual((c['kind'], c['confidence']), (kind, conf), subj)
            self.assertEqual(gi.extract_company(m)[0], co, subj)
        # interview subjects don't turn generic words into companies
        for subj in ['Your Interview Confirmation', 'Virtual Interview Invitation', 'Final Interview Request']:
            self.assertNotIn(gi.extract_company({'sender': 'Pat Kim <pat@gmail.com>', 'subject': subj})[1], ('subject',), subj)
        # "we'll reach out to schedule a chat" in a confirmation is still boilerplate
        m = {'sender': 'no-reply@us.greenhouse-mail.io', 'subject': 'Thank you for applying to Brightwater',
             'snippet': "Thanks for applying! If your background is a match, we will reach out to schedule a call."}
        self.assertEqual(gi.classify(m)['kind'], 'confirmation')

    def test_queries_include_interview_scheduling(self):
        qs = gi.queries('6m')
        self.assertTrue(any('"interview confirmation"' in q and '"recruiter screen"' in q for q in qs))

    def test_same_company(self):
        for a, b in [('Learnly', 'Learnly + Skillshop'), ('Fernbrook', 'Fern Brook Holdings'),
                     ('Globex', 'Streamly & Globex Studios'), ('Hooli', 'The Gavin Hooli Company'),
                     ('Wayfield Inc', 'Wayfield')]:
            self.assertTrue(gi.same_company(a, b), (a, b))
        for a, b in [('Meta', 'Metabase'), ('Cube', 'Cubesat Capital'), ('Pairing Group', 'Sparkly')]:
            self.assertFalse(gi.same_company(a, b), (a, b))

    def test_unknown_role_at_company_with_several_applications(self):
        rows = []
        for t in ('Chief of Staff, Product', 'Chief of Staff, Sales'):
            tracker.upsert(rows, {'company': 'Kestrel', 'title': t, 'status': 'applied', 'date_applied': '2026-07-01'})
        tracker.write(tracker.path_of(self.ws), rows)
        prop = gi.propose([{'id': 'k1', 'date': '2026-07-01', 'sender': 'no-reply@kestrel.example',
                            'subject': 'Thank you for applying to Kestrel', 'snippet': 'Thanks for applying to Kestrel.'}], self.ws)
        self.assertEqual(prop['rows'][0]['action'], 'which?')
        self.assertEqual(prop['rows'][0]['candidates'], ['Chief of Staff, Product', 'Chief of Staff, Sales'])
        with self.assertRaises(SystemExit):
            gi.apply(prop, self.ws, '1')

    def test_mbox(self):
        import mailbox
        from email.message import EmailMessage
        p = os.path.join(self.tmp, 'mail.mbox')
        box = mailbox.mbox(p)
        for i, (frm, subj, body) in enumerate([
                ('Brightwater <no-reply@us.greenhouse-mail.io>', 'Thank you for applying to Brightwater', 'Thanks for applying for the Chief of Staff role.'),
                ('Mom <mom@example.org>', 'Dinner', 'See you Sunday')]):
            m = EmailMessage()
            m['From'], m['Subject'], m['Date'] = frm, subj, 'Mon, 05 Oct 2026 10:00:00 -0000'
            m['Message-ID'] = f'<x{i}@example>'
            m.set_content(body)
            box.add(m)
        box.flush()
        out = gi.from_mbox(p, since='6m', today=__import__('datetime').date(2026, 10, 20))
        self.assertEqual([m['id'] for m in out], ['x0@example'])
        self.assertEqual(out[0]['date'], '2026-10-05')


if __name__ == '__main__':
    unittest.main()


sys.path.insert(0, HERE)
from private_workspace import private_workspace  # noqa: E402
VAULT = private_workspace() or os.path.join(HERE, 'no-private-workspace')
PRIVATE_PACK = os.path.join(VAULT, 'pack.json')


# The pack's one deliberate widening of the original title filter: "Senior Manager of Product, ..." style titles
# (manager of product), which the original pipeline missed. Only a title the original's include pattern doesn't
# match at all, and this one does, may differ; every other title and every score must still match exactly.
WIDER_TITLE = re.compile(r'^(\([^)]*\)\s*)?((senior|sr\.?|staff|principal|lead|group)\s+)*manager,? (of )?product'
                         r'( management)?(\s*[,:(|-]|\s+[\u2013\u2014]|$)', re.I)


@unittest.skipUnless(os.path.exists(os.path.join(VAULT, 'Pipeline', 'score.py')) and os.path.exists(PRIVATE_PACK),
                     'needs the original pipeline vault and the migrated workspace (set GMH_PRIVATE_WORKSPACE)')
class LegacyParityTest(unittest.TestCase):
    """A private pack reproduces the original score.py and discover.py title filter exactly."""

    def test_pack_matches_score_py(self):
        import glob, importlib
        sys.path.insert(0, os.path.join(VAULT, 'Pipeline'))
        try:
            score, discover = importlib.import_module('score'), importlib.import_module('discover')
        finally:
            sys.path.pop(0)
        pk = packs.load(PRIVATE_PACK)
        master = open(os.path.join(VAULT, 'master-resume.md'), encoding='utf-8').read()
        n = 0
        for f in sorted(glob.glob(os.path.join(VAULT, 'Pipeline', 'queue', 'discovered-*.csv'))):
            for r in csv.DictReader(open(f, encoding='utf-8', newline='')):
                jp = os.path.join(VAULT, 'Pipeline', 'state', 'jd', r['id'] + '.txt')
                if os.path.exists(jp):
                    jd = open(jp, encoding='utf-8').read()
                    self.assertEqual(score.score(r, jd), packs.score(pk, r['title'], jd, master, r['salary_max']), r['id'])
                    old, new = discover.title_ok(r['title']), packs.title_ok(pk, r['title'])
                    if not (old is False and new and WIDER_TITLE.search(r['title']) and not discover.INC_RE.search(r['title'])):
                        self.assertEqual(old, new, r['title'])
                    n += 1
        self.assertGreater(n, 100)
