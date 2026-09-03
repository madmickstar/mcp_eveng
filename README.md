![mcp-eveng](assets/banner.png)

# mcp-eveng

[![CI](https://github.com/madmickstar/mcp_eveng/actions/workflows/ci.yml/badge.svg)](https://github.com/madmickstar/mcp_eveng/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets LLM
clients (Claude Desktop, Claude Code, or any other MCP host) drive an
[EVENG](https://www.eve-ng.net/) network emulator instance: create and edit labs,
add/wire nodes and networks, start/stop/wipe devices, and browse templates,
folders and users — all through the EVENG REST API.

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Upgrading](#upgrading)
- [Capture relay](#capture-relay)
- [Run App](#run-app)
- [Configuration](#configuration)
  - [EVENG connection](#eveng-connection-always-used-regardless-of-transport)
  - [MCP network settings](#mcp-network-settings-only-used-with---sse-or---http)
    - [`MCP_LOG_LEVEL`](#mcp_log_level-options-and-where-logs-go)
    - [`MCP_ALLOWED_HOSTS`](#mcp_allowed_hosts-dns-rebinding-protection)
    - [`MCP_STATEFUL`](#mcp_stateful-session-persistence-across-restarts)
    - [`MCP_API_KEY` and `MCP_TLS_*`](#mcp_api_key-and-mcp_tls_-optional-extra-security)
- [EVE-NG Pro vs Community MCP tools](#eve-ng-pro-vs-community-mcp-tools)
- [Available MCP tools](#available-mcp-tools)
- [Controlling which MCP tools are exposed](#controlling-which-mcp-tools-are-exposed)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Manual curl commands](#manual-curl-commands)
- [A note on sessions and relogin](#a-note-on-sessions-and-relogin)
- [Known issues](#known-issues)
- [Development](#development)
  - [Why `mcp` is pinned below `2.0`](#why-mcp-is-pinned-below-20)
- [License](#license)
- [Tested versions](#tested-versions)

## Features

- All three MCP transports: `stdio`, `--sse`, `--http`
- Full coverage of the EVE-NG REST API
- HTTP/HTTPS and API key support
- 47 tools to manage your EVE-NG labs
- Bulk edits across many nodes at once
- Stream Wireshark captures to a local Wireshark
- Adjust link quality settings
- Supports both Community and PRO editions

## Installation

This project is **not published on PyPI** — install directly from a git
clone:

```bash
git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng
pip install -e .
```

- **[Linux / macOS install & running guide](docs/install-linux.md)**
- **[Windows install & running guide](docs/install-windows.md)**

## Upgrading

**[Upgrading guide](docs/upgrading.md)** — updating an existing
`mcp-eveng` and/or `mcp-relay` install.

## Capture relay

Stream Wireshark capture to a local Wireshark without a personal
SSH+sudo account on the EVE-NG host. Limited to EVE-NG PRO only.

**[Capture relay guide](docs/capture-relay.md)**

## Run App

```bash
python -m mcp_eveng          # stdio mode (default)
python -m mcp_eveng --sse    # sse mode
python -m mcp_eveng --http   # streamable-http mode
```

`--sse` and `--http` rely on variables configured in your `.env` file —
see `.env.example`.

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
| `MCP_API_KEY` | unset | If set, every request needs `Authorization: Bearer <key>` or gets a 401 |
| `MCP_TLS_CERT_PATH` | unset | TLS certificate file. Serves HTTPS instead of plain HTTP when set together with `MCP_TLS_KEY_PATH` |
| `MCP_TLS_KEY_PATH` | unset | TLS certificate's private key file. Required together with `MCP_TLS_CERT_PATH` |
| `MCP_TLS_KEY_PASSWORD` | unset | Only needed if the private key above is itself password-protected |

All variables can also be set as real environment variables, which take
precedence over `.env`.

`MCP_TOOLS_CONFIG_PATH` (default `tools.env`) applies to **every**
transport, including stdio — it isn't scoped to `--sse`/`--http` like the
rest of this table, since tool registration itself doesn't depend on
transport. See "Controlling which MCP tools are exposed" below.

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

#### `MCP_API_KEY` and `MCP_TLS_*`: optional extra security

Neither is required — `MCP_ALLOWED_HOSTS` above is the only thing this
server enforces by default. Both are opt-in for anyone who wants more than
that, e.g. a `--http` deployment reachable beyond localhost.

`MCP_API_KEY`, if set, requires every `--sse`/`--http` request to present
it via `Authorization: Bearer <key>`, or the request gets a `401` before
it ever reaches the MCP handler.

`MCP_TLS_CERT_PATH`/`MCP_TLS_KEY_PATH` (both required together, or leave
both unset) serve `--sse`/`--http` over HTTPS instead of plain HTTP.
`MCP_TLS_KEY_PASSWORD` is only needed if the private key file itself is
encrypted. Requires this server's own certificate to be one the *client*
trusts.

If `MCP_TLS_CERT_PATH` points at a certificate file inclusive of
certificate chain, the server certificate must come first, with the CA
certificate below it — this is a universal PEM chain-file convention
(the same order Apache/nginx/every OpenSSL-based server expects), not
specific to this project. See `docs/tools-reference.md` for the full
detail on both settings, including request/response examples.

For running the server and configuring it in Claude Desktop / Claude Code
(both stdio and streamable-http), see the
**[Linux/macOS](docs/install-linux.md)** or
**[Windows](docs/install-windows.md)** guide — the exact commands and
JSON differ enough between platforms (path syntax, shell env-var syntax,
and how each OS handles `PATH` for GUI-launched subprocesses) that they're
kept there rather than duplicated here.

## EVE-NG Pro vs Community MCP tools

EVE-NG's REST API has no explicit "edition" field, but the version string
`get_status` returns carries a `-PRO` suffix on PRO servers (confirmed
live: `6.5.0-27-PRO`); plain Community builds don't have it (confirmed
live: `6.2.0-4`). This is the only reliable signal for which edition a
server is running, and it's what every edition-aware behavior below
derives from (`edition.is_pro_edition`). An unrecognized or missing
version string is treated as Community, the more conservative assumption.

Five tools genuinely behave differently by edition — confirmed against
EVE-NG's own official [features-compare page](https://www.eve-ng.net/index.php/features-compare/),
live testing, or both:

- `connect_interface` — Pro and Community versions both support this MCP tool. Community version requires nodes to be stopped; Pro does not.
- `export_node` — Pro only.
- `share_lab` — Pro only.
- `set_link_quality` / `get_link_quality` — Pro only.
- `list_captures` / `get_capture` — Pro only.

## Available MCP tools

Tool names have no prefix (`get_status`, not `eveng_get_status`) — be aware
this means a name could collide with another MCP server's tool if you ever
connect more than one server with overlapping names to the same client.

**Comm Eve**/**Pro Eve**: which EVE-NG edition(s) support the tool — see
"EVE-NG Pro vs Community MCP tools" above for how edition is detected
and why these six specifically differ.

| Area | Tool | Description | Comm Eve | Pro Eve |
| --- | --- | --- | --- | --- |
| System | `get_status` | Reports EVE-NG server status and version. | ✅ | ✅ |
| | `list_node_templates` | Lists available node templates. | ✅ | ✅ |
| | `get_node_template` | Gets details for a single node template, including its images. | ✅ | ✅ |
| | `list_network_types` | Lists valid network types (bridge, cloud/pnetX, etc.). | ✅ | ✅ |
| | `list_user_roles` | Lists available user roles. Disabled by default. | ✅ | ✅ |
| Server introspection | `list_tools` | Lists the tools published by the MCP server. | ✅ | ✅ |
| Folders | `list_folder` | Lists the contents of a folder. | ✅ | ✅ |
| | `add_folder` | Creates a new folder. | ✅ | ✅ |
| | `move_folder` | Moves or renames a folder. | ✅ | ✅ |
| | `delete_folder` | Deletes a folder. Requires user confirmation before it does anything. | ✅ | ✅ |
| Users | `list_users` | Lists user accounts. Disabled by default. | ✅ | ✅ |
| | `get_user` | Gets details for a single user. Disabled by default. | ✅ | ✅ |
| | `add_user` | Creates a new user account. Disabled by default. | ✅ | ✅ |
| | `edit_user` | Edits an existing user account. Disabled by default. | ✅ | ✅ |
| | `delete_user` | Deletes a user account. Requires user confirmation before it does anything. Disabled by default. | ✅ | ✅ |
| Labs | `get_lab` | Gets metadata for a lab. | ✅ | ✅ |
| | `open_lab` | Looks up a lab and reports its lock status. | ✅ | ✅ |
| | `create_lab` | Creates a new lab. | ✅ | ✅ |
| | `edit_lab` | Edits a lab's metadata. | ✅ | ✅ |
| | `share_lab` | Shares a lab with one or more users. | | ✅ |
| | `move_lab` | Moves a lab to a different folder. | ✅ | ✅ |
| | `delete_lab` | Deletes a lab. Requires user confirmation before it does anything. Disabled by default. | ✅ | ✅ |
| | `get_lab_topology` | Gets a lab's node/network topology. | ✅ | ✅ |
| | `get_lab_links` | Gets a lab's link (interface) mappings. | ✅ | ✅ |
| | `list_lab_pictures` | Lists background pictures placed in a lab. | ✅ | ✅ |
| | `list_labs` | Recursively lists every lab under a folder. | ✅ | ✅ |
| Networks | `list_lab_networks` | Lists networks in a lab. | ✅ | ✅ |
| | `add_lab_network` | Adds a network to a lab. | ✅ | ✅ |
| | `edit_lab_network` | Edits an existing network. | ✅ | ✅ |
| | `delete_lab_network` | Deletes a network. Requires user confirmation before it does anything. | ✅ | ✅ |
| Nodes | `list_lab_nodes` | Lists nodes in a lab. | ✅ | ✅ |
| | `add_lab_node` | Adds a node to a lab. | ✅ | ✅ |
| | `edit_lab_node` | Edits an existing node. | ✅ | ✅ |
| | `change_node_delay` | Changes a node's startup delay, one node or in bulk. | ✅ | ✅ |
| | `edit_lab_nodes_by_template` | Bulk-edits interfaces/cpu/memory/icon/image across nodes sharing a template. | ✅ | ✅ |
| | `delete_lab_node` | Deletes a node. Requires user confirmation before it does anything. | ✅ | ✅ |
| | `get_node_interfaces` | Gets a node's interfaces and what they're wired to. | ✅ | ✅ |
| | `connect_interface` | Wires a node's interface to another node or to a network. | ✅ | ✅ |
| | `start_node` | Starts a node, or every node in a lab. | ✅ | ✅ |
| | `stop_node` | Stops a node, or every node in a lab. | ✅ | ✅ |
| | `wipe_node` | Wipes a node's saved configuration. | ✅ | ✅ |
| | `export_node` | Exports a node's running configuration. | | ✅ |
| | `set_link_quality` | Sets per-connection delay/jitter/packet-loss/bandwidth. | | ✅ |
| | `get_link_quality` | Gets current delay/jitter/packet-loss/bandwidth on both sides of a connection. | | ✅ |
| Live console access | `telnet_node` | Sends CLI commands to a running node's console over telnet. | ✅ | ✅ |
| Capture relay | `list_captures` | Lists running Wireshark capture containers. Disabled by default. | | ✅ |
| | `get_capture` | Mints a one-time URL to stream a capture to a local Wireshark. Disabled by default. | | ✅ |

"Disabled by default" tools: see "Controlling which MCP tools are exposed"
below for how to turn them on. "Requires user confirmation" tools: see
`docs/tools-reference.md` for the search → select → confirm flow they
each go through before anything is deleted.

More detailed information about each tool — confirmed EVE-NG quirks,
design reasoning, and non-obvious behavior — can be found in
**[docs/tools-reference.md](docs/tools-reference.md)**.

## Controlling which MCP tools are exposed

Every tool can be individually enabled or disabled, via a dedicated
dotenv-syntax config file — kept separate from the main `.env` so tool
visibility is easy to review and diff independently of connection
settings. Copy **`tools.env.pro.example`** (PRO edition) or
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
the Community one, since both are PRO-only features (see
"EVE-NG Pro vs Community MCP tools" above) with nothing useful to do on
Community.
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
│   ├── client.py          # async EVENG REST API client (incl. list_all_labs recursion helper)
│   ├── config.py          # pydantic-settings, reads .env
│   ├── confirmation.py    # shared search/select/confirm state machine for deletes
│   ├── dependencies.py    # shared client singleton
│   ├── edition.py         # PRO vs Community detection, shared by all edition-gated tools
│   ├── exceptions.py
│   ├── search.py          # case-insensitive record search (used by delete tools)
│   ├── telnet.py          # raw asyncio telnet client (IAC handling) for telnet_node
│   ├── tool_config.py     # per-tool enable/disable config loader (tools.env)
│   ├── vendor.py          # best-effort vendor extraction + image-availability check
│   ├── server.py          # FastMCP assembly + transport security/statefulness/API key/TLS
│   ├── __main__.py        # CLI: --sse / --http flags
│   ├── tools/             # one module per API area
│   └── capture_relay/     # standalone mcp-relay service (own entrypoint, own config,
│                           # shares this same venv and .env -- see docs/capture-relay.md)
├── systemd/
│   ├── mcp-eveng.service  # ready-to-use unit for the main MCP server
│   └── mcp-relay.service  # ready-to-use unit for the standalone capture-relay service
├── scripts/
│   └── eve-capture.bat    # Windows capture:// protocol handler companion
├── tests/
│   ├── conftest.py
│   ├── test_*.py
│   ├── tools/
│   └── capture_relay/
├── docs/
│   ├── install-linux.md        # Linux/macOS install, running, Claude Desktop JSON
│   ├── install-windows.md      # Windows install, running, Claude Desktop JSON
│   ├── capture-relay.md        # full capture-relay setup guide
│   ├── upgrading.md            # updating an existing install
│   ├── manual-curl-commands.md # testing the server directly over HTTP
│   └── tools-reference.md      # detailed per-tool design notes (see "Available MCP tools")
├── assets/
│   └── banner.png
├── .env.example             # shared config for both mcp-eveng and mcp-relay -- copy to .env
├── tools.env.pro.example    # per-tool enable/disable config, PRO -- copy to tools.env
├── tools.env.comm.example   # same, Community edition (disables 2 PRO-only tools)
└── .github/workflows/       # CI + PyPI publish
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

**Streaming capture via curl** — if a Windows client connecting to this
server (`curl.exe`, or anything else using Windows' native Schannel TLS
stack) fails with `schannel: next InitializeSecurityContext failed:
SEC_E_INTERNAL_ERROR`, check your certificate's key algorithm —
confirmed by directly comparing a cert that triggered this against one
that didn't: the failing one used ECDSA with the P-521 curve
(`secp521r1`). Windows Schannel has a documented incompatibility with
P-521 certificates specifically (P-256/P-384 ECDSA and RSA are
unaffected — this isn't "avoid ECDSA," just that one specific curve).
Regenerate the certificate with RSA (2048-bit or larger) or ECDSA
P-256/P-384 instead.

## Manual curl commands

Test the server directly over HTTP without an MCP client — useful for
quick troubleshooting. **[Manual curl commands guide](docs/manual-curl-commands.md)**.

## A note on sessions and relogin

EVE-NG only allows one active session per user account — see
[docs/tools-reference.md](docs/tools-reference.md#sessions-and-relogin)
for what that means in practice and how `EvengClient` handles it.

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

## License

MIT — see [LICENSE](LICENSE).

## Tested versions

The EVE-NG server versions this project has actually been exercised
against live, confirmed via each server's own `get_status` response:

- **PRO**: `6.5.0-27-PRO`
- **Community**: `6.2.0-4`

Other versions of either edition likely work too — nothing in this
project depends on a specific point release beyond the documented
edition differences (see "EVE-NG Pro vs Community MCP tools") — but these are
the two actually confirmed.
