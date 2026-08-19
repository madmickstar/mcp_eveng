# mcp-eveng on Windows

Full install, running, and MCP-host configuration instructions for
Windows. See the [main README](../README.md) for what this project does,
the full tool list, configuration variables, and the delete-confirmation
flow — this doc only covers OS-specific setup.

## Install

```powershell
pip install mcp-eveng
```

Or, for local development (PowerShell):

```powershell
git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If PowerShell blocks the activation script with an execution-policy
error, run this once in that PowerShell session first, then retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Using `cmd.exe` instead of PowerShell, activate with
`.venv\Scripts\activate.bat` in place of `Activate.ps1` — everything else
is the same.

The repository (and the Python package inside it) uses an underscore --
`mcp_eveng` -- not a hyphen, so `git clone` produces a `mcp_eveng\`
directory. Only the PyPI *distribution* name (`pip install mcp-eveng`
above) uses a hyphen, which is a PyPI naming convention, not the actual
package/module name.

## Running

Transport is a **CLI flag**, not an environment variable. `--sse` and
`--http` are mutually exclusive; passing neither runs stdio.

```powershell
mcp-eveng          # stdio (default) -- for MCP hosts that launch the server as a subprocess
mcp-eveng --http    # Streamable HTTP -- recommended for networked / remote deployments
mcp-eveng --sse     # legacy SSE transport, network-exposed

# Bound to all interfaces, requires MCP_ALLOWED_HOSTS (see main README)
$env:MCP_HOST="0.0.0.0"; $env:MCP_ALLOWED_HOSTS="192.168.1.100:8000,192.168.1.150:*"; mcp-eveng --http
```

(The last example uses PowerShell's `$env:VAR="value"` syntax for setting
environment variables inline; in `cmd.exe` the equivalent is
`set MCP_HOST=0.0.0.0 && set MCP_ALLOWED_HOSTS=... && mcp-eveng --http`.)

`mcp-eveng` above is the installed console-script name; from an activated
venv in a terminal it works fine. `python -m mcp_eveng [flags]` is exactly
equivalent, e.g. `python -m mcp_eveng --http`.

- **stdio** (no flag): the MCP host (Claude Desktop, Claude Code, ...)
  launches `mcp-eveng` as a subprocess and supplies configuration directly
  in its own `env` block — see below. No `.env` file or `MCP_*` variable
  is needed in this mode at all.
- **`--sse` / `--http`**: you run the process yourself as a standalone
  network service, so you'll typically want a `.env` file (copy
  `.env.example` to `.env`) for both the `EVENG_*` connection settings and
  the `MCP_*` network settings — see the main README's Configuration
  section for the full variable table. Binding to `0.0.0.0` may trigger a
  Windows Firewall prompt the first time; allow it on your local/private
  network profile.

Press Ctrl+C to stop a foreground server — it's caught and exits cleanly
with a "Goodbye!" message on stderr instead of a raw traceback.

## Using it with Claude Desktop / Claude Code (stdio)

In stdio mode the host supplies `EVENG_*` directly in its own config — no
`.env` file needed. **Point `command` at your venv's Python interpreter
directly, with `args: ["-m", "mcp_eveng"]`** — not at the bare `mcp-eveng`
console-script name. Claude Desktop is a GUI app and does not inherit
your shell's `PATH`, so it can't find a console-script shim sitting in
your venv's `Scripts\` folder even though it works fine from a terminal
where the venv is activated. Giving the full interpreter path sidesteps
`PATH` entirely:

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

Replace `C:\\path\\to\\your\\venv\\Scripts\\python` with the actual path
to your venv's Python (e.g.
`C:\\Users\\you\\mcp_eveng\\.venv\\Scripts\\python`) — note backslashes
must be doubled (`\\`) inside JSON strings, since a single `\` is an
escape character there.

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
itself elsewhere. If `npx` isn't recognized, confirm Node.js's install
added itself to your `PATH` (the installer does this by default) and
that you've opened a new terminal/restarted Claude Desktop since
installing it.
