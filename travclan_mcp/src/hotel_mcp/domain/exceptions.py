from __future__ import annotations

from typing import Any


class HotelMcpError(Exception):
    """Base error for every failure the hotel MCP server surfaces to callers."""


class AuthenticationError(HotelMcpError):
    """Raised when a Travclan access token cannot be obtained."""


class CredentialsError(HotelMcpError):
    """Raised when the caller did not supply the required TravClan credentials."""


class TravclanApiError(HotelMcpError):
    def __init__(
        self,
        status_code: int,
        message: str,
        upstream_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.upstream_body = upstream_body
