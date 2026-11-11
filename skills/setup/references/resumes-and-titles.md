---
name: resumes-and-titles
description: Setup steps 2 and 3 - collecting every resume version (PDFs included), cross-checking facts, suggesting target titles, and choosing a shipped role pack or starting a new one. Read before asking for the user's resumes.
---

# Resumes and target titles

## Every version of the resume
1. Ask the user to share **every version of their resume they have**: the current one, older ones, versions tailored
   for different roles (PDF, DOCX, `.txt`, `.md` or pasted text), plus a LinkedIn profile PDF if they like
   (LinkedIn, their profile, More, Save to PDF). More versions are better: together they show which titles and
   keywords they've used, and the facts to build one master resume from.
2. Save pasted text to a `.txt` file in the workspace's scratch folder first. Then
   `gmh setup resumes <ws> <file or folder> <file> ...` keeps each version's text in `resume/sources/` (duplicates are
   kept once). It reads PDFs with `pdftotext`; if it says that is missing, give the install line it prints, or read
   the PDF yourself, save its text to a `.txt` named after the original, and pass that. These versions are evidence
   for titles, keywords and the role pack; they are never used to score or to tailor.
3. Read each version (`gmh setup resumes <ws> --list` lists them). Cross-check titles, companies, dates and numbers
   across the versions and LinkedIn; list every conflict and ask which is right. A fact only one older version has
   is still a fact to confirm, not to drop.
4. **No resume, or they'd rather start from scratch:** a guided interview instead. Ask about each job (title,
   company, dates, location, what they owned, 3 to 6 results with numbers they can stand behind), then education. A
   pasted resume plus questions for whatever it leaves out also works.

## Target titles
1. `gmh setup resumes <ws> --titles` counts each job title across the versions, most common first. **Suggest
   titles from it**, labeled as suggestions: the titles they've held, the titles in each version's headline or
   summary, and how often each appears ("Senior UX Researcher: your title at your last job and the headline of 3
   versions"). Past titles aren't always target titles (a career change, a step up), so ask which they want, then
   **ask for any titles to add** that their resumes don't show. With no resumes, ask for their titles directly.
   Most people have several.
2. `gmh setup suggest-pack --titles "<title 1>" "<title 2>" ...` says which shipped pack covers how many of the
   titles. There is no default pack. Use a shipped pack only when it covers most of the titles, and say what it is:
   `product-management` (checked against real postings) or `chief-of-staff` (a draft from general knowledge, not yet
   tested on real postings). Otherwise offer **a new pack built for their kind of job**: its titles now, its scoring
   rules later from real postings and their resume, every item approved by them.
   - **Shipped pack:** `gmh setup pack-use <ws> <pack>`, then `gmh setup titles <ws> "<title 1>" ...` (one argument
     per title; add `--replace` after the titles to search only these, otherwise they are added to the pack's own).
   - **New pack:** `gmh setup pack-new <ws> --name <lowercase-with-hyphens> --label "<Label>" --titles "<title 1>"
     ...`. Ask whether a title without a level word (senior, lead, staff...) is still a role they want when it
     posts no pay range; if their level words differ, pass `--senior-words <word> <word> ...` (roles with no posted
     range are kept only when the title has one, unless the pay setting says otherwise:
     [search-settings.md](search-settings.md)).
3. Read back each title's "matches" line (and any excluded phrase that was removed). Then
   `gmh setup pack-sample <ws>` once, to see how many real postings each title finds (a scratch search; the
   workspace's queue doesn't change). Say which titles are rare ("Design Researcher: 1 posting") and which near-miss
   titles from `pack-sample/evidence.md` look like their job, and adjust the titles with them.

Whenever the user later asks to search another title, or to see the list (`gmh setup titles <ws> --list`), use
`gmh setup titles`: postings with other titles are skipped by discover and never shown.
