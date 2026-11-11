# Answer bank

Your own answers. They run before the engine's generic rules, so anything here wins.
Generic rules already cover identity, work authorization, EEO, education and
logistics from `profile.yaml`; add lines here only for what they get wrong or don't cover.

Two kinds of line work anywhere in this file:

- A rule: a regex on the lowercased question label, a kind, and an answer.
  Kinds: fixed, eeo, rule, draft, consent, required_only, skip, ask.
  Answers can use `@profile.keys` and `{tokens}` (full_name, home, today, start_date).
- An exact question: the label in bold, then the answer.

## Rules

- `do you have a portfolio` -> fixed: Available on request.
- `have not, and i will not, use ai tools` -> ask
- `within \d+ miles of (the|our) (office|hub)` -> fixed: {home}

## Exact questions

- **Are you a current customer of our product?** -> No
