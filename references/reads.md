---
name: reads
description: Getting the posting-reader's gap and strength read for every A, B and gap-tier role not read yet (write briefs, one agent per brief, apply all replies). Read before the review page, or for picked roles that have no read.
---

# Reads

A read is the posting-reader agent's reading of one posting against the master resume ([glossary.md](glossary.md)).
Each role is read once; reads cover tiers A, B and gap. They decide what the user sees: a critical gap takes a role
out of review, a major gap holds an A to B.

1. `gmh review reads --briefs --workspace <ws>` writes one brief per 9 unread roles and prints one path per line.
   Add `--ids <id> ...` for picked roles that have no read (a picked near miss, a rescued drop). "Already has a valid
   read" means there is nothing to do.
2. Launch one `posting-reader` per brief, several at once ([agents.md](agents.md)). Its whole prompt is the brief's
   path. The brief names the master resume, the workspace's gap rules (if any), the roles, the `reply_path` and the
   reply format.
3. Save each reply to its brief's `reply_path` as each agent finishes: `gmh reply <output-file> <reply_path>`
   ([platforms.md](platforms.md), "Saving agent replies").
4. `gmh review reads --apply <reply file> <reply file> ... --workspace <ws>` checks and caches every reply at once,
   re-scores the run while no picks are in yet (after picks it only fills empty `gap_type` and `top_gap` in the
   reviewed rows), and prints the summary. If it rejects a file, fix what it lists or re-run that brief's agent, and
   apply again.
5. Show each picked role's gap in one line. Say plainly which have a critical gap: the rules say pass, but the call
   stays apply until the user changes it.
