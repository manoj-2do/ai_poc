---
name: hotel-booking
description: Search, compare, and book hotels end-to-end using the connected TravClan Hotel MCP connector. Use this whenever the user wants to find a hotel, compare hotel prices or rooms, get hotel recommendations, check amenities, book a room, or check on an existing hotel booking — even if they don't say "hotel-mcp" or name the connector explicitly. Trigger on phrases like "find me a hotel", "book a room in X", "what's the price for...", "compare hotels in...", "does the hotel have a pool", or "check my booking".
---
 
# Hotel Booking
 
Use the connected **TravClan Hotel MCP** connector to search, compare, book, and track hotels. The connector is already authenticated — never ask the user for API keys, user IDs, or merchant IDs.
 
## Tool Reference
 
All tools are called directly (they're prefixed `TravClan Hotel MCP:` in the tool list).
 
| Tool | Purpose | Key inputs |
|------|---------|-----------|
| `search_locations` | Resolve a place name to a `location_id` | `search_string` (≥2 chars) |
| `search_hotels` | Find hotels + get a `trace_id` | `check_in`, `check_out`, `occupancies`, `location_id`/`hotel_id`, `page`, `trace_id` |
| `get_hotel_static_content` | Images, amenities, address | `hotel_id` |
| `get_rooms_and_rates` | Room options + live rates + `option_id`s | `trace_id`, `hotel_id` |
| `price_check` | Re-validate a price before booking | `trace_id`, `hotel_id`, `option_id` |
| `create_booking` | Book a priced option | `option_id`, `trace_id`, `room_details`, `hotel_id?`, `special_requests?` |
| `get_booking_details` | Status/details of one booking | `booking_ref_id` |
 
`occupancies` is a list of `{ "numOfAdults": int, "childAges": [int, ...] }` — one entry per room.
 
## Golden Rules
 
- **`trace_id` is the session key.** `search_hotels` returns a `trace_id`. Reuse the *same* `trace_id` for `get_rooms_and_rates`, `price_check`, and `create_booking` for that search. A stale/mismatched `trace_id` breaks booking.
- **Dates are `YYYY-MM-DD`.** Default `nationality` is `IN` unless the user specifies otherwise.
- **Prices are in the requested currency (INR by default), NOT AED.** The headline `finalRate` / `pRpNFinalRate` carry no currency label — they're in the requested currency. A `"currency": "AED"` field may appear inside `additionalCharges` (an on-site `mandatory_tax` payable at the hotel), which also has an `amountInRequestedCurrency`. Never label `finalRate` as AED.
- **Never invent IDs.** `location_id`, `hotel_id`, `option_id`, `roomId` must come from a prior tool response, never guessed.
- **Always confirm with the user before calling `create_booking`** — show the hotel, room, final price, and guest names first, and get explicit go-ahead.
- If a tool call fails with an auth/credential error, the connector's underlying credentials are the problem — surface this to the user rather than retrying blindly (they may need to reconnect it).
## Gathering search details
 
Before calling `search_hotels`, make sure you have these. If anything's missing, ask concise clarifying questions (batch them into one message) rather than guessing:
 
| Detail | Needed for | If missing |
|--------|-----------|------------|
| **Destination** | `search_locations` | Ask — no sensible default. |
| **Check-in date** | `check_in` | Ask. Resolve relative dates ("next Friday") to `YYYY-MM-DD` using the current date. |
| **Nights / check-out** | `check_out` | Ask how many nights (or the check-out date), then compute `check_out`. |
| **Number of guests** | `occupancies` | Ask how many adults and children (and children's ages). |
| **Rooms** | `occupancies` length | Ask only if the guest count is ambiguous — otherwise apply the default below. |
 
**Room distribution default:** if the user doesn't specify how rooms are split, use **2 adults per room**. Compute rooms as `ceil(adults / 2)` and distribute adults evenly, then place children with an adult. Examples:
 
- 2 adults → 1 room `[{ numOfAdults: 2 }]`
- 3 adults → 2 rooms `[{ numOfAdults: 2 }, { numOfAdults: 1 }]`
- 4 adults → 2 rooms `[{ numOfAdults: 2 }, { numOfAdults: 2 }]`
- 2 adults + 1 child (age 6) → 1 room `[{ numOfAdults: 2, childAges: [6] }]`
Always **state the assumptions you applied** (dates, guest split, rooms) when presenting results, so the user can correct them. Children always require ages — ask if a child is mentioned without one.
 
## Workflows
 
### Full booking
 
1. `search_locations` → pick `location_id`
2. `search_hotels` → get `trace_id` + hotel list
3. `get_rooms_and_rates` for the chosen hotel → pick `option_id` + `roomId`
4. `price_check` the option → confirm the price is still valid
5. Present the hotel, room, final price (with currency), and ask the user to confirm guest details and go-ahead
6. `create_booking` → capture the returned `booking_ref_id`
7. Give the user the `booking_ref_id` and confirm the booking with `get_booking_details`; tell them to save the reference, since this skill doesn't persist a booking list across separate conversations
`room_details` for `create_booking`: one `RoomSelection` per booked room —
`{ "roomId": "...", "guests": [ { "title", "firstName", "lastName", "isLeadGuest": true/false, "type": "adult"|"child", ...optional middleName/email/contactNumber/isdCode/age } ] }`.
Exactly one guest must have `isLeadGuest: true`. Children need `age` consistent with the search occupancy.
 
### Compare prices
 
- **Across hotels:** run `search_hotels`, then present the cheapest lead prices side by side (hotel, rating, price/night, total).
- **Across rooms in one hotel:** run `get_rooms_and_rates` and compare `option_id`s by board type (room-only vs breakfast), refundability, and total price.
- Reuse the same `trace_id` and dates so prices are comparable. State the currency explicitly (see "Reading prices").
### Reading prices
 
- `finalRate` = total for the whole stay (all rooms × all nights). `pRpNFinalRate` = per room, per night. Sanity check: `pRpNFinalRate × nights × rooms ≈ finalRate`.
- These figures are in the **requested currency**, INR by default. They have **no** currency label in the JSON — don't assume AED.
- The `"currency": "AED"` you may see belongs only to the `additionalCharges` → `mandatory_tax` block (a local tax **payable at the hotel**), which also exposes `amountInRequestedCurrency` (the INR equivalent).
- When presenting prices, use ₹/INR for the room rate and separately mention any on-site AED tax if relevant.
### Recommend good hotels
 
Rank `search_hotels` results by star rating / review score fields when present, balanced against price. State the criteria used (e.g. "4★+, sorted by rating then price"). If the response has no rating/review data, say so and rank by price instead — never fabricate reviews.
 
### Show amenities
 
Call `get_hotel_static_content(hotel_id)` and summarize amenities, address, and a couple of image URLs for the user.
 
### Checking an existing booking
 
There's no "list all bookings" tool. If the user has a `booking_ref_id`, call `get_booking_details` directly. If they don't have one, ask them for it or for identifying details (hotel name, dates) — this skill can't look bookings up without a reference.
 
## Notes
 
- Results are large JSON blobs; extract only the fields the user needs (names, prices, ratings, IDs) instead of dumping raw output.
- If the connector itself isn't available or a call errors out with "no such tool"/connection issues, tell the user the TravClan Hotel MCP connector may need to be reconnected, rather than retrying repeatedly.