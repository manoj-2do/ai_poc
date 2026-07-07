from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from hotel_mcp.domain.entities import BookingRequest, PriceCheckCriteria, SearchCriteria


class TokenProvider(Protocol):
    async def get_token(self) -> str: ...

    async def refresh_token(self) -> str: ...


class HotelGateway(Protocol):
    async def search_locations(self, search_string: str) -> Mapping[str, Any]: ...

    async def search_hotels(self, criteria: SearchCriteria) -> Mapping[str, Any]: ...

    async def get_rooms_and_rates(
        self, trace_id: str, hotel_id: str
    ) -> Mapping[str, Any]: ...

    async def get_hotel_static_content(self, hotel_id: str) -> Mapping[str, Any]: ...

    async def price_check(self, criteria: PriceCheckCriteria) -> Mapping[str, Any]: ...

    async def create_booking(self, request: BookingRequest) -> Mapping[str, Any]: ...

    async def get_booking_details(self, booking_ref_id: str) -> Mapping[str, Any]: ...
