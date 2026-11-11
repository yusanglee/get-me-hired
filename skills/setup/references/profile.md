---
name: profile
description: Setup step 4 - filling profile.yaml section by section with the user's yes on each, written with gmh setup profile set. Read before asking for profile facts.
---

# The profile

`profile.yaml` holds the facts forms ask for. Fill it section by section: identity, home, work authorization,
languages, attestations, education, employment, EEO, preferences, salary, location answers, files and forms.

1. Show each section's values and get a yes before writing it. Ask legal attestations exactly and never infer them
   or any EEO answer ([rules.md](../../../references/rules.md), "Facts only").
2. Write each confirmed value in the same turn: `gmh setup profile set <dotted.path> <value> --workspace <ws>` (for
   example `identity.email`). `--add` appends to a list; `--json-value` reads the value as JSON (lists, mappings,
   exact strings). It refuses an unknown top-level key. `gmh setup profile show [<path>] --workspace <ws>` prints
   the profile or one value.
3. **Canada:** when the user would work in Canada, ask `work_authorization.authorized_canada` and
   `work_authorization.needs_sponsorship_canada` exactly. Canadian employment-equity questions
   (`eeo.employment_equity.*`) default to "decline".
4. **Forms:** these are the exact strings typed into application pickers. Fill the obvious ones (city, school,
   degree, dates) and leave the rest for the first form fill.
5. Empty is fine: a value left empty makes that form question stop for the user instead of being guessed.
   `gmh setup check <ws>` shows what is still empty.
