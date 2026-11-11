"""Fixes from the first real v1.0 day (Nov 10): local agent copies find the user's Playwright server, gmh reply saves
an agent's reply word for word, the day keeps going between steps, the long reading steps run as agents."""
import contextlib, io, json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from engine import agent_reply, platforms, setup  # noqa: E402


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding='utf-8') as fh:
        return fh.read()


def tools_line(text):
    return next(l for l in text.splitlines() if l.startswith('tools:'))


class LocalAgentCopies(unittest.TestCase):
    def test_form_filler_copy_lists_every_playwright_server_name(self):
        local = setup.agent_files('claude')['form-filler.md']
        line = tools_line(local)
        for prefix in platforms.LOCAL_PLAYWRIGHT:
            self.assertIn(prefix + 'browser_file_upload', line)
            self.assertIn(prefix + 'browser_run_code_unsafe', line)
        self.assertIn('Read', line)
        # only the tools line changes
        src = read('subagents', 'form-filler.md')
        self.assertEqual(local.replace(line, ''), src.replace(tools_line(src), ''))

    def test_plugin_file_keeps_the_plugin_names(self):
        line = tools_line(read('subagents', 'form-filler.md'))
        self.assertIn(platforms.PLUGIN_PLAYWRIGHT, line)
        self.assertNotIn('mcp__playwright__', line)

    def test_agents_without_playwright_are_copied_as_they_are(self):
        files = setup.agent_files('claude')
        for name in ('posting-reader', 'resume-tailor', 'gmail-reader', 'review-publisher'):
            self.assertEqual(files[name + '.md'], read('subagents', name + '.md'))

    def test_install_writes_the_local_form(self):
        d = tempfile.mkdtemp()
        try:
            setup.install_agents(d, 'claude')
            with open(os.path.join(d, '.claude', 'agents', 'form-filler.md'), encoding='utf-8') as fh:
                self.assertIn('mcp__plugin_playwright_playwright__browser_click', fh.read())
            self.assertEqual(set(setup.agents_status(d, 'claude').values()), {'ok'})
        finally:
            shutil.rmtree(d)


def transcript(*assistant_texts):
    lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '/path/brief.json'}})]
    for t in assistant_texts:
        lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant',
                                                                  'content': [{'type': 'text', 'text': t}]}}))
        lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant',
                                                                  'content': [{'type': 'tool_use', 'name': 'Read'}]}}))
    return '\n'.join(lines) + '\n'


class Reply(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def put(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        return p

    def run_cli(self, *argv):
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                agent_reply.main(list(argv))
            except SystemExit as e:
                code = 1 if e.code else 0
                err.write(str(e.code or ''))
        return code, out.getvalue(), err.getvalue()

    def test_last_message_of_a_transcript_fenced(self):
        reply = {'rows': [{'id': 'gh-brightwater-1', 'gap_type': 'minor', 'top_gap': 'Ads — "quoted"'}]}
        src = self.put('a.output', transcript('Reading the brief.', '```json\n' + json.dumps(reply, ensure_ascii=False) + '\n```'))
        out = os.path.join(self.d, 'sub', 'reply.json')
        code, printed, err = self.run_cli(src, out)
        self.assertEqual(code, 0, err)
        with open(out, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh), reply)
        self.assertIn('rows: 1', printed)

    def test_plain_file_and_bare_json(self):
        src = self.put('reply.txt', 'Here it is:\n[{"old_string": "a", "new_string": "b"}]\nDone.')
        self.assertEqual(agent_reply.save(src, os.path.join(self.d, 'r.json')), [{'old_string': 'a', 'new_string': 'b'}])

    def test_no_json_writes_nothing(self):
        src = self.put('a.output', transcript('I could not read the brief.'))
        out = os.path.join(self.d, 'r.json')
        code, _, err = self.run_cli(src, out)
        self.assertEqual(code, 1)
        self.assertIn('no JSON reply', err)
        self.assertFalse(os.path.exists(out))

    def test_launcher_knows_the_command(self):
        from engine.__main__ import COMMANDS
        self.assertEqual(COMMANDS['reply'][0], 'engine.agent_reply')


class DayFlow(unittest.TestCase):
    def test_today_keeps_going_between_steps(self):
        t = read('skills', 'today', 'SKILL.md')
        self.assertIn('Keep going between steps', t)
        for bit in ('reads start when score finishes', 'the review page opens', 'prepare starts once the'):
            self.assertIn(bit, t.replace('\n', ' ').replace('   ', ' '))
        self.assertIn("don't read engine source", t.replace('\n', ' '))

    def test_long_reading_steps_are_agents(self):
        self.assertIn('gmail-reader', read('references', 'gmail.md'))
        self.assertIn('review-publisher', read('skills', 'review-run', 'references', 'review-page.md'))
        agents = read('references', 'agents.md')
        for name in ('gmail-reader', 'review-publisher'):
            self.assertIn(f'| `{name}` |', agents)

    def test_gmail_reader_never_applies(self):
        t = read('subagents', 'gmail-reader.md')
        self.assertIn('Never run `gmh gmail apply`', t)
        self.assertIn('gmh gmail settle', t)

    def test_replies_saved_with_gmh_reply(self):
        self.assertIn('gmh reply <output-file>', read('references', 'platforms.md'))
        self.assertIn('gmh reply', read('references', 'reads.md'))
        self.assertEqual(read('references', 'prepare.md').count('`gmh reply`'), 3)


if __name__ == '__main__':
    unittest.main()
