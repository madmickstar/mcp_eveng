# mcp-eveng

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets LLM
clients (Claude Desktop, Claude Code, or any other MCP host) drive an
[EVENG](https://www.eve-ng.net/) network emulator instance: create and edit labs,
add/wire nodes and networks, start/stop/wipe devices, and browse templates,
folders and users — all through the EVENG REST API.

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Choosing a transport](#choosing-a-transport)
- [A note on sessions and relogin](#a-note-on-sessions-and-relogin)
- [PRO vs Community differences](#pro-vs-community-differences)
- [Configuration](#configuration)
  - [EVENG connection](#eveng-connection-always-used-regardless-of-transport)
  - [MCP network settings](#mcp-network-settings-only-used-with---sse-or---http)
    - [`MCP_LOG_LEVEL`](#mcp_log_level-options-and-where-logs-go)
    - [`MCP_ALLOWED_HOSTS`](#mcp_allowed_hosts-dns-rebinding-protection)
    - [`MCP_STATEFUL`](#mcp_stateful-session-persistence-across-restarts)
- [Available tools](#available-tools)
- [Controlling which tools are exposed](#controlling-which-tools-are-exposed)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Known issues](#known-issues)
- [Development](#development)
  - [Why `mcp` is pinned below `2.0`](#why-mcp-is-pinned-below-20)
- [Publishing to PyPI](#publishing-to-pypi)
- [License](#license)
- [Tested versions](#tested-versions)

## Features

- Full coverage of the documented EVENG REST API: auth, system status, node
  templates, network types, folders, users, labs, lab networks, lab nodes
  (including start/stop/wipe/export), topology, links and pictures. Plus
  one PRO/Corporate-only, undocumented endpoint reverse-engineered from a
  live capture: per-connection link quality (delay/jitter/packet loss/
  bandwidth) — see `set_link_quality` and `tools/quality.py`.
- Every destructive tool (delete folder/user/network/node/lab) goes through
  a search -> select -> confirm flow before anything is deleted -- no
  special MCP host capability required (Claude Desktop doesn't support MCP
  elicitation, so this deliberately avoids depending on it).
- All three MCP transports: `stdio` (default), `sse`, and `streamable-http`
  (recommended for networked deployments), selected with a CLI flag.
- DNS-rebinding Host-header protection and optional stateless streamable-http,
  both configurable.
- Async, typed, cookie-session-aware EVENG client with automatic re-login on
  session expiry.
- Configuration lives entirely in environment variables / a `.env` file —
  nothing is hardcoded.
- Ships as an installable, PyPI-packagable Python distribution with a full
  unit test suite.

## Installation

This project is **not published on PyPI** — install directly from a git
clone:

```bash
git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng
pip install -e .
```

For local development and running it, OS-specific setup (virtual
environment activation, path syntax, Claude Desktop JSON config) differs
enough to warrant their own guides:

- **[Linux / macOS install & running guide](docs/install-linux.md)**
- **[Windows install & running guide](docs/install-windows.md)**

Both cover cloning and installing, choosing a transport (`stdio` /
`--sse` / `--http`), and the exact Claude Desktop / Claude Code JSON
configuration for stdio and streamable-http.

PRO/Corporate only, and a substantially bigger setup than anything
else in this project: **[Capture relay guide](docs/capture-relay.md)**
-- streams an EVE-NG PRO Wireshark capture to a local Wireshark without
a personal SSH+sudo account on the EVE-NG host. Implemented and
unit-tested but not yet verified against a live server -- see the
guide's status note before relying on it.

## Choosing a transport

Transport is a **CLI flag**, not an environment variable: no flag runs
`stdio` (default, used when an MCP host launches the server as a
subprocess), `--sse` runs the legacy SSE transport, `--http` runs
Streamable HTTP (recommended for networked deployments). `--sse` and
`--http` are mutually exclusive. See the OS-specific guides above for the
exact commands and Claude Desktop JSON configuration for each.

- **stdio** (no flag): the MCP host supplies configuration directly in
  its own `env` block. No `.env` file or `MCP_*` variable is needed in
  this mode at all.
- **`--sse` / `--http`**: you run the process yourself as a standalone
  network service, so you'll typically want a `.env` file for both the
  `EVENG_*` connection settings and the `MCP_*` network settings below.

## A note on sessions and relogin

EVE-NG only allows **one active session per user account** — confirmed
against EVE-NG's own official documentation: "each user can login from a
single location only. If the same user login twice, the second login
disable the first one." If the account this server logs in as (via
`EVENG_USERNAME`/`EVENG_PASSWORD`) is the same account used elsewhere at
the same time — the EVE-NG GUI, a separate script, another instance of
this server — whichever logs in most recently silently invalidates every
other session, including this one.

This is confirmed to actually happen, not just a documented possibility —
traced via a timestamped EVE-NG server audit log (`api.txt`) showing a
`stop` request failing with `400` in the exact same second as a second
login to the same account. What that log also revealed: the invalidated
session did **not** come back self-identifying as an auth problem — no
`status: "unauthorized"` in the response body, just a bare `400` with a
generic `"fail"` status and EVE-NG's generic `"Request not valid"`
message, indistinguishable at the JSON level from any other validation
failure. An earlier version of this project's relogin check looked for
the documented `status: "unauthorized"` marker and missed this exact case
because of that gap between documented and observed behavior.

`EvengClient` now retries once, transparently, on **any** `400` or `401`
response — trusting the HTTP status code alone, not the response body.
The trade-off, accepted deliberately: a genuine validation failure
unrelated to auth (e.g. an invalid template name) also gets one wasted
relogin-retry under this broader check, since relogging in obviously
doesn't fix bad parameters — but it reproduces the identical final error
either way, just with one extra round-trip. That's a better trade than
silently missing real session invalidation, which is now confirmed to
happen in exactly the shared-account workflow described above.

If you're troubleshooting something similar, using a separate, dedicated
account for this server (rather than sharing your own login) rules this
class of issue out entirely.

## PRO vs Community differences

EVE-NG's REST API has no explicit "edition" field, but the version string
`get_status` returns carries a `-PRO` suffix on Professional/Corporate/
Learning Center tiers (confirmed live: `6.5.0-27-PRO`); plain Community
builds don't have it (confirmed live: `6.2.0-4`). This is the only
reliable signal for which edition a server is running, and it's what
every edition-aware behavior below derives from (`edition.is_pro_edition`).
An unrecognized or missing version string is treated as Community, the
more conservative assumption.

Five tools genuinely behave differently by edition — confirmed against
EVE-NG's own official [features-compare page](https://www.eve-ng.net/index.php/features-compare/),
live testing, or both:

- **`connect_interface`**: PRO allows wiring interfaces on running nodes;
  Community requires every node involved stopped first. This tool checks
  automatically and, on Community only, stops any running node(s)
  involved before wiring them — you don't need to handle this yourself.
- **`export_node`**: listed on the official comparison page as a separate
  toggleable feature ("Export/Import configs or config packs to local
  PC"). Confirmed live: fails unconditionally on Community — across
  multiple node types, running and stopped, with and without a saved
  startup config — while the identical request shape works normally for
  `start_node`/`stop_node`/`wipe_node` on the same server. This tool
  checks edition first and returns a clear error immediately on
  Community, rather than the generic `"Request not valid"` EVE-NG itself
  gives no useful detail on.
- **`share_lab`**: listed on the official comparison page as two separate
  toggleable features ("Shared Lab", "Shared Project"). Confirmed live on
  Community: `get_lab` never returns a `shared` key at all, and
  attempting to actually add a share fails with `"Lab has not been
  modified"` — the request is silently accepted with no effect. Confirmed
  directly (Community user, not from the official docs): there's no
  per-lab sharing concept to toggle in the first place — all labs are
  shared by default. This tool checks edition first and returns a clear
  error immediately, before wasting a search/select round-trip on a
  feature that would fail anyway.
- **`set_link_quality`**: per-connection delay/jitter/packet-loss/bandwidth,
  set independently on each side. Unlike the three tools above, this
  isn't a restricted version of a shared feature — it has no Community
  equivalent at all (confirmed directly by a user: no GUI option exists
  there), and there's no open-source Community-side code to cross-check
  against either. There's no documented public API for it — EVE-NG's own
  API docs don't cover it, and PRO's backend is closed-source — so the
  request shape in `tools/quality.py` was captured live from a real PRO
  server's own GUI network traffic, not inferred. One confirmed
  restriction: a side attached to a network of any kind (not just a
  literal bridge) can't have its quality set at all — EVE-NG forces it
  to 0 regardless of what's requested. The far side's current values are
  read automatically from `get_lab_topology` (confirmed live that a PRO
  server's response includes them) rather than needing to be supplied
  explicitly.
- **`list_captures`/`get_capture`**: EVE-NG PRO forces Wireshark captures
  into an embedded Guacamole session rather than Community's
  browser-protocol-handler handoff to a local Wireshark. These tools
  (plus a standalone relay service and a Windows `.bat` companion) let a
  PRO capture stream to a local Wireshark without a personal SSH+sudo
  account on the EVE-NG host — PRO/Corporate only, no Community
  equivalent needed, and disabled by default even on PRO until the
  supporting infrastructure is set up. See
  [docs/capture-relay.md](docs/capture-relay.md) for the full
  architecture and setup — and its status note, since this hasn't been
  verified against a live server yet.

The six user-management tools (`list_users`, `get_user`, `add_user`,
`edit_user`, `delete_user`, `list_user_roles`) are **not** edition-gated —
confirmed via direct manual testing against a real Community server
(adding a second admin user) that user management works normally there.
They're disabled by default on both editions in `tools.env.comm.example`/
`tools.env.pro.example` alike, for the same general reason (not exposing
user administration to an LLM by default), not because Community can't
support it — see "Controlling which tools are exposed" below. An earlier
version of this section (and of `tools.env.comm.example`) assumed user
management was Community-unsupported and omitted these tools entirely;
that assumption was wrong and has been corrected.

A few other confirmed differences worth being aware of, per the same
official comparison page, though nothing in this project currently
adjusts behavior for them: node limit per lab (63 on Community vs 1024 on
PRO/Corporate), and TCP port allocation (fixed 128 per POD on Community
vs dynamic 1–65000 on PRO/Corporate).

## Configuration

Copy `.env.example` to `.env` and fill in your EVENG server details:

```bash
cp .env.example .env
```

### EVENG connection (always used, regardless of transport)

| Variable | Default | Description |
| --- | --- | --- |
| `EVENG_HOST` | `127.0.0.1` | EVENG server IP or hostname — **no scheme or port**, those are separate variables below |
| `EVENG_PORT` | `443` | EVENG server port |
| `EVENG_PROTOCOL` | `https` | `http` or `https` |
| `EVENG_USERNAME` | `admin` | Login username |
| `EVENG_PASSWORD` | `eve` | Login password |
| `EVENG_HTML5` | `-1` | EVENG `html5` login flag (`-1` auto, `0` Pro/HTML5-only, `1` native console) |
| `EVENG_VERIFY_SSL` | `false` | Verify TLS certs. Default is `false`, since EVE-NG (especially Pro) commonly uses a self-signed HTTPS cert; set to `true` if your server has a valid cert |
| `EVENG_TIMEOUT_SECONDS` | `30` | HTTP request timeout |

Since `EVENG_HOST` is an IP/hostname only, always set `EVENG_PORT` and
`EVENG_PROTOCOL` explicitly to match your deployment rather than relying on
the https/443 defaults.

### MCP network settings (only used with `--sse` or `--http`)

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_HOST` | `127.0.0.1` | Bind host |
| `MCP_PORT` | `8000` | Bind port |
| `MCP_HTTP_PATH` | `/mcp` | Mount path for the Streamable HTTP app (`--http`) |
| `MCP_SSE_PATH` | `/sse` | Mount path for the legacy SSE app (`--sse`) |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `MCP_ALLOWED_HOSTS` | `localhost:*` | Comma-separated Host-header allowlist. **Required** when `MCP_HOST` is not a loopback address |
| `MCP_STATEFUL` | `true` | `false` disables streamable-http session persistence |

All variables can also be set as real environment variables, which take
precedence over `.env`.

`MCP_TOOLS_CONFIG_PATH` (default `tools.env`) applies to **every**
transport, including stdio — it isn't scoped to `--sse`/`--http` like the
rest of this table, since tool registration itself doesn't depend on
transport. See "Controlling which tools are exposed" below.

#### `MCP_LOG_LEVEL`: options and where logs go

Options are the standard Python logging levels — `DEBUG`, `INFO`, `WARNING`,
`ERROR`, `CRITICAL` (case-insensitive; an invalid value fails fast at
startup). Logs always go to **stderr**, never stdout, in every transport —
not just stdio — because stdout is reserved for the stdio JSON-RPC stream
and nothing else should ever print to it. There's no file logging built in;
redirect stderr yourself if you want persistent logs, e.g.
`mcp-eveng --http 2>> mcp-eveng.log`.

#### `MCP_ALLOWED_HOSTS`: DNS-rebinding protection

The `mcp` SDK validates the HTTP `Host` header on `--sse`/`--http` requests to
guard against DNS-rebinding attacks ([`TransportSecuritySettings`](https://github.com/modelcontextprotocol/python-sdk)).
The default, `localhost:*`, matches the default loopback bind host
(`MCP_HOST=127.0.0.1`) for local use out of the box. When `MCP_HOST` is
anything else (e.g. `0.0.0.0` to bind all interfaces), update
`MCP_ALLOWED_HOSTS` to match — since it now has a non-empty default,
`mcp-eveng` no longer refuses to start if you forget; it starts, but then
rejects every request at runtime with a Host-header mismatch, which is a
more confusing failure to debug than a startup error. See
[Troubleshooting](#troubleshooting) if requests are being rejected
unexpectedly.

Format is a comma-separated list of `host:port` or `host:*` (any port)
entries, matching the SDK's native `allowed_hosts` syntax:

```bash
MCP_ALLOWED_HOSTS="localhost:*,192.168.10.100:*"
```

#### `MCP_STATEFUL`: session persistence across restarts

Streamable HTTP is stateful by default (`stateless_http=False` in the SDK):
each client gets a session id tied to server-side state. If you restart the
server, clients that already negotiated a session can be left holding a
session id the server no longer recognizes. Set `MCP_STATEFUL=false` to run
with `stateless_http=True` instead, which drops session persistence so a
restart never confuses connected clients — useful for `--http` deployments
that get redeployed/restarted regularly. This is a real SDK feature
(`FastMCP(..., stateless_http=...)`), not a workaround.

For running the server and configuring it in Claude Desktop / Claude Code
(both stdio and streamable-http), see the
**[Linux/macOS](docs/install-linux.md)** or
**[Windows](docs/install-windows.md)** guide — the exact commands and
JSON differ enough between platforms (path syntax, shell env-var syntax,
and how each OS handles `PATH` for GUI-launched subprocesses) that they're
kept there rather than duplicated here.

## Available tools

Tool names have no prefix (`get_status`, not `eveng_get_status`) — be aware
this means a name could collide with another MCP server's tool if you ever
connect more than one server with overlapping names to the same client.

| Area | Tool | Description |
| --- | --- | --- |
| System | `get_status` | Reports EVE-NG server status and version. |
| | `list_node_templates` | Lists available node templates. |
| | `get_node_template` | Gets details for a single node template, including its images. |
| | `list_network_types` | Lists valid network types (bridge, cloud/pnetX, etc.). |
| | `list_user_roles` | Lists available user roles. Disabled by default. |
| Server introspection | `list_tools` | Lists the tools published by the MCP server. |
| Folders | `list_folder` | Lists the contents of a folder. |
| | `add_folder` | Creates a new folder. |
| | `move_folder` | Moves or renames a folder. |
| | `delete_folder` | Deletes a folder. Requires user confirmation before it does anything. |
| Users | `list_users` | Lists user accounts. Disabled by default. |
| | `get_user` | Gets details for a single user. Disabled by default. |
| | `add_user` | Creates a new user account. Disabled by default. |
| | `edit_user` | Edits an existing user account. Disabled by default. |
| | `delete_user` | Deletes a user account. Requires user confirmation before it does anything. Disabled by default. |
| Labs | `get_lab` | Gets metadata for a lab. |
| | `open_lab` | Looks up a lab and reports its lock status. |
| | `create_lab` | Creates a new lab. |
| | `edit_lab` | Edits a lab's metadata. |
| | `share_lab` | Shares a lab with one or more users. |
| | `move_lab` | Moves a lab to a different folder. |
| | `delete_lab` | Deletes a lab. Requires user confirmation before it does anything. Disabled by default. |
| | `get_lab_topology` | Gets a lab's node/network topology. |
| | `get_lab_links` | Gets a lab's link (interface) mappings. |
| | `list_lab_pictures` | Lists background pictures placed in a lab. |
| | `list_labs` | Recursively lists every lab under a folder. |
| Networks | `list_lab_networks` | Lists networks in a lab. |
| | `add_lab_network` | Adds a network to a lab. |
| | `edit_lab_network` | Edits an existing network. |
| | `delete_lab_network` | Deletes a network. Requires user confirmation before it does anything. |
| Nodes | `list_lab_nodes` | Lists nodes in a lab. |
| | `add_lab_node` | Adds a node to a lab. |
| | `edit_lab_node` | Edits an existing node. |
| | `change_node_delay` | Changes a node's startup delay, one node or in bulk. |
| | `edit_lab_nodes_by_template` | Bulk-edits interfaces/cpu/memory/icon/image across nodes sharing a template. |
| | `delete_lab_node` | Deletes a node. Requires user confirmation before it does anything. |
| | `get_node_interfaces` | Gets a node's interfaces and what they're wired to. |
| | `connect_interface` | Wires a node's interface to another node or to a network. |
| | `start_node` | Starts a node, or every node in a lab. |
| | `stop_node` | Stops a node, or every node in a lab. |
| | `wipe_node` | Wipes a node's saved configuration. |
| | `export_node` | Exports a node's running configuration. |
| Live console access | `telnet_node` | Sends CLI commands to a running node's console over telnet. |

"Disabled by default" tools: see "Controlling which tools are exposed"
below for how to turn them on. "Requires user confirmation" tools: see
`docs/tools-reference.md` for the search → select → confirm flow they
each go through before anything is deleted.

More detailed information about each tool — confirmed EVE-NG quirks,
design reasoning, and non-obvious behavior — can be found in
**[docs/tools-reference.md](docs/tools-reference.md)**.

## Controlling which tools are exposed

Every tool can be individually enabled or disabled, via a dedicated
dotenv-syntax config file — kept separate from the main `.env` so tool
visibility is easy to review and diff independently of connection
settings. Copy **`tools.env.pro.example`** (PRO/Corporate edition) or
**`tools.env.comm.example`** (Community edition) to `tools.env` (or point
`MCP_TOOLS_CONFIG_PATH` at wherever you keep it) and set any tool to
`enabled` or `disabled`:

```
get_status=enabled
list_users=disabled
```

The two example files list exactly the same tools — full parity, nothing
omitted from either — and differ only in the *value* of two lines:
`export_node`/`share_lab` are `enabled` in the PRO file and `disabled` in
the Community one, since both are PRO/Corporate-only features (see "PRO
vs Community differences" above) with nothing useful to do on Community.
Everything else, including the six user-management tools, is listed
identically in both files: confirmed via direct manual testing against a
real Community server (adding a second admin user; adding a folder and
moving a lab into it) that user management and folder/lab operations work
normally there — they're disabled by default on both editions for the
same general reason (not exposing user administration to an LLM by
default), not because Community can't support them. Nothing stops you
from enabling `export_node`/`share_lab` on Community anyway if you'd
rather see the tools' own clear edition-check error message than not see
them at all — they're edition-gated at call time regardless of which file
you start from.

Any tool not listed in the file defaults to enabled. Any value other than
`disabled` (case-insensitive) is treated as enabled, so a typo in the file
fails safe — the tool stays visible rather than silently disappearing.

**The six user-management tools (`list_users`, `get_user`, `add_user`,
`edit_user`, `delete_user`, `list_user_roles`) plus `delete_lab` are
disabled by default**, even with no `tools.env` file present at all —
EVE-NG user administration often isn't something you want exposed to an
LLM by default, and deleting an entire lab is a more severe,
harder-to-recover-from action than deleting one thing inside it (unlike
`delete_folder`/`delete_lab_node`/`delete_lab_network`, all still enabled
by default). Set any of them to `enabled` in `tools.env` to turn them
back on.

A disabled tool isn't just hidden with an error if called — it's never
registered with the MCP server at all, so it doesn't appear in the tool
list a connected client sees in the first place. Call `list_tools` (with
no arguments) at any time to get a single authoritative answer to "what's
actually available right now" — it reflects `tools.env` exactly, since it
just reports what actually got registered.

## Project layout

```
mcp-eveng/
├── src/mcp_eveng/
│   ├── client.py        # async EVENG REST API client (incl. list_all_labs recursion helper)
│   ├── config.py        # pydantic-settings, reads .env
│   ├── confirmation.py  # shared search/select/confirm state machine for deletes
│   ├── dependencies.py  # shared client singleton
│   ├── edition.py         # PRO vs Community detection, shared by 3 edition-gated tools
│   ├── exceptions.py
│   ├── search.py         # case-insensitive record search (used by delete tools)
│   ├── telnet.py          # raw asyncio telnet client (IAC handling) for telnet_node
│   ├── tool_config.py     # per-tool enable/disable config loader (tools.env)
│   ├── vendor.py          # best-effort vendor extraction + image-availability check
│   ├── server.py        # FastMCP assembly + transport security/statefulness
│   ├── __main__.py       # CLI: --sse / --http flags
│   └── tools/             # one module per API area
├── tests/
│   ├── conftest.py
│   ├── test_cli.py
│   ├── test_client.py
│   ├── test_config.py
│   ├── test_confirmation.py
│   ├── test_dependencies.py
│   ├── test_edition.py
│   ├── test_search.py
│   ├── test_telnet.py
│   ├── test_tool_config.py
│   ├── test_vendor.py
│   ├── test_server.py
│   └── tools/
├── docs/
│   ├── install-linux.md    # Linux/macOS install, running, Claude Desktop JSON
│   ├── install-windows.md  # Windows install, running, Claude Desktop JSON
│   └── tools-reference.md  # detailed per-tool design notes (see "Available tools")
├── tools.env.pro.example   # per-tool enable/disable config, PRO/Corporate -- copy to tools.env
├── tools.env.comm.example  # same, Community edition (disables 2 PRO-only tools)
└── .github/workflows/      # CI + PyPI publish
```

## Troubleshooting

**A tool call fails with `500 Internal Server Error` and no useful
message** — `mcp-eveng` itself now raises a more actionable error for
this (any 5xx response from EVE-NG with no JSON body, which is what an
unhandled server-side exception typically looks like). This is often
caused by a stale lock file left behind on the EVE-NG server by an
earlier interrupted request. On the EVE-NG server, check for one with:

```bash
find /opt/unetlab/labs/ -name '*.lock'
```

and remove any found with:

```bash
find /opt/unetlab/labs/ -name '*.lock' -exec rm {} \;
```

then retry. If that doesn't resolve it, check the EVE-NG server's own
logs for the underlying exception.

**`IncompleteFieldDefinitionWarning: Field 'lifespan' has an incomplete
definition...`** — this comes from inside the `mcp` SDK itself, not from
`mcp-eveng`. The SDK's internal `FastMCP` `Settings` model has a
self-referential `lifespan` field type that it never calls
`model_rebuild()` on, so `pydantic-settings` warns about it on every
`FastMCP` construction. It has no functional effect (nothing reads that
field from the environment) and `mcp-eveng` suppresses it by default — if
you still see it, you're likely on an `mcp` version where the warning text
changed slightly; it's safe to ignore either way.

## Known issues

`stop_node` (and anything that requires stopping a node first —
`edit_lab_node`, `change_node_delay`, `edit_lab_nodes_by_template`,
`connect_interface` on Community edition) can fail persistently on
certain nodes with `"Request not valid (60027)."`, with no way found so
far to make that specific node stoppable again through the API.

## Development

```bash
pip install -e ".[dev]"

# run tests with coverage
pytest

# lint / type-check
ruff check .
mypy src
```

### Why `mcp` is pinned below `2.0`

The official MCP Python SDK shipped a `2.0.0` release on 2026-07-28 alongside
the `2026-07-28` protocol revision. It is a deliberate breaking rework
(`FastMCP` renamed to `MCPServer`, new import paths, stateless transports)
and the SDK maintainers themselves recommend the `1.x` line for production
use while `2.x` stabilizes. This project pins `mcp[cli]>=1.23.0,<2.0.0`
intentionally — see `pyproject.toml`. Revisit this pin (and re-verify all
three transports, `transport_security`, and `stateless_http`) when migrating
to `2.x`.

## Publishing to PyPI

This repo is set up for [Trusted Publishing](https://docs.pypi.org/trusted-publishers/):
tagging a release (`vX.Y.Z`) triggers `.github/workflows/publish.yml`, which
builds and uploads to PyPI with no stored API tokens. Configure the trusted
publisher on PyPI's project settings page pointing at this repository and the
`publish.yml` workflow before tagging your first release.

## License

MIT — see [LICENSE](LICENSE).

## Tested versions

The EVE-NG server versions this project has actually been exercised
against live, confirmed via each server's own `get_status` response:

- **PRO/Corporate**: `6.5.0-27-PRO`
- **Community**: `6.2.0-4`

Other versions of either edition likely work too — nothing in this
project depends on a specific point release beyond the documented
edition differences (see "PRO vs Community differences") — but these are
the two actually confirmed.
