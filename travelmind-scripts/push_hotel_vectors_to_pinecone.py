#!/usr/bin/env python3
"""Upload prepared hotel vectors from output/vectors to Pinecone."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from constants import (
    DEFAULT_OUTPUT_DIR,
    PINECONE_STATIC_CONTENT_NAMESPACE,
    VECTORS_DIR_NAME,
    VECTORS_MANIFEST_FILE,
)
from script_utils import get_env_int, normalize_pinecone_host, parse_hotel_ids, require_env


def vectors_dir(output_dir: Path) -> Path:
    return output_dir / VECTORS_DIR_NAME


def load_hotel_vector_files(vectors_root: Path, hotel_ids: list[str], *, all_hotels: bool) -> list[Path]:
    if not vectors_root.exists():
        print(
            f"Error: vectors directory not found ({vectors_root}). "
            "Run prepare_hotel_vectors.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    files = sorted(
        path
        for path in vectors_root.glob("*.json")
        if path.name != VECTORS_MANIFEST_FILE
    )
    if not files:
        print(
            f"Error: no hotel vector files found in {vectors_root}. "
            "Run prepare_hotel_vectors.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if all_hotels or not hotel_ids:
        return files

    wanted = set(hotel_ids)
    selected: list[Path] = []
    for path in files:
        if path.stem in wanted:
            selected.append(path)
            wanted.discard(path.stem)

    if wanted:
        missing = ", ".join(sorted(wanted))
        print(f"Warning: vector files not found for hotel IDs: {missing}", file=sys.stderr)

    if not selected:
        print("Error: no matching hotel vector files selected.", file=sys.stderr)
        sys.exit(1)

    return selected


def load_vectors_from_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        vectors = payload.get("vectors") or []
        if isinstance(vectors, list):
            return vectors
    raise ValueError(f"Invalid vectors payload in {path}")


def upsert_vectors(
    vectors: list[dict[str, Any]],
    *,
    namespace: str,
    upsert_batch_size: int,
) -> int:
    from pinecone import Pinecone

    api_key = require_env("PINECONE_API_KEY")
    pinecone_host = normalize_pinecone_host(require_env("PINECONE_HOST"))

    pc = Pinecone(api_key=api_key)
    index = pc.Index(host=pinecone_host)

    total_uploaded = 0
    for start in range(0, len(vectors), upsert_batch_size):
        batch = vectors[start : start + upsert_batch_size]
        index.upsert(vectors=batch, namespace=namespace)
        total_uploaded += len(batch)
        print(f"  Upserted {total_uploaded}/{len(vectors)} vectors...")

    return total_uploaded


def run(hotel_ids: list[str], *, all_hotels: bool, namespace: str) -> None:
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    vectors_root = vectors_dir(output_dir)
    upsert_batch_size = get_env_int("PINECONE_UPSERT_BATCH_SIZE", default=100)

    hotel_files = load_hotel_vector_files(vectors_root, hotel_ids, all_hotels=all_hotels)

    print(f"\nUploading hotel vectors from {vectors_root}")
    print(f"Target Pinecone namespace: {namespace}")

    total_vectors = 0
    for index, path in enumerate(hotel_files, start=1):
        vectors = load_vectors_from_file(path)

        print("\n--------------------------------------------")
        print(f"[{index}/{len(hotel_files)}] Uploading {path.name}")
        print(f"  └─ {len(vectors)} vector(s)")

        if not vectors:
            print("  └─ Skipping: no vectors in file")
            continue

        uploaded = upsert_vectors(
            vectors,
            namespace=namespace,
            upsert_batch_size=upsert_batch_size,
        )
        total_vectors += uploaded
        print(f"  └─ Uploaded {uploaded} vector(s)")

    print(f"\nUploaded {total_vectors} vector(s) to namespace '{namespace}'.")
    print("\nDone!\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload prepared hotel vectors from output/vectors to Pinecone."
    )
    parser.add_argument(
        "hotel_ids",
        nargs="*",
        help="Hotel IDs to upload (space or comma separated). Defaults to all vector files.",
    )
    parser.add_argument(
        "--all",
        dest="all_hotels",
        action="store_true",
        help="Upload all hotel vector files.",
    )
    parser.add_argument(
        "--namespace",
        default=os.environ.get(
            "PINECONE_HOTEL_NAMESPACE",
            PINECONE_STATIC_CONTENT_NAMESPACE,
        ),
        help=f"Pinecone namespace (default: {PINECONE_STATIC_CONTENT_NAMESPACE}).",
    )
    args = parser.parse_args()

    hotel_ids = parse_hotel_ids(args.hotel_ids)
    run(hotel_ids, all_hotels=args.all_hotels or not hotel_ids, namespace=args.namespace)


if __name__ == "__main__":
    main()
