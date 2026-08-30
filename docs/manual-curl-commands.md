# Manual curl commands

Test `mcp-eveng` directly over HTTP, without an MCP client. Requires the
server running in `--http` mode (see [Run App](../README.md#run-app)).

Every example below was run against a real local server to confirm it
works exactly as shown.

## 1. Use `localhost`, not `127.0.0.1`

The default `MCP_ALLOWED_HOSTS=localhost:*` only matches the `localhost`
hostname — `127.0.0.1` gets rejected with `421 Misdirected Request:
Invalid Host header` (confirmed live). Use `http://localhost:PORT/mcp`
in every command below, or add your IP to `MCP_ALLOWED_HOSTS` first.

## 2. Initialize a session

```bash
curl -s -i -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-test","version":"1.0"}}}'
```

Copy the `mcp-session-id` response header's value — every following
request needs it.

## 3. Send the `initialized` notification

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
```

## 4. Call a tool

Same `Mcp-Session-Id` header on every call. Responses are Streamable
HTTP's own `event: message` / `data: {...}` framing, even for a single
non-streaming result — that's expected, not an error.

`list_tools`:

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_tools","arguments":{}}}'
```

`list_node_templates`:

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_node_templates","arguments":{}}}'
```

`list_labs`:

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_labs","arguments":{}}}'
```

`list_captures` (PRO only):

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"list_captures","arguments":{}}}'
```

A `"result":{"isError":true, ... "All connection attempts failed"}`
response means the request format was fine — it means `EVENG_HOST` in
`.env` isn't reachable, not a curl problem.
