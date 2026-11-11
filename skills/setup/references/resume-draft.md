---
name: resume-draft
description: Setup steps 5 and 6 - building one resume document from the user's own words and approving it bullet by bullet, then the resume layout rules. Read before drafting the resume.
---

# The resume draft

## Build it
Build one resume document as JSON from the user's own text: the newest version as the base, older versions for
bullets and jobs it dropped (each one is the user's words; ask before bringing one back).

```json
{"bio": "Product Leader  ·  Consumer Apps",
 "summary": "...",
 "experience": [{"id": "acme", "role": "Senior PM", "dates": "Jan 2022 - Present", "company": "Acme",
                 "location": "Chicago, IL", "scope": "One line on the company.",
                 "bullets": ["Grew **X** by ...", "..."]}],
 "skills": "Term  |  Term  |  Term",
 "education": [{"school": "State University", "degree": "B.A., Economics", "years": "2010 - 2014"}],
 "extra_sections": [{"heading": "INTERESTS", "text": "..."}]}
```

Experience is newest first; each job's `id` is short and lowercase; the result in each bullet is in `**bold**`;
`extra_sections` is optional. Name and contact lines come from the profile. Save it to a file in the scratch folder
and run `gmh setup resume-draft <ws> <file>`: it writes `resume/draft/base.json` and a `master-resume.md` marked
unapproved.

## Approve it
Walk through the summary, then each job's bullets. For each: keep, edit (in the user's wording) or drop. Tighten
grammar or formatting only; never add a number, scope, tool or outcome their documents don't state. Apply the
changes to the draft and run `resume-draft` again. Once the user approves the whole document,
`gmh setup resume-approve <ws>`. Only approved templates are ever used to tailor.

## Layout rules
Offer the resume layout checks, with these values for a new user, and write each the user accepts with
`gmh setup config resume <key> <value> --workspace <ws>`:

| Key | Value | Checks |
|---|---|---|
| `max_pages` | 2 | at most this many pages |
| `max_scope_lines` | 2 | each job's scope line fits in this many lines |
| `min_last_line_words` | 3 | no bullet, scope, summary or skills line ends on fewer words |
| `skills_lines` | 3 | the skills line takes exactly this many lines |
| `max_page1_free_pt` | 40 | page 1 ends with at most this much empty space |

`pages` (an exact page count) and `page_breaks` are set after the first build looks right. A check that is not set
is off.
