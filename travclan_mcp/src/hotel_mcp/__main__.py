from __future__ import annotations

import os

from hotel_mcp.config import ServerConfig
from hotel_mcp.server import create_server


def main() -> None:
    server_config = ServerConfig.from_env()
    server = create_server(server_config)
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
