---
name: glossary
description: Plain definitions of the words get-me-hired uses (workspace, run, tier, read, pick, spec, bank, brief, fill plan and the rest). Read when a skill, a gmh output or the user uses a term you need to explain.
---

# Glossary

## The workspace and its files
- **workspace**: the user's private folder holding all their job-search files (older versions called it the
  "vault"). `$GMH_WORKSPACE` names it. Nothing in it leaves the user's machine.
- **Pipeline**: `<workspace>/Pipeline/`, the engine's working files: `queue/` (runs, reviewed CSVs, batch files),
  `state/` (forms, answers, notes, fill plans, fill records), `specs/`, `drafts/` and `scratch/`.
- **scratch folder**: `<workspace>/Pipeline/scratch/<date>/`, where briefs, packets and agent replies go
  (`<kind>-<key>.json`). Every command that writes one prints its path.
- **Workflow**: `<workspace>/Workflow/`, one folder per application, moved between `02-Ready to Apply`, `03-Applied`,
  `04-Interviewing` and `Passed` as it progresses.
- **context file**: the workspace's `CLAUDE.md` (or `AGENTS.md`, `GEMINI.md`): rules and the Engine line (where the
  plugin's `gmh` lives) for any session opened in the workspace.
- **HOME.md**: a page in the workspace with how to start each day, what is waiting on the user, and links. Rewritten
  by `gmh home` and `gmh today`; never edited by hand.
- **tracker**: `tracker.csv`, every application and its status (the source of truth). **dashboard**: `report.html`,
  the tracker as a page with filters, rebuilt by `gmh tracker report`.
- **master resume**: `master-resume.md`, the user's approved facts. Every claim anywhere comes from it or the profile.
- **profile**: `profile.yaml`, facts for forms (identity, work authorization, education, EEO, preferences).
- **answer bank**: `answer-bank.md`, the user's own answers to form questions; they win over the generic rules.

## Finding and picking roles
- **run**: one day's `gmh discover` (find postings) plus `gmh score` (score and tier them).
- **role pack**: `pack.json`, the scoring rules for one kind of job: titles searched, **strengths** (a posting that
  mentions one scores higher), **gaps** (a requirement the resume lacks scores lower) and **terms** (keywords
  recruiters search for).
- **tier**: where a scored role lands. **A** and **B**: sent to review, best first. **C+**: a near miss, also shown.
  **C**: below the line, not shown by default. **gap**: a critical gap from the read took it out of review.
  **cap**: held back because the company already has enough recent applications. **gate**: failed a hard gate
  (work authorization, a license, a language) and was not scored.
- **read**: the posting-reader agent's reading of one posting against the master resume: the gap rating (none,
  minor, major, critical) with the posting line behind it, up to 3 standout strengths, and what the posting stresses
  most (its **needs**). A role is read once.
- **review page**: one page per run listing every scored and dropped role with reasons, where the user picks.
- **pick**: the user's call on a role: **apply** (the engine prepares and fills it), **manual** (the user applies by
  hand), **hold** or **pass**. A `d` number is a dropped role; picking one **rescues** it.
- **reviewed CSV**: `Pipeline/queue/reviewed-<date>.csv`, the picks of one run. Its apply and manual rows are that
  day's **queue**.

## Preparing an application
- **bank**: `resume/bank.json`, the approved resume material: bullets (each with an id), bios, summaries, skills
  and skill sets. **template**: an approved resume in `resume/templates/`.
- **bio**: the short line under the user's name on a resume. **summary**: the paragraph at the top.
- **spec**: one role's resume choice (template, bio, summary, skills, bullet ids), chosen by the resume tailor from
  approved material only. The day's specs collect in the **batch file** `Pipeline/queue/batch-<date>.json`.
- **missing**: a strength the posting asks for that the master resume states but no bank bullet does, noted by the
  resume tailor. It never changes a resume by itself (see [prepare.md](prepare.md)).
- **materials**: proposals for new bank bullets, bios, summaries and template versions, each approved word for word.
- **brief** and **packet**: the JSON file an agent works from (a brief starts a draft or read; a packet is what a
  reviewer checks). **reply**: the JSON an agent returns, saved to the scratch folder.
- **ai_policy**: per role, `ok`, `banned` or `ask` (see [rules.md](rules.md), "AI-use policy").

## Applying
- **fill plan**: `Pipeline/state/fillplans/<id>.js`, the code that fills one form with that role's answers and
  attaches its tailored resume and cover letter (`gmh fillplan`).
- **fill record**: where a filled form stands: `ready`, `needs_user` or `blocked`, plus what is `left` for the user
  (`gmh fills set`, `gmh fills show`).
- **submit script**: the file that clicks Submit for one applicant tracking system (`submit_script:` in
  `gmh fillplan`'s output). Only the session runs it, after the user's approval.
- **ATS**: applicant tracking system. Greenhouse, Lever and Ashby forms are filled by the engine; any other ATS
  (Workday, iCIMS, career sites) is **manual**: the user applies, with notes the engine prepares.

## Ids
- **id**: a role's id, such as `gh-acme-123` (the prefix names the ATS: `gh` Greenhouse, `lv` Lever, `ab` Ashby).
- **slug**: the role's folder-safe name, used for drafts and specs. **key**: `job_key`, the tracker's dedup key.

## Tools
- **skill**: one workflow, such as today or setup (`skills/<name>/SKILL.md`). **agent**: a helper that runs inside
  the session on its own model and returns JSON ([agents.md](agents.md)).
- **gmh**: the engine's command line. How to find it: [platforms.md](platforms.md).
