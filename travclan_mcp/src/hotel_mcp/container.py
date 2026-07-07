from __future__ import annotations

import asyncio
from dataclasses import dataclass

from hotel_mcp.application.ports import HotelGateway
from hotel_mcp.application.use_cases.create_booking import CreateBooking
from hotel_mcp.application.use_cases.get_booking_details import GetBookingDetails
from hotel_mcp.application.use_cases.get_hotel_static_content import GetHotelStaticContent
from hotel_mcp.application.use_cases.get_rooms_and_rates import GetRoomsAndRates
from hotel_mcp.application.use_cases.price_check import PriceCheck
from hotel_mcp.application.use_cases.search_hotels import SearchHotels
from hotel_mcp.application.use_cases.search_locations import SearchLocations
from hotel_mcp.config import Credentials, ServerConfig, Settings
from hotel_mcp.infrastructure.auth import TravclanAuthManager
from hotel_mcp.infrastructure.travclan_hotel_api import TravclanHotelGateway


@dataclass(frozen=True)
class Container:
    search_locations: SearchLocations
    search_hotels: SearchHotels
    get_rooms_and_rates: GetRoomsAndRates
    get_hotel_static_content: GetHotelStaticContent
    price_check: PriceCheck
    create_booking: CreateBooking
    get_booking_details: GetBookingDetails

    @classmethod
    def build(cls, gateway: HotelGateway) -> "Container":
        return cls(
            search_locations=SearchLocations(gateway),
            search_hotels=SearchHotels(gateway),
            get_rooms_and_rates=GetRoomsAndRates(gateway),
            get_hotel_static_content=GetHotelStaticContent(gateway),
            price_check=PriceCheck(gateway),
            create_booking=CreateBooking(gateway),
            get_booking_details=GetBookingDetails(gateway),
        )


class ContainerProvider:
    """Builds a per-user :class:`Container` from request-scoped credentials.

    Auth managers are cached per credential set so repeated calls from the same
    user reuse a valid token, while different users stay fully isolated.
    """

    def __init__(self, server_config: ServerConfig) -> None:
        self._server_config = server_config
        self._auth_managers: dict[tuple[str, str, str], TravclanAuthManager] = {}
        self._lock = asyncio.Lock()

    async def for_credentials(self, credentials: Credentials) -> Container:
        settings = Settings.for_request(self._server_config, credentials)
        auth_manager = await self._auth_manager(credentials, settings)
        gateway = TravclanHotelGateway(settings, auth_manager)
        return Container.build(gateway)

    async def _auth_manager(
        self, credentials: Credentials, settings: Settings
    ) -> TravclanAuthManager:
        key = credentials.cache_key()
        async with self._lock:
            manager = self._auth_managers.get(key)
            if manager is None:
                manager = TravclanAuthManager(settings)
                self._auth_managers[key] = manager
            return manager
