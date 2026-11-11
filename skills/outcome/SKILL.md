---
name: outcome
description: Records one application's outcome or status change (assessment, interview, offer, rejection, withdrawal, no response) after you confirm it. Use when you hear back, or news did not come by email.
model: haiku
---

# Outcome: update one application

Before the first step, read [rules.md](../../references/rules.md) (a tracker write needs the user's yes for that
item) and [platforms.md](../../references/platforms.md) (finding `gmh` and the workspace `<ws>`; no Sheets connector
means skip the mirror). How to ask: [questions.md](../../references/questions.md).

## Steps
1. **Find the application.** `gmh tracker find "<the user's words>" --workspace <ws>` returns up to five rows, best
   first (`gmh tracker status --workspace <ws>` gives counts). Show the match back (company, title, current status)
   and confirm it is the right one.
2. **Confirm the new status**, its date (default today) and an optional short note. The statuses come from
   `gmh tracker statuses`, which marks the ones that close an application.
3. **Only after the user says yes:** `gmh tracker set <id|job_key> <status> --date <D> --note "<N>" --workspace
   <ws>`. At `interviewing` or `offer` this also moves the row's folder from `Workflow/03-Applied` to
   `Workflow/04-Interviewing` and updates its `folder` cell; tell the user the new path. An existing destination is
   left alone and reported.
4. **Rebuild the dashboard:** `gmh tracker report --workspace <ws>`. If `config.json` has `tracker.sheet_id`, a
   Sheets connector is connected and the user wants it, mirror with `gmh tracker sheet-rows --workspace <ws>`, add
   or update those rows, then `gmh tracker sheet-rows --mark --workspace <ws>`.
5. At `interviewing`, offer [interview](../interview/SKILL.md) for a prep pack.

When the news came by email, prefer [gmail-sync](../gmail-sync/SKILL.md): it finds and cites the message.

## Leave a summary
Follow [session-summary.md](../../references/session-summary.md): `gmh home log outcome --auto --workspace <ws>`
with `--summary` (company and new status). In the day session the wrap-up covers it.
