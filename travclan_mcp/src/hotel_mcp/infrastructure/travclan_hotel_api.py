from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from hotel_mcp.application.ports import TokenProvider
from hotel_mcp.config import Settings
from hotel_mcp.domain.entities import BookingRequest, PriceCheckCriteria, SearchCriteria
from hotel_mcp.domain.exceptions import TravclanApiError


class TravclanHotelGateway:
    def __init__(self, settings: Settings, token_provider: TokenProvider) -> None:
        self._settings = settings
        self._token_provider = token_provider

    async def search_locations(self, search_string: str) -> Mapping[str, Any]:
        return await self._request(
            "GET",
            self._settings.hotel_helper_host,
            "/api/v1/locations/search",
            params={"searchString": search_string},
        )

    async def search_hotels(self, criteria: SearchCriteria) -> Mapping[str, Any]:
        payload = criteria.model_dump(by_alias=True, exclude_none=True)
        return await self._request(
            "POST", self._settings.search_api_url, "/api/v1/search", json=payload
        )

    async def get_rooms_and_rates(self, trace_id: str, hotel_id: str) -> Mapping[str, Any]:
        return await self._request(
            "POST",
            self._settings.search_api_url,
            "/api/v1/roomsandrates",
            json={"traceId": trace_id, "hotelId": hotel_id},
        )

    async def get_hotel_static_content(self, hotel_id: str) -> Mapping[str, Any]:
        return await self._request(
            "GET",
            self._settings.hotel_helper_host,
            f"/api/v1/hotels/{hotel_id}/static-content",
        )

    async def price_check(self, criteria: PriceCheckCriteria) -> Mapping[str, Any]:
        payload = criteria.model_dump(by_alias=True)
        return await self._request(
            "POST", self._settings.search_api_url, "/api/v1/price-check", json=payload
        )

    async def create_booking(self, request: BookingRequest) -> Mapping[str, Any]:
        payload = self._normalize_booking_payload(
            request.model_dump(by_alias=True, exclude_none=True)
        )
        return await self._request(
            "POST", self._settings.search_api_url, "/api/v1/book", json=payload
        )

    async def get_booking_details(self, booking_ref_id: str) -> Mapping[str, Any]:
        return await self._request(
            "GET",
            self._settings.hotel_helper_host,
            f"/api/v1/hotels/itineraries/bookings/{booking_ref_id}",
        )

    async def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retry_on_unauthorized: bool = True,
    ) -> Mapping[str, Any]:
        token = await self._token_provider.get_token()
        headers = self._build_headers(method, token)
        response = await self._send(method, base_url, path, headers, json, params)

        if response.status_code == 401 and retry_on_unauthorized:
            await self._token_provider.refresh_token()
            return await self._request(
                method,
                base_url,
                path,
                json=json,
                params=params,
                retry_on_unauthorized=False,
            )

        if not response.is_success:
            raise TravclanApiError(
                status_code=response.status_code,
                message=f"Travclan {path} returned {response.status_code}",
                upstream_body=self._read_body(response),
            )

        return response.json()

    async def _send(
        self,
        method: str,
        base_url: str,
        path: str,
        headers: dict[str, str],
        json: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> httpx.Response:
        last_error: httpx.TransportError | None = None
        async with httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            base_url=base_url.rstrip("/") + "/",
        ) as client:
            for _ in range(self._settings.http_max_retries):
                try:
                    return await client.request(
                        method, path.lstrip("/"), headers=headers, json=json, params=params
                    )
                except httpx.TransportError as error:
                    last_error = error
        raise TravclanApiError(
            status_code=503,
            message=f"Travclan {path} is unreachable",
        ) from last_error

    def _build_headers(self, method: str, token: str) -> dict[str, str]:
        headers = {
            "Authorization-Type": "external-service",
            "source": self._settings.source,
            "Authorization": f"Bearer {token}",
        }
        if method.upper() != "GET":
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _read_body(response: httpx.Response) -> dict[str, Any] | None:
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _normalize_booking_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)

        special_requests = normalized.get("specialRequests")
        if special_requests is not None:
            cleaned = " ".join(str(special_requests).split()).strip()
            if cleaned:
                normalized["specialRequests"] = cleaned
            else:
                normalized.pop("specialRequests", None)

        rooms = normalized.get("roomDetails")
        if isinstance(rooms, list):
            normalized["roomDetails"] = [
                {
                    **room,
                    "guests": [
                        {**guest, "isdCode": str(guest["isdCode"]).lstrip("+").strip()}
                        if guest.get("isdCode") is not None
                        else guest
                        for guest in room.get("guests", [])
                    ],
                }
                for room in rooms
            ]

        return normalized
