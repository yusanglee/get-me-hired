# get-me-hired: reference guide

The detailed reference. To install and run your first day, start with the [README](../README.md). Job sources have
their own page: [SOURCES.md](SOURCES.md).

## Contents
- [The daily loop](#the-daily-loop)
- [Sessions and models](#sessions-and-models)
- [Approvals and the submit guard](#approvals-and-the-submit-guard)
- [What it will and won't do](#what-it-will-and-wont-do)
- [Privacy](#privacy)
- [Your workspace](#your-workspace)
- [Settings reference](#settings-reference)
- [Per-tool notes](#per-tool-notes)

## The daily loop
One skill runs the day: `/get-me-hired:today` in Claude Code, or "run today's job search" (other tools: the today
skill by name). `gmh today` names each step's place in brackets, such as `[step: find]`.

| Step | What you do | What runs |
|---|---|---|
| 0. Where are we | Read where the day stands; pick what to do first | `gmh today`: what has run, what is waiting, the next step |
| 1. Check | Fix anything it marks as not ready | `gmh setup check` |
| 2. Find and score | Nothing, unless it ran already today: then keep today's results or run again | `gmh discover` (can take 15 minutes or more), then `gmh score`: new roles from your companies' boards and the job sites, scored into tiers |
| 2a. Gmail sync | Approve each tracker update | Searches email for confirmations, assessments, interviews, offers and rejections (`gmh gmail`). Skipped in one line if Gmail isn't connected |
| 3. Reads | Nothing | The `posting-reader` agent reads every A, B and gap-tier role not read yet (`gmh review reads`). A critical gap moves a role to its own section; a major gap holds an A to B; standout strengths show as badges |
| 4. Review and pick | Pick apply, manual, hold or pass on the review page; approve the dry run | `gmh review summary`, the review page, `gmh review picks` (dry run first, then for real after your yes). Then whether to pass the roles you didn't pick |
| 5. Prepare | Approve resume updates, any resume that fails its checks, new form answers, and any draft whose checks stay open | Applied-check and open-check; `gmh materials` (offered once, before resumes are built); the `resume-tailor` agent and `gmh specs accept`; `gmh forms`, `gmh answers`, `gmh specs`, `gmh tailor`; the `application-drafter` and `application-reviewer` agents; `gmh notes` |
| 6. Fill and submit | Finish what's left in each tab; name the applications to submit | The `form-filler` agent fills one form at a time up to Submit (`gmh fillplan`, `gmh fills`); one question per batch, A tier first; only the named ones are submitted; `gmh applied` records them |
| 7. LinkedIn follow-up | Optional. Click "I'm interested"; send the notes you want | `/get-me-hired:linkedin-followup` in the same session: opens the company's Jobs page, finds people by public web search, drafts 300-character notes |
| 8. Anything else | Ask | `gmail-sync`, `outcome`, `followup`, `interview`, `design` or `materials`, in the same session |
| 9. Wrap up | Say "wrap up" | Gmail sync again, `gmh today`, leftover resume updates offered, the day summary, `gmh home log today --auto`, `gmh tracker report` |

**Tiers.** A and B are sent to review, best first. C+ is a near miss, also shown. C is below the line. "gap" is a
role a critical gap took out of review. "cap" is held back because the company already has enough recent
applications. "gate" failed a hard requirement (work authorization, a license, a language) and wasn't scored. Every
dropped role is still on the review page with its reason, and picking it rescues it.

**Manual-apply roles.** Greenhouse, Lever and Ashby forms are filled for you. Any other ATS (Workday, iCIMS,
company career sites) is manual: `gmh manual-notes` prepares your answers and cover letter, and you create the
account and submit. A role found on a job board is first looked up on the company's own Greenhouse, Lever or Ashby
board, and only stays manual when it isn't there.

**After applying.** `outcome` records news by hand, `gmail-sync` finds it in email, `followup` drafts follow-up
emails after 10 or more quiet days (two at most, never sent for you) and sweeps applications still at `applied`
after 60 days, and `interview` builds a prep pack from the exact resume, cover letter and posting you submitted.

**Materials over time.** The resume tailor and the posting reader note strengths your master resume states but no
approved bullet does. `materials` turns them into proposed bullets, bios, summaries and template versions. Each
quotes the master-resume lines it rests on, the engine rejects any number those lines don't state, and nothing is
added until you approve its exact wording. Every built resume records the template version it used.

## Sessions and models
**One session a day.** Open a session in your workspace folder each morning and run the today skill. Everything for
the day happens in it. Steps that suit another model run as helper agents inside it, and get-me-hired never opens
another session. If the session closes or gets long mid-day, open a new one and run the today skill again: it reads
where the day stands from your files (`gmh today`). Say "wrap up" at the end; tomorrow, start fresh.

**The session holds every approval and every submit**, so run it on the strongest model you have. Agents never ask
you anything, never submit and never write the tracker; they return JSON and the session shows you the result.

### Skills
| Skill | Model on Claude | Used for |
|---|---|---|
| `today` | Opus | The whole day |
| `setup` | Opus, medium effort | Building the workspace: the most judgment |
| `apply-all` | Opus | Applying to a day's queue |
| `materials` | Opus | Reviewing proposed resume material |
| `apply` | Sonnet | One application |
| `review-drafts` | Sonnet | Running the draft reviewer and showing its edits |
| `followup` | Sonnet | Follow-up emails and the stale sweep |
| `interview` | Sonnet | Prep pack and thank-you notes |
| `linkedin-followup` | Sonnet | "I'm interested" and connect notes |
| `daily-run` | Haiku | Find, score, reads and picks only |
| `review-run` | Haiku | The review page and picks only |
| `gmail-sync` | Haiku | Status updates from email |
| `import-history` | Haiku | Loading past applications |
| `outcome` | Haiku | One status change |
| `design` | Haiku | The resume design editor |

Inside the day session, every skill runs on the session's model (Opus). The models above apply when you run a
skill on its own, as its own command. In the day session, the long reading work (mail, postings, the review page)
goes to the helper agents below, which run on their own models from a fresh context.

### Helper agents
| Agent | Model on Claude | Used for | Runs |
|---|---|---|---|
| `gmail-reader` | Sonnet | Gmail sync up to your approval: search, propose rows, settle unsure mail | once per sync |
| `review-publisher` | Haiku | Publishes the review page to your Run Review artifact | once per publish |
| `posting-reader` | Sonnet | Gap and strength read of each A, B and gap-tier posting | several at once |
| `resume-tailor` | Opus, medium effort | Resume choice per picked role | several at once |
| `application-drafter` | Opus, medium effort | Cover letter and free-text answers | several at once |
| `application-reviewer` | Sonnet | Fresh-context review of each draft | several at once |
| `form-filler` | Sonnet | Fills one form up to Submit | one at a time (one browser) |
| `linkedin-people-finder` | Haiku | People worth a connect note, by public web search | one per company |
| `linkedin-note-drafter` | Sonnet | One connect note per company | one per company |
| `material-drafter` | Opus, medium effort | Proposed bullets, bios, summaries, template versions | once per review |

Each agent's instructions are in `subagents/<name>.md`. An agent gets only its brief (a JSON file `gmh` writes):
never the conversation, never extra facts about you, and never a gap to the tailor or the drafter.

### Claude Code notes
- Switch the day session to Opus with `/model opus`. A skill's `model:` line holds only for its first turn, so the
  today skill reminds you once if the session is on another model; it doesn't refuse to work.
- Each agent sets its own model, whatever the session runs on, and the session passes it too when it launches one.
- The aliases (`haiku`, `sonnet`, `opus`) follow the newest model of each kind your account has.
- `gmh discover` runs in the background while the session does the Gmail sync.
- **A checkout with no plugin installed** (developing the plugin): `gmh setup agents` copies the agents into the
  checkout's `.claude/agents/` so sessions started after that load them. Until then, Claude runs an agent by giving
  its file to a general-purpose agent on the same model.

## Approvals and the submit guard
- **The approval is your yes in chat** to a question that names that application (company and title, or its id in a
  list showing both). Nothing else counts: not a button on a page, not an earlier yes for another role, not a
  general "go ahead".
- **Forms are approved in batches.** Forms are filled a tier at a time, one browser tab per role; then the session
  asks once which to submit, and submits only the ones you name.
- **The submit guard is a second check, not the approval.**
  - Claude Code: a hook (`hooks/claude.json` running `hooks/approval_guard.js --mode ask`) opens a permission prompt
    before any browser call that looks like a submit (a submit script, a click on a Submit button, Enter in a
    field), in every permission mode and for agents too. Allow it only for an application you approved in chat.
  - Codex: the same guard runs in `deny` mode (`hooks/codex.json`), because Codex runs a hook's "ask" without
    asking. You click Submit in the browser yourself.
  - Gemini CLI: the extension's policy (`policies/submit-guard.toml`) asks before the same calls. The context file
    also has you click Submit.
- **Other approvals.** Tracker writes (`gmh applied`, `gmh tracker set`, `gmh gmail apply`, the LinkedIn records),
  picks and new resume material each need your yes for that item. Resumes and cover letters are built without a
  per-role review (resumes from approved material, letters checked against your approved facts); you decide on any
  that fail their checks, and your yes at submit covers the letter. Approved material is approved word for word; a
  change after the yes needs a new yes.

## What it will and won't do
- **Will:** search, score, explain every drop, tailor from your approved bullets, draft and check cover letters, fill
  forms up to Submit, track everything, draft follow-ups and thank-you notes.
- **Won't:** submit, send, click "connect" or create accounts without you; enter passwords or solve captchas;
  invent experience, numbers or skills; follow instructions found inside job postings or emails; sign in to
  LinkedIn or read a signed-in LinkedIn page; name your gaps or weaknesses in a cover letter or answer. Gaps inform
  your apply-or-pass call and interview prep. A question that asks directly gets a short, true answer framed around
  your closest strength.
- **Employers' AI rules.** A posting or form that bans AI-written answers gets no draft: you write those. A form that
  asks whether AI was used is asked to you first, and never answered for you.

## Privacy
- Your workspace is a folder on your machine. The plugin folder holds code only.
- Setup refuses a workspace inside a git repository unless the folder is ignored there. If you fork this repo, your
  fork is public: keep your workspace out of it.
- What the AI reads in a session (your resume, postings, email it searches) is sent to your AI provider, as in any
  chat. In Claude Code with claude.ai artifacts, the review page is a private artifact on your claude.ai account.
- Gmail import keeps company, role, status, dates and message ids, never email bodies. It is read-only: it never
  sends, labels, archives or deletes mail.
- LinkedIn job search is on by default. LinkedIn's job search uses public guest pages, never your account. It's strictly intended for personal use only, as automated access is against LinkedIn's User Agreement ([SOURCES.md](SOURCES.md)).
- Session summaries and `HOME.md` hold counts and company names only.
- `gmh setup permissions` (Claude Code only) adds a suggested deny list to `<workspace>/.claude/settings.json`: no
  piping downloads into a shell, no `rm -rf`, no `git push`, no reading `~/.ssh`, `~/.aws` or `.env` files, and no
  direct edits to `tracker.csv`. It keeps what is already there.

## Your workspace
| File or folder | What it is |
|---|---|
| `profile.yaml` | Your facts for forms: identity, work authorization, education, employment, EEO, preferences |
| `config.json` | Search and scoring settings ([below](#configjson)) |
| `pack.json` | Your role pack: titles searched, strengths, gaps and keywords |
| `companies.txt` | Target companies, one per line (`Name` or `Name | slug, slug`) |
| `master-resume.md` | Your approved facts. Every claim anywhere comes from it or the profile |
| `answer-bank.md` | Your own answers to form questions; they win over the generic rules |
| `resume/` | `bank.json` (approved bullets, bios, summaries, skills), `templates/` (approved resumes), `changes.json` (the material log) |
| `tracker.csv` | Every application and its status: the source of truth |
| `report.html` | The dashboard, rebuilt by `gmh tracker report` |
| `HOME.md` | How to start each day, what is waiting, and links. Rewritten by `gmh home` and `gmh today` |
| `run-review/run-review.html` | The latest review page |
| `design.json` | Your resume design, from the design editor (`design-backups/` keeps earlier ones) |
| `Pipeline/` | The engine's working files: `queue/` (runs, reviewed CSVs, batch files), `state/`, `specs/`, `drafts/`, `scratch/` |
| `Workflow/` | One folder per application, moved through `02-Ready to Apply`, `03-Applied`, `04-Interviewing` and `Passed` |
| `CLAUDE.md`, `AGENTS.md` or `GEMINI.md` | The context file for your AI tool: the rules and the Engine line (where `gmh` lives) |

## Settings reference
Edit settings through setup or the `gmh setup` commands where one exists; they show the change and keep the file
valid. Defaults live in `engine/profile.py` (`DEFAULT_CONFIG`); `templates/config.example.json` and
`templates/profile.example.yaml` are annotated examples.

### config.json
| Key | Default | Meaning |
|---|---|---|
| `salary.floor_usd`, `salary.floor_cad` | none | The lowest top-of-range pay worth a look, per currency, never converted. A CAD range with no `floor_cad` is not dropped for pay. `gmh setup config salary --floor <N> [--currency USD\|CAD]` |
| `salary.rule` | `top_of_range` | What the floor is compared with |
| `salary.no_range_policy` | `include_if_level_fits` | A posting with no pay range: `include`, `exclude`, or keep it only when the title has a level word. `gmh setup config salary --no-range <policy>` |
| `salary.down_level_below` | none | With no level word in the title, a posted top under this flags a possible down-level |
| `locations.home` | none | Your home metro |
| `locations.metros` | `[]` | Metros you'd work in: `{"name", "policy", "max_office_days", "pattern"}`. Policy `any` (on-site fine), `hybrid_ok` (at most `max_office_days` a week) or `remote_only`. Known names need no pattern: LA, SF, NYC, Chicago, Seattle, Austin, Boston, DC, Denver, Toronto, Vancouver, Montreal, Ottawa, Calgary, Edmonton, Waterloo |
| `locations.remote_countries` | `["US"]` | Where a remote role may hire you: `["US"]`, `["US", "CA"]`, `["CA"]`, or `[]` for no remote roles. Replaces the older `remote_us` |
| `locations.top`, `locations.top_bonus` | `[]`, `5` | First-choice places (metro names or `Remote`): their roles get `top_bonus` fit points and show in green. `gmh setup config top <metro\|Remote>... [--bonus N]` |
| `locations.company_rules` | none | Count one company's postings as a metro when the location text matches |
| `scoring.tier_a`, `scoring.tier_b` | `70`, `55` | Fit lines for tiers A and B |
| `scoring.near_miss_margin` | `5` | How far under the B line a near miss (C+) may be |
| `scoring.over_bar_tier` | `B` | Holds roles asking for more years than you have, or for managing managers when your profile says no, out of tier A. `A` turns the hold off |
| `scoring.gap_rules` | `{"critical": "section", "major": "B"}` | What a posting read does: a critical gap gets its own section (or `flag`); a major gap holds an A to B (or `flag`) |
| `per_company.max_applications`, `per_company.window_days` | `5`, `90` | The company cap: reviewable roles per company in a rolling window |
| `company_limits` | none | Per-company limits, e.g. `{"<company, lowercase>": {"max_applications": 0, "window_days": 3650}}` (0 means never) |
| `company_aliases` | none | Names one employer hires under, e.g. `[["<parent>", "<brand>", "<other brand>"]]`: a role under any of them matches an application under another (applied-check and dedup). A name in parentheses ("Parent (Brand)") counts on its own |
| `since_days` | `14` | How far back a search looks |
| `sources` | the defaults | Job boards: [SOURCES.md](SOURCES.md) |
| `resolve_guess` | `true` | Look up a job-board role on the company's own board by guessing its board name |
| `gates.enabled` | `true` | Hard gates: work eligibility, licenses, languages |
| `paths.soffice` | found on its own | Full path to LibreOffice's `soffice`, when it isn't found |
| `paths.node_modules` | set by `gmh setup tools` | Where the resume builder's Node package lives |
| `linkedin.gmail_followup_days` | `7` | LinkedIn follow-up covers roles applied through get-me-hired, plus Gmail-imported ones applied within this many days |
| `review.artifact_url` | none | Your standing claude.ai review page (set the first time it is published) |
| `review.location_drops` | `{"tiers": ["A"], "us_only": true}` | Which location drops the review page lists up front |
| `tracker.sheet_id` | none | A Google Sheet that mirrors the tracker, one way |
| `pack` | `pack.json` | The role pack file |

### Resume layout rules
Set with `gmh setup config resume <key> <value>`. `gmh setup check` lists unknown keys and rules that are off. The
rules marked "off when missing" stay off until you set them. New workspaces start from
`templates/config.example.json`, which turns on all of them except `skills_lines`.

| Key | Example | Meaning |
|---|---|---|
| `pages` | `2` | Exact page count (set after your first build looks right) |
| `max_pages` | `2` | Page ceiling (off when missing) |
| `page_breaks` | `{"first_on_page_2": "experience[2]"}` | Which job starts page 2 |
| `max_bullet_lines` | `2` | Lines per bullet |
| `max_summary_lines` | `4` | Lines in the summary |
| `max_scope_lines` | `2` | Lines in a job's scope line (off when missing) |
| `min_last_line_words` | `3` | No runt last lines in bullets, scope, summary and skills (off when missing) |
| `skills_lines` | `3` | Exact line count of the skills paragraph (off when missing) |
| `max_page1_free_pt` | `40` | How much space page 1 may leave empty at the bottom, in points (off when missing) |
| `bottom_margin_pt` | `28` | The bottom margin used for that page-1 measurement |
| `max_extra_bullets` | `1` | How many approved bullets the tailor may add to a job beyond the template's own |
| `font` | `null` | A font name that must be among the PDF's embedded fonts (off when empty) |
| `sections` | `["EXECUTIVE SUMMARY", ...]` | Section headings that must appear in the PDF text |

Every built resume also gets ATS checks: unreadable glyphs in the PDF text layer, date ranges without a plain
hyphen, no tables, text boxes or columns, and a keyword table that never stuffs keywords. A page never starts with
a carried-over bullet. Resumes stay left-aligned, on US Letter pages.

### profile.yaml
| Section | Holds |
|---|---|
| `identity` | Name, preferred name, pronouns, email, phone, LinkedIn, website |
| `home` | City, state, country |
| `work_authorization` | `authorized_us`, `needs_sponsorship`, citizenship, optional `permanent_resident` and `clearance`; for Canada, `authorized_canada`, `needs_sponsorship_canada`, `permanent_resident_canada` |
| `languages` | Languages and levels, read by the language gate (none listed means English only) |
| `attestations` | Over 18, non-compete, previously employed, referred and similar |
| `education`, `employment` | Highest degree first; current or most recent job, years of experience, optional `managed_managers` |
| `eeo` | Voluntary; "Decline to self-identify" is always fine. Canadian `employment_equity` answers default to "I prefer not to answer" |
| `preferences` | How you heard, travel, start date, salary history and similar |
| `salary` | The number entered when a form requires one |
| `location_answers` | Optional wording per metro |
| `files.prefix` | The file-name prefix for resumes and cover letters (default `First_Last_`) |
| `resume.stale_numbers` | Figures you've retired; any match fails the resume check |
| `forms` | What the form fillers type and pick for city, school, degree and dates |

Set one value with `gmh setup profile set <dotted.path> <value>`, or show it with `gmh setup profile show`. A value
left empty makes that form question stop for you instead of being guessed.

### Canada
- Add Canadian metros (`gmh setup config locations --home Toronto --metro Toronto ...`) and `CA` to remote countries
  (`--remote-countries US,CA` or `CA`).
- Set a CAD pay floor: `gmh setup config salary --floor <N> --currency CAD`. C$, CA$ and CAD ranges are read in
  Canadian dollars and compared only with `floor_cad`.
- Fill the Canadian work-authorization fields in `profile.yaml`; once either is set, Canadian postings are checked
  against them instead of the US ones.
- Postings that require French are gated (flagged for you) unless `languages` lists French.

## Per-tool notes
| | Claude Code | Codex CLI (experimental, untested) | Gemini CLI (experimental, untested) |
|---|---|---|---|
| Install | `/plugin marketplace add yusanglee/get-me-hired`, `/plugin install get-me-hired@get-me-hired` | Codex marketplace (`.agents/plugins/marketplace.json`), installed from `/plugins` | `gemini extensions install https://github.com/yusanglee/get-me-hired` |
| Context file | `CLAUDE.md` | `AGENTS.md` (`--tool codex` or `GMH_TOOL=codex`) | `GEMINI.md` (`--tool gemini` or `GMH_TOOL=gemini`) |
| Helper agents | Load with the plugin | `gmh setup agents --tool codex <workspace>` writes `.codex/agents/` | `gmh setup agents --tool gemini <workspace>` writes `.gemini/agents/` |
| Agent models | As in the tables above | The session's model, with a reasoning effort mapped from the Claude model | The session's model |
| Running a skill | `/get-me-hired:<name>` | Ask for the skill by name | Ask for the skill by name, or its `/` command |
| Submit guard | Permission prompt (`hooks/claude.json`) | Blocks the call; you click Submit (`hooks/codex.json`) | Asks first (`policies/submit-guard.toml`); you click Submit |
| Review page | Always the private claude.ai artifact with Confirm choices where the app has artifacts; the local file only without them | Local file with Copy picks | Local file with Copy picks |
| Gmail | claude.ai Gmail connector | A Gmail MCP server, or a Takeout `.mbox` | A Gmail MCP server, or a Takeout `.mbox` |
| Permissions | `gmh setup permissions` | Not available | Not available |

On every tool, `gmh` runs with Python 3.9 or newer (`bin/gmh` finds `python3`, `python` or `py -3`; on Windows use
`bin\gmh.cmd`). The browser is the Playwright server the plugin starts with `npx`, so it needs Node.js and Google
Chrome. Gemini CLI now needs a paid plan or an API key; the extension may also work in Antigravity CLI, untested.
