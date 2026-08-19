# mcp-eveng on Linux / macOS

Full install, running, and MCP-host configuration instructions for
Linux and macOS. See the [main README](../README.md) for what this
project does, the full tool list, configuration variables, and the
delete-confirmation flow — this doc only covers OS-specific setup.

## Install

```bash
pip install mcp-eveng
```

Or, for local development:

```bash
git clone https://github.com/madmickstar/mcp_eveng.git
cd mcp_eveng
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The repository (and the Python package inside it) uses an underscore --
`mcp_eveng` -- not a hyphen, so `git clone` produces a `mcp_eveng/`
directory. Only the PyPI *distribution* name (`pip install mcp-eveng`
above) uses a hyphen, which is a PyPI naming convention, not the actual
package/module name.

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
