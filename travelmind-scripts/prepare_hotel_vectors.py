#!/usr/bin/env python3
"""Normalize hotel static content, create embeddings, and write vectors to output/vectors."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from constants import (
    DEFAULT_OUTPUT_DIR,
    REVIEWS_CONTENT_FILE_PREFIX,
    STATIC_CONTENT_FILE_PREFIX,
    VECTORS_DIR_NAME,
    VECTORS_MANIFEST_FILE,
)
from utils.hotel_static_normalizer import normalize as normalize_static
from utils.reviews_normalizer import normalize as normalize_reviews
from script_utils import (
    dated_output_path,
    env_bool,
    extract_hotel_doc,
    extract_reviews_payload,
    find_dated_output_file,
    get_env_int,
    load_output_file,
    parse_hotel_ids,
    require_env,
)


def vectors_dir(output_dir: Path) -> Path:
    return output_dir / VECTORS_DIR_NAME


def hotel_vector_path(vectors_root: Path, hotel_id: str) -> Path:
    return vectors_root / f"{hotel_id}.json"


def build_reviews_doc(
    hotel_id: str,
    reviews_payload: dict[str, Any],
    hotel_data: dict[str, Any],
) -> dict[str, Any]:
    address = (hotel_data.get("contact") or {}).get("address") or {}
    return {
        "hotelId": hotel_id,
        "hotelName": hotel_data.get("name") or "",
        "starRating": float(hotel_data.get("starRating") or 0),
        "city": (address.get("city") or {}).get("name") or "",
        "country": (address.get("country") or {}).get("name") or "",
        "results": reviews_payload.get("results") or {},
    }


def embed_texts(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=require_env("OPENAI_API_KEY"))
    model = require_env("EMBEDDING_MODEL")
    dimensions = get_env_int("EMBEDDING_DIMENSIONS")

    response = client.embeddings.create(
        model=model,
        input=texts,
        dimensions=dimensions,
    )
    return [item.embedding for item in response.data]


def build_vector_records(chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for chunk, values in zip(chunks, embeddings):
        records.append(
            {
                "id": chunk["id"],
                "values": values,
                "metadata": chunk["metadata"],
            }
        )
    return records


def write_hotel_vectors(path: Path, vectors: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(vectors, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_manifest(vectors_root: Path) -> dict[str, Any]:
    manifest_path = vectors_root / VECTORS_MANIFEST_FILE
    if not manifest_path.exists():
        return {"files": []}

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"files": []}
    return payload


def get_file_state(manifest: dict[str, Any], filename: str) -> dict[str, Any] | None:
    for entry in manifest.get("files") or []:
        if entry.get("file") == filename:
            return entry
    return None


def build_manifest(
    vectors_root: Path,
    *,
    file_states: dict[str, dict[str, Any]],
    previous_manifest: dict[str, Any],
) -> dict[str, Any]:
    total_vectors = 0
    files: list[dict[str, Any]] = []

    for path in sorted(vectors_root.glob("*.json")):
        if path.name == VECTORS_MANIFEST_FILE:
            continue

        vectors = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(vectors, list):
            continue

        vector_count = len(vectors)
        total_vectors += vector_count
        state = file_states.get(path.name) or get_file_state(previous_manifest, path.name) or {}
        files.append(
            {
                "file": path.name,
                "vector_count": vector_count,
                "static_hash_id": state.get("static_hash_id"),
                "reviews_hash_id": state.get("reviews_hash_id"),
            }
        )

    return {
        "files_processed": len(files),
        "total_vectors": total_vectors,
        "files": files,
    }


def run(
    hotel_ids: list[str],
    *,
    run_date: date | None,
    all_hotels: bool,
) -> None:
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    vectors_root = vectors_dir(output_dir)

    static_path = find_dated_output_file(output_dir, STATIC_CONTENT_FILE_PREFIX, run_date)
    if static_path is None:
        expected = dated_output_path(
            output_dir,
            STATIC_CONTENT_FILE_PREFIX,
            run_date or date.today(),
        )
        print(
            f"Error: static content file not found ({expected}). "
            "Run fetch_hotel_static_content.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    static_records = load_output_file(static_path)
    if not static_records:
        print(
            f"Error: static content file is empty ({static_path}). "
            "Run fetch_hotel_static_content.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    reviews_path = find_dated_output_file(output_dir, REVIEWS_CONTENT_FILE_PREFIX, run_date)
    reviews_records = load_output_file(reviews_path) if reviews_path else {}

    if all_hotels or not hotel_ids:
        selected_ids = list(static_records.keys())
    else:
        selected_ids = hotel_ids

    skip_unchanged = env_bool("SKIP_UNCHANGED_VECTORS", default=True)

    print(f"\nPreparing hotel vectors from {static_path}")
    if reviews_path:
        print(f"Reviews source: {reviews_path}")
    print(f"Writing vectors to: {vectors_root}")

    processed_files: list[Path] = []
    file_states: dict[str, dict[str, Any]] = {}
    manifest = load_manifest(vectors_root)

    for index, hotel_id in enumerate(selected_ids, start=1):
        print("\n--------------------------------------------")
        print(f"[{index}/{len(selected_ids)}] Processing hotel ID: {hotel_id}")

        wrapped = static_records.get(hotel_id)
        if not wrapped:
            print(f"  └─ Skipping: hotel ID not found in {static_path.name}")
            continue

        doc = extract_hotel_doc(hotel_id, wrapped)
        if not doc:
            print("  └─ Skipping: could not extract hotel data from static content")
            continue

        hotel_data = doc["data"]
        static_hash_id = wrapped.get("raw_hash_id") or ""

        output_path = hotel_vector_path(vectors_root, hotel_id)
        if skip_unchanged and output_path.exists():
            reviews_wrapped = reviews_records.get(hotel_id)
            reviews_hash_id = (reviews_wrapped or {}).get("raw_hash_id")
            existing_state = get_file_state(manifest, output_path.name)
            if (
                existing_state
                and existing_state.get("static_hash_id") == static_hash_id
                and existing_state.get("reviews_hash_id") == reviews_hash_id
            ):
                print("  └─ Skipping: vectors already up to date")
                processed_files.append(output_path)
                file_states[output_path.name] = {
                    "static_hash_id": static_hash_id,
                    "reviews_hash_id": reviews_hash_id,
                }
                continue

        chunks = normalize_static(doc)
        print(f"  └─ Created {len(chunks)} static content chunk(s)")

        reviews_wrapped = reviews_records.get(hotel_id)
        reviews_payload = extract_reviews_payload(reviews_wrapped)
        reviews_hash_id = (reviews_wrapped or {}).get("raw_hash_id")

        if reviews_payload:
            reviews_doc = build_reviews_doc(hotel_id, reviews_payload, hotel_data)
            review_chunks = normalize_reviews(reviews_doc)
            if review_chunks:
                chunks.extend(review_chunks)
                print(f"  └─ Added reviews chunk. Total chunks: {len(chunks)}")

        if not chunks:
            print("  └─ Skipping: no chunks generated")
            continue

        print("  └─ Generating embeddings via OpenAI...")
        embeddings = embed_texts([chunk["text"] for chunk in chunks])
        vectors = build_vector_records(chunks, embeddings)

        write_hotel_vectors(output_path, vectors)
        processed_files.append(output_path)
        file_states[output_path.name] = {
            "static_hash_id": static_hash_id,
            "reviews_hash_id": reviews_hash_id,
        }
        print(f"  └─ Wrote {len(vectors)} vector(s) to {output_path}")

    if not processed_files:
        print("\nNo hotel vectors were written.")
        return

    manifest = build_manifest(vectors_root, file_states=file_states, previous_manifest=manifest)
    manifest_path = vectors_root / VECTORS_MANIFEST_FILE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"\nPrepared {manifest['total_vectors']} vectors across "
        f"{manifest['files_processed']} file(s)."
    )
    print(f"Wrote manifest to {manifest_path}")
    print("\nDone!\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize hotel static content, embed chunks, and write vectors."
    )
    parser.add_argument(
        "hotel_ids",
        nargs="*",
        help="Hotel IDs to process (space or comma separated). Defaults to all hotels in static content file.",
    )
    parser.add_argument(
        "--date",
        dest="run_date",
        default=None,
        help="Use STATIC_CONTENT_YYYY-MM-DD.json for this date (default: latest or today).",
    )
    parser.add_argument(
        "--all",
        dest="all_hotels",
        action="store_true",
        help="Process all hotels in the static content file.",
    )
    args = parser.parse_args()

    run_date = date.fromisoformat(args.run_date) if args.run_date else None
    hotel_ids = parse_hotel_ids(args.hotel_ids)
    run(hotel_ids, run_date=run_date, all_hotels=args.all_hotels or not hotel_ids)


if __name__ == "__main__":
    main()
