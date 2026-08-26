# mcp-eveng — session handoff summary

Written to let a new chat continue this project without replaying the
full conversation history. Paste this file's content (or attach it) as
the first message in a new chat, along with the current project zip —
the zip is the authoritative source of truth for the code; this document
covers the *reasoning and investigation* that isn't visible just from
reading the files.

## What this project is

`mcp-eveng` — a Model Context Protocol (MCP) server that lets an LLM
client (Claude Desktop, Claude Code, LM Studio, etc.) drive an EVE-NG
network emulator instance over its REST API: create/edit labs, add/wire
nodes and networks, start/stop/wipe devices, browse templates, manage
folders and users. Built in Python on the `mcp` SDK (`FastMCP`), async
throughout, with a dedicated `EvengClient` wrapping EVE-NG's JSend-style
REST API.

Supports both EVE-NG **PRO/Corporate** and **Community** editions, with a
small number of tools genuinely behaving differently by edition (see
below) — confirmed against EVE-NG's own official
[features-compare page](https://www.eve-ng.net/index.php/features-compare/)
and extensive live testing against real servers of both editions this
session: PRO `6.5.0-27-PRO`, Community `6.2.0-4` (see README's "Tested
versions").

## Architecture at a glance

```
src/mcp_eveng/
  client.py        — async EvengClient (JSend REST, session/relogin handling)
  config.py        — pydantic-settings, .env
  confirmation.py   — shared search→select→confirm state machine for deletes
  dependencies.py   — shared client singleton
  edition.py        — is_pro_edition() -- shared by 3 edition-gated tools
  search.py         — case-insensitive record search helpers
  telnet.py         — raw asyncio telnet client (IAC handling) for telnet_node
  tool_config.py    — per-tool enable/disable (tools.env)
  vendor.py         — vendor extraction + image-availability (has_image/strip_hidden_marker)
  server.py         — FastMCP assembly, transport security
  tools/            — one module per API area: system, folders, users, labs,
                       networks, nodes, console, meta
tests/              — mirrors src/ structure, one test file per module
docs/
  tools-reference.md  — detailed per-tool design notes (README points here)
  install-linux.md / install-windows.md
tools.env.pro.example   — per-tool enable/disable, PRO/Corporate
tools.env.comm.example  — same, Community (2 tools disabled -- see below)
```

43 tools total, organized by area (System, Folders, Users, Labs, Networks,
Nodes, Live console access). Full list with descriptions is in the
README's "Available tools" table.

## Confirmed EVE-NG quirks this project works around

These aren't obvious from reading the code alone — they're the result of
extensive live testing against real EVE-NG servers this session:

1. **EVE-NG's own bulk "all nodes" start/stop endpoint is unreliable on
   PRO.** `start_node`/`stop_node`, when `node_id` is omitted, loop
   through every node individually instead — confirmed via a working
   reference implementation (`evengsdk`) independently avoiding the bulk
   endpoint on PRO too.
2. **A no-image template is marked differently by edition**: `.hided` on
   PRO, `.missing` on Community. `vendor.py`'s `_HIDDEN_SUFFIXES`
   recognizes both.
3. **`get_node_template`'s `has_image` must be computed the same way
   `list_node_templates` computes it** (from the description's suffix),
   not from whether `options.image.list` is non-empty — those two
   signals disagree for a template with no "image" option at all (e.g.
   VPCS, a built-in simulator, not a separately-installed binary).
4. **Session invalidation**: EVE-NG allows only one active session per
   account — logging into the GUI with the same account the server uses
   silently invalidates its session. Confirmed live (server audit log,
   timestamped) this can present as a bare HTTP `400` with a *generic*
   `"fail"` status, not a self-identifying `"unauthorized"` — so
   `EvengClient`'s auto-relogin now retries on any `400` or `401`,
   trusting the HTTP status code alone, not the response body.
5. **Three tools behave differently by edition** (all edition-gated via
   `edition.is_pro_edition`, checked at call time via `get_status`):
   - `connect_interface`: PRO allows wiring running nodes; Community
     requires stopping first — handled automatically.
   - `export_node`: PRO/Corporate-only (confirmed live + official docs);
     returns a clear error on Community instead of EVE-NG's generic one.
   - `share_lab`: PRO/Corporate-only. On Community there's no per-lab
     sharing concept at all — every lab is shared by default (confirmed
     directly by the project's Community user, not from official docs).
6. **User management is NOT edition-gated** — confirmed live by direct
   testing (adding a second admin user, adding a folder, moving a lab all
   worked normally on Community). An earlier assumption to the contrary
   was wrong and was corrected. The six user-management tools are
   disabled by default on *both* editions for a different reason
   (not exposing user administration to an LLM by default).
7. **`delete_lab` is disabled by default on both editions** — deleting an
   entire lab is more severe/harder to recover from than deleting one
   thing inside it, unlike `delete_folder`/`delete_lab_node`/
   `delete_lab_network`, which stay enabled.

## Known issue — genuinely unresolved

**`stop_node` (and anything requiring a node to be stopped first) can
fail persistently on certain PRO nodes with `"Request not valid
(60027)."`, with no fix found despite extensive live investigation.**
Ruled out: session/auth (a fresh session fails identically), node history
(reproduces on brand-new nodes), resource exhaustion (server had ample
spare capacity), all three `EVENG_HTML5` login modes, and
`unl_wrapper -a fixpermissions`. Confirmed the request never reaches
EVE-NG's own stop wrapper script at all (nothing logged server-side),
while the request itself matches EVE-NG's official API docs exactly.
Untried: `unl_wrapper -a restoredb` (more invasive, wasn't available to
try), a raw `curl` comparison, and confirming whether the GUI can stop
the same already-stuck node. Documented in the README's "Known issues"
section — **if you pick this project back up, this is the open thread
most worth continuing.**

## Most recent fix (last thing done this session)

**`connect_interface` could silently overwrite an already-connected
interface.** Reported live: a smaller/weaker (35B) model was observed
connecting interfaces it hadn't been told to, sometimes leaving an
interface disconnected entirely. Root cause: when `interface`/
`target_interface` is given as an explicit numeric index, it was used
directly *regardless of whether it was already connected* — unlike the
name-search/omitted paths, which are scoped to available interfaces only
by construction and were never affected. Fixed with a new `confirm`
parameter: an explicit index that's already connected to something now
returns `status: "confirmation_required"` instead of silently rewiring
it. Verified directly against the extracted real functions (not just
mocked tests) before shipping.

## Other things worth knowing if continuing

- The user has seen "Clone" and "Rename" options in the EVE-NG GUI that
  aren't mapped to any tool yet — mentioned as an observation, not
  requested as a task. Worth asking about if picking this up again.
- This project's `tools.env.pro.example`/`tools.env.comm.example` differ
  in exactly two lines (`export_node`, `share_lab`) — full parity
  otherwise, verified directly against the real files multiple times
  this session after an earlier design iteration got this wrong.
- Every code change this session was verified by compiling
  (`python3 -m py_compile`) and, for anything touching the tool-enable
  config or the interface-resolution logic specifically, by extracting
  and directly executing the real functions against realistic data
  rather than trusting hand-traced logic alone.

## What to say when starting the new chat

Something like: *"Continuing work on mcp-eveng, an MCP server for EVE-NG
network automation. Attached is the current project zip. See
HANDOFF.md inside it for full context on what's been done and what's
still open. I'd like to [pick up the stop_node investigation / add a new
tool / whatever the actual next task is]."*
