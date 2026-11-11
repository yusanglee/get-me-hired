---
name: today
description: Runs the whole job-search day in one session, from Gmail sync, finding and scoring roles, reads and picks through resumes, drafts, forms filled up to Submit, submit approvals, LinkedIn follow-up and wrap-up. Use to start each day (run today's job search) or to pick a day up again.
argument-hint: "[YYYY-MM-DD to pick up an earlier day, default today]"
model: opus
---

# Today: the whole day in one session

The one skill to start each day; "run today's job search" means the same. The whole day runs **in this session**:
every step that needs its own model runs as an agent inside it, and nothing starts another session. At the end the
user says "wrap up"; tomorrow they open a new session and start again. If the session closes or compacts mid-day, a
new one picks up from the files (`gmh today`).

Before the first step, read [rules.md](../../references/rules.md) (approvals, data, facts, no gaps, one session) and
[platforms.md](../../references/platforms.md) (finding `gmh` and the workspace `<ws>`, and every fallback). Agents
and their models: [agents.md](../../references/agents.md). How to ask: [questions.md](../../references/questions.md).

## The session's model
This session holds the approvals and the submits all day, so it should be on the strongest model (Opus in Claude
Code). On the first run, check which model it is on. If it isn't, say so once, in one line, and ask the user to
switch (`/model opus`) before going on. Don't refuse to work if they decline.

## Steps
`gmh today` ends with the suggested next step and its name (`[step: find]`); the names are in brackets below.

**Keep going between steps.** Don't end a turn or ask to start the next step: the Gmail sync starts while discover
runs, reads start when score finishes, the review page opens when the reads are applied, and prepare starts once the
picks are written. Stop only for what the user decides ([rules.md](../../references/rules.md): Gmail rows for the
tracker, the picks, the one `missing` question, new form answers, drafts with open checks, submits), when a step fails, or when the
user asks to stop. A failing `gmh` command is reported in one line with its error and the day goes on without that
step where it can; don't read engine source in this session to debug it.

0. **Where are we?** `gmh today --workspace <ws>` (add `--json` for the ids). Show its lines as printed. On a new
   day, start step 1 right away. Ask first only when work is open from an earlier day (offer that queue or today's
   run, in one question) or the user asked for something else (step 8). With a date argument, work that day's queue
   (`--date <day>`) and skip steps 2 to 4.
1. **Check** [check]: [find-and-score.md](../../references/find-and-score.md), step 1.
2. **Find and score** [find, score]: [find-and-score.md](../../references/find-and-score.md), including the rerun
   guard (two options; `--force` only on "Run it again anyway"). While discover runs, do the Gmail sync (step 2a);
   then score, and go on to the reads.
2a. **Gmail sync at the start of the day**, whenever `gmh today` says it hasn't run today (also on a day with
   nothing to find): [gmail.md](../../references/gmail.md), the reading done by the `gmail-reader` agent in the
   background while discover runs. Every tracker write is a row the user
   approved. If Gmail isn't connected, say so in one line and carry on with the day without it. An application the
   sync adds (made outside get-me-hired) is caught by the applied-check in step 5 if today's run found it too.
3. **Reads** [reads]: [reads.md](../../references/reads.md), for every A, B and gap-tier role not read yet, started
   as soon as score finishes. Then the review page, without asking.
4. **Review and pick** [pick]: [review-run](../review-run/SKILL.md), from the run summary through the picks (the
   review page, always published to the user's Run Review artifact by the `review-publisher` agent where there is an
   artifact tool, never the local file; then `gmh review picks` with a dry run first and the user's yes). In that same question, ask whether the
   roles not picked should be passed; pass them only if the user says so. Then prepare, without asking.
5. **Prepare** [prepare]: [prepare.md](../../references/prepare.md), in its order:
   a. the applied-check (stop on any role already applied to), the open-check, and reads for picks with none;
   b. **resume updates for today's picks, before any resume is built** (`gmh materials candidates --date <day>`),
      offered once;
   c. `resume-tailor` per role and `gmh specs accept` (no per-role review); the one `missing` question if any; then
      build every accepted resume (`gmh specs`, `gmh tailor`), show one line per role (company, template, PASS or
      FAIL) and ask only about the failures;
   d. forms, answers (new questions to the user once, batched); then `application-drafter` and
      `application-reviewer` per role (no per-role text review: one line per role, ask only about open checks); then
      `gmh notes` right away.
6. **Fill and submit in batches by tier, A first** [fill, submit]:
   [fill-and-submit.md](../../references/fill-and-submit.md). `form-filler` fills one role at a time; one question
   per batch names each role; only the ids the user names are submitted, from this session; `gmh applied` records
   the confirmed ones. Manual roles: `gmh manual-notes`, then the user applies. An earlier day's queue [earlier]:
   steps 5 and 6 with `--date <day>`.
7. **LinkedIn follow-up, optional** [linkedin]: when `gmh applied` says the day's queue is done, offer it once; also
   whenever the user asks. Follow [linkedin-followup](../linkedin-followup/SKILL.md) in this session (its rules
   hold: the user clicks and sends everything). The company loop stays here; people search is the
   `linkedin-people-finder` agent; the note is the `linkedin-note-drafter` agent, given the path
   `gmh linkedin packet <key> --workspace <ws>` prints, and its note is checked with `gmh linkedin table` as that
   skill says.
8. **Anything else the user asks for today**, in this session, following that skill:
   [gmail-sync](../gmail-sync/SKILL.md), [outcome](../outcome/SKILL.md), [followup](../followup/SKILL.md),
   [interview](../interview/SKILL.md), the resume look ([design](../design/SKILL.md)) or resume updates
   ([materials](../materials/SKILL.md)). Their own summary step becomes part of the wrap-up.
9. **Wrap up** [wrap] when the user says so ("wrap up", "done for today"):
   [wrap-up.md](references/wrap-up.md): a Gmail sync first, then the day's summary, `gmh home log today --auto`
   and `gmh tracker report`.

## Telling the user how to start
In Claude Code the user types `/get-me-hired:today` or says "run today's job search"; other tools run the today
skill by name.
