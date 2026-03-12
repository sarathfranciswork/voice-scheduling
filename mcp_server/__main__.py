"""Allow running with: python -m mcp_server"""

from mcp_server.server import mcp
import os

if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", "8001"))
    host = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
    mcp.run(transport="http", host=host, port=port)
