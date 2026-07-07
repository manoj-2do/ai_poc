from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hotel_mcp.application.ports import HotelGateway


class GetRoomsAndRates:
    def __init__(self, gateway: HotelGateway) -> None:
        self._gateway = gateway

    async def execute(self, trace_id: str, hotel_id: str) -> Mapping[str, Any]:
        return await self._gateway.get_rooms_and_rates(trace_id, hotel_id)
