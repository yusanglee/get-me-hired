---
name: design
description: Changes how resumes and cover letters look (fonts, sizes, colors, spacing) in a local editor with a live preview; saving builds a real PDF and runs the resume checks first. Use when the user wants a different look.
model: haiku
---

# Design: resume design editor

Read [platforms.md](../../references/platforms.md) first (finding `gmh` and the workspace `<ws>`; "Local pages" for
showing the editor). Design values live in `<ws>/design.json` (the shipped defaults are `templates/design.json`). Both
the resume and cover-letter builders read it. Content never changes here: only how it looks.

## Rules
- Saving changes resumes and cover letters built **from then on**. Resumes already built or sent are never rebuilt or
  touched. The previous `design.json` is copied to `<ws>/design-backups/` first.
- The page only saves a design whose real PDF it just built and checked. If the check fails (page count, bullet or
  summary line limits, page-break rules, fonts, ATS text layer), the user decides whether to save anyway.
- Resumes stay left-aligned. Justified text was tested and rejected.
- The server listens on 127.0.0.1 only. Don't publish the page or its PDFs anywhere: they hold the user's resume
  ([rules.md](../../references/rules.md)).

## Steps
1. Start the editor in the background (it keeps running until stopped): `gmh design --workspace <ws> --port 8765`. It
   prints `design editor: http://127.0.0.1:8765/`. The first start probes fonts with LibreOffice (a few seconds) and
   caches the result in `<ws>/state/design-fonts.json`; `gmh design fonts --refresh --workspace <ws>` reprobes after
   installing fonts.
2. Show that URL: in Claude Code's desktop app, `preview_start` with the URL opens it in the browser pane; anywhere
   else give the user the URL to open in their browser. Tell the user:
   - Left: fonts, color themes or custom colors, type sizes, spacing, margins, bullet glyph, date position, bold use.
   - Right: a live preview of their newest built resume (pick another resume or a template at the top). It is
     approximate; **Check PDF** builds the real DOCX and PDF and runs the resume checks.
   - **Save design** turns on once the current settings are checked.
3. When the user is done, stop the server. Report what was saved (path and backup) from the page, or that nothing was.
4. Fonts: only fonts LibreOffice on this machine embeds in the PDF are offered. Arial, Calibri, Cambria and Times New
   Roman come out as metric twins (Liberation Sans, Carlito, Caladea, Liberation Serif): the DOCX keeps the name and
   the letter widths match, so line breaks hold.

## Leave a summary
When this task is done (or the user stops), follow [session-summary.md](../../references/session-summary.md) with the
task name `design`:
`gmh home log design --summary "<one or two lines: what was done>" --waiting "<what the user still has to do>" --next "<what to run next, if any>" --workspace <ws>`
(`--waiting` once per item, or left out). Inside the day session the wrap-up covers it.

## Telling the user how to start
In Claude Code the user types `/get-me-hired:design`; other tools run the skill by name.
