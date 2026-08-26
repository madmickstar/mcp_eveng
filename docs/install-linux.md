# mcp-eveng on Linux / macOS

Full install, running, and MCP-host configuration instructions for
Linux and macOS. See the [main README](../README.md) for what this
project does, the full tool list, configuration variables, and the
delete-confirmation flow — this doc only covers OS-specific setup.

## Install

This project is **not published on PyPI** — install directly from a git
clone.

```bash
git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # editable/development install
# or, for a fixed install (e.g. before deploying as a systemd service --
# see "Running as a systemd service" below):
# pip install .
```

The repository (and the Python package inside it) uses an underscore --
`mcp_eveng` -- not a hyphen, so `git clone` produces a `mcp_eveng/`
directory. The hyphenated `mcp-eveng` name only appears as the installed
console-script/distribution name (see `pyproject.toml`'s `[project.scripts]`
and `name` fields) -- it's not something you clone or import, and `pip
install mcp-eveng` doesn't currently work, since this project isn't on
PyPI yet (see the main README's "Publishing to PyPI" section for the CI
setup that will make that command work once it's actually published).

## Running

Transport is a **CLI flag**, not an environment variable. `--sse` and
`--http` are mutually exclusive; passing neither runs stdio.

```bash
mcp-eveng          # stdio (default) -- for MCP hosts that launch the server as a subprocess
mcp-eveng --http    # Streamable HTTP -- recommended for networked / remote deployments
mcp-eveng --sse     # legacy SSE transport, network-exposed

# Bound to all interfaces, requires MCP_ALLOWED_HOSTS (see main README)
MCP_HOST="0.0.0.0" MCP_ALLOWED_HOSTS="192.168.1.100:8000,192.168.1.150:*" mcp-eveng --http
```

`mcp-eveng` above is the installed console-script name; from an activated
venv in a terminal it works fine on Linux/macOS. `python -m mcp_eveng
[flags]` is exactly equivalent, e.g. `python -m mcp_eveng --http`.

- **stdio** (no flag): the MCP host (Claude Desktop, Claude Code, ...)
  launches `mcp-eveng` as a subprocess and supplies configuration directly
  in its own `env` block — see below. No `.env` file or `MCP_*` variable
  is needed in this mode at all.
- **`--sse` / `--http`**: you run the process yourself as a standalone
  network service, so you'll typically want a `.env` file (copy
  `.env.example` to `.env`) for both the `EVENG_*` connection settings and
  the `MCP_*` network settings — see the main README's Configuration
  section for the full variable table.

Press Ctrl+C to stop a foreground server — it's caught and exits cleanly
with a "Goodbye!" message on stderr instead of a raw traceback.

## Using it with Claude Desktop / Claude Code (stdio)

In stdio mode the host supplies `EVENG_*` directly in its own config — no
`.env` file needed. Point `command` at your venv's Python interpreter
directly, with `args: ["-m", "mcp_eveng"]`:

```json
{
  "mcpServers": {
    "eveng_stdio": {
      "command": "/home/you/mcp_eveng/.venv/bin/python",
      "args": ["-m", "mcp_eveng"],
      "env": {
        "EVENG_HOST": "192.168.1.50",
        "EVENG_USERNAME": "admin",
        "EVENG_PASSWORD": "eve",
        "EVENG_VERIFY_SSL": "false"
      }
    }
  }
}
```

Replace `/home/you/mcp_eveng/.venv/bin/python` with the actual path to
your venv's Python (on macOS this is typically under your project
directory the same way, e.g. `/Users/you/mcp_eveng/.venv/bin/python`).
Using the bare console-script name `mcp-eveng` here would usually also
work on Linux/macOS since GUI apps here more often inherit a usable
`PATH` than on Windows, but pointing directly at the interpreter is more
reliable regardless of how your particular desktop environment or login
shell sets up `PATH` for GUI-launched processes.

(`EVENG_VERIFY_SSL: "false"` is shown here because this example EVE-NG
host is assumed to be running HTTPS with a self-signed cert. Drop it, or
set it to `"true"`, for a plain-HTTP or properly-certed target.)

## Using it with Claude Desktop / Claude Code (streamable-http)

Claude Desktop/Code don't speak Streamable HTTP directly, so bridge
through [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) to a
`mcp-eveng --http` instance running elsewhere (e.g. `mcp-eveng --http` on
`192.168.1.100:8000`):

```json
{
  "mcpServers": {
    "eveng_http": {
      "command": "npx",
        "args": [
            "-y",
            "mcp-remote@latest",
            "http://192.168.1.100:8000/mcp",
            "--allow-http"
        ]
    }
  }
}
```

This requires [Node.js](https://nodejs.org/) (for `npx`) to be installed
locally, in addition to the Python environment running `mcp-eveng`
itself elsewhere.

## Running as a systemd service (Linux)

For a `--http`/`--sse` deployment that should keep running in the
background and survive reboots, run `mcp-eveng` as a systemd service
under its own dedicated, non-root account. The steps below are a
confirmed working install into `/opt/mcp_eveng`, tested end-to-end.

### 1. Prerequisites

```bash
sudo apt install python3.13-venv
```

(Debian/Ubuntu split the `venv` module out of the base `python3` package
for some Python versions -- if `python3 -m venv` already works on your
system, skip this.)

### 2. Clone and configure

```bash
cd /opt
sudo git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng

sudo cp /opt/mcp_eveng/.env.example /opt/mcp_eveng/.env

# Copy whichever of these matches your EVE-NG server's edition -- see the
# main README's "PRO vs Community differences" section if you're not sure:
sudo cp /opt/mcp_eveng/tools.env.pro.example /opt/mcp_eveng/tools.env
# sudo cp /opt/mcp_eveng/tools.env.comm.example /opt/mcp_eveng/tools.env

sudo vi /opt/mcp_eveng/.env
```

At minimum, set `EVENG_HOST`/`EVENG_USERNAME`/`EVENG_PASSWORD` to your
actual EVE-NG server's details. `.env.example` already ships sensible
defaults for everything else (`MCP_HOST="127.0.0.1"`,
`MCP_STATEFUL="true"`, etc.) -- there's nothing wrong with those
defaults, but it's worth reviewing all of them for your deployment,
particularly `MCP_HOST` if this service needs to be reachable from
another machine (a non-loopback `MCP_HOST` also requires
`MCP_ALLOWED_HOSTS` -- see the main README's Configuration section).

### 3. Create the venv and install

```bash
sudo python3 -m venv /opt/mcp_eveng/.venv
source /opt/mcp_eveng/.venv/bin/activate
pip install /opt/mcp_eveng
deactivate
```

This is a plain (non-editable) install, appropriate for a fixed
production deployment -- unlike the `pip install -e .` shown earlier in
this doc for day-to-day development, where you want code changes picked
up without reinstalling.

### 4. Create the service account and fix ownership

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mcp-eveng
sudo chown mcp-eveng:mcp-eveng -R /opt/mcp_eveng
```

A dedicated, unprivileged account -- not root, and not your own login --
that owns nothing outside `/opt/mcp_eveng`. The venv can be created as
root first (as above) since ownership of the whole tree, venv included,
is handed to this account afterward, before the service ever runs.

### 5. Create the systemd unit

```bash
sudo vi /etc/systemd/system/mcp-eveng.service
```

```ini
# /etc/systemd/system/mcp-eveng.service

[Unit]
Description=MCP server for EVE-NG network emulator automation
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# Dedicated, non-root service account -- create it first:
#   sudo useradd --system --no-create-home --shell /usr/sbin/nologin mcp-eveng
User=mcp-eveng
Group=mcp-eveng

# Project checkout containing the venv and the .env file (pydantic-settings
# auto-loads ./.env relative to the working directory, so this MUST be the
# directory the .env file actually lives in).
WorkingDirectory=/opt/mcp_eveng

# Venv's own console-script entry point -- no "source activate" needed,
# calling the venv's binary directly is enough.
ExecStart=/opt/mcp_eveng/.venv/bin/mcp-eveng --http

Restart=on-failure
RestartSec=5

# Journal logging (view with: journalctl -u mcp-eveng -f)
StandardOutput=journal
StandardError=journal

# --- Light sandboxing -- relax/remove any of these if they cause problems
# (e.g. ProtectSystem=strict + a WorkingDirectory outside /opt if you
# relocate it) ---
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/mcp_eveng

[Install]
WantedBy=multi-user.target
```

The unit's own `ExecStart` line points directly at the venv's own
generated script (`/opt/mcp_eveng/.venv/bin/mcp-eveng`), which has the
venv's Python interpreter baked into its shebang -- no explicit `python3
.../mcp-eveng` prefix, and no "activate" step, is needed. If you ever
move or rename `/opt/mcp_eveng` after this install, that baked-in
absolute path breaks and the venv needs recreating (or reinstalling)
rather than just relocating.

### 6. Start, verify, and enable at boot

```bash
sudo systemctl daemon-reload
sudo systemctl start mcp-eveng.service
sudo systemctl status mcp-eveng.service
sudo systemctl stop mcp-eveng.service      # if you need to stop it again

sudo systemctl enable mcp-eveng.service    # start automatically on boot

sudo ss -tulnp                             # confirm it's listening where expected
```

