#!/usr/bin/env python3
"""Fetch books, shelves, and full book content from the TravClan BookStack wiki API."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "http://wiki.travclan.com/api"
DEFAULT_SITE_URL = "http://wiki.travclan.com"
DEFAULT_PAGE_SIZE = 200

BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ol", "ul"}
)

PAGE_CONTENT_FIELDS = (
    "id",
    "book_id",
    "chapter_id",
    "name",
    "slug",
    "html",
    "markdown",
    "priority",
    "draft",
    "template",
    "created_at",
    "updated_at",
    "revision_count",
    "tags",
)


def get_token(explicit_token: str | None) -> str:
    token = explicit_token or os.environ.get("WIKI_API_TOKEN")
    if not token:
        print(
            "Error: API token required. Set WIKI_API_TOKEN or pass --token.",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def fetch_paginated(
    session: requests.Session,
    base_url: str,
    resource: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all records from a paginated BookStack list endpoint."""
    items: list[dict[str, Any]] = []
    offset = 0
    url = api_url(base_url, resource)
    query = dict(params or {})

    while True:
        query.update({"count": page_size, "offset": offset})
        response = session.get(url, params=query, timeout=30)
        response.raise_for_status()
        payload = response.json()

        batch = payload.get("data", [])
        if not isinstance(batch, list):
            raise ValueError(f"Unexpected response from {url}: missing 'data' list")

        items.extend(batch)
        total = payload.get("total", len(items))

        if len(items) >= total or not batch:
            break

        offset += len(batch)

    return items


def fetch_json(
    session: requests.Session,
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.get(api_url(base_url, path), params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected response from {path}: expected JSON object")
    return payload


def fetch_text_export(
    session: requests.Session,
    base_url: str,
    path: str,
) -> str | None:
    response = session.get(api_url(base_url, path), timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def is_top_level_page(page: dict[str, Any]) -> bool:
    chapter_id = page.get("chapter_id")
    return chapter_id in (None, 0, "0")


def pick_fields(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: data.get(field) for field in fields if field in data}


def site_url_from_base_url(base_url: str) -> str:
    site_url = os.environ.get("WIKI_SITE_URL", DEFAULT_SITE_URL).rstrip("/")
    if site_url:
        return site_url
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_url(url: str, base_url: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", url.strip())


class HtmlContentExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.text_parts: list[str] = []
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value for name, value in attrs if value is not None}
        if tag == "img" and "src" in attr_map:
            self._add_image(attr_map["src"])
        elif tag in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = html.unescape(data).strip()
        if text:
            self.text_parts.append(text)

    def _add_image(self, raw_url: str) -> None:
        absolute_url = normalize_url(raw_url, self.base_url)
        if absolute_url not in self.image_urls:
            self.image_urls.append(absolute_url)

    def result(self) -> tuple[str, list[str]]:
        text = " ".join(self.text_parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip(), self.image_urls


def extract_text_and_images(raw_html: str, base_url: str) -> tuple[str, list[str]]:
    if not raw_html:
        return "", []

    parser = HtmlContentExtractor(base_url)
    parser.feed(raw_html)
    return parser.result()


def build_book_url(site_url: str, book_slug: str) -> str:
    return f"{site_url.rstrip('/')}/books/{book_slug}"


def build_chapter_url(site_url: str, book_slug: str, chapter_slug: str) -> str:
    return f"{site_url.rstrip('/')}/books/{book_slug}/chapter/{chapter_slug}"


def build_page_url(
    site_url: str,
    book_slug: str,
    page_slug: str,
    *,
    chapter_slug: str | None = None,
) -> str:
    base = site_url.rstrip("/")
    if chapter_slug:
        return f"{base}/books/{book_slug}/chapter/{chapter_slug}/{page_slug}"
    return f"{base}/books/{book_slug}/page/{page_slug}"


def normalize_page_content(
    page: dict[str, Any],
    *,
    site_url: str,
    book_slug: str,
    chapter_slug: str | None = None,
) -> dict[str, Any]:
    raw_html = page.pop("html", "") or ""
    text, image_urls = extract_text_and_images(raw_html, site_url)

    page["text"] = text
    page["image_urls"] = image_urls
    page["url"] = build_page_url(
        site_url,
        book_slug,
        page["slug"],
        chapter_slug=chapter_slug,
    )

    if not page.get("markdown"):
        page.pop("markdown", None)

    return page


def normalize_book_content(book: dict[str, Any], site_url: str) -> dict[str, Any]:
    book_slug = book["slug"]
    book["url"] = build_book_url(site_url, book_slug)

    for chapter in book.get("chapters", []):
        chapter_slug = chapter.get("slug", "")
        if chapter_slug:
            chapter["url"] = build_chapter_url(site_url, book_slug, chapter_slug)
        chapter["pages"] = [
            normalize_page_content(
                page,
                site_url=site_url,
                book_slug=book_slug,
                chapter_slug=chapter_slug or None,
            )
            for page in chapter.get("pages", [])
        ]

    book["pages"] = [
        normalize_page_content(page, site_url=site_url, book_slug=book_slug)
        for page in book.get("pages", [])
    ]

    return book


def fetch_page_content(
    session: requests.Session,
    base_url: str,
    page_id: int,
    cache: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    if page_id in cache:
        return cache[page_id]

    page = fetch_json(session, base_url, f"pages/{page_id}")
    content = pick_fields(page, PAGE_CONTENT_FIELDS)
    cache[page_id] = content
    return content


def build_book_contents_from_api(
    session: requests.Session,
    base_url: str,
    book_id: int,
    page_cache: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (chapters_with_pages, top_level_pages) with full page content."""
    chapters_meta = fetch_paginated(
        session,
        base_url,
        "chapters",
        params={"filter[book_id]": book_id},
    )
    pages_meta = fetch_paginated(
        session,
        base_url,
        "pages",
        params={"filter[book_id]": book_id},
    )

    chapters: list[dict[str, Any]] = []
    chapter_page_ids: set[int] = set()

    for chapter_meta in sorted(chapters_meta, key=lambda item: item.get("priority", 0)):
        chapter = fetch_json(session, base_url, f"chapters/{chapter_meta['id']}")
        chapter_pages = []
        for page_stub in chapter.get("pages", []):
            page_id = page_stub["id"]
            chapter_page_ids.add(page_id)
            chapter_pages.append(fetch_page_content(session, base_url, page_id, page_cache))

        chapters.append(
            {
                "id": chapter.get("id"),
                "book_id": chapter.get("book_id"),
                "name": chapter.get("name"),
                "slug": chapter.get("slug"),
                "description": chapter.get("description", ""),
                "priority": chapter.get("priority"),
                "created_at": chapter.get("created_at"),
                "updated_at": chapter.get("updated_at"),
                "tags": chapter.get("tags", []),
                "pages": chapter_pages,
            }
        )

    top_level_pages = []
    for page_meta in sorted(pages_meta, key=lambda item: item.get("priority", 0)):
        if page_meta["id"] in chapter_page_ids:
            continue
        if not is_top_level_page(page_meta):
            continue
        top_level_pages.append(
            fetch_page_content(session, base_url, page_meta["id"], page_cache)
        )

    return chapters, top_level_pages


def build_book_contents_from_tree(
    contents: list[dict[str, Any]],
    session: requests.Session,
    base_url: str,
    page_cache: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build chapter/page tree when GET /books/{id} returns a contents array."""
    chapters: list[dict[str, Any]] = []
    top_level_pages: list[dict[str, Any]] = []

    for item in contents:
        item_type = item.get("type")
        if item_type == "chapter":
            chapter_pages = [
                fetch_page_content(session, base_url, page_stub["id"], page_cache)
                for page_stub in item.get("pages", [])
            ]
            chapters.append(
                {
                    "id": item.get("id"),
                    "book_id": item.get("book_id"),
                    "name": item.get("name"),
                    "slug": item.get("slug"),
                    "description": item.get("description", ""),
                    "priority": item.get("priority"),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "tags": item.get("tags", []),
                    "pages": chapter_pages,
                }
            )
        elif item_type == "page":
            top_level_pages.append(
                fetch_page_content(session, base_url, item["id"], page_cache)
            )

    return chapters, top_level_pages


def fetch_book(
    session: requests.Session,
    base_url: str,
    book_id: int,
    *,
    site_url: str,
    include_plaintext_export: bool = True,
    page_cache: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch a book and all page content inside it."""
    cache = page_cache if page_cache is not None else {}
    book = fetch_json(session, base_url, f"books/{book_id}")

    contents = book.get("contents")
    if isinstance(contents, list) and contents:
        chapters, top_level_pages = build_book_contents_from_tree(
            contents, session, base_url, cache
        )
    else:
        chapters, top_level_pages = build_book_contents_from_api(
            session, base_url, book_id, cache
        )

    result = {
        "id": book.get("id"),
        "name": book.get("name"),
        "slug": book.get("slug"),
        "description": book.get("description", ""),
        "created_at": book.get("created_at"),
        "updated_at": book.get("updated_at"),
        "created_by": book.get("created_by"),
        "updated_by": book.get("updated_by"),
        "owned_by": book.get("owned_by"),
        "tags": book.get("tags", []),
        "cover": book.get("cover"),
        "chapters": chapters,
        "pages": top_level_pages,
        "stats": {
            "chapter_count": len(chapters),
            "page_count": sum(len(chapter["pages"]) for chapter in chapters)
            + len(top_level_pages),
        },
    }

    if include_plaintext_export:
        plaintext = fetch_text_export(
            session, base_url, f"books/{book_id}/export/plaintext"
        )
        if plaintext is not None:
            result["export_plaintext"] = plaintext

    return normalize_book_content(result, site_url)


def find_shelf_by_keywords(
    shelves: list[dict[str, Any]],
    keywords: list[str],
) -> dict[str, Any] | None:
    for shelf in shelves:
        name_lower = shelf["name"].lower()
        if all(keyword.lower() in name_lower for keyword in keywords):
            return shelf
    return None


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def parse_book_ids(values: list[str]) -> list[int]:
    book_ids: list[int] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                book_ids.append(int(part))
    return book_ids


def fetch_all_book_ids(
    session: requests.Session,
    base_url: str,
    *,
    page_size: int,
) -> list[int]:
    books = fetch_paginated(session, base_url, "books", page_size=page_size)
    return [book["id"] for book in books]


def book_output_path(output_dir: Path, book: dict[str, Any]) -> Path:
    return output_dir / "books" / f"book_{book['id']}_{book['slug']}.json"


def fetch_books_content(
    session: requests.Session,
    base_url: str,
    book_ids: list[int],
    *,
    site_url: str,
    output_dir: Path,
    include_plaintext_export: bool,
    skip_existing: bool,
    force_fetch_ids: set[int] | None = None,
    write_stdout: bool,
) -> dict[str, Any]:
    page_cache: dict[int, dict[str, Any]] = {}
    books_full: list[dict[str, Any]] = []
    skipped = 0
    failed: list[dict[str, Any]] = []
    force_fetch = force_fetch_ids or set()

    total = len(book_ids)
    for index, book_id in enumerate(book_ids, start=1):
        if skip_existing and book_id not in force_fetch:
            existing = list((output_dir / "books").glob(f"book_{book_id}_*.json"))
            if existing:
                skipped += 1
                print(
                    f"[{index}/{total}] Skipping book {book_id} (already fetched).",
                    file=sys.stderr,
                )
                continue

        print(f"[{index}/{total}] Fetching book {book_id}...", file=sys.stderr)
        try:
            book = fetch_book(
                session,
                base_url,
                book_id,
                site_url=site_url,
                include_plaintext_export=include_plaintext_export,
                page_cache=page_cache,
            )
        except requests.RequestException as exc:
            print(f"  Failed book {book_id}: {exc}", file=sys.stderr)
            failed.append({"book_id": book_id, "error": str(exc)})
            continue

        books_full.append(book)

        if not write_stdout:
            save_json(book_output_path(output_dir, book), book)
            print(
                f"  Saved book {book_id} ({book['stats']['page_count']} pages).",
                file=sys.stderr,
            )

    result: dict[str, Any] = {
        "books": books_full,
        "stats": {
            "book_count": len(books_full),
            "page_count": sum(book["stats"]["page_count"] for book in books_full),
            "skipped": skipped,
            "failed": len(failed),
        },
    }
    if failed:
        result["errors"] = failed

    return result


def load_failed_book_ids(output_dir: Path) -> list[int]:
    path = output_dir / "books_full.json"
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    errors = data.get("errors", [])
    if not errors:
        print("No errors to retry in books_full.json.", file=sys.stderr)
        sys.exit(0)

    return [int(item["book_id"]) for item in errors]


def merge_retry_result(
    output_dir: Path,
    new_result: dict[str, Any],
) -> dict[str, Any]:
    path = output_dir / "books_full.json"
    with path.open(encoding="utf-8") as handle:
        previous = json.load(handle)

    succeeded_ids = {book["id"] for book in new_result.get("books", [])}

    merged_books = [
        book for book in previous.get("books", [])
        if book["id"] not in succeeded_ids
    ]
    merged_books.extend(new_result.get("books", []))

    merged_errors = [
        err for err in previous.get("errors", [])
        if err["book_id"] not in succeeded_ids
    ]
    merged_errors.extend(new_result.get("errors", []))

    result: dict[str, Any] = {
        "books": merged_books,
        "stats": {
            "book_count": len(merged_books),
            "page_count": sum(book["stats"]["page_count"] for book in merged_books),
            "skipped": previous.get("stats", {}).get("skipped", 0)
            + new_result["stats"].get("skipped", 0),
            "failed": len(merged_errors),
        },
    }
    if merged_errors:
        result["errors"] = merged_errors
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("WIKI_API_BASE_URL", DEFAULT_BASE_URL),
        help=f"Wiki API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="BookStack API token (default: WIKI_API_TOKEN env var)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Records per page (default: {DEFAULT_PAGE_SIZE})",
    )
    parser.add_argument(
        "--book-id",
        action="append",
        default=[],
        metavar="ID",
        help="Fetch full content for a book ID (repeatable, or comma-separated)",
    )
    parser.add_argument(
        "--all-books",
        action="store_true",
        help="Fetch full content for every book returned by /api/books",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip books whose output JSON file already exists",
    )
    parser.add_argument(
        "--shelf-keywords",
        nargs="+",
        metavar="WORD",
        help="Find a shelf whose name contains all keywords, then fetch every book in it",
    )
    parser.add_argument(
        "--no-plaintext-export",
        action="store_true",
        help="Skip fetching /books/{id}/export/plaintext for each book",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory to write JSON files (default: ./output)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of writing files",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only fetch shelf/book indexes (skip even if --book-id is omitted)",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry book IDs listed in <output-dir>/books_full.json errors",
    )
    args = parser.parse_args()

    token = get_token(args.token)
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        }
    )

    book_ids = parse_book_ids(args.book_id)

    if args.all_books:
        all_book_ids = fetch_all_book_ids(
            session,
            args.base_url,
            page_size=args.page_size,
        )
        print(f"Found {len(all_book_ids)} books from API.", file=sys.stderr)
        book_ids.extend(all_book_ids)

    if args.shelf_keywords:
        shelves = fetch_paginated(session, args.base_url, "shelves", page_size=args.page_size)
        shelf = find_shelf_by_keywords(shelves, args.shelf_keywords)
        if not shelf:
            keywords = ", ".join(args.shelf_keywords)
            print(f"Error: no shelf found matching keywords: {keywords}", file=sys.stderr)
            sys.exit(1)

        shelf_details = fetch_json(session, args.base_url, f"shelves/{shelf['id']}")
        shelf_book_ids = [book["id"] for book in shelf_details.get("books", [])]
        book_ids.extend(shelf_book_ids)
        print(
            f"Found shelf '{shelf['name']}' (ID: {shelf['id']}) with {len(shelf_book_ids)} books.",
            file=sys.stderr,
        )

    retry_book_ids: list[int] = []
    if args.retry_errors:
        retry_book_ids = load_failed_book_ids(args.output_dir)
        print(
            f"Retrying {len(retry_book_ids)} failed book(s) from books_full.json.",
            file=sys.stderr,
        )
        book_ids.extend(retry_book_ids)

    book_ids = list(dict.fromkeys(book_ids))
    include_plaintext = not args.no_plaintext_export
    site_url = site_url_from_base_url(args.base_url)

    if book_ids:
        result = fetch_books_content(
            session,
            args.base_url,
            book_ids,
            site_url=site_url,
            output_dir=args.output_dir,
            include_plaintext_export=include_plaintext,
            skip_existing=args.skip_existing,
            force_fetch_ids=set(retry_book_ids) if retry_book_ids else None,
            write_stdout=args.stdout,
        )

        if args.retry_errors:
            result = merge_retry_result(args.output_dir, result)

        if args.stdout:
            json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            return

        save_json(args.output_dir / "books_full.json", result)
        print(
            f"Fetched {result['stats']['book_count']} book(s), "
            f"{result['stats']['page_count']} page(s) total."
        )
        if result["stats"]["skipped"]:
            print(f"Skipped {result['stats']['skipped']} existing book(s).")
        if result["stats"]["failed"]:
            print(f"Failed {result['stats']['failed']} book(s). See books_full.json for details.")
        print(f"Wrote JSON to {args.output_dir.resolve()}")
        return

    if args.list_only or not book_ids:
        books = fetch_paginated(session, args.base_url, "books", page_size=args.page_size)
        shelves = fetch_paginated(session, args.base_url, "shelves", page_size=args.page_size)

        result = {
            "books": {"total": len(books), "data": books},
            "shelves": {"total": len(shelves), "data": shelves},
        }

        if args.stdout:
            json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            return

        save_json(args.output_dir / "books.json", {"total": len(books), "data": books})
        save_json(args.output_dir / "shelves.json", {"total": len(shelves), "data": shelves})
        save_json(args.output_dir / "wiki_data.json", result)

        print(f"Fetched {len(books)} books and {len(shelves)} shelves.")
        print(f"Wrote JSON to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
