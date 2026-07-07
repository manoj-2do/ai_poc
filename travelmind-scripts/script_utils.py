"""Shared helpers for travelmind-scripts."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DATED_OUTPUT_PATTERN = re.compile(r"^(.+)_(\d{4}-\d{2}-\d{2})\.json$")


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


def get_env_int(name: str, default: int | None = None) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        if default is not None:
            return default
        print(f"Error: {name} is required.", file=sys.stderr)
        sys.exit(1)
    try:
        return int(value.strip())
    except ValueError:
        print(f"Error: {name} must be an integer.", file=sys.stderr)
        sys.exit(1)


def load_output_file(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        print(f"Warning: could not parse {path}: {error}.", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        print(f"Warning: {path} is not a JSON object.", file=sys.stderr)
        return {}

    return data


def dated_output_path(output_dir: Path, prefix: str, run_date: date) -> Path:
    return output_dir / f"{prefix}_{run_date.isoformat()}.json"


def find_dated_output_file(output_dir: Path, prefix: str, run_date: date | None = None) -> Path | None:
    if run_date is not None:
        path = dated_output_path(output_dir, prefix, run_date)
        return path if path.exists() else None

    matches: list[tuple[date, Path]] = []
    for path in output_dir.glob(f"{prefix}_*.json"):
        match = DATED_OUTPUT_PATTERN.match(path.name)
        if not match or match.group(1) != prefix:
            continue
        matches.append((date.fromisoformat(match.group(2)), path))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def parse_hotel_ids(argv: list[str], *, default: list[str] | None = None) -> list[str]:
    if not argv:
        return list(default or [])

    hotel_ids: list[str] = []
    for arg in argv:
        hotel_ids.extend(part.strip() for part in arg.split(",") if part.strip())
    return hotel_ids


def extract_hotel_doc(hotel_id: str, wrapped: dict[str, Any]) -> dict[str, Any] | None:
    raw_json = wrapped.get("raw_json") or {}
    results = raw_json.get("results") or []
    if not results:
        return None

    first_result = results[0]
    hotel_data = (first_result.get("data") or [{}])[0]
    if not hotel_data:
        return None

    return {
        "hotelId": str(hotel_id),
        "provider": first_result.get("provider"),
        "data": hotel_data,
    }


def extract_reviews_payload(wrapped: dict[str, Any] | None) -> dict[str, Any] | None:
    if not wrapped:
        return None
    raw_json = wrapped.get("raw_json") or {}
    results = raw_json.get("results")
    if results is None:
        return None
    return raw_json


def normalize_pinecone_host(host: str) -> str:
    host = host.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host
