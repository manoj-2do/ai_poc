from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from hotel_mcp.config import Credentials
from hotel_mcp.container import Container, ContainerProvider
from hotel_mcp.domain.entities import (
    BookingRequest,
    Occupancy,
    PriceCheckCriteria,
    RoomSelection,
    SearchCriteria,
)
from hotel_mcp.domain.exceptions import CredentialsError, HotelMcpError

API_KEY_PATH_PARAM = "api_key"
USER_ID_QUERY_PARAM = "user_id"
MERCHANT_ID_QUERY_PARAM = "merchant_id"


def register_tools(mcp: FastMCP, provider: ContainerProvider) -> None:
    @mcp.tool()
    async def search_locations(search_string: str, ctx: Context) -> Mapping[str, Any]:
        """Search Travclan hotel locations by name. Requires at least 2 characters."""
        return await _dispatch(
            ctx, provider, lambda c: c.search_locations.execute(search_string)
        )

    @mcp.tool()
    async def search_hotels(
        check_in: str,
        check_out: str,
        occupancies: list[Occupancy],
        ctx: Context,
        location_id: str | None = None,
        hotel_id: str | None = None,
        nationality: str = "IN",
        page: int = 1,
        trace_id: str | None = None,
    ) -> Mapping[str, Any]:
        """Search hotels for the given dates and room occupancies.

        Dates use the YYYY-MM-DD format. Leave trace_id empty on the first
        search and reuse the value returned by the response for pagination.
        """
        criteria = SearchCriteria(
            checkIn=check_in,
            checkOut=check_out,
            occupancies=occupancies,
            locationId=location_id,
            hotelId=hotel_id,
            nationality=nationality,
            page=page,
            traceId=trace_id,
        )
        return await _dispatch(ctx, provider, lambda c: c.search_hotels.execute(criteria))

    @mcp.tool()
    async def get_rooms_and_rates(
        trace_id: str, hotel_id: str, ctx: Context
    ) -> Mapping[str, Any]:
        """Fetch room options and live rates for a hotel from a prior search trace."""
        return await _dispatch(
            ctx, provider, lambda c: c.get_rooms_and_rates.execute(trace_id, hotel_id)
        )

    @mcp.tool()
    async def get_hotel_static_content(
        hotel_id: str, ctx: Context
    ) -> Mapping[str, Any]:
        """Fetch static descriptive content (images, amenities, address) for a hotel."""
        return await _dispatch(
            ctx, provider, lambda c: c.get_hotel_static_content.execute(hotel_id)
        )

    @mcp.tool()
    async def price_check(
        trace_id: str, hotel_id: str, option_id: str, ctx: Context
    ) -> Mapping[str, Any]:
        """Re-validate the live price of a selected room option before booking."""
        criteria = PriceCheckCriteria(
            traceId=trace_id, hotelId=hotel_id, optionId=option_id
        )
        return await _dispatch(ctx, provider, lambda c: c.price_check.execute(criteria))

    @mcp.tool()
    async def create_booking(
        option_id: str,
        trace_id: str,
        room_details: list[RoomSelection],
        ctx: Context,
        hotel_id: str | None = None,
        special_requests: str | None = None,
    ) -> Mapping[str, Any]:
        """Create a hotel booking for a priced room option with guest details."""
        request = BookingRequest(
            optionId=option_id,
            traceId=trace_id,
            roomDetails=room_details,
            hotelId=hotel_id,
            specialRequests=special_requests,
        )
        return await _dispatch(ctx, provider, lambda c: c.create_booking.execute(request))

    @mcp.tool()
    async def get_booking_details(
        booking_ref_id: str, ctx: Context
    ) -> Mapping[str, Any]:
        """Fetch the current status and details of an existing booking."""
        return await _dispatch(
            ctx, provider, lambda c: c.get_booking_details.execute(booking_ref_id)
        )


async def _dispatch(
    ctx: Context,
    provider: ContainerProvider,
    operation: Callable[[Container], Awaitable[Mapping[str, Any]]],
) -> Mapping[str, Any]:
    try:
        credentials = _credentials_from_context(ctx)
        container = await provider.for_credentials(credentials)
        return await operation(container)
    except HotelMcpError as error:
        return {"error": str(error)}


def _credentials_from_context(ctx: Context) -> Credentials:
    """Read TravClan credentials from the request URL.

    The API key is taken from the URL path (`/<api_key>/mcp`) and the remaining
    identifiers from the query string (`?user_id=...&merchant_id=...`).
    """
    request = ctx.request_context.request
    if request is None:
        raise CredentialsError(
            "No HTTP request available. Connect via "
            "http://<host>/<api_key>/mcp?user_id=<user_id>&merchant_id=<merchant_id>."
        )

    path_params = getattr(request, "path_params", {}) or {}
    query_params = getattr(request, "query_params", {}) or {}

    api_key = path_params.get(API_KEY_PATH_PARAM)
    user_id = query_params.get(USER_ID_QUERY_PARAM)
    merchant_id = query_params.get(MERCHANT_ID_QUERY_PARAM)

    missing = [
        label
        for label, value in (
            (f"{API_KEY_PATH_PARAM} (URL path)", api_key),
            (f"{USER_ID_QUERY_PARAM} (query param)", user_id),
            (f"{MERCHANT_ID_QUERY_PARAM} (query param)", merchant_id),
        )
        if not value
    ]
    if missing:
        raise CredentialsError(
            f"Missing required credential(s): {', '.join(missing)}"
        )

    return Credentials(api_key=api_key, user_id=user_id, merchant_id=merchant_id)
