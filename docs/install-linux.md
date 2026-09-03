# mcp-eveng on Linux / macOS

See the [main README](../README.md) for what this project does, the
full tool list, configuration variables, and the delete-confirmation
flow — this doc only covers OS-specific setup.

## Contents

- [Install](#install)
- [Running](#running)
- [Client integration: stdio](#client-integration-stdio)
- [Client integration: streamable-http](#client-integration-streamable-http)
- [Running as a systemd service (Linux)](#running-as-a-systemd-service-linux)

## Install

Always do this first — every path below (manual running, systemd)
builds on it.

```bash
sudo apt install python3.13-venv
sudo git clone https://github.com/madmickstar/mcp_eveng.git /opt/mcp_eveng
sudo python3 -m venv /opt/mcp_eveng/.venv
sudo /opt/mcp_eveng/.venv/bin/pip install /opt/mcp_eveng
```

If you're doing development work on this project itself (running the
test suite, linting), append `[dev]` to the path instead:
`sudo /opt/mcp_eveng/.venv/bin/pip install "/opt/mcp_eveng[dev]"`.

## Running

Either activate the venv first (`source /opt/mcp_eveng/.venv/bin/activate`)
and use the bare commands below, or call
`/opt/mcp_eveng/.venv/bin/mcp-eveng` directly every time without
activating — both work identically.

```bash
mcp-eveng          # stdio (default)
mcp-eveng --http   # Streamable HTTP
mcp-eveng --sse    # legacy SSE

# Bound to all interfaces, requires MCP_ALLOWED_HOSTS
MCP_HOST="0.0.0.0" MCP_ALLOWED_HOSTS="192.168.1.100:8000,192.168.1.150:*" mcp-eveng --http
```

`python -m mcp_eveng [flags]` is equivalent. Ctrl+C stops a foreground
server cleanly.

- **stdio** (no flag): no `.env` needed — the MCP host supplies config
  in its own `env` block.
- **`--sse` / `--http`**: copy `.env.example` to `.env` and set
  `EVENG_*`/`MCP_*` — see the main README's Configuration section.
  Binding to anything other than a loopback address (`0.0.0.0`, a LAN
  IP, etc.) requires `MCP_ALLOWED_HOSTS` set too, or the server refuses
  to start.

## Client integration: stdio

Replace the `command` path with your venv's actual Python interpreter
path.

```json
{
  "mcpServers": {
    "eveng_stdio": {
      "command": "/opt/mcp_eveng/.venv/bin/python",
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

## Client integration: streamable-http

Requires [Node.js](https://nodejs.org/) (for `npx`). Bridge through
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote) to a running
`mcp-eveng --http` instance:

```json
{
  "mcpServers": {
    "eveng_http": {
      "command": "npx",
        "args": [
            "-y",
            "mcp-remote@latest",
            "http://192.168.1.50:8000/mcp",
            "--allow-http"
        ]
    }
  }
}
```

If `MCP_API_KEY` is set on the server (see README's Configuration
section), add the header and switch to `https://` if TLS is also
configured. `NODE_TLS_REJECT_UNAUTHORIZED=0` below skips certificate
verification — needed for a self-signed cert in a lab; remove it if
your server has a CA-signed certificate, since it otherwise weakens
the connection for no reason:

```json
{
  "mcpServers": {
    "eveng_http": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "https://192.168.1.50:8000/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": {
        "AUTH_HEADER": "Bearer <your MCP_API_KEY value>",
        "NODE_TLS_REJECT_UNAUTHORIZED": "0"
      }
    }
  }
}
```

## Running as a systemd service (Linux)

Builds on the [Install](#install) step above — that already cloned,
created the venv, and installed the package at `/opt/mcp_eveng`; the
steps below are what's needed on top of that for a systemd deployment.

1. Configure:

```bash
sudo cp /opt/mcp_eveng/.env.example /opt/mcp_eveng/.env

# Match your EVE-NG server's edition:
sudo cp /opt/mcp_eveng/tools.env.pro.example /opt/mcp_eveng/tools.env
# sudo cp /opt/mcp_eveng/tools.env.comm.example /opt/mcp_eveng/tools.env

sudo vi /opt/mcp_eveng/.env
```

Set `EVENG_HOST`/`EVENG_USERNAME`/`EVENG_PASSWORD`. Review the rest for
your deployment (e.g. `MCP_HOST` if reachable from another machine —
also requires `MCP_ALLOWED_HOSTS`).

2. Create the service account and fix ownership:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mcp-eveng
sudo chown mcp-eveng:mcp-eveng -R /opt/mcp_eveng
```

3. Optional: create `/etc/mcp-eveng`, for TLS certs (only needed if
you're using `MCP_TLS_*`/`CAPTURE_RELAY_TLS_*` — see the comments in
`.env.example`):

```bash
sudo mkdir -p /etc/mcp-eveng
sudo chown mcp-eveng:mcp-eveng /etc/mcp-eveng
sudo chmod 750 /etc/mcp-eveng
```

After copying your actual cert/key files in, matching whatever
filenames you set `MCP_TLS_CERT_PATH`/`_KEY_PATH` (and, if you're also
using the relay's own TLS, `CAPTURE_RELAY_TLS_CERT_PATH`/`_KEY_PATH`)
to in `.env`:

```bash
sudo chown mcp-eveng:mcp-eveng /etc/mcp-eveng/cert.pem /etc/mcp-eveng/key.pem
sudo chmod 640 /etc/mcp-eveng/cert.pem
sudo chmod 600 /etc/mcp-eveng/key.pem

# Same again if you're also using the relay's own TLS:
sudo chown mcp-eveng:mcp-eveng /etc/mcp-eveng/relay-cert.pem /etc/mcp-eveng/relay-key.pem
sudo chmod 640 /etc/mcp-eveng/relay-cert.pem
sudo chmod 600 /etc/mcp-eveng/relay-key.pem
```

Whatever files you put there should stay owned by `mcp-eveng`, matching
the `chown` calls above; private key files specifically get the
stricter `600` (owner read/write only), since unlike the certificate
itself, a private key is genuinely sensitive. No systemd unit change
needed to read from here — `ProtectSystem=strict` (set in
`systemd/mcp-eveng.service`, see the next step) makes the filesystem
read-only outside `ReadWritePaths`, not inaccessible, and this
directory is only ever read from, never written to.

4. Install the systemd unit — a ready-to-use copy ships in the repo
   itself, already cloned to `/opt/mcp_eveng` from the Install step:

```bash
sudo cp /opt/mcp_eveng/systemd/mcp-eveng.service /etc/systemd/system/mcp-eveng.service
```

Review it first if your paths/account differ from this guide's
(`/opt/mcp_eveng`, the `mcp-eveng` account) — it's a plain text file,
`systemd/mcp-eveng.service` in the repo.

5. Start, verify, and enable at boot:

```bash
sudo systemctl daemon-reload
sudo systemctl start mcp-eveng.service
sudo systemctl status mcp-eveng.service
sudo systemctl stop mcp-eveng.service      # if you need to stop it again

sudo systemctl enable mcp-eveng.service    # start automatically on boot

sudo ss -tulnp                             # confirm it's listening where expected
```

See [Upgrading](upgrading.md) for updating an existing install.
