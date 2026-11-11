---
name: materials
description: Grows the approved resume material over time - new bank bullets, bios, summaries and template versions drafted from what recent applications kept asking for - and adds each only after the user approves its exact wording. Use before resumes are built, at wrap-up, or on request.
argument-hint: "[days to look back, default 30]"
model: opus
---

# Materials: grow the bullet bank and refresh templates

Resumes are built only from approved material (`<ws>/resume/bank.json` and `resume/templates/`). The resume tailor and
the posting reader note true strengths from the master resume that no bullet states, and bios, summaries or templates
that fit roles badly; the day session saves the tailor's notes (`gmh materials save`). This turns them into proposals
and adds the ones the user approves. It runs in the day session ([today](../today/SKILL.md) offers it before resumes
are built, and at wrap-up when candidates remain) or on its own when the user asks; it never starts another session.

Read [rules.md](../../references/rules.md) and [platforms.md](../../references/platforms.md) first (finding `gmh` and
the workspace `<ws>`; fallbacks). Agents: [agents.md](../../references/agents.md). How to ask:
[questions.md](../../references/questions.md).

## Rules
- **Nothing is added without the user's OK for that item's exact wording.** Run `gmh materials approve` only after
  they approve that proposal; pass the exact text they approved with `--text` when they edited it. Approved text is
  used on resumes word for word; the tailor never rewords it.
- **Every proposal rests on master-resume lines it quotes.** The engine rejects a number those lines don't state.
  Facts come only from the master resume; never invent or inflate numbers, scope, titles or tools. No gaps or
  weaknesses in any text ([rules.md](../../references/rules.md)). A fact that isn't in the master resume yet goes
  there first, in its own step the user approves, not here.
- **A question carries its own content.** Put everything the user needs to answer inside the question itself: the
  exact text being approved, the list with its numbers, the link, the warning or the dry run. Keep a list to about 20
  items per question ([questions.md](../../references/questions.md)).
- Don't edit `bank.json`, templates or the master resume by hand: `approve` keeps a backup and a log
  (`resume/changes.json`), and a template's old version stays in `resume/templates/.history/`.
- **One exception: `gmh materials fit <bullet-id> "<text>"`** rewords an approved bullet only to meet a layout rule
  (for example a line limit). It keeps every number and adds none; it is applied and logged at once, so show the user
  the before and after lines it prints. It exits 1 if a number changed. It is never used to improve wording.

## Scope
From the day session before resumes are built, pass `--date <day>` (only what that day's picks asked for) or, for a
re-tailor, `--ids <role ids>` to `gmh materials candidates` and `gmh materials brief` below. At wrap-up or on its own,
pass neither.

## Steps
0. **Bios already on your resumes.** `gmh materials bios --workspace <ws>` lists, numbered, the bios used on resumes
   already built that were never approved (the resume tailor can't use them until they are). It pages by 20:
   `gmh materials bios --page N --workspace <ws>`; numbers run across pages. Ask about them **inside the question**,
   one page per question, each with its number and exact text, for example "Bios 1-20 of 58, used on resumes you
   built; approved bios are used word for word: 1. ... 2. ...". Buttons: **Approve all on this page**, **Choose**
   (the user types numbers to approve and to turn down), **Not now**. Collect the answers for every page first
   (don't run anything between pages), then run one command for all of them. "Approve all" everywhere:
   `gmh materials approve-bios all --workspace <ws>`. Otherwise
   `gmh materials approve-bios <numbers> --reject <numbers> --workspace <ws>` (or `all --reject <numbers>`).
   Turned-down bios aren't offered again; unmentioned ones stay for later. The text is approved as written; a bio the
   user wants reworded is turned down here and can come back as a drafted proposal.
1. `gmh materials candidates --days <argument or 30> [--date <day> | --ids <ids>] --workspace <ws>`. Nothing listed:
   say so and stop. Lines marked "not in master resume (ignored)" are claims a tailor or reader made that the master
   resume doesn't hold: mention them only if the user wants to add a fact.
2. `gmh materials brief --days <same> [same --date or --ids] --workspace <ws>` writes the packet and prints its path.
   Launch the `material-drafter` agent with that path as its whole prompt. Save its JSON reply
   ([platforms.md](../../references/platforms.md), "Saving agent replies") and run
   `gmh materials propose <reply.json> --workspace <ws>`. Re-ask the agent once for the rejected ones, quoting the
   problems; drop what still fails.
3. **Review each pending proposal, one at a time**: [item-review.md](references/item-review.md) (the question, the
   approve, edit, reject and later answers, and undo).
4. **Finish.** Tell the user what changed (new bullet ids, bios, summaries, template versions) and that the resume
   tailor uses them from the next resume it builds (today's, when this ran before tailoring). Then record it:
   `gmh home log materials --summary "<approved, rejected, pending counts>" --workspace <ws>`
   ([session-summary.md](../../references/session-summary.md); inside the day session the wrap-up covers it).

## Telling the user how to start
In Claude Code the user types `/get-me-hired:materials` (optionally with the number of days to look back); other
tools run the skill by name.
