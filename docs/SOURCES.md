# Job sources

Where get-me-hired looks for roles, which sources are on by default, and how to turn others on.

## What runs each day
`gmh discover` searches two kinds of source:
1. **Your target companies' own job boards.** Every company in `companies.txt` that resolves to a Greenhouse, Lever
   or Ashby board is searched through that board's official public API. This always runs; it isn't a `sources`
   entry. Add companies with `gmh setup companies add "<Company>"`, then `gmh setup resolve-companies <workspace>`.
2. **Job boards**, set by `sources` in your workspace's `config.json`. With no `sources` (or an empty one), the
   defaults run: **Himalayas, Remotive and NoDesk** (`DEFAULT_SOURCES` in `engine/discover.py`). Every other board is
   opt-in.

Each board's search terms are your pack's `titles.board_queries`, unless a source sets its own `queries`.

`engine/boards.run_boards()` then works through the board results in this order:
1. Search every enabled board.
2. Drop titles that fail your role pack.
3. Fetch details only for the survivors.
4. Drop closed or stale postings.
5. Swap a board hit for the same role on the company's own Greenhouse, Lever or Ashby board, when one exists (found
   from the apply link, your watchlist, or by guessing the company's board name; a board found by name is labeled
   so you can check it's the same company). `"resolve_guess": false` in `config.json` turns the guessing off.
6. Dedup by `job_key` against the tracker and earlier runs.
7. Clean every description with the posting guard (hidden text removed, prompt-injection lines flagged).

Each source then reports its health: `ok`, `degraded`, `empty`, or `error`.

Every source returns postings in one shape (`engine/sources/base.py`):
`id, source, company, title, location, remote, salary_min, salary_max, url, apply_url, ats, posted_at, description, company_linkedin`.

## Supported sources

| Source | Method | Default | Terms and notes |
|---|---|---|---|
| Greenhouse, Lever, Ashby | Official public board APIs, per company in `companies.txt` | always on | The cleanest source: the original posting with a real apply form, which get-me-hired fills. |
| Himalayas | Official JSON API (`/jobs/api/search`, `sort=recent`) | **on** | Remote jobs. Credit Himalayas and apply via its link. Optional `opts.seniority` narrows a busy search. Keeps Canadian-dollar pay when `CA` is in `locations.remote_countries`. |
| Remotive | Official API | **on** | Remote jobs. Listings are 24h delayed. Keep to about 4 calls a day. Credit Remotive. |
| NoDesk | Job sitemap plus JSON-LD on job pages; robots.txt honored | **on** | Remote jobs. The sitemap has no dates, so stale postings drop after the detail fetch. |
| Built In | Category pages plus JobPosting JSON-LD on job pages; robots.txt honored | opt-in | Needs a category (below). Applying needs a Built In account. |
| remote100k | Category pages plus JSON-LD; robots.txt honored | opt-in | Needs a category (below). Links straight to the employer's ATS, so most hits resolve to Greenhouse, Ashby or Workday. |
| RemoteOK | Official API | opt-in | Credit and link back. Descriptions can hide "include this word" filters; the posting guard catches these. |
| Fractionus | Webflow list plus page config; robots.txt honored | opt-in | Fractional and interim roles. Only a public preview is shown; the full listing is behind its link. |
| LinkedIn | Unauthenticated guest endpoints (ported from ai-job-search, MIT) | on | Personal use only: automated access is against LinkedIn's User Agreement. See [LinkedIn](#linkedin) below. |
| Remote Rocketship | Official REST API | not built | Needs a paid subscriber key. The adapter is not built yet. |

## Turning sources on
Listing `sources` in `config.json` replaces the defaults, so list the defaults too when you add one:

```json
"sources": {
  "himalayas": {"enabled": true},
  "remotive": {"enabled": true},
  "nodesk": {"enabled": true},
  "remoteok": {"enabled": true}
}
```

A source runs only when it has `"enabled": true`. Each entry can also set `queries` (search terms) and `opts`
(source-specific options, such as Himalayas' `seniority`). `gmh discover --skip-source <name>` leaves one board out
for a single run.

### Built In and remote100k categories
These two boards search by job category, which depends on your field. The category comes from, in order:
1. `config.json`: `sources.builtin.opts.paths` (a Built In path such as `/jobs/remote/nursing`) or
   `sources.remote100k.opts.categories` (a remote100k category such as `healthcare`);
2. your role pack: `sources.builtin_path` or `sources.remote100k_category` (a string or a list);
3. only for the product-management pack, the searchers' built-in product defaults.

A board with no category from any of these is skipped, with a note in the run report, rather than searching the
wrong field. The shipped Chief of Staff pack sets no category, so for it these boards need one in `config.json`.

```json
"builtin": {"enabled": true, "opts": {"paths": ["/jobs/remote/nursing"]}}
```

## Places: US and Canada
`locations.remote_countries` in `config.json` (`["US"]`, `["US", "CA"]` or `["CA"]`) says where a remote role may hire
you. The sources use it like this:
- **Himalayas** keeps a posting's Canadian-dollar pay range when `CA` is listed (otherwise only USD pay is read).
- **LinkedIn** searches one place per country ("United States", "Canada"), plus your home city when it's one of the
  Canadian metros (Toronto, Vancouver, Montreal, Ottawa, Calgary, Edmonton, Waterloo). A US-only config searches
  "United States". `sources.linkedin.opts.locations` overrides this.

Location matching itself (which postings count as your metros or as remote for you) happens after the search, for
every source, from `locations` in `config.json`.

## LinkedIn
LinkedIn's job search uses public guest pages, never your account. It's strictly intended for personal use only, as automated access is against LinkedIn's User Agreement. It is on by default; to leave it out, list only the
boards you want under `sources` in `config.json` (any `sources` block replaces the defaults).

How it searches:
- Newest first: the last day, then 7 days, then 14 (`opts.windows_days`, default `[1, 7, 14]`), each window its own
  search because the guest API ignores sort order.
- 10 cards a page, about 1,000 results per search at most (`opts.pages`, default and max 100, per window, query and
  place), and `opts.max_requests` (default 200) search pages per run, spent newest window first. Within a window,
  queries and places take turns page by page.
- LinkedIn's experience filter keeps mid-senior, director and executive postings by default (`opts.experience`;
  `[]` for all levels).
- A throttled or failed page ends the search and keeps what was found; the run report shows pages used and new
  cards per window.
- Descriptions are fetched only for title matches, at most `opts.max_details` (default 150) per run: titles with a
  level word (the pack's `senior` pattern) first, then titles with none, then step-down titles, newest first within
  each. A role seen on an earlier run reuses its saved description; the rest wait for the next run.
- Apply links sit behind a sign-in, so roles are matched to the company's own ATS board by watchlist or by name.

## Not supported (browse these yourself)

| Source | Why |
|---|---|
| Hiring Cafe | Every automated request, sitemaps included, gets a Cloudflare challenge. Getting past it means defeating bot detection, which get-me-hired doesn't do. |
| SimplyHired | Owned by Indeed, whose terms ban automated access. Cloudflare too. |
| remote.co | Timed out in testing. Mostly routes into paid FlexJobs. |
| Flexa | UK-heavy and JS-rendered. Low yield for US searches. |

## Adding a source

1. Write `search(queries, since_days, opts) -> [posting(...)]` in `engine/sources/`.
2. If list pages lack descriptions, add an `enrich(p)` that fetches them.
3. Register both in `engine/boards.py`.
4. Add a hand-written fixture test in `tests/test_sources.py`.
5. Use `fetch(..., respect_robots=True)` for any page that isn't an official API.
