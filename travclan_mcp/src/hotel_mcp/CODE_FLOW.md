# hotel_mcp — Code Flow

A quick map of how the code is wired and how a single tool call travels through it. This is a high-level guide (what each piece does and *why* it exists), not a line-by-line reference.

## The big picture

`hotel_mcp` is an MCP server that exposes TravClan's hotel APIs (search, rooms/rates, price-check, booking) as MCP tools. It follows a **clean / hexagonal architecture**: the layers depend inward, and the outer world (MCP transport, HTTP) is kept at the edges so the core stays simple and testable.

```
MCP client
   │  (HTTP: /<api_key>/mcp?user_id=..&merchant_id=..)
   ▼
interface/tools.py      ← MCP tool definitions + credential extraction
   ▼
application/use_cases   ← one thin class per operation (the "verbs")
   │  (talks only to the port, never to httpx)
   ▼
application/ports.py    ← HotelGateway / TokenProvider protocols (the contract)
   ▲ implemented by
infrastructure/         ← travclan_hotel_api.py (HTTP) + auth.py (tokens)
   ▼
TravClan REST APIs
```

Supporting pieces:
- `domain/` — the data shapes (`entities.py`) and error types (`exceptions.py`). No I/O.
- `config.py` — non-secret server config + per-user credentials/settings.
- `container.py` — dependency injection: builds the use cases and wires them to a per-user gateway.
- `server.py` / `__main__.py` — boot the FastMCP server.

## Why the layers exist

| Layer | Files | Responsibility | Why it's separate |
|-------|-------|----------------|-------------------|
| **Interface** | `interface/tools.py` | Declare MCP tools, read credentials from the request, convert raw args into domain models, catch errors | Keeps MCP/transport concerns out of the business logic |
| **Application** | `application/use_cases/*`, `application/ports.py` | One class per operation; defines *what* happens via a gateway interface | Business logic depends on an abstraction, not on httpx/TravClan |
| **Domain** | `domain/entities.py`, `domain/exceptions.py` | Validated data models (Pydantic) and typed errors | Pure, reusable, no external dependencies |
| **Infrastructure** | `infrastructure/travclan_hotel_api.py`, `infrastructure/auth.py` | Actually call TravClan over HTTP; manage auth tokens | The only place that knows about URLs, headers, retries |
| **Config / Wiring** | `config.py`, `container.py`, `server.py`, `__main__.py` | Configuration, DI, and server startup | Assembles everything; the "main" seam |

## Startup flow (once, at boot)

1. `__main__.main()` — reads `ServerConfig.from_env()` (URLs, timeouts, retry count from env vars) and calls `create_server`.
2. `server.create_server()` — creates the `FastMCP` app with the URL shape `/{api_key}/mcp`, builds a `ContainerProvider`, and calls `register_tools`.
3. `interface.register_tools()` — registers each `@mcp.tool()` (search_locations, search_hotels, get_rooms_and_rates, get_hotel_static_content, price_check, create_booking, get_booking_details).
4. `server.run(transport=...)` — starts serving (default `streamable-http`).

## Per-request flow (every tool call)

Using `search_hotels` as the example — every other tool follows the same shape:

1. **Tool entry** — `tools.search_hotels(...)` receives the arguments and the MCP `Context`.
2. **Build a domain model** — raw args become a validated `SearchCriteria` (Pydantic). Invalid input fails here.
3. **Dispatch** — `_dispatch(ctx, provider, op)` runs the shared plumbing:
   - `_credentials_from_context(ctx)` pulls `api_key` (URL path) + `user_id`/`merchant_id` (query params). Missing → `CredentialsError`.
   - `provider.for_credentials(credentials)` returns a per-user `Container` (see DI below).
   - Runs the operation: `container.search_hotels.execute(criteria)`.
   - Any `HotelMcpError` is caught and returned as `{"error": "..."}` so the client gets a clean message instead of a crash.
4. **Use case** — `SearchHotels.execute()` simply forwards to `gateway.search_hotels(criteria)`. (Use cases are intentionally thin now; they're the place to add business rules later without touching transport or HTTP.)
5. **Gateway (HTTP)** — `TravclanHotelGateway.search_hotels()`:
   - Serializes the model with `by_alias=True` (so Python `snake_case` → API `camelCase`).
   - Calls `_request("POST", search_api_url, "/api/v1/search", json=payload)`.
6. **Auth + send** — inside `_request`:
   - `token_provider.get_token()` returns a cached token or fetches a new one.
   - `_send()` issues the HTTP call with retries on transport errors.
   - On **401**, it refreshes the token once and retries; other non-2xx → `TravclanApiError`.
7. **Response** — the parsed JSON bubbles straight back up to the MCP client.

```
tools.search_hotels
  → SearchCriteria (validate)
  → _dispatch → credentials → provider.for_credentials → Container
  → SearchHotels.execute
  → TravclanHotelGateway.search_hotels
  → _request → get_token → _send (retry / 401-refresh)
  → TravClan /api/v1/search
  ← JSON response
```

## Dependency injection & multi-tenancy (`container.py`)

The server process holds **no** TravClan secrets of its own — credentials arrive with each request, so one deployment safely serves many users.

- `ContainerProvider.for_credentials(credentials)`:
  - Builds per-request `Settings` (server config + this caller's credentials).
  - Gets/creates a `TravclanAuthManager` **cached per credential set** (`cache_key()`), so repeated calls from the same user reuse a valid token while different users stay isolated. A lock guards the cache.
  - Creates a fresh `TravclanHotelGateway` and returns `Container.build(gateway)`.
- `Container` is just a frozen dataclass holding one use-case instance per tool, each pointing at the same gateway.

## Auth token lifecycle (`infrastructure/auth.py`)

`TravclanAuthManager` implements the `TokenProvider` port:
- `get_token()` — returns the in-memory token if still valid (with a 5-min expiry buffer); otherwise fetches one. A lock prevents multiple concurrent logins.
- `refresh_token()` — clears the token and forces a new login (called by the gateway on a 401).
- `_fetch_token()` — POSTs credentials to the auth service and stores the `AccessToken` + expiry.

## Where to make common changes

- **Add a new TravClan operation** → add a method to the `HotelGateway` port, implement it in `TravclanHotelGateway`, add a use case in `application/use_cases/`, wire it in `container.py`, expose it as a `@mcp.tool()` in `tools.py`.
- **Add business logic / validation** → put it in the relevant use case (keeps transport and HTTP untouched).
- **Change API URLs, timeouts, retries** → `config.py` (env vars).
- **Change request/response field shapes** → `domain/entities.py` (the Pydantic aliases handle snake_case ↔ camelCase).
- **Change how errors reach the client** → `_dispatch` in `tools.py` and the types in `domain/exceptions.py`.
