---
name: mbox
description: Importing past applications from a Google Takeout .mbox file when Gmail is not connected. Read when import-history or a Gmail sync has no Gmail access.
---

# Import from a Takeout .mbox

1. Ask the user for a Google Takeout export: takeout.google.com, Mail, `.mbox`. Name the file back to them; it is
   their private mail and stays on their machine.
2. `gmh gmail from-mbox <file.mbox> --out <ws>/state/gmail/incoming.jsonl --since 6m` (use the lookback the user
   gave). It keeps only the extracted fields, never a body.
3. Skip the search and ingest steps of [gmail.md](../../../references/gmail.md) and go on from "Propose and settle":
   propose, settle unsure mail, decide, apply. The rules there hold: the user approves every row.
