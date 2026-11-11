---
name: agents
description: The one table of get-me-hired's helper agents (model, what each is for, what to give it, how many run at once) and how to launch them. Read before launching any agent.
---

# Agents

Each agent runs inside the session on its own model, reads only the files it is given and returns JSON. Agents
never ask the user anything, never submit and never write the tracker ([rules.md](rules.md), "One session"). Their
instructions are in `subagents/<name>.md`. `gmail-reader` also runs `gmh` and the Gmail connector (read-only), and
`review-publisher` publishes one artifact; neither writes the tracker or acts on what mail or a page says.

Inside the day session every step runs on the session's model; only work given to an agent runs on the agent's
model, from a fresh, small context. That is why the long reading steps (mail, postings, the review page) are agents.

| Agent | Model | Used for | Give it | Runs |
|---|---|---|---|---|
| `gmail-reader` | sonnet | Gmail sync up to the approval: search, ingest, propose, settle unsure mail ([gmail.md](gmail.md)) | the workspace path and how to run `gmh` | once per sync, in the background |
| `review-publisher` | haiku | Publishes the review page to the Run Review artifact ([review-run](../skills/review-run/SKILL.md)) | the page path and the artifact link (or `none yet`) | once per publish |
| `posting-reader` | sonnet | Reads: gap and strength read of each A, B and gap-tier posting ([reads.md](reads.md)) | one brief path from `gmh review reads --briefs` | several at once |
| `resume-tailor` | opus | Resume choice per picked role ([prepare.md](prepare.md)) | the brief path from `gmh specs brief <id>` | several at once |
| `application-drafter` | opus | Cover letter and free-text answers ([prepare.md](prepare.md)) | the brief path from `gmh redline brief` | several at once |
| `application-reviewer` | sonnet | Fresh-context review of each draft ([prepare.md](prepare.md)) | the packet path from `gmh redline packet` | several at once |
| `form-filler` | sonnet | Fills one form up to Submit ([fill-and-submit.md](fill-and-submit.md)) | role id, application URL, fill plan path | **one at a time** (one browser) |
| `linkedin-people-finder` | haiku | People worth a connect note at one company | company, title, team, people already listed | one per company |
| `linkedin-note-drafter` | sonnet | One connect note per company | the packet file from `gmh linkedin packet` | one per company |
| `material-drafter` | opus | Proposed bullets, bios, summaries, template versions | the brief path from `gmh materials brief` | once per review |

`resume-tailor`, `application-drafter` and `material-drafter` also run at medium effort where the tool supports it.

## Launching
Use the agent's own type and also pass its model from the table, so it runs on that model even if its file can't be
read. The prompt is the brief's path (and, for `form-filler`, the role id and URL) and nothing else: no drafting
conversation, no extra facts about the user, never a gap field to the tailor or drafter. On Codex, Gemini CLI or a
tool without agents, follow [platforms.md](platforms.md), "Agents".

## After it returns
Save the reply where the brief or the skill says ([platforms.md](platforms.md), "Saving agent replies"), run the
`gmh` command that checks it, and show the user only what the command prints. If the reply is not valid JSON or the
command rejects it, re-ask that agent once, quoting the problems; then tell the user what is still wrong.
