---
name: wrap-up
description: The end of the day in the today skill (Gmail sync again, where the day stands, leftover resume updates, the day summary, the session log, the dashboard). Read when the user says wrap up or done for today.
---

# Wrap up the day

1. **Gmail sync** first, the same way as at the start ([gmail.md](../../../references/gmail.md)), the user approving
   each row. It picks up today's confirmations, rejections and interview invites.
2. `gmh today --workspace <ws>` once more.
3. **What's left of the resume updates** (ideas skipped or found after the resumes were built):
   `gmh materials candidates --workspace <ws>`. If it lists any, or bios on built resumes that aren't approved, say
   how many and offer once to review them now ([materials](../../materials/SKILL.md), in this session) or another
   day.
4. Show the day as [day-summary.md](../../../templates/day-summary.md) lays it out, from `gmh today` and the sync:
   the sync's updates (rejections, interviews, offers), roles found and scored, picks, applied, held and passed, and
   LinkedIn companies done. Counts and company names only.
5. `gmh home log today --auto --waiting "<each thing left for the user>" --next "<what tomorrow starts with>"
   --workspace <ws>` ([session-summary.md](../../../references/session-summary.md)).
6. `gmh tracker report --workspace <ws>` rebuilds the dashboard with the day's last statuses.
7. Tell the user what is waiting tomorrow and that they can close this session. Tomorrow: a new session on the
   strongest model, then `/get-me-hired:today` in Claude Code (other tools: the today skill by name).
