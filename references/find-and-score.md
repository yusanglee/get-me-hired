---
name: find-and-score
description: Finding and scoring the day's roles (gmh discover, then gmh score) and the once-a-day rerun guard. Read before running discover or score.
---

# Find and score

1. `gmh setup check --workspace <ws>`. Fix anything it marks as not ready for finding and scoring. If it says this
   computer can't build resumes or fill forms yet, tell the user now (filling needs it) and carry on.
2. `gmh discover --workspace <ws>` finds new postings. It can take 15 minutes or more: tell the user, and run it in
   the background where the tool allows ([platforms.md](platforms.md), "Long commands").
3. Once it has finished, `gmh score --workspace <ws>` scores and tiers them and builds the review page.

## Already ran today?
Discover and score run once a day. If either stops with a first line `RERUN-GUARD: ...` (exit code 3), nothing was
changed. Ask with two options, its message as printed inside the question: **Keep today's results** (recommended)
or **Run it again anyway**. On "Keep", go on with today's run. Only on "Run it again anyway" (or the user saying so
in their own words) run that same command again with `--force`; after a forced discover, score follows on its own.
Never add `--force` without that answer.
