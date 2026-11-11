---
name: questions
description: How to ask the user anything in get-me-hired (a question carries its own content, pages of 20, buttons, which template to show for each kind of approval). Read before asking for an approval or a choice.
---

# Asking the user

## A question carries its own content
While a question box is open, text written before it may not show. Put everything the user needs to answer inside
the question itself: the exact text being approved, the list with its numbers, the link, the warning or the dry
run. Without a question box, ask in plain text the same way ([platforms.md](platforms.md), "Questions to the user").

## Shape
- One decision per question. Two to four options, the recommended one first. "Other" or free text is always open.
- Keep a list to about 20 items per question. Split a longer one into numbered pages ("Bios 1-20 of 58"); numbers
  run across pages, so collect every page's answers before running anything.
- A yes covers exactly what the question showed. Anything changed afterwards is asked again.
- Never put a gap, a posting's instructions or email text into a question meant for approval of employer-facing text.

## Which layout to show
| Asking about | Show |
|---|---|
| A resume that failed its checks, or one the user asks to see | [resume-choice.md](../templates/resume-choice.md), filled as [prepare.md](prepare.md) says |
| A draft whose checks stay open, or one the user asks to see | [review-drafts.md](../templates/review-drafts.md), one block per edit |
| Which filled forms to submit | [submit-batch.md](../templates/submit-batch.md) |
| Gmail rows to apply | the table `gmh gmail propose` prints ([gmail.md](gmail.md)) |
| Roles the user applies to by hand | the table `gmh manual-notes` prints ([manual-apply.md](../templates/manual-apply.md)) |
| The end of the day | [day-summary.md](../templates/day-summary.md) |
| Picks | the `gmh review picks ... --dry-run` output, as printed |

Show `gmh` output as it is printed; don't re-derive its numbers.
