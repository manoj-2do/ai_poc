from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hotel_mcp.application.ports import HotelGateway


class GetHotelStaticContent:
    def __init__(self, gateway: HotelGateway) -> None:
        self._gateway = gateway

    async def execute(self, hotel_id: str) -> Mapping[str, Any]:
        return await self._gateway.get_hotel_static_content(hotel_id)
