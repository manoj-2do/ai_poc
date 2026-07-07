from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hotel_mcp.application.ports import HotelGateway


class GetBookingDetails:
    def __init__(self, gateway: HotelGateway) -> None:
        self._gateway = gateway

    async def execute(self, booking_ref_id: str) -> Mapping[str, Any]:
        return await self._gateway.get_booking_details(booking_ref_id)
