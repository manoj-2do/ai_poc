# travclan-mcp

An MCP server that exposes the TravClan Hotel API (locations, hotel search, rooms and rates, static content, price check, booking) as MCP tools.

## Architecture

```
interface (MCP tools)  ->  application (use cases + ports)  ->  domain (entities, errors)
        |                                                              ^
        +--------->  infrastructure (auth + HTTP gateway)  --implements-+ (ports)
```

- `domain/` — request value objects and errors, no external layer imports.
- `application/` — one use case per operation plus the `HotelGateway` and `TokenProvider` ports.
- `infrastructure/` — `TravclanAuthManager` (token lifecycle) and `TravclanHotelGateway` (HTTP calls, upstream payload mapping).
- `interface/` — MCP tool functions that translate tool arguments into use case calls.
- `container.py` / `__main__.py` — composition root that wires everything and runs the server.

## Setup

Requires Python 3.10+.

```bash
cd travclan_mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Fill in real TravClan credentials in `.env`:

```
TRAVCLAN_API_KEY, TRAVCLAN_USER_ID, TRAVCLAN_MERCHANT_ID
```

## Run

```bash
python -m hotel_mcp
```

Inspect the tools interactively:

```bash
npx -y @modelcontextprotocol/inspector python -m hotel_mcp
```

## Register with an MCP client

```json
{
  "mcpServers": {
    "travclan-hotel": {
      "command": "/absolute/path/travclan_mcp/.venv/bin/python",
      "args": ["-m", "hotel_mcp"]
    }
  }
}
```

## Tools

| Tool | TravClan endpoint |
|---|---|
| `search_locations` | `GET /api/v1/locations/search` |
| `search_hotels` | `POST /api/v1/search` |
| `get_rooms_and_rates` | `POST /api/v1/roomsandrates` |
| `get_hotel_static_content` | `GET /api/v1/hotels/{hotelId}/static-content` |
| `price_check` | `POST /api/v1/price-check` |
| `create_booking` | `POST /api/v1/book` |
| `get_booking_details` | `GET /api/v1/hotels/itineraries/bookings/{bookingRefId}` |
