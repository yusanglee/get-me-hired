"""The skills, references and agents follow the one-session design and keep their safety rules. Pinned phrases are
checked against a skill's bundle (its SKILL.md plus the files it links to), so text can move between a skill and a
shared reference without weakening the checks."""
import glob, os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_skills_structure import REPO, bundle, frontmatter, skill_docs, text  # noqa: E402

# Wording from the retired multi-session design. A session can't start another on a higher model than its own, so
# none of this may come back.
STARTS_A_SESSION = [
    r'as a new session', r'start a new, separate session', r'in its own session', r'starts the apply session',
    r"start the user's home session", r'a tool that starts a new session', r'hand(s)? (applying|off) to (a|the) ',
    r'one-click task card', r'start it as a session', r'opens the day.s run in its own session', r'as its own session',
]


def ref(name):
    return text(os.path.join(REPO, 'references', name + '.md'))


def flat(t):
    return re.sub(r'\s+', ' ', t)


def shipped_docs():
    return sorted(skill_docs() + glob.glob(os.path.join(REPO, 'commands', '*.md'))
                  + [os.path.join(REPO, 'docs', 'GUIDE.md'), os.path.join(REPO, 'README.md')])


class OneSession(unittest.TestCase):
    def test_nothing_starts_a_session(self):
        for p in shipped_docs():
            t = text(p)
            for pat in STARTS_A_SESSION:
                self.assertIsNone(re.search(pat, t, re.I), f'{os.path.relpath(p, REPO)}: "{pat}"')

    def test_every_agent_names_a_model(self):
        for p in glob.glob(os.path.join(REPO, 'subagents', '*.md')):
            fm = frontmatter(p)
            self.assertIn(fm.get('model'), ('haiku', 'sonnet', 'opus'), p)
            self.assertEqual(fm.get('name'), os.path.basename(p)[:-3], p)

    def test_today_is_opus_and_keeps_approvals_in_the_session(self):
        self.assertEqual(frontmatter(os.path.join(REPO, 'skills', 'today', 'SKILL.md'))['model'], 'opus')
        t = flat(bundle('today'))
        self.assertIn('Never start another session on your own', t)
        self.assertIn('only when the user explicitly asks for one', t)
        self.assertIn('These stay in this session, never in an agent', t)
        self.assertIn('Agents never ask the user anything, never submit and never write the tracker', t)

    def test_setup_is_opus_and_has_no_default_pack(self):
        fm = frontmatter(os.path.join(REPO, 'skills', 'setup', 'SKILL.md'))
        self.assertEqual((fm['model'], fm['effort']), ('opus', 'medium'))
        t = flat(bundle('setup'))
        self.assertIn('gmh setup init <folder> --pack later', t)
        self.assertIn('There is no default pack', t)
        self.assertIn('Legal attestations are asked exactly', t)
        self.assertIn('Resume bullets are the user\'s words', t)

    def test_today_syncs_gmail_at_the_start_and_at_wrap_up(self):
        t = text(os.path.join(REPO, 'skills', 'today', 'SKILL.md'))
        start = t[t.index('2a. **Gmail sync at the start of the day**'):t.index('3. **Reads**')]
        self.assertIn('../../references/gmail.md', start)
        self.assertIn('Every tracker write is a row the user', start)
        self.assertIn('Every tracker write is a row the user approved', flat(ref('gmail')))
        wrap = text(os.path.join(REPO, 'skills', 'today', 'references', 'wrap-up.md'))
        self.assertIn('Gmail sync', wrap)
        self.assertLess(wrap.index('Gmail sync'), wrap.index('gmh home log today'))
        self.assertIn('gmh tracker report', wrap)
        self.assertIn('references/wrap-up.md', t[t.index('9. **Wrap up**'):])

    def test_questions_carry_their_own_content(self):
        for name in ('today', 'materials'):
            self.assertIn('A question carries its own content', bundle(name), name)
        m = bundle('materials')
        self.assertIn('word for word', m)
        self.assertIn('gmh materials reopen <pid>', m)
        q = ref('questions')
        self.assertIn('about 20 items per question', q)
        for tpl in ('resume-choice', 'review-drafts', 'submit-batch', 'day-summary'):
            self.assertIn(f'../templates/{tpl}.md', q, tpl)

    def test_resume_updates_come_before_the_resumes_they_help(self):
        t = text(os.path.join(REPO, 'skills', 'today', 'SKILL.md'))
        step5 = t[t.index('5. **Prepare**'):t.index('6. **Fill and submit')]
        self.assertLess(step5.index('gmh materials candidates --date'), step5.index('`resume-tailor` per role'))
        p = ref('prepare')
        self.assertLess(p.index('gmh materials candidates --date'), p.index('Launch `resume-tailor`'))
        self.assertLess(p.index('Launch `resume-tailor`'), p.index('gmh tailor '))
        self.assertIn('re-tailor', p)

    def test_resumes_build_without_a_per_role_review(self):
        p = ref('prepare')
        self.assertIn('No per-role review', p)
        self.assertNotIn('get the user\'s OK on each', p.lower())
        build = p[p.index('## Build the resumes'):p.index('## Answers')]
        self.assertLess(build.index('gmh specs '), build.index('gmh tailor '))
        self.assertIn('Ask only about failures', build)
        t = text(os.path.join(REPO, 'skills', 'today', 'SKILL.md'))
        self.assertNotIn("OK on each resume choice", t)
        self.assertIn('ask only about the failures', flat(t))

    def test_one_missing_rule(self):
        p = ref('prepare')
        rule = p[p.index('## The missing rule'):p.index('## Build the resumes')]
        self.assertIn('`gmh specs accept` saves them', flat(rule))
        self.assertIn('never change a resume by themselves', rule)
        self.assertIn('Add bullets and re-tailor those roles', rule)
        self.assertIn('Keep these resumes', rule)
        for path in skill_docs():
            if os.path.basename(path) in ('prepare.md', 'resume-tailor.md', 'glossary.md'):
                continue
            self.assertNotIn('Add bullets and re-tailor', text(path), path)  # stated once

    def test_submit_approval_is_defined_once_and_the_prompt_is_a_second_check(self):
        r = ref('rules')
        self.assertIn("Submit approval is the user's yes in chat to a question that names that application", r)
        self.assertIn("The platform's own check comes second", r)
        for p in skill_docs() + glob.glob(os.path.join(REPO, 'commands', '*.md')):
            self.assertNotRegex(text(p), r'prompt is the approval', p)
        plat = ref('platforms')
        sub = plat[plat.index('## Submitting'):]
        for tool in ('Claude Code', 'Codex', 'Gemini CLI'):
            self.assertIn(f'**{tool}', sub, tool)
        self.assertIn('click Submit', sub)

    def test_fill_and_submit_asks_once_and_submits_only_named_roles(self):
        f = ref('fill-and-submit')
        self.assertIn('**one at a time**', text(os.path.join(REPO, 'references', 'agents.md')))
        self.assertIn('Ask once', f)
        self.assertIn("never a role the user didn't name", flat(f))
        self.assertIn('gmh applied <id> ... --workspace <ws>', f)
        self.assertLess(f.index('gmh fills show'), f.index('submit script'))
        self.assertIn('Reply with the ids to submit', text(os.path.join(REPO, 'templates', 'submit-batch.md')))

    def test_drafts_honor_ai_policy_and_never_get_gaps(self):
        r = ref('rules')
        self.assertIn('Never pass a gap field (`gap_type`, `top_gap`, `gap_quote`)', r)
        self.assertIn('`banned`', r)
        self.assertIn('`ai_policy`', ref('prepare'))
        self.assertIn('ai_policy', text(os.path.join(REPO, 'subagents', 'application-drafter.md')))

    def test_reads_cover_a_b_and_gap(self):
        self.assertIn('reads cover tiers A, B and gap', ref('reads'))
        self.assertIn('gmh review reads --briefs', ref('reads'))
        self.assertIn('gmh review reads --apply <reply file> <reply file>', ref('reads'))

    def test_form_filler_never_submits(self):
        p = os.path.join(REPO, 'subagents', 'form-filler.md')
        t = text(p)
        self.assertIn('**Never submit.**', t)
        self.assertIn('tools/submit/', t)  # named as off limits
        self.assertNotIn('submit_greenhouse', t)
        self.assertIn('**Never press Enter by hand**', t)
        self.assertIn('`submit: true`', t)
        tools = [x.strip() for x in frontmatter(p)['tools'].split(',')]
        self.assertIn('Read', tools)
        self.assertTrue(all(x == 'Read' or re.match(r'mcp__plugin_get-me-hired_playwright__browser_[a-z_]+$', x)
                            for x in tools), tools)
        for banned in ('browser_press_key', 'browser_evaluate', 'browser_run_code', 'Bash'):
            self.assertNotIn('mcp__plugin_get-me-hired_playwright__' + banned, tools)
        self.assertIn('mcp__plugin_get-me-hired_playwright__browser_run_code_unsafe', tools)

    def test_agents_keep_their_safety_clause_in_the_body(self):
        for p in glob.glob(os.path.join(REPO, 'subagents', '*.md')):
            body = text(p).split('\n---\n', 1)[1]
            self.assertRegex(body, r'(?i)read-only|never (submit|sign in)', p)


if __name__ == '__main__':
    unittest.main()
