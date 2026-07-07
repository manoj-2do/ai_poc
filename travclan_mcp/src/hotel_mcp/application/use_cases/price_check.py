from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hotel_mcp.application.ports import HotelGateway
from hotel_mcp.domain.entities import PriceCheckCriteria


class PriceCheck:
    def __init__(self, gateway: HotelGateway) -> None:
        self._gateway = gateway

    async def execute(self, criteria: PriceCheckCriteria) -> Mapping[str, Any]:
        return await self._gateway.price_check(criteria)
