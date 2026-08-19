# mcp-eveng

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets LLM
clients (Claude Desktop, Claude Code, or any other MCP host) drive an
[EVENG](https://www.eve-ng.net/) network emulator instance: create and edit labs,
add/wire nodes and networks, start/stop/wipe devices, and browse templates,
folders and users — all through the EVENG REST API.

## Features

- Full coverage of the documented EVENG REST API: auth, system status, node
  templates, network types, folders, users, labs, lab networks, lab nodes
  (including start/stop/wipe/export), topology, links and pictures.
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

```bash
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

| Area | Tools |
| --- | --- |
| System | `get_status`, `list_node_templates`, `get_node_template`, `list_network_types`, `list_user_roles`† |
| Server introspection | `list_tools` |
| Folders | `list_folder`, `add_folder`, `move_folder`, `delete_folder`* |
| Users | `list_users`†, `get_user`†, `add_user`†, `edit_user`†, `delete_user`*† |
| Labs | `get_lab`, `open_lab`, `create_lab`, `edit_lab`, `share_lab`, `move_lab`, `delete_lab`*, `get_lab_topology`, `get_lab_links`, `list_lab_pictures`, `list_labs` |
| Networks | `list_lab_networks`, `add_lab_network`, `edit_lab_network`, `delete_lab_network`* |
| Nodes | `list_lab_nodes`, `add_lab_node`, `edit_lab_node`, `change_node_delay`, `edit_lab_nodes_by_template`, `delete_lab_node`*, `get_node_interfaces`, `connect_interface`, `start_node`, `stop_node`, `wipe_node`, `export_node` |
| Live console access | `telnet_node` |

\* Requires user confirmation before it does anything — see below.

† Disabled by default — see "Controlling which tools are exposed" below.

| Tool | Description |
| --- | --- |
| `get_status` | Reports EVE-NG server status and version. |
| `list_node_templates` | Lists available node templates. |
| `get_node_template` | Gets details for a single node template, including its images. |
| `list_network_types` | Lists valid network types (bridge, cloud/pnetX, etc.). |
| `list_user_roles` | Lists available user roles. |
| `list_tools` | Lists the tools published by the MCP server. |
| `list_folder` | Lists the contents of a folder. |
| `add_folder` | Creates a new folder. |
| `move_folder` | Moves or renames a folder. |
| `delete_folder` | Deletes a folder. |
| `list_users` | Lists user accounts. |
| `get_user` | Gets details for a single user. |
| `add_user` | Creates a new user account. |
| `edit_user` | Edits an existing user account. |
| `delete_user` | Deletes a user account. |
| `get_lab` | Gets metadata for a lab. |
| `open_lab` | Looks up a lab and reports its lock status. |
| `create_lab` | Creates a new lab. |
| `edit_lab` | Edits a lab's metadata. |
| `share_lab` | Shares a lab with one or more users. |
| `move_lab` | Moves a lab to a different folder. |
| `delete_lab` | Deletes a lab. |
| `get_lab_topology` | Gets a lab's node/network topology. |
| `get_lab_links` | Gets a lab's link (interface) mappings. |
| `list_lab_pictures` | Lists background pictures placed in a lab. |
| `list_labs` | Recursively lists every lab under a folder. |
| `list_lab_networks` | Lists networks in a lab. |
| `add_lab_network` | Adds a network to a lab. |
| `edit_lab_network` | Edits an existing network. |
| `delete_lab_network` | Deletes a network. |
| `list_lab_nodes` | Lists nodes in a lab. |
| `add_lab_node` | Adds a node to a lab. |
| `edit_lab_node` | Edits an existing node. |
| `change_node_delay` | Changes a node's startup delay, one node or in bulk. |
| `edit_lab_nodes_by_template` | Bulk-edits interfaces/cpu/memory/icon/image across nodes sharing a template. |
| `delete_lab_node` | Deletes a node. |
| `get_node_interfaces` | Gets a node's interfaces and what they're wired to. |
| `connect_interface` | Wires a node's interface to another node or to a network. |
| `start_node` | Starts a node, or every node in a lab. |
| `stop_node` | Stops a node, or every node in a lab. |
| `wipe_node` | Wipes a node's saved configuration. |
| `export_node` | Exports a node's running configuration. |
| `telnet_node` | Sends CLI commands to a running node's console over telnet. |

More detailed information about each tool — confirmed EVE-NG quirks,
design reasoning, and non-obvious behavior — can be found in
**[docs/tools-reference.md](docs/tools-reference.md)**.

## Controlling which tools are exposed

Every tool can be individually enabled or disabled, via a dedicated
dotenv-syntax config file — kept separate from the main `.env` so tool
visibility is easy to review and diff independently of connection
settings. Copy `tools.env.example` to `tools.env` (or point
`MCP_TOOLS_CONFIG_PATH` at wherever you keep it) and set any tool to
`enabled` or `disabled`:

```
get_status=enabled
list_users=disabled
```

Any tool not listed in the file defaults to enabled. Any value other than
`disabled` (case-insensitive) is treated as enabled, so a typo in the file
fails safe — the tool stays visible rather than silently disappearing.

**The six user-management tools (`list_users`, `get_user`, `add_user`,
`edit_user`, `delete_user`, `list_user_roles`) are disabled by default**,
even with no `tools.env` file present at all — EVE-NG user administration
often isn't something you want exposed to an LLM by default. Set any of
them to `enabled` in `tools.env` to turn them back on.

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
│   ├── test_search.py
│   ├── test_telnet.py
│   ├── test_tool_config.py
│   ├── test_vendor.py
│   ├── test_server.py
│   └── tools/
├── docs/
│   ├── install-linux.md   # Linux/macOS install, running, Claude Desktop JSON
│   └── install-windows.md # Windows install, running, Claude Desktop JSON
├── tools.env.example      # per-tool enable/disable config -- copy to tools.env
└── .github/workflows/     # CI + PyPI publish
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

**`stop_node` (and anything that requires stopping a node first —
`edit_lab_node`, `change_node_delay`, `edit_lab_nodes_by_template`,
`connect_interface` on Community edition) can fail persistently on
certain nodes with `"Request not valid (60027)."`**, with no way found
so far to make that specific node stoppable again through the API.

What's confirmed about this, from extensive live investigation:

- **Not a session/auth issue** — distinct from the session-invalidation
  problem described above ("A note on sessions and relogin"), which *is*
  fixed. A completely fresh, never-before-used session fails identically
  and immediately.
- **Not related to node history** — reproduces on a brand-new node in a
  brand-new lab that was only ever started and left idle; heavy prior
  interaction isn't a prerequisite.
- **Not a resource-exhaustion issue** — confirmed on a server with ample
  spare CPU/RAM/disk.
- **Not the `EVENG_HTML5` login mode** — `-1` (auto), `0`, and `1` all
  reproduce the identical failure.
- **Not fixed by `unl_wrapper -a fixpermissions`** — EVE-NG's own
  documented general-purpose remediation command for this class of
  symptom; tried live, no change.
- **The request never reaches EVE-NG's own stop wrapper script at all.**
  Confirmed by tailing `/opt/unetlab/data/Logs/unl_wrapper.txt` server-side
  during a failing request — nothing is written for it, while a
  successful stop (e.g. via the GUI) does log a `unl_wrapper -a stop`
  invocation. Whatever rejects the request happens earlier, at EVE-NG's
  PHP application layer, before it ever shells out to actually stop
  anything at the OS/hypervisor level.
- **The request itself is structurally correct** — endpoint path, HTTP
  method, and payload all match EVE-NG's own official API documentation
  exactly.

**Not yet tried**: `unl_wrapper -a restoredb` (EVE-NG's documented fix for
a crashed login database, notably attributed to improper suspend/shutdown
— a more invasive step, restarts MySQL, requires shell access some
deployments won't have); a byte-for-byte comparison between a manual
`curl` stop request and what this client sends, to rule out anything at
the wire level (headers, cookie encoding) not visible in the JSON
exchanged; and confirming whether the EVE-NG GUI can stop the *same*,
already-API-confirmed-stuck node, to isolate whether this is specific to
API-originated requests or the node's state itself regardless of source.

If you hit this and find a fix, please open an issue or PR — this section
should be updated with whatever the actual resolution turns out to be.

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
