---
name: item-review
description: Reviewing the pending resume-material proposals in the materials skill, one at a time (the question, approve as written, edit, reject, later) and undoing a mistake. Read at step 3 of the materials skill.
---

# Review each proposal

1. `gmh materials show --workspace <ws>` lists the pending proposals with their exact text and sources.
2. Ask about them **one at a time**, with everything **inside the question**
   ([questions.md](../../../references/questions.md)): the exact text (for a template, each change and what it
   replaces), the master-resume lines it rests on, how many roles asked, and "If approved, this exact text is used on
   resumes word for word; the tailor never rewords it." Buttons: **Approve as written**, **Edit**, **Reject**,
   **Later**.
3. On the user's answer for that item:
   - **Approve as written:** `gmh materials approve <pid> --workspace <ws>`.
   - **Edit:** `gmh materials approve <pid> --text "<their exact wording>" --workspace <ws>`. Template proposals take
     no `--text`. An edit is checked again; if it fails, show why and ask again.
   - **Reject:** `gmh materials reject <pid> --reason "<their reason>" --workspace <ws>` (it won't come back on its
     own).
   - **Later:** leaves it pending.

## Undo
Use these when the user says they rejected something by mistake, then ask about it again as above (or step 0 of the
skill for bios):
- A rejected proposal goes back to pending with `gmh materials reopen <pid> --workspace <ws>` (it is checked again
  first).
- Turned-down bios come back on the list with `gmh materials reopen-bios all|<text> --workspace <ws>`;
  `gmh materials bios --rejected --workspace <ws>` lists them.
