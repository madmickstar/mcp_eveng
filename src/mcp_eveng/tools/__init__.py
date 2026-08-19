"""Tool registration modules, grouped by EVENG API area.

Each module exposes a single `register(mcp, get_client)` function that
attaches its tools to a `FastMCP` instance. Keeping registration as plain
functions (rather than import-time decorator side effects) makes the tools
trivial to unit test: call `register` against a throwaway `FastMCP()` and
inspect/call the resulting tools directly.
"""
