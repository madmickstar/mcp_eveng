# mcp-eveng on Windows

See the [main README](../README.md) for what this project does, the
full tool list, configuration variables, and the delete-confirmation
flow — this doc only covers OS-specific setup.

## Contents

- [Install](#install)
- [Running](#running)
- [Windows paths: use forward slashes](#windows-paths-use-forward-slashes)
- [Client integration: stdio](#client-integration-stdio)
- [Client integration: streamable-http](#client-integration-streamable-http)

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
```

- **stdio**: requires no `.env`
- **--sse**: requires `.env`
- **--http**: requires `.env`

## Windows paths: use forward slashes

**For any `*_PATH` variable in `.env`** (`MCP_TLS_CERT_PATH`,
`CAPTURE_SSH_KEY_PATH`, etc. — TLS certs are the most common case,
but this applies to every one), **use forward slashes**
(`"C:/path/to/file"`) instead of backslashes. A backslash immediately
followed by certain letters (`\t`, `\n`, `\r`, and a few others) inside
a double-quoted `.env` value gets silently turned into an actual
tab/newline/etc. character by `.env`'s own parsing — confirmed live: a
path containing `\to\` or `\new...` breaks exactly this way. This
project now catches and clearly reports the corruption if it happens,
but forward slashes avoid it happening at all.

## Client integration: stdio

Point `command` at your venv's actual Python interpreter path.
Backslashes must be doubled (`\\`) inside JSON strings. Specific
example is for Claude Desktop / Claude Code:

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

## Client integration: streamable-http

Requires [Node.js](https://nodejs.org/) (for `npx`). Specific
example is for Claude Desktop / Claude Code:

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
