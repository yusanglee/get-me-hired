---
name: session-summary
description: Leaving a short summary when a skill's task ends (gmh home log with --auto), so gmh today and HOME.md show where things stand. Read at the end of any skill, or when the user stops.
---

# Leave a summary

When a skill's task is done, or the user stops, record how it ended:

`gmh home log <task> --auto [--summary "<anything the counts don't say>"] [--waiting "<one thing left for the user>"]... [--next "<what to run next>"] --workspace <ws>`

- `<task>` is the skill's name (`today`, `gmail-sync`, `materials`, ...).
- `--auto` fills the counts from the day's files: Gmail sync, roles found and scored by tier, picks, the queue
  (applied, filled and waiting, needing the user, manual), applications recorded that day and LinkedIn companies
  done.
- `--waiting` once per item left for the user (a manual apply, a captcha, an approval); leave it out when nothing
  is. `--next` names what to run next, if anything.
- Counts and company names only: no posting or email text, no personal details ([rules.md](rules.md),
  "Summaries").

It refreshes `<ws>/HOME.md`. Inside the day session the wrap-up writes one summary for the whole day, so a skill
run as part of the day leaves its summary to the wrap-up.
