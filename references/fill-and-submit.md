---
name: fill-and-submit
description: Filling application forms up to Submit with the form-filler agent, one question per batch, submitting only the applications the user names, then recording them. Read before filling any form, for a whole queue or one role.
---

# Fill and submit

Forms are filled a tier at a time, A first, one role at a time (there is one browser). The session asks once per
batch which to submit, and submits only those. Rules: [rules.md](rules.md), "Approval".

## Before the first fill
- `gmh setup check --workspace <ws>` must say this computer can build resumes and fill forms; if not, tell the user
  what it prints and stop here.
- The Playwright browser tools must be present ([platforms.md](platforms.md), "The browser"). If they aren't, stop
  filling and tell the user; never fall back to another browser tool.
- Each role needs its application notes from `gmh notes` ([prepare.md](prepare.md)).

## Fill, one role at a time
1. `gmh fillplan <id> --workspace <ws>`. It prints `<id>: N fields planned -> state/fillplans/<id>.js` (the plan,
   inside `<ws>/Pipeline/`), an `apply_url:` line, a `submit_script:` line and `REVIEW` lines (fields the user should
   check). It refuses a role whose tailored resume fails its checks: rebuild it with `gmh tailor` and run it again.
2. Launch `form-filler` ([agents.md](agents.md)) with the role id, the `apply_url` and the plan's absolute path
   (`<ws>/Pipeline/state/fillplans/<id>.js`). If the browser can't read the plan there, copy it into
   `.playwright-mcp/` in this session's folder and pass that path. Wait for its JSON before the next role. If it
   reports no Playwright browser tools while this session has them (a Playwright server other than the plugin's),
   fill the role here instead, following [form-filler.md](../subagents/form-filler.md) exactly.
3. `gmh fills set <id> --status <its status> [--left "<item>"]... --workspace <ws>`, one `--left` per item in its
   `left`. Note its `tab` and its `review` list (the plan's `REVIEW` fields).

## One question per batch
4. `gmh fills show --date <day> <ids> --workspace <ws>` prints `id | company | title | status | left`. Ask once,
   with that table and each role's `review` fields inside the question, as
   [submit-batch.md](../templates/submit-batch.md) lays out.
5. The user does what is left (a captcha, an account, a missing answer) in that role's tab. When they say a role is
   done, `gmh fills set <id> --status ready --workspace <ws>`.

## Submit only what the user named
6. For each id the user named in their answer, one at a time: select the role's tab (`browser_tabs`), then run its
   submit script (`browser_run_code_unsafe` with `filename` set to the `submit_script:` path). The tool's own check
   comes next ([platforms.md](platforms.md), "Submitting"); on Codex and Gemini CLI, or when the user prefers, they
   click Submit and you wait for them to say it went through.
7. The script reports the confirmation or the form's validation errors. Fix errors with the user (from the plan's
   values or their answer, never a guess) and try again. Never submit from an agent, and never a role the user
   didn't name.

## Record
8. `gmh applied <id> ... --workspace <ws>` for the confirmed ones, one call for the batch. It refuses a role whose
   fill record isn't `ready`, and prints where that day's queue stands.
9. **Manual roles** (any ATS other than Greenhouse, Lever and Ashby): `gmh manual-notes --workspace <ws>` prepares
   their answers, builds the cover letter from any reviewed draft (`drafts/drafts-<date>.json` or
   `drafts-manual-<date>.json`) and prints a table with the posting and notes links. Show it. The user creates any
   account and submits; record each with `gmh applied` once they say it went through.
10. **A role that closed, or that the user drops:** `gmh review picks "pass <n>: <reason>" --workspace <ws>`, so it
    doesn't hold the queue open.
11. Then the next tier. When `gmh applied` says every role queued that day is applied, offer LinkedIn follow-up
    once ([linkedin-followup](../skills/linkedin-followup/SKILL.md)).
