"""Normalize hotel static content into semantic chunks for vector search."""

from __future__ import annotations

import json
import re
from typing import Any

FACILITY_FLAGS_RULES: dict[str, list[str]] = {
    "free_wifi": ["wifi", "wireless", "internet", "broadband"],
    "pool": ["pool", "swimming"],
    "spa": ["spa", "wellness", "massage", "facial", "treatment room"],
    "gym": ["gym", "fitness", "exercise"],
    "parking": ["parking", "garage", "valet"],
    "restaurant": ["restaurant", "dining", "cafe", "coffee shop"],
    "breakfast": ["breakfast"],
    "airport_shuttle": ["airport transportation", "airport shuttle", "airport transfer"],
    "wheelchair_access": ["wheelchair", "accessible"],
    "pet_friendly": ["pet friendly", "pets allowed"],
    "laundry_service": ["laundry", "dry cleaning", "laundromat"],
    "non_smoking": ["non-smoking", "smoke-free"],
    "lounge": ["lounge", "bar"],
    "business_facility": ["meeting room", "business center", "conference center", "meeting space"],
    "golf": ["golf course", "golfing", "golf"],
}

ATTRIBUTE_FLAGS_RULES: dict[str, list[str]] = {
    "luxury_property": ["luxury"],
    "business_property": ["business"],
    "family_friendly_property": ["family"],
    "spa_property": ["spa"],
    "pet_friendly": ["pet friendly"],
    "no_pets": ["pets not allowed", "no pets allowed"],
    "contactless_checkout": ["contactless check-out"],
}

HTML_TAG_RE = re.compile(r"<[^>]*>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return " ".join(clean_text(item) for item in value if item)
    text = HTML_TAG_RE.sub(" ", str(value))
    return WHITESPACE_RE.sub(" ", text).strip()


def title_case_policy_type(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _group_key(value: Any) -> str:
    return str(value) if value is not None else "Other"


class HotelsStaticNormalizer:
    def normalize(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        hotel = doc.get("data") or {}
        hotel_id = doc.get("hotelId") or hotel.get("id")
        hotel_name = hotel.get("name") or ""

        if not hotel_id or not hotel_name:
            raise ValueError("Invalid hotel document: hotelId and hotelName are required")

        hotel_id = str(hotel_id)
        address = (hotel.get("contact") or {}).get("address") or {}
        city = (address.get("city") or {}).get("name") or ""
        state = (address.get("state") or {}).get("name") or ""
        country = (address.get("country") or {}).get("name") or ""
        postal_code = address.get("postalCode") or ""
        address_line = address.get("line1") or ""
        chain_name = hotel.get("chainName") or ""
        star_rating = float(hotel.get("starRating") or 0)

        lat = _as_number((hotel.get("geoCode") or {}).get("lat"))
        long_value = _as_number((hotel.get("geoCode") or {}).get("long"))

        grouped_facilities_map: dict[str, dict[str, Any]] = {}
        facility_groups = hotel.get("facilityGroups") or []
        raw_facilities = hotel.get("facilities") or []

        for group in facility_groups:
            grouped_facilities_map[_group_key(group.get("id"))] = {
                "name": group.get("name"),
                "facilities": [],
            }

        for facility in raw_facilities:
            group_id = _group_key(facility.get("groupId") or "Other")
            if group_id in grouped_facilities_map:
                grouped_facilities_map[group_id]["facilities"].append(facility.get("name"))
            else:
                if group_id not in grouped_facilities_map:
                    grouped_facilities_map[group_id] = {
                        "name": facility.get("groupName") or "Other Facilities",
                        "facilities": [],
                    }
                grouped_facilities_map[group_id]["facilities"].append(facility.get("name"))

        facilities_list_lines: list[str] = []
        for group in grouped_facilities_map.values():
            unique_names = sorted({name for name in group.get("facilities") or [] if name})
            if unique_names:
                facilities_list_lines.append(f"- {group.get('name')}: {', '.join(unique_names)}")
        facilities_text = "\n".join(facilities_list_lines)

        desc_map = {item.get("type"): item.get("text") for item in hotel.get("descriptions") or []}

        reviews = (hotel.get("reviews") or [{}])[0] if hotel.get("reviews") else {}
        review_rating = _as_number(reviews.get("rating"))
        review_count = _as_number(reviews.get("count"))

        attractions = hotel.get("nearByAttractions") or []
        attraction_lines = [
            f"- {attraction.get('name')} ({attraction.get('distance')} {attraction.get('unit') or 'km'})"
            for attraction in attractions
            if attraction.get("name")
        ]
        attractions_text = "\n".join(attraction_lines)

        checkin = hotel.get("checkinInfo") or {}
        checkout = hotel.get("checkoutInfo") or {}
        checkin_inst = clean_text(checkin.get("instructions"))
        checkin_special = clean_text(checkin.get("specialInstructions"))

        checkin_details_text = " ".join(
            part
            for part in [
                f"Check-in starts at {checkin.get('beginTime') or 'N/A'} and ends at {checkin.get('endTime') or 'N/A'}.",
                f"Minimum check-in age is {checkin.get('minAge')}." if checkin.get("minAge") else "",
                f"Instructions: {checkin_inst}" if checkin_inst else "",
                f"Special Instructions: {checkin_special}" if checkin_special else "",
            ]
            if part
        )
        checkout_details_text = f"Check-out time is by {checkout.get('time') or 'N/A'}."

        policy_lines = []
        for policy in hotel.get("policies") or []:
            policy_type = title_case_policy_type(policy.get("type") or "policy")
            policy_lines.append(f"- **{policy_type}:** {clean_text(policy.get('text'))}")
        policies_text = "\n".join(policy_lines)

        badge_lines = []
        for badge in hotel.get("badges") or []:
            score_str = (
                f" (Score: {badge.get('badge_data', {}).get('score')})"
                if badge.get("badge_data", {}).get("score")
                else ""
            )
            subtext_str = f" - {badge.get('subtext')}" if badge.get("subtext") else ""
            highlights = ", ".join(
                item.get("text", "")
                for item in badge.get("highlight_list") or []
                if item.get("text")
            )
            highlights_str = f" | Highlights: {highlights}" if highlights else ""
            badge_lines.append(
                f"- **{badge.get('text') or 'Award'}{score_str}**: {subtext_str}{highlights_str}"
            )
        badges_text = "\n".join(badge_lines)

        room_lines = []
        for room in hotel.get("rooms") or []:
            room_name = room.get("type") or "Room Option"
            area = room.get("area") or {}
            area_str = f" ({area.get('squareFeet')} sq ft)" if area.get("squareFeet") else ""
            room_fac_list = [facility.get("name") for facility in room.get("facilities") or [] if facility.get("name")]
            unique_room_facs = sorted(set(room_fac_list))
            facs_str = f" | Amenities: {', '.join(unique_room_facs)}" if unique_room_facs else ""
            room_lines.append(f"- **{room_name}{area_str}**{facs_str}")
        rooms_text = "\n".join(room_lines[:15])

        all_facilities_text = " ".join((facility.get("name") or "").lower() for facility in raw_facilities)
        facility_flags = [
            flag
            for flag, keywords in FACILITY_FLAGS_RULES.items()
            if any(keyword in all_facilities_text for keyword in keywords)
        ]

        raw_attributes = hotel.get("attributes") or []
        all_attributes_text = " ".join((attribute.get("value") or "").lower() for attribute in raw_attributes)
        attribute_flags = [
            flag
            for flag, keywords in ATTRIBUTE_FLAGS_RULES.items()
            if any(keyword in all_attributes_text for keyword in keywords)
        ]

        metadata: dict[str, Any] = {
            "hotelId": hotel_id,
            "hotelName": hotel_name,
            "starRating": star_rating,
            "chainName": chain_name,
            "facilities": facility_flags,
            "attributes": attribute_flags,
        }
        if review_rating is not None:
            metadata["reviewRating"] = review_rating
        if review_count is not None:
            metadata["reviewCount"] = review_count

        unique_images: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        seen_captions: set[str] = set()
        for image in hotel.get("images") or []:
            caption = image.get("caption") or "Other"
            links = image.get("links") or []
            url = links[0].get("url") if links else None
            if url and url not in seen_urls and caption not in seen_captions:
                seen_urls.add(url)
                seen_captions.add(caption)
                unique_images.append({"link": url, "caption": caption})

        chain_suffix = (
            f" by {chain_name}"
            if chain_name and chain_name != "-9"
            else ""
        )
        anchor_header = (
            f"{hotel_name} is a {star_rating}-star {hotel.get('type') or 'hotel'}"
            f"{chain_suffix}, located at {address_line} in {city}, {state}, {country} "
            f"(Postal: {postal_code})."
        )
        coords_header = (
            f"Coordinates: Latitude {lat}, Longitude {long_value}."
            if lat is not None and long_value is not None
            else ""
        )

        chunks: list[dict[str, Any]] = []

        overview_text = "\n".join(
            part
            for part in [
                anchor_header,
                coords_header,
                f"\n**About the Property (Headline):** {clean_text(desc_map.get('headline'))}"
                if desc_map.get("headline")
                else "",
                f"\n**General Description & Amenities:** {clean_text(desc_map.get('amenities'))}"
                if desc_map.get("amenities")
                else "",
                f"\n**Grouped Facilities by Category:**\n{facilities_text}" if facilities_text else "",
            ]
            if part
        )
        chunks.append(
            self._build_chunk(
                chunk_id=f"{hotel_id}_overview",
                chunk_type="overview",
                text=overview_text,
                metadata=metadata,
                images=unique_images[:5],
            )
        )

        dining_groups = [
            grouped_facilities_map.get(group_id)
            for group_id in ("81003", "82000", "82001")
            if grouped_facilities_map.get(group_id)
        ]
        if desc_map.get("dining") or dining_groups:
            dining_text = "\n".join(
                part
                for part in [
                    anchor_header,
                    f"\n**Dining & Restaurants:** {clean_text(desc_map.get('dining'))}"
                    if desc_map.get("dining")
                    else "",
                    f"\n**Dining Facilities:** {', '.join(grouped_facilities_map['81003']['facilities'])}"
                    if grouped_facilities_map.get("81003")
                    else "",
                    f"\n**Bar Services:** {', '.join(grouped_facilities_map['82000']['facilities'])}"
                    if grouped_facilities_map.get("82000")
                    else "",
                    f"\n**Lounge Facilities:** {', '.join(grouped_facilities_map['82001']['facilities'])}"
                    if grouped_facilities_map.get("82001")
                    else "",
                ]
                if part
            )
            dining_images = [
                image
                for image in unique_images
                if any(
                    category in image.get("caption", "")
                    for category in ("Restaurant", "Bar", "Lounge", "Breakfast area", "Dining")
                )
            ][:5]
            chunks.append(
                self._build_chunk(
                    chunk_id=f"{hotel_id}_dining",
                    chunk_type="dining",
                    text=dining_text,
                    metadata=metadata,
                    images=dining_images,
                )
            )

        if desc_map.get("rooms") or rooms_text:
            rooms_chunk_text = "\n".join(
                part
                for part in [
                    anchor_header,
                    f"\n**Rooms & Accommodation Summary:** {clean_text(desc_map.get('rooms'))}"
                    if desc_map.get("rooms")
                    else "",
                    f"\n**Available Room Types & Options:**\n{rooms_text}" if rooms_text else "",
                ]
                if part
            )
            room_images = [
                image
                for image in unique_images
                if any(
                    category in image.get("caption", "")
                    for category in ("Room", "Bathroom", "Living room", "Suite", "Bedding")
                )
            ][:5]
            chunks.append(
                self._build_chunk(
                    chunk_id=f"{hotel_id}_rooms",
                    chunk_type="rooms",
                    text=rooms_chunk_text,
                    metadata=metadata,
                    images=room_images,
                )
            )

        policies_chunk_text = "\n".join(
            part
            for part in [
                anchor_header,
                f"\n**Check-in Details & Instructions:**\n{checkin_details_text}",
                f"\n**Check-out Details:**\n{checkout_details_text}",
                f"\n**Awards, Badges & Guest Reviews:**\n{badges_text}" if badges_text else "",
                f"\n**Policies & Guest Guidelines:**\n{policies_text}" if policies_text else "",
            ]
            if part
        )
        chunks.append(
            self._build_chunk(
                chunk_id=f"{hotel_id}_policies",
                chunk_type="policies",
                text=policies_chunk_text,
                metadata=metadata,
                images=[],
            )
        )

        if desc_map.get("location") or attractions_text:
            attractions_chunk_text = "\n".join(
                part
                for part in [
                    anchor_header,
                    f"\n**Location & Neighborhood Overview:** {clean_text(desc_map.get('location'))}"
                    if desc_map.get("location")
                    else "",
                    f"\n**Nearby Attractions, Landmarks & Distances:**\n{attractions_text}"
                    if attractions_text
                    else "",
                ]
                if part
            )
            attraction_images = [
                image
                for image in unique_images
                if any(category in image.get("caption", "") for category in ("Exterior", "View", "Landmark"))
            ][:5]
            chunks.append(
                self._build_chunk(
                    chunk_id=f"{hotel_id}_attractions",
                    chunk_type="attractions",
                    text=attractions_chunk_text,
                    metadata=metadata,
                    images=attraction_images,
                )
            )

        return chunks

    @staticmethod
    def _build_chunk(
        *,
        chunk_id: str,
        chunk_type: str,
        text: str,
        metadata: dict[str, Any],
        images: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "id": chunk_id,
            "text": text,
            "metadata": {
                **metadata,
                "chunkType": chunk_type,
                "text": text,
                "images": json.dumps(images),
            },
            "images": images,
        }


_normalizer = HotelsStaticNormalizer()


def normalize(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return _normalizer.normalize(doc)
