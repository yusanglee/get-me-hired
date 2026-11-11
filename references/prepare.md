---
name: prepare
description: Preparing picked roles for their forms (applied and open checks, reads, resume updates before resumes, the resume tailor, the one missing rule and building resumes, form answers, drafting and draft review, application notes). Read before preparing any role.
---

# Prepare the picked roles

The queue is the `apply` and `manual` rows of `<ws>/Pipeline/queue/reviewed-<date>.csv`. Drafts, new material and
submits wait for the user's yes ([rules.md](rules.md)); resumes are built from approved material without a per-role
review. Agents: [agents.md](agents.md).

## Contents
- [Checks](#checks)
- [Resume updates first](#resume-updates-first)
- [Resume choice](#resume-choice)
- [The missing rule](#the-missing-rule)
- [Build the resumes](#build-the-resumes)
- [Answers](#answers)
- [Drafts](#drafts)
- [Draft review](#draft-review)
- [Application notes](#application-notes)
- [Other text the user sends](#other-text-the-user-sends)

## Checks
1. `gmh review applied-check --workspace <ws>` lists queued rows already in the tracker, `applied.csv` or an Applied
   folder (exit 1). Show them and stop on those until the user clears them (`gmh review picks "clear <id>"`); don't
   read, tailor or fill them. Run it again before filling.
2. `gmh review open-check --workspace <ws>` checks Greenhouse, Lever and Ashby roles against their boards. Show the
   closed ones with the `gmh review picks "pass ...: closed"` line it prints, and run it once the user says yes.
   For an `unknown` one, open the posting link; a closed one, or one the user drops, gets
   `gmh review picks "pass <n>: closed"` too.
3. `gmh review todo --workspace <ws>` lists rows still missing their read or their resume choice. Reads for picked
   roles with none: [reads.md](reads.md), with `--ids`.

## Resume updates first
Before any resume is built: `gmh materials candidates --date <day> --workspace <ws>` lists only what that day's
picked roles asked for (strengths from their reads that no bullet states), plus how many bios on built resumes are
still unapproved. If it lists anything, offer it once: **Review now** (so these resumes can use it) or **Skip for
today**. On "Review now", follow [materials](../skills/materials/SKILL.md) with `--date <day>`, then go on.

## Resume choice
Per role, several at once:
1. `gmh specs brief <id> --workspace <ws>` writes the brief and prints its path.
2. Launch `resume-tailor` with that path as its whole prompt. Save its reply to
   `<ws>/Pipeline/scratch/<date>/tailor-reply-<id>.json` (`gmh reply`: [platforms.md](platforms.md), "Saving agent
   replies").
3. `gmh specs accept <id> <reply file> --workspace <ws>` checks the reply, fills the reviewed row's labels itself, adds
   the role to the day's batch file (`<ws>/Pipeline/queue/batch-<date>.json`) and saves the reply's `missing` and
   `material_feedback`. It prints `accepted <id>`, or the problems (exit 1): re-ask the tailor once, quoting them. A
   role that fails twice is a problem to show the user (next section).

No per-role review: an accepted choice uses approved material only, so it is built as it is. Don't lay out the
choices or ask for an OK on each. Show one laid out as [resume-choice.md](../templates/resume-choice.md) only when
the user asks to see it, or for a role whose built resume fails (below); `gmh specs coverage <id> --spec <reply file>`
prints its posting key-term coverage on request.

## The missing rule
`missing` lists strengths a posting asks for that the master resume states and no bullet does. `gmh specs accept`
saves them; they never change a resume by themselves. If any accepted reply has `missing`, ask once, naming those
roles: **Add bullets and re-tailor those roles** ([materials](../skills/materials/SKILL.md) with `--ids <those ids>`,
then the resume choice again for just those roles) or **Keep these resumes** (the ideas wait for the wrap-up). Never
add a bullet, edit the master resume or change a spec because of `missing` in any other way.

## Build the resumes
Right after the missing question (or straight after the resume choices when none has `missing`):
1. `gmh specs <ws>/Pipeline/queue/batch-<date>.json --workspace <ws>` writes each role's spec to
   `<ws>/Pipeline/specs/`. A role passed since its choice was accepted is skipped (`skipped <id>: ...`).
2. `gmh tailor <ws>/Pipeline/specs/<slug>.json ... --workspace <ws>` builds each tailored resume and checks it. It
   prints one line per role: `PASS` or `FAIL`, the company, the template in parentheses, the file.
3. Show the user one compact line per role: company, template, PASS or FAIL. Nothing more for the ones that pass.
4. Fix these two layout failures yourself, once, without asking (re-tailor quoting the failure and the fix, then
   accept and build that role again): a skills line ending on too few words drops its last skill, or adds approved
   skills until the line is full; a page break that moved up (a role rose onto page 1, or page 2 starts mid-bullet)
   gets one more approved bank bullet on an earlier role. Mention the fix in that role's line.
5. Ask only about failures still left (and any role whose choice `gmh specs accept` refused twice): per role, the failed checks,
   the choice laid out as [resume-choice.md](../templates/resume-choice.md), and the fix you propose. A layout failure
   is fixed with another approved choice (re-tailor quoting the failure, then accept and build that role again), or
   with a fit-only reword: `gmh materials fit <bullet id> "<text>" --workspace <ws>` keeps every number and adds none;
   show the user its before and after lines. Any other new wording needs the materials review.

## Answers
1. `gmh forms --workspace <ws>` fetches each queued role's application form.
2. `gmh answers --workspace <ws>` answers what the profile and answer bank cover and lists new questions. Ask the
   user those once, batched (pages of 20). Write each answer to `answer-bank.md` (an exact-question line) or
   `profile.yaml` (`gmh setup profile set <path> <value> --workspace <ws>`) in the same turn, then run `gmh answers`
   again.

## Drafts
Cover letters and free-text answers, per role (several at once):
1. `gmh redline brief <ws>/Pipeline/drafts/drafts-<date>.json <slug> --workspace <ws>` writes the brief and prints
   its path. Its questions come from the answers step (`--question "<label>"` overrides them). Check its
   `ai_policy` ([rules.md](rules.md), "AI-use policy"): `banned`, draft nothing and tell the user; `ask`, ask the
   user first.
2. Launch `application-drafter` with the brief's path as its whole prompt. Save its reply to
   `<ws>/Pipeline/scratch/<date>/draft-<slug>.json` (`gmh reply`).
3. `gmh redline put <drafts.json> <slug> <reply file> --workspace <ws>` files it and prints the rule checks. Pass the
   drafter's `notes` on to the user.

## Draft review
Per role, several at once. The reviewer gets only its packet: never the drafting conversation or more about the user.
1. `gmh redline packet <drafts.json> <slug> --workspace <ws>` writes the packet and prints its path.
2. Launch `application-reviewer` with that path as its whole prompt. Save its reply to
   `<ws>/Pipeline/scratch/<date>/review-edits-<slug>.json` (`gmh reply`).
3. `gmh redline apply <drafts.json> <slug> <edits file> --workspace <ws>` applies an edit only if its `old_string`
   occurs once and its `new_string` adds no unsupported number, dash or volunteered gap. It keeps one backup
   (`drafts-<date>.pre-review.json`) and reports `applied`, `rejected` and `remaining_checks`.
4. If the verdict was `needs_changes` and edits were rejected or checks remain, run steps 1 to 3 once more (two
   rounds at most; then hand the rest to the user).
5. No per-role text review: a draft that passed the reviewer with no checks left is built as it is (next section).
   Don't show the letter or ask for an OK on it. Show the user one compact line per role: company, `cover letter +
   <n> answers`, `<n> reviewer edits`, `checks OK`. Pass on any drafter or reviewer `notes` that need the user's
   input (a fact to confirm, a choice only they can make) in that same list.
6. Ask only about roles with checks still open after two rounds: per role, laid out as
   [review-drafts.md](../templates/review-drafts.md) (applied edits before and after, rejected edits, notes, open
   checks), with the fix you propose. Show that layout for any other role only when the user asks to see it. The user
   approves, changes or reverts (restore from the `.pre-review.json` backup); an edit the user makes is checked with
   `gmh redline check <drafts.json> <slug> --workspace <ws>`.

## Application notes
Right after the draft review, with no OK asked: `gmh notes <drafts.json> --workspace <ws>` builds the cover letter
document and the application notes the fill plan uses, for every role with no open checks. Then fill
([fill-and-submit.md](fill-and-submit.md)). The user approves each application, letter included, in the submit
question; any letter is shown on request before then.

## Other text the user sends
Any follow-up, thank-you note, connect note or edited answer is checked before it is shown:
`gmh check-text <followup|thank-you|note|cover|answer> <file> [--id <id>] --workspace <ws>` prints `ok` or one line
per problem (dashes, numbers not in the facts, gap lines, length).
