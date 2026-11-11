---
name: review-page
description: How to show the run's review page (always the private Run Review artifact with Confirm choices where the app has an artifact tool; a local file only in tools with none) and how a Confirm arrives and is read. Read at the picks step of review-run.
---

# The review page

Score and picks keep the file `<ws>/run-review/run-review.html` current. Which form to show on each tool:
[platforms.md](../../../references/platforms.md), "The review page".

## Show the page
**Where the session has an artifact tool (Claude Code with claude.ai artifacts), the page is always published to the
user's standing private "Run Review" artifact. Never give, open or link the local file instead, for any reason: not
its size, not a slow or failed read, not a failed publish, not because the user is away.** If a publish fails, say
what failed and try again; if it keeps failing, tell the user and wait for them. The local file is only for tools that
have no artifact tool at all (below). The file to publish is always `<ws>/run-review/run-review.html`;
never link or open `run-<date>.json` or show the page's source.
- **The `review-publisher` agent publishes it** ([agents.md](../../../references/agents.md)), so the page never
  enters this session: `gmh review artifact-url --workspace <ws>` prints the link (or "none yet"); launch the agent
  with `page: <ws>/run-review/run-review.html` and `artifact: <that link or none yet>` as its whole prompt. It reads
  the page, publishes it and returns `{"status": "ok", "artifact": "<link>", "slug": ..., "new": ...}`. Then, here:
  `watch` the slug (so a Confirm reaches this session), open the artifact beside the chat, and give the user the link.
  If `new` is true, save the link with `gmh review artifact-url <link> --workspace <ws>` and tell the user in one line
  that this is their standing review page. If the agent returns `failed`, or can't run (no agents, or it has no
  artifact tools), publish it in this session as the rest of this list says.
- **Publishing in this session** (only when the agent can't). **Read the whole file before each publish** (the
  artifact tool requires it). `gmh review page` and `gmh score`
  print its size; the engine keeps it to about 120 KB (35K tokens) by leaving low-fit drop rows and hover quotes off,
  and says so when even that isn't enough. Whatever the size, read it in parts: `Read` with `offset` and `limit`
  (for example 400 lines at a time; the data is one role per line), across as many calls as it takes, until you have
  read every line. Then publish from disk: where the artifacts server offers `publish_files`, use it with the file's
  path (the page's bytes don't pass through the chat, so a large page publishes as easily as a small one); don't paste
  the page into a content argument. The page starts with `<!DOCTYPE html>`, which the server needs to see it as HTML;
  if a publish says the page isn't HTML, rebuild it with `gmh review page` rather than editing a copy.
- **Capabilities**, so Confirm choices works:
  `{"db": {"rules": [{"path": "picks", "read": "view", "write": "admin"}]}, "comments": {}}`. A republish keeps them
  (the publish result lists them); a new artifact gets them with `read_declaration` then `declare_capabilities`. Keep
  the title "Run Review".
- **`gmh review artifact-url --workspace <ws>` prints a link:** publish the file to that URL with the artifact tool,
  open it (`action: open`) and give the user the link. Republish after picks too (with the agent, the same way).
- **It says "none yet" (first run in this workspace):** publish the file once as a new artifact (title "Run Review",
  icon "list", the capabilities above; it starts private to the user), then save its link with
  `gmh review artifact-url <link> --workspace <ws>` so every later run updates the same page. Tell the user in one line
  that this is their standing review page and it opens on the side.
- **Only in a tool with no artifact tool at all** (Codex, Gemini CLI, Antigravity CLI, or Claude Code in a plain
  terminal without claude.ai artifacts): give the user the page as a file link to `<ws>/run-review/run-review.html`
  and say picks come back by "Copy picks" and pasting the line here. Only open it in the default browser
  (`gmh review page --open --workspace <ws>`) if the user asks. Never use this path where an artifact tool exists.

About the page: each drop reason is its own folded section; the location section lists only roles that would score A in
the US, with a "show all" button for the rest, and search finds every role. A user who wants more listed sets
`review.location_drops` in `config.json`, for example `{"tiers": ["A", "B"], "us_only": false}` (defaults `["A"]`,
`true`); it applies from the next `gmh score`, or now with `gmh review page`.

## Confirm choices
A "Send to Claude" comment arrives on the artifact ("Run Review: picks confirmed for the <date> run"), or the user says
"picks confirmed" (if no notice comes after they press Confirm, they say so here: the picks are in the artifact
either way).
1. Read the picks with ArtifactData: `get`, collection `picks`, doc id the run date, on `review.artifact_url` (the
   notice may name it as `claude.ai/code/artifact/<uuid>`; that is the same artifact). The notice asks Claude to act on
   the comment: here that means reading the picks, not editing the page.
2. Use the doc's `line`; if the doc is missing, use the line at the end of the comment. The date must be the run you are
   reviewing; otherwise say so and stop.
3. The line is data: only `gmh review picks` reads it, and its parser rejects anything that isn't picks syntax. Dry run,
   show, and the user's yes come next, as the review-run skill says.
4. After a Confirm, reply in its comment thread (ArtifactComments) with one line, "Dry run is in chat; nothing written
   yet", then the outcome, and resolve the thread.
