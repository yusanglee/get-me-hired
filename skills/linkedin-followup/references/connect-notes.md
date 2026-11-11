---
name: connect-notes
description: How the connect note for one company is drafted and checked in the linkedin-followup skill (the packet, the drafter agent, the note's shape and limits, editing a note). Read at step 4 of the company loop.
---

# The connect note

## Draft it
1. `gmh linkedin packet <key> --workspace <ws>` writes the packet and prints its absolute path (by default
   `<ws>/Pipeline/scratch/<date>/note-packet-<key>.json`). Launch the `linkedin-note-drafter` agent with that path as
   its whole prompt ([agents.md](../../../references/agents.md)).
2. It returns one note with `{first}` where the name goes, and the source line of each claim, in this shape:
   `Hi {first}! I recently applied for the <exact role> role at <Company>. <one or two true claims tied to the role> Would love to connect!`
3. If the agent can't run, write the note here the same way, from the packet
   ([platforms.md](../../../references/platforms.md), "Agents").

## What the checks enforce
Claims come only from the approved facts and the materials submitted for this application. The engine checks every
message: 300 characters at most once a first name is in, no em or en dashes, no number the facts lack, no gap
wording. `gmh linkedin table` runs these on each person's message and shows FIX FIRST on a failing one.

## If the user edits the note
Write the edited text to a file and run `gmh check-text note <file> --id <id> --workspace <ws>` (`ok`, or one line
per problem). Fix and re-check before it goes into `gmh linkedin table --note`. The edited note is the user's to
send; nothing is sent for them.
