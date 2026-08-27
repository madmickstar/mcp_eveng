# mcp-eveng tool reference

Detailed design notes, confirmed EVE-NG quirks, and the reasoning behind
each tool's behavior — moved out of the main README to keep that focused
on getting started. See the README's "Available tools" section for the
full tool list and a one-line description of each.


†-marked tools are disabled by default — see "Controlling which tools are
exposed" in the main README.

**`add_lab_node` resolves `template` by search, not by exact id.**
`template` is a case-insensitive substring match against every available
template's id, name, and (best-effort) vendor — e.g. `"cisco"`,
`"juniper"`, `"vios"`, or `"csr1000v"` all work, not just the exact
template id. Empty (the default) matches every template. However many
match, the behavior is consistent: no matches cancels; exactly one match
proceeds directly with no prompt; more than one match lists every match
(numbered, with vendor shown) and asks you to call again with `selection`
set to the number or exact id/name of the one you want — same
number-or-exact-name pattern as the delete tools. Only templates with an
image installed are ever considered, same as `list_node_templates`'
default.

Once the template is resolved, it auto-fills defaults from it. Rather
than requiring you to know a template's RAM, CPU, ethernet count, console
type, and icon ahead of time, it calls `get_node_template` and uses the
template's own defaults for anything you didn't specify — this works the
same way for every vendor's templates, not just specific ones, since it
reads whatever the template itself reports. `node_type` also defaults to
the template's own declared type if you don't pass one. If the template
has more than one image available and you didn't specify `image`, it
doesn't guess: it returns the list of images (`status:
"selection_required"`) and asks you to call again with the one you want.
With exactly one image (or one you already specified), it proceeds
directly with no prompt.

It also passes through **every other default the template reports** as-is
(e.g. QEMU-specific fields like `qemu_version`, `qemu_arch`, `qemu_nic`,
`qemu_options`), matching what EVE-NG's own "Add Node" UI dialog actually
submits, rather than omitting them and hoping the server fills in
something sensible. One subtlety worth knowing: some list-type template
options report an empty `value` with the real default only encoded in a
list label like `{"value": "", "list": {"": "tpl(e1000)"}}` (observed for
`qemu_nic`) — this is unwrapped correctly rather than sent as an empty
string.

**`left`/`top` (canvas position) are never omitted, even when you don't
specify one** — this is the confirmed root cause of a `500 Internal Server
Error` (no JSON body) that reproduced on *every* node-add attempt against
a live EVE-NG PRO server, regardless of lab, template, node type, or
payload completeness — tracked down via the server's own error log:
EVE-NG's `api_nodes.php` (`apiAddLabNode()`) reads `$_POST['left']`
unconditionally with no `isset()` check, so PHP's "undefined array key"
warning gets promoted to a fatal exception by EVE-NG's own error handler
whenever that key is missing from the request body.

Instead of a bare fallback, an omitted `left`/`top` triggers **canvas
auto-placement**: nodes are placed left to right, 5 per row, 100 units
apart, starting at `(100, 100)`; a new row starts 100 units below the
previous one, back at the left edge. Before using a grid slot, existing
nodes already in the lab are checked, and any slot within 50 units of an
existing node on *both* axes is skipped in favor of the next one — so
adding nodes one at a time (or across many separate calls) lays them out
sensibly instead of piling up on top of each other or on top of anything
already there. You can still override either `left` or `top` with an
exact position, which skips auto-placement (and the extra `list_lab_nodes`
call it would otherwise make) entirely.

**`edit_lab_node(lab_path, node_id, ...)` edits an existing node by id**
(not a name search, unlike `delete_lab_node` — editing is inherently about
one specific node you already know the id of, e.g. from `list_lab_nodes`).
Covers every field EVE-NG's own "Edit Node" dialog exposes — not just the
original small set: `name`, `icon`, `image`, `ram`/`cpu`/`cpulimit`/
`ethernet`, `console`/`config`, canvas position, `delay`, the QEMU-specific
fields (`qemu_version`/`qemu_arch`/`qemu_nic`/`qemu_options`),
`disable_offload`, `sat`, `eth_format`/`eth_name`, and `rdp_user`/
`rdp_password` (for rdp/rdp-tls console nodes). Deliberately excludes
`uuid` — an identity field EVE-NG assigns itself, not something meant to
be user-edited. Only supplied fields are changed. EVE-NG requires a node
to be stopped to edit it, on **both** PRO and Community (unlike
`connect_interface`'s wiring, which PRO allows on running nodes) — this
checks the node's current `status` first and calls `stop_node`
automatically if needed before applying the edit, so you don't have to
stop it yourself first.

If `name` is being changed and another node already has that exact name
(case-insensitive), it does **not** rename it — EVE-NG allows duplicate
node names, but silently creating one seemed worth avoiding by default.
Instead it comes back with `status: "confirmation_required"`, naming the
conflicting node; call again with either a different `name`, or the same
`name` plus `confirm_duplicate_name=true` to use it anyway. This is also
the way to actually *fix* a duplicate-name collision (rather than just
working around it via numbered selection every time, which is all
`delete_lab_node` and friends can do when two nodes share a name).

**`change_node_delay(lab_path, ...)` changes a node's startup delay** (how
many seconds it waits before auto-starting), one node or in bulk.
`node_id` always means single-node mode regardless of `bulk` — sets that
one node's delay to `delay` (default `10`). Otherwise `bulk=true` is
required, in one of two forms:
- `names` given (a name, or list of names — case-insensitive substring
  against every node's name): every match gets an *incrementing* delay
  (`increment`, default `10`) — the first matched node gets `increment`
  seconds, the second `increment*2`, and so on, in the order the names
  were given (and, within one name's several matches, by node id). A node
  matching more than one given name is only assigned a delay once, not
  once per matching term.
- `names` omitted: lists every node in the lab with its *current* delay
  (`status: "selection_required"`) and asks for `order` — the list
  numbers, in the sequence you want increasing delays applied (e.g.
  `"3,1,2"`); a partial subset is fine, only the listed nodes are touched.

Every mode ends the same way — one more explicit confirmation summarizing
every affected node (old delay → new delay) and warning that each will be
stopped first (required regardless of PRO/Community, same as
`edit_lab_node`). Reply **"accept" or "yes"** (`confirm`) to apply — same
wording as every delete tool and `edit_lab_nodes_by_template`, kept
consistent rather than introducing "confirm" as a third phrase for the
same thing. This confirmation step applies to *every* mode, including
single-node — the request that prompted this tool only explicitly asked
for it on the bulk-with-no-names path, but since every mode stops nodes,
the same safety step applies uniformly rather than only some of the time.

**`edit_lab_nodes_by_template(lab_path, vendor=..., template=..., ...)`
bulk-edits interfaces/cpu/memory/icon/image across nodes of exactly one
template** — the multi-node counterpart to `edit_lab_node`'s single-node
scope (`name` stays single-node-only: a duplicate-name check inherently
needs one specific node in mind, not a group). Never targets more than
one template per call.

Search by `vendor` and/or `template` (case-insensitive substring, at
least one required, both AND'd together if given) against each *existing
node's* template id and best-effort vendor — not the global catalog
(`add_lab_node`'s template search). More than one template matching never
guesses: every match is listed (numbered, with vendor and node count) and
you're asked to narrow further — a more specific `vendor`/`template`, or
`template_selection` (number or exact template id) — repeat until exactly
one remains.

Once resolved, `node_selection` picks which of that template's nodes to
target — `"all"`, or number(s)/exact name(s) (space/comma separated).
Unlike template resolution, `"all"` *is* a valid shortcut at this stage.

Then `component` (`"interfaces"`, `"cpu"`, `"memory"`, `"icon"`, or
`"image"` — a few case-insensitive synonyms accepted, e.g.
`"ethernet"`/`"ram"`) and `value` say what to change it to. For
`component="icon"`, `value` isn't used — `icon_search` narrows EVE-NG's
icon catalog the same way template matches do, resolved further via
`icon_selection`. For `component="image"`, `value` also isn't used —
`image_search` narrows *this resolved template's own* valid images (not
a global catalog like icons — images are template-scoped, e.g. `c8000v`
has 4, `viosl2` has 1), resolved further via `image_selection`. This is
what makes it possible to update a shared image (or firmware version)
across every node using a given template in one call, rather than
editing each node individually.

Whatever isn't supplied is prompted for one piece at a time. Every stage
is stateless — each call re-derives everything fresh from what's
currently given, so a reply just needs the one new piece plus whatever
was already resolved, not a repeat of the whole request.

The final step always asks for one more explicit confirmation,
summarizing every affected node, the template, and the change, and warns
that every affected node will be stopped first (required regardless of
PRO/Community, same as `edit_lab_node`). Reply **"accept" or "yes"**
(`confirm`) to apply — the same wording used by every delete tool, kept
consistent rather than introducing a third phrase like "confirm" for the
same thing. Anything else cancels; nothing changes until that reply.

**`connect_interface(lab_path, node_id, ...)` wires nodes together.**
EVE-NG has **no dedicated "connect two nodes" API endpoint** — confirmed
against EVE-NG's own API documentation, a real community troubleshooting
thread, and a working third-party client library, all independently
pointing at the same underlying mechanism: the actual primitive is `PUT
/nodes/{id}/interfaces` with a body like `{"0": "7"}` (interface index →
network id), wiring **one** node's interface to a network.

What looks like a direct line between two node icons in EVE-NG's own GUI
is an ordinary bridge network wired to both nodes' interfaces — but
getting it to actually *render* that way turned out to matter more than
initially assumed. Confirmed live and against a working reference
implementation: it is **not** something set when the network is created.
The correct, working sequence is: create the bridge network (visible,
default settings), wire both nodes' interfaces to it, and only *then*
set the network's own `visibility` field to `0` via a separate follow-up
call. Setting a hide-related field at creation time (tried first here)
does not produce a direct line — it produces no visible cable at all.
`connect_interface` now follows the proven sequence exactly.

`connect_interface` takes exactly one target:
- **`target_node_id`** — connects directly to another node. Creates a new
  bridge network behind the scenes (named `p2p_<node>_<if>_<node>_<if>`,
  the same convention observed used for this in the wild), wires both
  nodes' interfaces to it, then sets its `visibility` to `0` — reproducing
  exactly what a working reference implementation does.
- **`network_id`** or **`network_name`** — connects to a network you
  already created yourself (e.g. via `add_lab_network`). This one *stays
  visible* on the canvas as its own icon, same as wiring a cloud/bridge
  manually. `network_name` does an exact case-insensitive match against
  the lab's current networks and errors if more than one shares that
  name; use `network_id` directly to disambiguate.

`interface`/`target_interface`: an interface index used directly, or any
other string used as a case-insensitive *substring* search against the
node's *available* (unconnected) ethernet interface names, or omit
entirely to match every available interface. There's no
auto-pick-the-first-available default — a specific interface always has
to be named or chosen; if the search (or an omitted `interface`) matches
more than one available interface, this returns `status:
"selection_required"` with a numbered list instead of guessing, and
`interface_selection`/`target_interface_selection` (the number from that
list, or the exact interface name) resolves it on the next call — same
search → select pattern used everywhere else in this project. With only
one available interface, no prompt is needed regardless — there's no
actual choice to make. Scoped to ethernet interfaces only: EVE-NG's
interfaces API returns ethernet and serial as separate lists with no
confirmed data here on whether the `PUT` endpoint's index space covers
serial too, so rather than guess, serial isn't supported by name/search
(an explicit numeric index is still passed straight through either way,
for anyone who knows the right value).

**An explicit index can point at an interface that's already connected to
something — the search/omitted paths can't, by construction, since both
are scoped to available interfaces only.** Reported live: a smaller/
weaker model was observed connecting interfaces it hadn't been told to,
and sometimes leaving an interface disconnected entirely — traced to
exactly this gap. Rewiring an already-connected interface silently
disconnects it from whatever it was previously wired to, with no separate
undo, so this checks first: if an explicit index (source or target)
resolves to an interface with a non-zero `network_id`, it returns
`status: "confirmation_required"` naming the interface and what it's
currently connected to, rather than proceeding — call again with
`confirm=true` to rewire it anyway, or supply a different interface.
This check happens before anything else with side effects (before target
network resolution, before the edition check, before stopping any node),
same discipline as an interface-resolution error.

**EVE-NG PRO allows wiring interfaces on running nodes; Community requires
every node involved to be stopped first.** `connect_interface` checks the
server's edition automatically (via `get_status`'s version string, e.g.
`"6.5.0-27-PRO"`) and, on Community only, stops whichever node(s) are
running before wiring them — you don't have to stop them yourself first,
same automatic behavior as `edit_lab_node`. Everything that can be
validated without side effects (interface resolution, target network
resolution) happens *before* any node is touched, so a node is never
stopped as a side effect of a connection that was going to fail anyway
(e.g. the other node having no free interface) — only once the connection
is confirmed workable does the edition check and any stopping happen.
See the README's "PRO vs Community differences" for the other two tools
that also behave differently by edition (`export_node`, `share_lab`).

**`add_lab_network` sends every field EVE-NG's own GUI sends when creating
a network** — not just `type`/`left`/`top`/`name`. This took two rounds to
actually fix: first, `left`/`top` being always present (the same bug class
as `add_lab_node`'s, but far more confusing here — omitting them from
`add_lab_node` produces a clean `500`; omitting them from
`add_lab_network` doesn't error at all, EVE-NG reports `201 Created` with
a plausible network id, but the network never persists). That alone
turned out not to be sufficient — confirmed live, the network still
silently failed to persist even with `left`/`top` always sent. Comparing
two networks created directly through EVE-NG's own GUI (one visible, one
hidden, left behind specifically for this comparison) against what this
project's request was actually sending revealed the real gap: EVE-NG's
own creation request includes 10 more fields (`style`, `icon`, `width`,
`linkstyle`, `color`, `label`, `visibility`, `hideme`, `native_vlan`,
`smart`) that this project wasn't sending at all. `EvengClient.add_lab_network`
now sends all of them, with the GUI's own observed defaults.
`connect_interface`'s node-to-node mode still polls for the new network to
actually appear before wiring to it (`_wait_for_network_ready`), kept as a
defensive check for genuine propagation delay independent of this.

`hideme` (`0`/`1`) does control whether a network shows its own icon —
that part held up. What *doesn't* is using it to make a node-to-node
bridge render as a direct line, which was this project's original theory
and turned out to be wrong: confirmed live, it produced no visible cable
at all rather than a direct one. The field that actually does this is
`visibility`, and only when set via a separate call *after* the network
is created and wired — never at creation time. See `connect_interface`
above for the corrected, verified-working sequence.

If `network_type` isn't given, `add_lab_network` fetches the current list
of valid types (via `list_network_types`) and prompts for one instead of
guessing or erroring — reply with the exact name, or its number from that
list (resolved as a 1-based index into the freshly-refetched,
alphabetically-sorted list).

`"cloud"`/`"cloud0"` through `"cloud9"` (case-insensitive) are also
accepted, resolved to `"pnet0"` through `"pnet9"` — confirmed against
EVE-NG's own official documentation: what the GUI displays as
`Cloud0`–`Cloud9` is always just `pnetN` at the API level (`cloud`/
`cloudN` isn't a value `list_network_types` or the creation endpoint
itself ever accepts — confirmed live, `list_network_types` only ever
returns `pnetN` keys, never `cloud`). EVE-NG creates exactly 10 of these
during installation, a fixed architectural limit rather than something
that scales with server hardware — each `pnetN` maps to one physical or
virtual NIC on the host, so `"cloud10"` and beyond are deliberately *not*
recognized aliases; they fall through as literal (invalid) type strings.

**`edit_lab_network(lab_path, network_id, ...)`** is the partial-update
counterpart to `add_lab_network`, same pattern as `edit_lab`/`edit_lab_node`
— only supplied fields are changed. This is what `connect_interface` uses
internally to set `visibility=0` after wiring a node-to-node bridge; call
it directly for anything else you want to change on an existing network.

**`start_node`/`stop_node`, when `node_id` is omitted (every node in the
lab), loop through each node individually rather than using EVE-NG's bulk
"all nodes" endpoint.** Confirmed live on a PRO server: the bulk endpoint
is unreliable — a bulk `stop_node()` call returned a genuine `500
Internal Server Error`, and a bulk `start_node()` call reported success
while one node silently never actually started. This isn't specific to
this server or this project's request format: a working reference
implementation (`evengsdk`) independently confirms it, deliberately
avoiding the bulk endpoint on PRO edition and looping per-node instead —
only Community edition uses the bulk endpoint there, per that library's
own source. Looping individually uses the exact same per-node calls
already confirmed working correctly elsewhere in this project. Failures
are aggregated rather than stopping at the first one, so one bad node
doesn't block every other node from being attempted — the result reports
exactly which nodes succeeded and which failed, with each failure's error
message, rather than a single pass/fail for the whole batch. Each node
started this way still respects its own configured `delay` (see
`change_node_delay`) — EVE-NG's staggered-boot behavior isn't tied to
using the bulk endpoint specifically.

**`telnet_node(lab_path, node_id, commands, ...)` is a fundamentally
different kind of tool from everything else in this project.** Every
other tool wraps EVE-NG's own REST API to manage lab-topology metadata
(nodes, networks, wiring, canvas layout). This one doesn't touch that API
at all — it opens a raw TCP connection directly to the host:port EVE-NG
itself reports for a running node's console (`list_lab_nodes`' own `url`
field), the same thing a real telnet client — or EVE-NG's own web console
button — connects to, and sends it live CLI commands. There is no REST
endpoint for "configure a running device's CLI"; the console connection
*is* the only way, in EVE-NG or on real hardware.

The node must already be running (`start_node` first) and use a telnet
console — most node types do; Docker/GUI nodes use rdp/vnc instead and
aren't supported here. Commands are sent one at a time, each only after
the previous one's output has settled (no new data for `wait_seconds`,
default 2s) — sending them all at once would race ahead of prompt changes
(entering config mode, for instance, changes what the device is ready to
accept next). Returns the full session transcript, not just success/
failure, since the actual device output is usually the point.

Implemented from scratch on raw `asyncio` sockets rather than `telnetlib`
— that module was deprecated in Python 3.11 and removed in 3.13, so
building new code on it would be a dead end. `src/mcp_eveng/telnet.py`
handles just enough of RFC 854 to work with EVE-NG's emulated consoles:
IAC (Interpret As Command) option negotiation is handled by refusing
every option offered (`WONT` to `WILL`, `DONT` to `DO`), which keeps the
session as plain text — what capturing scripted command/response output
needs, not a fully negotiated interactive terminal.

This sends whatever `commands` says verbatim to a live device — the same
judgment that applies to any console access applies here; there's no
vendor-aware command-safety filtering (building one would mean parsing
every possible CLI's syntax, which isn't attempted). Given that this is a
materially different risk profile from every other tool here, `telnet_node`
is a candidate worth disabling explicitly if you'd rather it be opt-in —
it's enabled by default like everything else in this project, but see
"Controlling which tools are exposed" in the main README for how to turn
it off in `tools.env`.

**`share_lab(lab_path, ...)` adds users to a lab's `shared` list**, via
`edit_lab` — the field `get_lab` already returns (`"shared": []`), just
not previously exposed as its own tool. `search` is a case-insensitive
substring against every EVE-NG username; empty matches everyone, and the
literal word `"all"` bypasses searching/selecting entirely to share with
every user that exists. Otherwise: no matches cancels; more than 20
matches doesn't dump an unwieldy list — it asks for a more specific
search instead; exactly one match proceeds directly, no prompt; more
than one (up to 20) is shown numbered, with an `"all"` option at the end
meaning every *matched* user, not necessarily everyone on the server.
Existing shares are always preserved — this reads the current `shared`
list first and adds to it, never replaces it, so sharing with one more
person doesn't silently revoke everyone else's access. Final
confirmation lists every user about to be newly added; reply **"accept"
or "yes"** (`confirm`) — same wording as every delete tool, kept
consistent.

**`open_lab` vs `edit_lab`**: `open_lab(name)` is read-only — it looks a
lab up by a loose path/name fragment (same substring matching as
`delete_lab`), reports whether it's locked (by name, e.g. `"Lab
'my_killer_lab' is unlocked."`), and suggests next steps. If more
than one lab matches, they're all listed (numbered) and you pick one via
`selection` — either the list number or the lab's full name/path
(case-insensitive). There is no "open a lab for editing" session in
EVE-NG's API the way there is in its web GUI — every change is its own
direct call, no prior "open" step required. `edit_lab(lab_path, ...)` is
the tool that actually changes a lab's metadata (name, description,
author, version, notes) and needs an exact `lab_path`, not a search string.

**`list_node_templates` only shows templates with an image installed, by
default.** EVE-NG's built-in catalog has ~180 templates, but most servers
only have images uploaded for a handful of them — the rest can't actually
be used to add a node yet. EVE-NG marks a template with no image by
suffixing its description — `.hided` on PRO, `.missing` on Community
(confirmed against live servers of both editions), and `has_image`
(returned by both `list_node_templates` and `get_node_template`, computed
the same way in both so they always agree on the same template) reflects
whichever suffix convention the server actually uses. `list_node_templates`
filters those out unless you pass `include_without_images=true`, in which
case you see the full catalog (each result's `has_image` field tells you
which is which).

**Vendor context on templates and nodes.** EVE-NG's API has no explicit
vendor field anywhere — not on templates, not on nodes. `list_node_templates`,
`get_node_template`, `list_lab_nodes`, and the numbered lists shown by
`delete_lab_node` all include a best-effort `vendor` label instead,
extracted from the template's description text (e.g. `"Cisco CSR 1000V
(XE 16.x)"` → `"Cisco"`, `"Barraccuda NGIPS"` → `"Barracuda"`, collapsing
known EVE-NG typos/full-legal-names onto one canonical name) via a
curated alias map (`vendor._VENDOR_ALIASES`), with a first-word fallback
for anything not in it. Treat it as a helpful label, not authoritative
data — see `src/mcp_eveng/vendor.py`.

**`list_labs`**: always recursive, regardless of `path` — `list_labs()`
(default `path="/"`) walks the whole server; `list_labs("/User1")` walks
the tree starting from `/User1`, not just that one folder's immediate
contents. EVE-NG's API has no recursive-listing endpoint (confirmed
against the actual server source, `api.php`'s `apiGetFolders()` route —
it only ever returns one folder's immediate children), so `list_labs`
walks the tree itself, one request per folder, with loop protection:
every folder's `".."` entry is skipped, each
folder is only ever visited once even if referenced more than once, and
hard `max_depth`/`max_folders` ceilings guard against any unexpected API
response shape. Labs are deduplicated by path, since EVE-NG's virtual
`/Running` folder can otherwise list the same lab twice. `search`, if
given, is a case-insensitive substring match against each lab's path or
file name — the same matching convention (and the same `_lab_matches`
helper) as `delete_lab`/`open_lab`; empty (the default) matches
everything found under `path`.

## Deleting things requires confirmation

Every delete tool (`delete_folder`, `delete_user`, `delete_lab_network`,
`delete_lab_node`, `delete_lab`) goes through the same **search → select →
confirm** flow — up to three calls, no special MCP host capability
required:

1. **Call with just the search string.** Nothing is deleted.
   - No matches: reported, nothing else happens.
   - Exactly one match: reported as a 1-item list; call again with
     `confirm=true` to delete it.
   - More than one match: the full numbered list is reported, and you're
     asked to reply with `selection` — the number(s) and/or exact name(s)
     of the item(s) you want.
2. **(only if there were multiple matches) Call again with `selection`
   set.** The search is re-run fresh and `selection` is resolved against
   the current results; the resolved item(s) are reported back as a new,
   narrowed numbered list. Call again with the same `selection` plus
   `confirm=true` to delete them.
3. **Call with `confirm=true`** (and the same `selection`, if one was
   used) to actually delete.

If you (or the person you're chatting with) reply with nothing, or with
something that doesn't resolve to a real item, the tool responds with an
error/selection prompt and **nothing is deleted** — there's no way to fall
through to a deletion by accident.

This deliberately does **not** use
[MCP elicitation](https://modelcontextprotocol.io/specification/2025-06-18#features)
(`ctx.elicit(...)`). Earlier versions of this project did, but **Claude
Desktop does not implement MCP elicitation at all** — confirmed via
[anthropics/claude-code#41110](https://github.com/anthropics/claude-code/issues/41110):
*"Claude Code CLI supports MCP elicitation, but the Claude Desktop app does
not. Elicitation is only available in the CLI."* Calling `ctx.elicit()`
against Claude Desktop errors out immediately, which made every delete
tool silently inert there. The search/select/confirm flow above needs no
special capability — every step is just an ordinary tool call with
ordinary parameters, mediated by whatever's driving the conversation (the
LLM relays the numbered list, gets your reply, and makes the next call).

Every delete tool also:
- **Requires a non-empty search string** — call it with nothing supplied
  and it fails immediately with a message explaining what's needed, before
  anything is searched.
- **Matches as a case-insensitive substring, never an id.** "test" matches
  "test.unl", "testing.unl", and "/User1/test.unl" alike — it just needs to
  appear anywhere in the name/path being searched. A network or node's
  numeric id is *never* matched against, even though it's shown in the
  numbered list for reference (e.g. `canvas-4 (id 11)`) — only its name.
  A broad substring can match many items at once (e.g. `"canvas"` matching
  every `canvas-N` node in a lab); the search/select/confirm flow is what
  keeps that safe.
- **Selection tokens** (in `selection`) are separated by spaces and/or
  commas, and each one is either a list number from the most recent
  listing, or an item's exact name/path (case-insensitive, not a
  substring this time — it must match exactly one item).

What each tool matches against, whether it allows multiple items per call,
and its search scope:

| Tool | Matches on | Multiple at once? | Searches |
| --- | --- | --- | --- |
| `delete_folder` | Folder **path** substring | No | Recursively (`search_path`, default whole server) |
| `delete_user` | Username substring | No | All users |
| `delete_lab_network` | Network **name** substring (never id) | **Yes** | One lab |
| `delete_lab_node` | Node **name** substring (never id) | **Yes** | One lab |
| `delete_lab` | Lab **path or name** substring | No | Recursively (`search_path`, default whole server) |

**Only `delete_lab_network` and `delete_lab_node` support selecting more
than one item in a call.** For the other three, if `selection` resolves to
more than one item, the call is refused with an error listing the current
matches — you narrow the search or selection down to exactly one.

**`delete_folder` refuses to delete a non-empty folder**, reporting its
contents instead of deleting it. It searches the whole tree (not just one
directory) since matching on a path fragment can't assume which parent
folder to look in the way an exact path could.

**`delete_lab` never deletes more than one lab in a single call**, even
when several labs share matching text in different folders — this is
deliberately stricter than the other tools, matching its status as the
most consequential delete tool in the set. It's also the only delete tool
disabled by default (see "Controlling which tools are exposed") — unlike
`delete_folder`/`delete_lab_node`/`delete_lab_network`, deleting an entire
lab is a more severe, harder-to-recover-from action than deleting one
thing inside it.

⚠️ **This has not been exercised against a live EVE-NG server yet** — the
logic is covered by unit tests, but please verify the actual flow
end-to-end before relying on it for anything you can't afford to lose.
