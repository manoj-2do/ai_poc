"""Shared constants for travelmind-scripts."""

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"

STATIC_CONTENT_FILE_PREFIX = "STATIC_CONTENT"
REVIEWS_CONTENT_FILE_PREFIX = "REVIEWS_CONTENT"

VECTORS_DIR_NAME = "vectors"
VECTORS_MANIFEST_FILE = "manifest.json"
PINECONE_STATIC_CONTENT_NAMESPACE = "hotel-static-content"

API_PATH_STATIC_CONTENT = "/api/v1/hotels/{hotel_id}/static-content"
API_PATH_AGGREGATED_REVIEWS = "/api/v1/hotels/internal/{hotel_id}/aggregated-reviews/"

DEFAULT_STATIC_CONTENT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-GB,en;q=0.7",
    "authorization-mode": "AWSCognito",
    "origin": "https://www.travclan.com",
    "referer": "https://www.travclan.com/",
    "source": "website",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
}

DEFAULT_REVIEWS_HEADERS = {
    "source": "website",
}
