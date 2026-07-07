from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_AUTH_URL = "https://trav-auth-sandbox.travclan.com"
_DEFAULT_SEARCH_API_URL = "https://hotel-volt-api-sandbox.travclan.com"
_DEFAULT_HOTEL_HELPER_HOST = "https://hotel-api-sandbox.travclan.com"


@dataclass(frozen=True)
class ServerConfig:
    """Deployment-wide, non-secret configuration.

    Holds everything the server needs to boot without any per-user secrets, so
    the hosted process carries no TravClan credentials of its own.
    """

    auth_url: str
    search_api_url: str
    hotel_helper_host: str
    source: str
    http_timeout_seconds: float
    http_max_retries: int

    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            auth_url=os.environ.get("TRAVCLAN_AUTH_URL", _DEFAULT_AUTH_URL),
            search_api_url=os.environ.get(
                "TRAVCLAN_SEARCH_API_URL", _DEFAULT_SEARCH_API_URL
            ),
            hotel_helper_host=os.environ.get(
                "TRAVCLAN_HOTEL_HELPER_HOST", _DEFAULT_HOTEL_HELPER_HOST
            ),
            source=os.environ.get("TRAVCLAN_SOURCE", "website"),
            http_timeout_seconds=float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30")),
            http_max_retries=max(1, int(os.environ.get("HTTP_MAX_RETRIES", "3"))),
        )


@dataclass(frozen=True)
class Credentials:
    """Per-user TravClan credentials supplied by the calling client."""

    api_key: str
    user_id: str
    merchant_id: str

    def cache_key(self) -> tuple[str, str, str]:
        return (self.api_key, self.user_id, self.merchant_id)


@dataclass(frozen=True)
class Settings:
    """Effective settings for a single user's request.

    Combines the deployment-wide :class:`ServerConfig` with one caller's
    :class:`Credentials`. Consumed by the auth manager and HTTP gateway.
    """

    api_key: str
    user_id: str
    merchant_id: str
    auth_url: str
    search_api_url: str
    hotel_helper_host: str
    source: str
    http_timeout_seconds: float
    http_max_retries: int

    @classmethod
    def for_request(
        cls, server_config: ServerConfig, credentials: Credentials
    ) -> "Settings":
        return cls(
            api_key=credentials.api_key,
            user_id=credentials.user_id,
            merchant_id=credentials.merchant_id,
            auth_url=server_config.auth_url,
            search_api_url=server_config.search_api_url,
            hotel_helper_host=server_config.hotel_helper_host,
            source=server_config.source,
            http_timeout_seconds=server_config.http_timeout_seconds,
            http_max_retries=server_config.http_max_retries,
        )
