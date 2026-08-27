"""mcp-eveng: an MCP server for automating the EVENG network emulator."""

from .client import EvengClient
from .server import create_server

__version__ = "0.3.1"

__all__ = ["EvengClient", "create_server", "__version__"]
