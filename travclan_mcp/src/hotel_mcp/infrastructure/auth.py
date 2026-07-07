from __future__ import annotations

import asyncio
import time

import httpx

from hotel_mcp.config import Settings
from hotel_mcp.domain.exceptions import AuthenticationError


class TravclanAuthManager:
    _EXPIRY_BUFFER_SECONDS = 300
    _TOKEN_LIFETIME_SECONDS = 3600

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        if self._is_token_valid():
            return self._token  # type: ignore[return-value]
        async with self._lock:
            if self._is_token_valid():
                return self._token  # type: ignore[return-value]
            return await self._fetch_token()

    async def refresh_token(self) -> str:
        async with self._lock:
            self._token = None
            self._expires_at = 0.0
            return await self._fetch_token()

    def _is_token_valid(self) -> bool:
        return self._token is not None and time.monotonic() < self._expires_at

    async def _fetch_token(self) -> str:
        url = f"{self._settings.auth_url.rstrip('/')}/authentication/internal/service/login"
        payload = {
            "api_key": self._settings.api_key,
            "user_id": self._settings.user_id,
            "merchant_id": self._settings.merchant_id,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization-Type": "Bearer",
            "source": self._settings.source,
        }
        async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)

        if not response.is_success:
            raise AuthenticationError(
                f"Travclan login failed with status {response.status_code}"
            )

        token = response.json().get("AccessToken")
        if not token:
            raise AuthenticationError("Travclan login response did not contain an access token")

        self._token = token
        self._expires_at = (
            time.monotonic() + self._TOKEN_LIFETIME_SECONDS - self._EXPIRY_BUFFER_SECONDS
        )
        return token
