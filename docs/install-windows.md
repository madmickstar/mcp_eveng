# mcp-eveng on Windows

See the [main README](../README.md) for what this project does, the
full tool list, configuration variables, and the delete-confirmation
flow — this doc only covers OS-specific setup.

## Contents

- [Install](#install)
- [Running](#running)
- [Using it with Claude Desktop / Claude Code (stdio)](#using-it-with-claude-desktop--claude-code-stdio)
- [Using it with Claude Desktop / Claude Code (streamable-http)](#using-it-with-claude-desktop--claude-code-streamable-http)

## Install

This project is **not published on PyPI** — install directly from a
git clone.

1. Clone and install (PowerShell):

```powershell
git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng
python -m venv .venv
.venv\Scripts\pip install -e .
```

Calls the venv's own `pip` directly, without a separate activation
step. If you're doing development work on this project itself (running
the test suite, linting), use `.[dev]` instead of `.` in that command.

## Running

Either activate the venv first (`.venv\Scripts\Activate.ps1`, or
`.venv\Scripts\activate.bat` for `cmd.exe`) and use the bare commands
below, or call `.venv\Scripts\mcp-eveng.exe` directly every time
without activating -- both work identically. If PowerShell blocks the
activation script: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

```powershell
mcp-eveng          # stdio (default)
mcp-eveng --http   # Streamable HTTP
mcp-eveng --sse    # legacy SSE

# Bound to all interfaces, requires MCP_ALLOWED_HOSTS
$env:MCP_HOST="0.0.0.0"; $env:MCP_ALLOWED_HOSTS="192.168.1.100:8000,192.168.1.150:*"; mcp-eveng --http
```

`cmd.exe` equivalent for env vars:
`set MCP_HOST=0.0.0.0 && set MCP_ALLOWED_HOSTS=... && mcp-eveng --http`.
`python -m mcp_eveng [flags]` is equivalent to `mcp-eveng [flags]`.
Ctrl+C stops a foreground server cleanly.

- **stdio** (no flag): no `.env` needed — the MCP host supplies config
  in its own `env` block.
- **`--sse` / `--http`**: copy `.env.example` to `.env` and set
  `EVENG_*`/`MCP_*` — see the main README's Configuration section.
  Binding to `0.0.0.0` may trigger a Windows Firewall prompt; allow it
  on your local/private network profile.

## Using it with Claude Desktop / Claude Code (stdio)

Point `command` at your venv's Python interpreter directly (not the
bare `mcp-eveng` name — Claude Desktop doesn't inherit your shell's
`PATH`):

```json
{
  "mcpServers": {
    "eveng_stdio": {
      "command": "C:\\path\\to\\your\\venv\\Scripts\\python",
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

Replace the `command` path with your venv's actual Python interpreter
path. Backslashes must be doubled (`\\`) inside JSON strings.

## Using it with Claude Desktop / Claude Code (streamable-http)

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
            "http://192.168.1.100:8000/mcp",
            "--allow-http"
        ]
    }
  }
}
```

If `MCP_API_KEY` is set on the server (see README's Configuration
section), add the header and switch to `https://` if TLS is also
configured:

```json
{
  "mcpServers": {
    "eveng_http": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "http://192.168.1.100:8000/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": { "AUTH_HEADER": "Bearer <your MCP_API_KEY value>" }
    }
  }
}
```

If `npx` isn't recognized, confirm Node.js added itself to `PATH` and
that you've opened a new terminal/restarted Claude Desktop since
installing it.

See [Upgrading](upgrading.md) for updating an existing install.
