from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hotel_mcp.application.ports import HotelGateway
from hotel_mcp.domain.entities import SearchCriteria


class SearchHotels:
    def __init__(self, gateway: HotelGateway) -> None:
        self._gateway = gateway

    async def execute(self, criteria: SearchCriteria) -> Mapping[str, Any]:
        return await self._gateway.search_hotels(criteria)
