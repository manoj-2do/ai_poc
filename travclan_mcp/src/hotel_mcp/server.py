from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from hotel_mcp.config import ServerConfig
from hotel_mcp.container import ContainerProvider
from hotel_mcp.interface.tools import register_tools


def create_server(server_config: ServerConfig) -> FastMCP:
    mcp = FastMCP(
        "travclan-hotel-mcp",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        streamable_http_path="/{api_key}/mcp",
    )
    provider = ContainerProvider(server_config)
    register_tools(mcp, provider)
    return mcp
