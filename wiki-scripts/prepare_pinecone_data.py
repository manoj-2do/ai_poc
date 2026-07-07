#!/usr/bin/env python3
"""Prepare wiki book JSON for Pinecone: flatten pages, chunk text, write JSONL, optional upload."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

load_dotenv()

BOOK_ID_FROM_FILENAME = re.compile(r"^book_(\d+)_")

DESTINATION_BOOK_IDS: set[int] = set()

OPERATIONS_KEYWORDS = (
    "booking",
    "refund",
    "cancellation",
    "finance",
    "post-booking",
    "monitoring",
    "billing",
    "payment",
    "wallet",
    "invoice",
    "reissuance",
    "fare",
    "flight",
    "hotel-ops",
    "supply",
    "pbo",
)

PRODUCT_KEYWORDS = (
    "portal",
    "api",
    "cms",
    "listing",
    "travclan.com",
    "website",
    "canva",
    "landing-page",
    "firebase",
    "notification",
    "lms",
    "bms",
)

INTERNAL_KEYWORDS = (
    "onboarding",
    "hiring",
    "employee",
    "policy",
    "policies",
    "hr",
    "people",
    "welfare",
    "appraisal",
    "offboarding",
    "interview",
)


def get_env_str(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Error: {name} must be set in environment.", file=sys.stderr)
        sys.exit(1)
    return value


def get_env_int(name: str) -> int:
    value = get_env_str(name)
    try:
        return int(value)
    except ValueError:
        print(f"Error: {name} must be an integer.", file=sys.stderr)
        sys.exit(1)


def get_env_path(name: str) -> Path:
    return Path(get_env_str(name))


def normalize_pinecone_host(host: str) -> str:
    host = host.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def parse_book_id_from_filename(path: Path) -> int | None:
    """Extract book ID from filenames like book_2_h-user-onboarding....json."""
    match = BOOK_ID_FROM_FILENAME.match(path.name)
    if not match:
        return None
    return int(match.group(1))


def parse_book_ids(values: list[str]) -> list[int]:
    book_ids: list[int] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                book_ids.append(int(part))
    return book_ids


def get_wiki_token(explicit_token: str | None, *, required: bool = True) -> str | None:
    token = explicit_token or os.environ.get("WIKI_API_TOKEN")
    if not token and required:
        print("Error: WIKI_API_TOKEN required for shelf lookup.", file=sys.stderr)
        sys.exit(1)
    return token


def get_wiki_base_url(explicit_base_url: str | None, *, required: bool = True) -> str | None:
    base_url = explicit_base_url or os.environ.get("WIKI_API_BASE_URL")
    if not base_url and required:
        print("Error: WIKI_API_BASE_URL is required for shelf lookup.", file=sys.stderr)
        sys.exit(1)
    return base_url.rstrip("/") if base_url else None


def destination_shelf_keywords() -> list[str]:
    env_value = os.environ.get("DESTINATIONS_SHELF_KEYWORDS", "").strip()
    if not env_value:
        return []
    return [part.strip() for part in env_value.split(",") if part.strip()]


def load_destination_book_ids(
    *,
    base_url: str | None,
    token: str | None,
) -> set[int]:
    global DESTINATION_BOOK_IDS

    if not token:
        print(
            "Warning: WIKI_API_TOKEN not set; destination books will not be auto-detected.",
            file=sys.stderr,
        )
        DESTINATION_BOOK_IDS = set()
        return DESTINATION_BOOK_IDS

    keywords = destination_shelf_keywords()
    if not keywords:
        print(
            "Warning: DESTINATIONS_SHELF_KEYWORDS not set; destination books will not be auto-detected.",
            file=sys.stderr,
        )
        DESTINATION_BOOK_IDS = set()
        return DESTINATION_BOOK_IDS

    if not base_url:
        print(
            "Warning: WIKI_API_BASE_URL not set; destination books will not be auto-detected.",
            file=sys.stderr,
        )
        DESTINATION_BOOK_IDS = set()
        return DESTINATION_BOOK_IDS

    ids = resolve_shelf_book_ids(keywords, base_url=base_url, token=token)
    DESTINATION_BOOK_IDS = set(ids)
    print(
        f"Loaded {len(DESTINATION_BOOK_IDS)} destination book IDs from shelf keywords: "
        f"{', '.join(keywords)}",
        file=sys.stderr,
    )
    return DESTINATION_BOOK_IDS


def resolve_shelf_book_ids(
    keywords: list[str],
    *,
    base_url: str,
    token: str,
) -> list[int]:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        }
    )
    url = f"{base_url.rstrip('/')}/shelves"
    response = session.get(url, params={"count": 200, "offset": 0}, timeout=30)
    response.raise_for_status()
    shelves = response.json().get("data", [])

    shelf = None
    for candidate in shelves:
        name_lower = candidate["name"].lower()
        if all(keyword.lower() in name_lower for keyword in keywords):
            shelf = candidate
            break

    if not shelf:
        keywords_str = ", ".join(keywords)
        print(f"Error: no shelf found matching keywords: {keywords_str}", file=sys.stderr)
        sys.exit(1)

    detail_url = f"{base_url.rstrip('/')}/shelves/{shelf['id']}"
    detail = session.get(detail_url, timeout=30)
    detail.raise_for_status()
    books = detail.json().get("books", [])
    print(
        f"Found shelf '{shelf['name']}' with {len(books)} books.",
        file=sys.stderr,
    )
    return [book["id"] for book in books]


def classify_book(book: dict[str, Any]) -> str:
    if book["id"] in DESTINATION_BOOK_IDS:
        return "destinations"

    haystack = f"{book.get('name', '')} {book.get('slug', '')}".lower()

    if any(keyword in haystack for keyword in OPERATIONS_KEYWORDS):
        return "operations"
    if any(keyword in haystack for keyword in PRODUCT_KEYWORDS):
        return "product"
    if any(keyword in haystack for keyword in INTERNAL_KEYWORDS):
        return "internal"
    return "general"


def build_context_header(
    book: dict[str, Any],
    page: dict[str, Any],
    chapter: dict[str, Any] | None,
) -> str:
    lines = [f"Book: {book['name']}"]
    if chapter and chapter.get("name"):
        lines.append(f"Chapter: {chapter['name']}")
    lines.append(f"Page: {page['name']}")
    return "\n".join(lines)


def split_fixed_window(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def split_paragraphs(body: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_fixed_window(paragraph, chunk_size, chunk_overlap))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = paragraph

    if current:
        chunks.append(current.strip())

    if len(chunks) <= 1:
        return chunks

    overlapped: list[str] = [chunks[0]]
    for chunk in chunks[1:]:
        prev = overlapped[-1]
        overlap = prev[-chunk_overlap:] if chunk_overlap and len(prev) > chunk_overlap else ""
        if overlap and not chunk.startswith(overlap):
            merged = f"{overlap}{chunk}"
            overlapped.append(merged[: chunk_size + chunk_overlap])
        else:
            overlapped.append(chunk)
    return overlapped


def chunk_page_text(
    header: str,
    body: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    full_text = f"{header}\n\n{body.strip()}"
    if len(full_text) <= chunk_size:
        return [full_text]

    available = max(chunk_size - len(header) - 2, 200)
    body_chunks = split_paragraphs(body.strip(), available, chunk_overlap)
    return [f"{header}\n\n{part}".strip() for part in body_chunks if part.strip()]


def iter_pages(book: dict[str, Any]) -> Iterator[tuple[dict[str, Any] | None, dict[str, Any]]]:
    for page in book.get("pages", []):
        yield None, page
    for chapter in book.get("chapters", []):
        for page in chapter.get("pages", []):
            yield chapter, page


def build_metadata(
    book: dict[str, Any],
    page: dict[str, Any],
    chapter: dict[str, Any] | None,
    *,
    category: str,
    chunk_index: int,
    total_chunks: int,
    max_image_urls: int,
) -> dict[str, Any]:
    image_urls = page.get("image_urls") or []
    if len(image_urls) > max_image_urls:
        image_urls = image_urls[:max_image_urls]

    chapter_id = 0
    chapter_name = ""
    if chapter:
        chapter_id = chapter.get("id") or 0
        chapter_name = chapter.get("name") or ""

    return {
        "source": "bookstack",
        "category": category,
        "book_id": book["id"],
        "book_name": book["name"],
        "book_url": book.get("url", ""),
        "chapter_id": chapter_id,
        "chapter_name": chapter_name,
        "page_id": page["id"],
        "page_name": page["name"],
        "page_url": page.get("url", ""),
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "has_images": bool(image_urls),
        "image_urls": image_urls,
        "updated_at": page.get("updated_at") or book.get("updated_at") or "",
    }


def book_records_from_file(
    path: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    category_override: str | None,
    max_image_urls: int,
) -> list[dict[str, Any]]:
    book = json.loads(path.read_text(encoding="utf-8"))
    file_book_id = parse_book_id_from_filename(path)
    if file_book_id is not None and book.get("id") != file_book_id:
        print(
            f"Warning: book id mismatch in {path.name}: "
            f"filename={file_book_id}, json={book.get('id')}",
            file=sys.stderr,
        )
    category = category_override or classify_book(book)
    records: list[dict[str, Any]] = []

    for chapter, page in iter_pages(book):
        if page.get("draft") or not (page.get("text") or "").strip():
            continue

        header = build_context_header(book, page, chapter)
        chunks = chunk_page_text(
            header,
            page["text"],
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        total_chunks = len(chunks)

        for chunk_index, text in enumerate(chunks):
            records.append(
                {
                    "id": f"page_{page['id']}_chunk_{chunk_index}",
                    "text": text,
                    "metadata": build_metadata(
                        book,
                        page,
                        chapter,
                        category=category,
                        chunk_index=chunk_index,
                        total_chunks=total_chunks,
                        max_image_urls=max_image_urls,
                    ),
                }
            )

    return records


def select_book_files(
    input_dir: Path,
    *,
    all_books: bool,
    book_ids: list[int],
) -> list[Path]:
    if not input_dir.exists():
        print(f"Error: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(input_dir.glob("book_*.json"))
    if not files:
        print(f"Error: no book JSON files in {input_dir}", file=sys.stderr)
        sys.exit(1)

    if all_books or not book_ids:
        return files

    wanted = set(book_ids)
    selected = []
    for path in files:
        file_book_id = parse_book_id_from_filename(path)
        if file_book_id is None:
            print(f"Warning: skipping file with unexpected name: {path.name}", file=sys.stderr)
            continue
        if file_book_id in wanted:
            selected.append(path)
            wanted.discard(file_book_id)

    if wanted:
        missing = ", ".join(str(book_id) for book_id in sorted(wanted))
        print(f"Warning: book IDs not found in {input_dir}: {missing}", file=sys.stderr)

    if not selected:
        print("Error: no matching book files selected.", file=sys.stderr)
        sys.exit(1)

    return selected


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def build_manifest(
    records: list[dict[str, Any]],
    *,
    books_processed: int,
    book_files: list[Path],
    destination_book_ids: set[int],
) -> dict[str, Any]:
    page_ids = {record["metadata"]["page_id"] for record in records}
    category_counts = Counter(record["metadata"]["category"] for record in records)

    return {
        "books_processed": books_processed,
        "book_files": [path.name for path in book_files],
        "destination_book_ids": sorted(destination_book_ids),
        "pages_with_text": len(page_ids),
        "total_chunks": len(records),
        "pinecone_namespace": "default",
        "categories": dict(sorted(category_counts.items())),
    }


def upload_to_pinecone(records: list[dict[str, Any]], *, upsert_batch_size: int) -> None:
    api_key = get_env_str("PINECONE_API_KEY")
    pinecone_host = normalize_pinecone_host(get_env_str("PINECONE_HOST"))
    openai_key = get_env_str("OPENAI_API_KEY")
    embedding_model = get_env_str("EMBEDDING_MODEL")
    embedding_dimensions = get_env_int("EMBEDDING_DIMENSIONS")

    from openai import OpenAI
    from pinecone import Pinecone

    client = OpenAI(api_key=openai_key)
    pc = Pinecone(api_key=api_key)
    index = pc.Index(host=pinecone_host)

    print(
        f"Embedding with {embedding_model} (dimensions={embedding_dimensions}) "
        f"→ host '{pinecone_host}' (default namespace)",
        file=sys.stderr,
    )

    total_uploaded = 0
    for start in range(0, len(records), upsert_batch_size):
        batch = records[start : start + upsert_batch_size]
        texts = [item["text"] for item in batch]

        embed_response = client.embeddings.create(
            model=embedding_model,
            input=texts,
            dimensions=embedding_dimensions,
        )
        embeddings = [item.embedding for item in embed_response.data]

        vectors = []
        for item, values in zip(batch, embeddings):
            vectors.append(
                {
                    "id": item["id"],
                    "values": values,
                    "metadata": {
                        **item["metadata"],
                        "text": item["text"],
                    },
                }
            )

        index.upsert(vectors=vectors)
        total_uploaded += len(vectors)
        print(f"  Upserted {total_uploaded}/{len(records)} vectors...", file=sys.stderr)

    print(f"Uploaded {total_uploaded} vectors to '{pinecone_host}'.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory with book JSON files (default: PINECONE_INPUT_DIR env var)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for Pinecone prep output (default: PINECONE_OUTPUT_DIR env var)",
    )
    parser.add_argument(
        "--all-books",
        action="store_true",
        help="Process every book JSON in input-dir (default when no filters are passed)",
    )
    parser.add_argument(
        "--book-id",
        action="append",
        default=[],
        metavar="ID",
        help="Process specific book IDs (repeatable or comma-separated)",
    )
    parser.add_argument(
        "--shelf-keywords",
        nargs="+",
        metavar="WORD",
        help="Resolve shelf by keywords and process its books (requires WIKI_API_TOKEN)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Wiki API base URL for shelf lookup (default: WIKI_API_BASE_URL env var)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Wiki API token for shelf lookup (default: WIKI_API_TOKEN env var)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Max characters per chunk (default: PINECONE_CHUNK_SIZE env var)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help="Character overlap between chunks (default: PINECONE_CHUNK_OVERLAP env var)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Override auto category assignment for all processed books (stored in metadata)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Write local JSONL only, do not upload (default)",
    )
    parser.add_argument(
        "--upload",
        dest="dry_run",
        action="store_false",
        help="Embed and upsert vectors to Pinecone",
    )
    parser.set_defaults(dry_run=True)
    args = parser.parse_args()

    input_dir = args.input_dir or get_env_path("PINECONE_INPUT_DIR")
    output_dir = args.output_dir or get_env_path("PINECONE_OUTPUT_DIR")
    chunk_size = args.chunk_size if args.chunk_size is not None else get_env_int("PINECONE_CHUNK_SIZE")
    chunk_overlap = (
        args.chunk_overlap if args.chunk_overlap is not None else get_env_int("PINECONE_CHUNK_OVERLAP")
    )
    max_image_urls = get_env_int("PINECONE_MAX_IMAGE_URLS")
    upsert_batch_size = get_env_int("PINECONE_UPSERT_BATCH_SIZE")

    dry_run = args.dry_run
    book_ids = parse_book_ids(args.book_id)
    token = get_wiki_token(args.token, required=bool(args.shelf_keywords))
    base_url = get_wiki_base_url(args.base_url, required=bool(args.shelf_keywords))

    load_destination_book_ids(base_url=base_url, token=token)

    if args.shelf_keywords:
        if not token:
            print("Error: WIKI_API_TOKEN required for --shelf-keywords.", file=sys.stderr)
            sys.exit(1)
        if not base_url:
            print("Error: WIKI_API_BASE_URL required for --shelf-keywords.", file=sys.stderr)
            sys.exit(1)
        book_ids.extend(
            resolve_shelf_book_ids(
                args.shelf_keywords,
                base_url=base_url,
                token=token,
            )
        )

    book_ids = list(dict.fromkeys(book_ids))
    all_books = args.all_books or (not book_ids)

    book_files = select_book_files(
        input_dir,
        all_books=all_books,
        book_ids=book_ids,
    )

    records: list[dict[str, Any]] = []
    for path in book_files:
        records.extend(
            book_records_from_file(
                path,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                category_override=args.category,
                max_image_urls=max_image_urls,
            )
        )

    chunks_path = output_dir / "chunks.json"
    manifest_path = output_dir / "manifest.json"
    write_jsonl(chunks_path, records)

    manifest = build_manifest(
        records,
        books_processed=len(book_files),
        book_files=book_files,
        destination_book_ids=DESTINATION_BOOK_IDS,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Prepared {manifest['total_chunks']} chunks from "
        f"{manifest['pages_with_text']} pages across {manifest['books_processed']} books."
    )
    print(f"Wrote {chunks_path.resolve()}")
    print(f"Wrote {manifest_path.resolve()}")
    print(f"Categories: {manifest['categories']}")

    if dry_run:
        print("Dry run complete. Review chunks.jsonl, then rerun with --upload to push to Pinecone.")
        return

    upload_to_pinecone(records, upsert_batch_size=upsert_batch_size)


if __name__ == "__main__":
    main()
