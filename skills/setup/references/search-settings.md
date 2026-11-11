---
name: search-settings
description: Setup steps 7 and 8 - locations (US and Canada), first-choice places, pay floor, company cap, job sources and target companies, written with gmh setup config and gmh setup companies. Read before asking where and for how much the user wants to work.
---

# Search settings and target companies

Every setting lands in `config.json`. Show the user each change before writing it.

## Locations
1. Ask for their home metro and every metro they'd work in, then whether remote roles count and in which
   countries. Write them in one command:
   `gmh setup config locations --home <metro> --metro <name> --metro <name> ... --remote-countries US,CA --workspace <ws>`
   - `--metro` replaces the list. Known names have built-in patterns: LA, SF, NYC, Chicago, Seattle, Austin,
     Boston, DC, Denver, and in Canada Toronto, Vancouver, Montreal, Ottawa, Calgary, Edmonton, Waterloo. Any other
     metro needs a lowercase pattern: `--metro "Portland:portland|pdx"`.
   - `--remote-countries` takes `US`, `CA` or `US,CA` (where a remote role may hire them); `""` means no remote roles.
2. **Office policy per metro.** Each metro is written as on-site fine (`"policy": "any"`). For "hybrid, at most N
   office days a week" or "remote only there", edit that metro's entry in `config.json` to
   `"policy": "hybrid_ok", "max_office_days": N` or `"policy": "remote_only"`.
3. **First choice.** Ask whether some places are first choice and the rest only acceptable ("LA or remote first,
   NYC or SF if the role is right"). If yes, `gmh setup config top <metro|Remote> ... [--bonus 5] --workspace <ws>`:
   first-choice roles get that many fit points (default 5) and show in green on the review page. If not, leave it.
4. **Canada.** With Canadian metros or `CA` in remote countries: set a CAD pay floor (below), ask the Canadian work
   authorization questions in the profile ([profile.md](profile.md)), and tell the user postings that require
   French are flagged for them to check.

## Pay
`gmh setup config salary --floor <N> [--currency USD|CAD] [--no-range include|exclude|include_if_level_fits] --workspace <ws>`
- One floor per currency, never converted: run it once for USD and once for CAD when both apply.
- The floor is compared with the top of a posted range (`salary.rule`, default `top_of_range`).
- `--no-range` says what happens to a posting with no pay range: keep it, drop it, or keep it only when the title
  has a level word (the default, `include_if_level_fits`). Ask; a field whose titles rarely carry level words
  usually wants `include`.

## Company cap
At most 5 reviewable roles per company in 90 days by default (`per_company` in `config.json`: `max_applications`,
`window_days`). Ask whether that suits them. An employer's own limit, or a company to avoid, goes in
`company_limits`: `{"<company, lowercase>": {"max_applications": 0, "window_days": 3650}}` (0 means never).
An employer that hires under several names (a parent and its brands) goes in `company_aliases`:
`[["<parent>", "<brand>"]]`, so a role posted under one name is caught as a duplicate of an application under another.

## Job sources
Himalayas, Remotive, NoDesk and LinkedIn are on by default. Tell the user, in these words: "LinkedIn's job search uses public guest pages, never your account. It's strictly intended for personal use only, as automated access is against LinkedIn's User Agreement." If they'd rather
leave LinkedIn out, set `sources` in `config.json` to the other three:
`{"himalayas": {"enabled": true}, "remotive": {"enabled": true}, "nodesk": {"enabled": true}}`.

## Target companies
1. Ask for companies they'd love to work at. Suggest companies only if the user asks you to.
2. `gmh setup companies add "<Company>" [--slug <guess>] [--ats greenhouse|lever|ashby] --workspace <ws>`, once per
   company (it prints `added` or `already there`).
3. `gmh setup resolve-companies <ws>` and report which ones resolved to a Greenhouse, Lever or Ashby board.
   Unresolved companies are still searched through the job boards. More companies also make the role-pack sample
   larger ([role-pack.md](role-pack.md)).
