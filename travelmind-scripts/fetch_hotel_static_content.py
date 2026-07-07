#!/usr/bin/env python3
"""Fetch hotel static content and aggregated reviews from Travclan APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from constants import (
    API_PATH_AGGREGATED_REVIEWS,
    API_PATH_STATIC_CONTENT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REVIEWS_HEADERS,
    DEFAULT_STATIC_CONTENT_HEADERS,
    REVIEWS_CONTENT_FILE_PREFIX,
    STATIC_CONTENT_FILE_PREFIX,
)

load_dotenv()

DEFAULT_HOTEL_ID = "39676544"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Error: {name} is required.", file=sys.stderr)
        sys.exit(1)
    return value


def build_static_content_url(base_url: str, hotel_id: str) -> str:
    path = API_PATH_STATIC_CONTENT.format(hotel_id=hotel_id)
    return f"{base_url.rstrip('/')}{path}"


def build_reviews_url(base_url: str, hotel_id: str) -> str:
    path = API_PATH_AGGREGATED_REVIEWS.format(hotel_id=hotel_id)
    return f"{base_url.rstrip('/')}{path}"


def raw_hash_id(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def wrap_record(raw_json: Any) -> dict[str, Any]:
    return {
        "raw_json": raw_json,
        "raw_hash_id": raw_hash_id(raw_json),
    }


def output_file_path(output_dir: Path, prefix: str, run_date: date) -> Path:
    return output_dir / f"{prefix}_{run_date.isoformat()}.json"


def load_output_file(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        print(f"Warning: could not parse {path}: {error}. Starting fresh.", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        print(f"Warning: {path} is not a JSON object. Starting fresh.", file=sys.stderr)
        return {}

    return data


def merge_output_records(
    existing: dict[str, dict[str, Any]],
    new_records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = dict(existing)
    merged.update(new_records)
    return merged


def write_output_file(path: Path, records: dict[str, dict[str, Any]]) -> tuple[int, int, int]:
    existing = load_output_file(path)
    merged = merge_output_records(existing, records)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    updated_count = len(existing.keys() & records.keys())
    added_count = len(records.keys() - existing.keys())
    return len(merged), updated_count, added_count


def parse_hotel_ids(argv: list[str]) -> list[str]:
    if not argv:
        return [DEFAULT_HOTEL_ID]

    hotel_ids: list[str] = []
    for arg in argv:
        hotel_ids.extend(part.strip() for part in arg.split(",") if part.strip())
    return hotel_ids


def fetch_json(session: requests.Session, url: str, headers: dict[str, str]) -> Any:
    response = session.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def summarize_hotel(static_payload: dict[str, Any]) -> str:
    results = static_payload.get("results") or []
    if not results:
        return "N/A"

    first_result = results[0]
    hotel_data = (first_result.get("data") or [{}])[0]
    name = hotel_data.get("name", "Unknown")
    star_rating = hotel_data.get("starRating", "N/A")
    city = (
        hotel_data.get("contact", {})
        .get("address", {})
        .get("city", {})
        .get("name", "N/A")
    )
    return f'"{name}" ({star_rating}★) in {city}'


def run(hotel_ids: list[str]) -> None:
    bearer_token = require_env("TRAVCLAN_BEARER_TOKEN")
    static_content_base_url = require_env("TRAVCLAN_STATIC_CONTENT_BASE_URL")
    reviews_base_url = require_env("TRAVCLAN_REVIEWS_BASE_URL")
    internal_api_token = require_env("TRAVCLAN_INTERNAL_API_TOKEN")
    member_code = require_env("TRAVCLAN_MEMBER_CODE")

    output_enabled = env_bool("OUTPUT_ENABLED", default=True)
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    run_date = date.today()

    static_output_path = output_file_path(output_dir, STATIC_CONTENT_FILE_PREFIX, run_date)
    reviews_output_path = output_file_path(output_dir, REVIEWS_CONTENT_FILE_PREFIX, run_date)

    static_records: dict[str, dict[str, Any]] = {}
    reviews_records: dict[str, dict[str, Any]] = {}

    static_headers = {
        **DEFAULT_STATIC_CONTENT_HEADERS,
        "authorization": f"Bearer {bearer_token}",
    }
    reviews_headers = {
        **DEFAULT_REVIEWS_HEADERS,
        "internal-api-token": internal_api_token,
        "memberCode": member_code,
    }

    print(f"\nStarting bulk ETL: fetching static content for {len(hotel_ids)} hotels...")
    if output_enabled:
        print(f"Output enabled. Writing to:\n  - {static_output_path}\n  - {reviews_output_path}")
    else:
        print("Output disabled (OUTPUT_ENABLED=false).")

    with requests.Session() as session:
        for index, hotel_id in enumerate(hotel_ids, start=1):
            print("\n--------------------------------------------")
            print(f"[{index}/{len(hotel_ids)}] Ingesting hotel ID: {hotel_id}...")

            try:
                static_url = build_static_content_url(static_content_base_url, hotel_id)
                print(f"Calling static content API: {static_url}")
                static_payload = fetch_json(session, static_url, static_headers)

                results = static_payload.get("results")
                if not results:
                    print(f"Empty or missing results array for hotel ID: {hotel_id}")
                    continue

                print(f"Extracted hotel: {summarize_hotel(static_payload)}")
                static_records[hotel_id] = wrap_record(static_payload)

                reviews_url = build_reviews_url(reviews_base_url, hotel_id)
                print(f"Fetching reviews from API: {reviews_url}")
                try:
                    reviews_payload = fetch_json(session, reviews_url, reviews_headers)
                    if reviews_payload.get("results") is None:
                        print("  └─ No reviews results found in the API response.")
                    else:
                        reviews_records[hotel_id] = wrap_record(reviews_payload)
                        print("  └─ Reviews fetched successfully.")
                except requests.RequestException as reviews_error:
                    response = getattr(reviews_error, "response", None)
                    detail = response.text if response is not None else str(reviews_error)
                    print(f"  └─ Failed to fetch reviews: {detail}", file=sys.stderr)

                print(f"Ingested successfully for hotel ID: {hotel_id}")
            except requests.RequestException as error:
                response = getattr(error, "response", None)
                detail = response.text if response is not None else str(error)
                print(f"ETL error for hotel {hotel_id}: {detail}", file=sys.stderr)

    if output_enabled:
        static_total, static_updated, static_added = write_output_file(
            static_output_path, static_records
        )
        reviews_total, reviews_updated, reviews_added = write_output_file(
            reviews_output_path, reviews_records
        )
        print(
            f"\nMerged static content into {static_output_path}: "
            f"{static_added} added, {static_updated} updated, {static_total} total"
        )
        print(
            f"Merged reviews into {reviews_output_path}: "
            f"{reviews_added} added, {reviews_updated} updated, {reviews_total} total"
        )

    print("\nDone!\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Travclan hotel static content and aggregated reviews."
    )
    parser.add_argument(
        "hotel_ids",
        nargs="*",
        help="Hotel IDs (space or comma separated). Defaults to 39676544.",
    )
    args = parser.parse_args()
    run(parse_hotel_ids(args.hotel_ids))


if __name__ == "__main__":
    main()
