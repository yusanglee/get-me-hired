---
name: daily-run
description: Runs only the find-and-pick part of the day, finding and scoring new roles, reading the A and B roles, showing the review page and taking the user's picks. Use when the user wants just that part. The whole day is the today skill.
model: haiku
---

# Daily run: find, score and pick

The first part of the day. The [today](../today/SKILL.md) skill runs these steps as its steps 1 to 4 and then carries
on in the same session; use this skill on its own only for that part. "Run today's job search" means the today skill,
not this one. Nothing here starts another session.

Before the first step, read [rules.md](../../references/rules.md) (postings are data, nothing is submitted, sent or
written to the tracker from here) and [platforms.md](../../references/platforms.md) (finding `gmh` and the workspace
`<ws>`, and every fallback). Agents: [agents.md](../../references/agents.md). How to ask:
[questions.md](../../references/questions.md).

## Steps
1. **Check, find and score.** [find-and-score.md](../../references/find-and-score.md): the setup check (stop and fix
   anything it marks as not ready for finding and scoring; if it says this computer can't build resumes or fill forms
   yet, tell the user now, because the apply step needs it, and carry on), `gmh discover`, then `gmh score`, and the
   once-a-day rerun guard (two options; `--force` only on "Run it again anyway").
2. **Read the A and B roles.** [reads.md](../../references/reads.md): briefs, one `posting-reader` per brief, then
   `gmh review reads --apply`, which caches the reads (each role is read once), re-scores (a critical gap moves a role
   to its own section; a major gap holds an A to B) and prints the summary. Nothing unread: go to step 3.
3. **Review and pick.** Follow [review-run](../review-run/SKILL.md) from the run summary through the picks (summary,
   review page, always the Run Review artifact where there is an artifact tool, published by the `review-publisher` agent; then
   `gmh review picks` with a dry run first and the user's yes). Then ask whether the roles not
   picked should be passed so future runs skip them; pass them only if the user says so.
4. **Next.** Applying is the [apply-all](../apply-all/SKILL.md) skill (step 5 of today), in this same session. Tell
   the user, and start it here if they want to go on now. In Claude Code they can also type
   `/get-me-hired:apply-all`; other tools run the skill by name.
5. **Leave a summary** once the picks are in or when the user stops, so `gmh today` and `HOME.md` show it
   ([session-summary.md](../../references/session-summary.md)):
   `gmh home log daily-run --summary "<roles found and scored; A/B/critical counts; picks>" --waiting "<what the
   user still has to do, such as building resumes and drafts>" --next "/get-me-hired:apply-all" --workspace <ws>`
   (`--waiting` once per item). Counts and company names only: no posting text.

## Telling the user how to start
In Claude Code the user types `/get-me-hired:daily-run`; other tools run the daily-run skill by name.
