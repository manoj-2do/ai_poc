from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hotel_mcp.application.ports import HotelGateway


class SearchLocations:
    def __init__(self, gateway: HotelGateway) -> None:
        self._gateway = gateway

    async def execute(self, search_string: str) -> Mapping[str, Any]:
        return await self._gateway.search_locations(search_string)
