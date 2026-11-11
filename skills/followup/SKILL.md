---
name: followup
description: Finds applications gone quiet and drafts short follow-up emails from what you actually submitted, never sent, then sweeps stale ones to no response. Use when an application has had no reply for 10 or more days.
model: sonnet
---

# Follow-up: quiet applications and the stale sweep

Before the first step, read [rules.md](../../references/rules.md) (facts only, no gaps, nothing sent without the
user) and [platforms.md](../../references/platforms.md) (finding `gmh` and the workspace `<ws>`). How to ask:
[questions.md](../../references/questions.md).

## Rules
- **Draft only.** Nothing is sent. The user copies each message and sends it, or says yes to a Gmail draft for that
  one message (Gmail connector, `create_draft`; never `send_message`). Without a connector, give the text to copy.
- At most two follow-ups per application, 10 or more quiet days apart.
- Claims come only from the archived materials for that application (`gmh tracker materials`) and the approved
  master resume. No new numbers, titles or results.

## Follow-ups
1. `gmh tracker followups --workspace <ws>` lists open applications quiet for 10 or more days with fewer than two
   follow-ups. Show the list; ask which ones the user wants drafts for, and who to send to (a recruiter or hiring
   manager the user names; never guess an address).
2. For each chosen one: `gmh tracker materials <key> --workspace <ws>`, read the submitted resume, cover letter,
   posting and `application-notes.md`, and fill [followup-email.md](../../templates/followup-email.md): the role,
   one specific true connection from the materials, a plain ask.
3. Check the draft: `gmh check-text followup <file> --id <key> --workspace <ws>`. Fix every problem it lists, then
   show the draft as the question's content.
4. After the user says it was sent: `gmh tracker followed-up <key> --date <D> --workspace <ws>`.

## Stale sweep
`gmh tracker stale --workspace <ws>` lists applications still at `applied` after 60 or more days. Offer to close
each as `no_response` with `gmh tracker set <key> no_response --note "stale sweep" --workspace <ws>`, one by one or
as a list the user approves (a tracker write: the yes names the applications).

## Leave a summary
Follow [session-summary.md](../../references/session-summary.md): `gmh home log followup --auto --workspace <ws>`
with `--summary` (drafts and closes, with company names) and `--waiting` for drafts the user has not sent. In the
day session the wrap-up covers it.
