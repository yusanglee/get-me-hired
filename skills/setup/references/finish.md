---
name: finish
description: Setup step 10 - the tracker and an optional Sheet mirror, importing past applications, installing the resume tools, the final check, the browser, and telling the user how each day starts. Read once the role pack is approved.
---

# Finish setup

## Tracker
`tracker.csv` and `report.html` already exist and are always the source of truth. Offer an optional Google Sheet
mirror ([platforms.md](../../../references/platforms.md), "Google Sheets"): with a Sheets connector, create a sheet
with the tracker's columns and record its id in `config.json` as `tracker.sheet_id`. The mirror is one way: the CSV
is never overwritten from the Sheet.

## Past applications
Offer [import-history](../../import-history/SKILL.md) to load past applications from email, so duplicate checks and
company caps know about them. Imported history is for those checks only: LinkedIn follow-up covers roles applied
through get-me-hired, plus imported ones applied in the last 7 days (`linkedin.gmail_followup_days` in
`config.json`).

## Tools and the final check
1. `gmh setup tools --workspace <ws>` installs the resume builder's Node package into the workspace, so it survives
   plugin updates. If it says Node.js or npm is missing, give the install hint it prints.
2. `gmh setup check <ws>` and show the result. If it reports LibreOffice or `pdftotext` (poppler) missing, give the
   install line it prints. Fix anything it marks as not ready.
3. Check that the Playwright browser tools are available (`browser_navigate`): applications are filled there,
   resume uploads included. If they're missing, see [platforms.md](../../../references/platforms.md), "The browser".
4. For a checkout without the plugin installed, or on Codex or Gemini CLI, set up the agents too
   ([platforms.md](../../../references/platforms.md), "Setting up for each tool").
5. **Claude Code only:** offer `gmh setup permissions --workspace <ws>`. It merges a suggested deny list into
   `<ws>/.claude/settings.json` (no piping downloads into a shell, no `rm -rf`, no `git push`, no reading `~/.ssh`,
   `~/.aws` or `.env` files, no direct edits to `tracker.csv`) and keeps what is already there. Tell the user what it
   adds and run it only if they say yes. Skip it on Codex and Gemini CLI.

## How each day starts
1. `gmh home --workspace <ws>` writes `<ws>/HOME.md`: how to start each day, what the user can ask for, and links
   to the tracker, dashboard, resumes, settings and the rest.
2. Tell the user to set `GMH_WORKSPACE=<ws>`, or always open their AI tool in that folder (its context file holds
   the rules).
3. Tell them, in plain words: each day, open a new session in `<ws>` (the desktop app, a terminal tab, or a new chat
   in their editor), switch it to the strongest model (`/model opus` in Claude Code), and run `/get-me-hired:today`
   or say "run today's job search" (other tools: the today skill by name). That one session takes them through the
   whole day; helpers on other models run inside it, and nothing opens another session. Say "wrap up" at the end of
   the day; tomorrow, a new session. HOME.md holds the same and the links.
4. Don't start a session for them: they open it. This setup session is done; leave a summary
   ([session-summary.md](../../../references/session-summary.md)) with `gmh home log setup --auto`.
