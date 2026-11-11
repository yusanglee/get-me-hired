---
name: platforms
description: How get-me-hired runs on Claude Code, Codex, Gemini CLI and Antigravity CLI, and the fallback for every step tied to one tool (finding gmh and the workspace, questions, agents, the model, the review page, Gmail, Sheets, local pages, the browser, submitting). Read when a step names a tool feature this session lacks.
---

# Platforms and fallbacks

Claude Code is the primary platform. Codex, Gemini CLI and Antigravity CLI support is experimental and untested. Every step that
depends on one tool has a fallback here, so a skill never stops for want of a feature.

## Contents
- [Finding gmh](#finding-gmh)
- [Finding the workspace](#finding-the-workspace)
- [Setting up for each tool](#setting-up-for-each-tool)
- [Running a skill](#running-a-skill)
- [Questions to the user](#questions-to-the-user)
- [Agents](#agents)
- [The session's model](#the-sessions-model)
- [Long commands](#long-commands)
- [Saving agent replies](#saving-agent-replies)
- [The review page](#the-review-page)
- [Gmail](#gmail)
- [Google Sheets](#google-sheets)
- [Local pages](#local-pages)
- [The browser](#the-browser)
- [Submitting](#submitting)

## Finding gmh
`gmh` is the engine's command line. Use the first that works (`gmh --help` lists the commands):
1. Claude Code with the plugin installed: plain `gmh` (the plugin's `bin/` folder is on the PATH).
2. `"${CLAUDE_PLUGIN_ROOT}/bin/gmh"` when that variable is set.
3. From the skill's own folder: `<skill folder>/../../bin/gmh` (Windows: `<skill folder>\..\..\bin\gmh.cmd`).
4. Antigravity CLI: `${PLUGIN_ROOT}/bin/gmh`, or `~/.gemini/config/plugins/get-me-hired/bin/gmh` (installed plugins are
   staged there).
5. The `Engine:` line in the workspace's context file (`CLAUDE.md`, `AGENTS.md` or `GEMINI.md`; Antigravity uses `AGENTS.md`).

It needs Python 3.9 or newer (`python3`, `python` or `py -3`). If none is found, tell the user to install Python
from python.org and stop.

## Finding the workspace
`$GMH_WORKSPACE`; else the folder this session is open in, if it holds `config.json`; else ask the user. Skills
write it as `<ws>`: pass `--workspace <ws>` to every command that takes it.

## Setting up for each tool
The setup skill runs the same on every tool; only these lines differ. The engine never guesses the tool from the
environment: it uses `--tool`, else `$GMH_TOOL`, else Claude Code. If you aren't sure which tool this session is, ask.
- **Claude Code:** `gmh setup init <folder> --pack later` writes the context file `CLAUDE.md`. The agents load with
  the plugin; a checkout without the plugin installed needs `gmh setup agents` once. Offer
  `gmh setup permissions --workspace <ws>`, which merges a suggested deny list into `<ws>/.claude/settings.json`
  (Claude Code only; it keeps what is there).
- **Codex (experimental):** add `--tool codex` to `gmh setup init` and `gmh setup check` (or the user sets
  `GMH_TOOL=codex`), so the context file is `AGENTS.md`. Then `gmh setup agents --tool codex <ws>` writes the agents
  into `<ws>/.codex/agents/`.
- **Gemini CLI (experimental):** the same with `--tool gemini` (or `GMH_TOOL=gemini`): the context file is
  `GEMINI.md`, and `gmh setup agents --tool gemini <ws>` writes `<ws>/.gemini/agents/`. Gemini CLI needs a paid plan
  or an API key.
- **Antigravity CLI (experimental):** Google replaced Gemini CLI with Antigravity CLI for free, Google One and AI
  Pro/Ultra users (Gemini CLI remains for Code Assist Standard/Enterprise). Install with
  `agy plugin install https://github.com/yusanglee/get-me-hired` (or a local path; `agy plugin validate <dir>` checks
  it; `agy plugin import gemini` converts an installed Gemini extension). Then add `--tool antigravity` to
  `gmh setup init` and `gmh setup check` (or `GMH_TOOL=antigravity`): the context file is `AGENTS.md` and the
  engine line names `~/.gemini/config/plugins/get-me-hired`. `gmh setup agents --tool antigravity` installs nothing
  and exits 0: v1 installs no Antigravity agents.

## Running a skill
In Claude Code the user types `/get-me-hired:<name>` (for example `/get-me-hired:today`) or says what they want. In
other tools they ask for the skill by name ("use the get-me-hired today skill"). Skills point to each other by
relative path, such as `../linkedin-followup/SKILL.md`: open that file and follow it in this session.

## Questions to the user
Claude Code has a question tool with buttons. Without one, ask a numbered plain-text question: the question, then
the options as `1.`, `2.`, ... with the recommended one first, and wait for the reply. Either way the question
carries its own content ([questions.md](questions.md)).

## Agents
Launch each agent with its own type and the model from [agents.md](agents.md):
- **Claude Code:** the Agent tool with the agent's name as its type and the table's model. If the type isn't found
  (the plugin isn't installed, only checked out), run `gmh setup agents <ws>` once (sessions started after that load
  them), and for now launch a general-purpose agent with the table's model, giving it the text of
  `subagents/<name>.md` (in the plugin folder: `<skill folder>/../../subagents/<name>.md`) and then the prompt.
- **Codex:** the custom agent of that name, from `.codex/agents/` (`gmh setup agents --tool codex <ws>` writes them).
- **Gemini CLI:** the subagent of that name, from `.gemini/agents/` (`gmh setup agents --tool gemini <ws>`).
- **Antigravity CLI:** none installed by v1; do the agent's job here, as in the next line.
- **No agent feature, or the launch fails:** do the agent's job here. Read `subagents/<name>.md` and follow it
  exactly, keeping its limits (read only the files it names, return its JSON), one brief at a time.

Say once, in one line, when a fallback was used.

## The session's model
Approvals and submits are held by the session, so it should run on the strongest model the user has: Opus in
Claude Code (`/model opus`; a skill's `model:` line holds only for its first turn). In other tools, the most capable
model they offer. If the session is on a weaker model, say so once and suggest switching; don't refuse to work.

## Long commands
`gmh discover` can take 15 minutes or more. In Claude Code run it in the background and go on with other steps;
check that it finished before `gmh score`. Elsewhere, tell the user how long it may take, then run it and wait.

## Saving agent replies
An agent's JSON reply goes to the path its brief names (`reply_path`), or to the scratch folder path the skill gives
(`<ws>/Pipeline/scratch/<date>/<kind>-<key>.json`).
- **Claude Code:** don't type the reply out again. Run `gmh reply <output-file> <path>` with the `<output-file>` the
  agent's task notification gives: it saves the agent's own JSON word for word (retyping costs tokens and drifts) and
  prints `saved <path> (...)`. If it says there is no JSON reply, re-ask that agent once.
- **Other tools** (no output file): save the reply with the file-writing tool, as it came. No shell redirection is
  needed, so this works on every OS.

## The review page
- **Any session with an artifact tool (Claude Code with claude.ai artifacts):** always the user's private "Run Review"
  artifact, so its **Confirm choices** button works; the review-run skill says how to publish it. Never the local
  file, whatever the page's size: read a large page in parts, then publish.
- **Only tools with no artifact tool at all (Codex, Gemini CLI, Antigravity CLI, a plain terminal):** the local page
  `<ws>/run-review/run-review.html`, given to the user as a file link (or opened with
  `gmh review page --open --workspace <ws>` if they ask). Picks come back with the page's **Copy picks** button,
  pasted into chat.

## Gmail
- **Claude Code:** the Gmail connector (claude.ai, Settings, Connectors), read-only: `search_threads`,
  `get_thread`, `get_message`.
- **Other tools:** a Gmail MCP server with the same searches, if the user has one.
- **No Gmail access:** a Google Takeout export (takeout.google.com, Mail, `.mbox`) read with `gmh gmail from-mbox`.
  During the day, say in one line that Gmail isn't connected and carry on without it.

## Google Sheets
An optional one-way mirror of the tracker through a Google Sheets connector. Without one, skip it: `tracker.csv` and
`report.html` are the record.

## Local pages
The resume design editor serves a local page (`http://127.0.0.1:8765`). Claude Code's desktop app can show it in a
side pane (`preview_start`); anywhere else, give the user the URL to open in their browser.

## The browser
Forms are filled in the Playwright browser that ships with the plugin; its tools end in `browser_navigate`,
`browser_run_code_unsafe`, `browser_snapshot`. Never fill or upload with another browser tool or screen control:
they can't attach a local resume file. If the Playwright tools are missing, the user restarts their AI tool; it
needs Node.js (`node -v`) and Google Chrome (or `npx playwright install chrome`).

## Submitting
Approval comes first, in chat ([rules.md](rules.md), "Approval"). Then:
- **Claude Code:** the session runs the role's submit script (`browser_run_code_unsafe` with the `submit_script:`
  path `gmh fillplan` printed). The plugin's guard opens a permission prompt first, in every permission mode, for
  agents too. That prompt is a second check: the user allows it only for an application they approved in chat.
- **Codex (experimental):** Codex runs a hook's "ask" without asking, so the guard blocks every submit-capable call.
  Ask the user to click Submit in that role's tab and wait for them to say it went through. Never retry or work
  around the block.
- **Gemini CLI (experimental):** the extension's policy asks the user before any browser call that could submit.
  The extension's context file has the user click Submit, so ask them to, as on Codex; the policy is a backstop.
- **Antigravity CLI (experimental):** the session never runs a submit script. Ask the user to click Submit in that
  role's tab, as on Codex, and wait for them to say it went through. The plugin's hook (`hooks.json`, guard in
  `--mode antigravity`) answers `force_ask` to any browser call that could submit, if Antigravity honors it; that is
  untested and only a backstop. Never retry or work around a refusal.
- **Any tool:** the user may prefer to click Submit themselves. Then wait for them to say it went through.
