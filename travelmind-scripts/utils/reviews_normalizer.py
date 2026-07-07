"""Normalize aggregated hotel reviews into a single searchable text chunk."""

from __future__ import annotations

import json
from typing import Any

GOOD_TO_KNOW_MIN_SCORE = 4.0


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class HotelsReviewsNormalizer:
    def normalize(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        results = doc.get("data") or doc.get("results") or {}
        hotel_id = doc.get("hotelId")
        hotel_name = doc.get("hotelName") or ""
        star_rating = float(doc.get("starRating") or 0)
        city = doc.get("city") or ""
        country = doc.get("country") or ""

        if not hotel_id:
            raise ValueError("Invalid reviews document: hotelId is required")

        hotel_id = str(hotel_id)
        raw_reviews = results.get("reviews") if isinstance(results.get("reviews"), list) else []
        good_to_know_lists = (
            results.get("goodToKnowLists") if isinstance(results.get("goodToKnowLists"), list) else []
        )
        highlight_lists = (
            results.get("highlightLists") if isinstance(results.get("highlightLists"), list) else []
        )

        first_review = raw_reviews[0] if raw_reviews else {}
        overall_rating = _as_number(first_review.get("rating"))
        total_reviews = _as_number(first_review.get("numberOfReviews"))

        positive_categories = []
        for review in raw_reviews:
            if review.get("sentiment") != "pos":
                continue
            positive_sentences = [
                sentence.get("text")
                for sentence in review.get("summarySentenceList") or []
                if sentence.get("sentiment") == "pos" and sentence.get("text")
            ]
            if not positive_sentences:
                continue
            positive_categories.append(
                {
                    "title": review.get("title") or "Category",
                    "score": _as_number(review.get("score")),
                    "count": _as_number(review.get("count")),
                    "sentences": positive_sentences,
                }
            )

        category_lines = []
        for category in positive_categories:
            score_str = ""
            if category["score"] is not None:
                score_str = f" ({category['score']}/5"
                if category["count"]:
                    score_str += f", {int(category['count'])} mentions"
                score_str += ")"
            sentences_str = "\n".join(f"  - {sentence}" for sentence in category["sentences"])
            category_lines.append(f"- **{category['title']}**{score_str}:\n{sentences_str}")
        categories_text = "\n".join(category_lines)

        good_to_know_entries = []
        for gtk_group in good_to_know_lists:
            for entry in gtk_group.get("goodToKnowList") or []:
                score = _as_number(entry.get("score"))
                if score is not None and score >= GOOD_TO_KNOW_MIN_SCORE:
                    good_to_know_entries.append(
                        {
                            "title": entry.get("title") or "Aspect",
                            "score": score,
                            "count": _as_number(entry.get("count")),
                            "tripType": gtk_group.get("tripType") or "all",
                        }
                    )

        good_to_know_map: dict[str, dict[str, Any]] = {}
        for entry in good_to_know_entries:
            existing = good_to_know_map.get(entry["title"])
            if not existing or entry["score"] > existing["score"]:
                good_to_know_map[entry["title"]] = entry
        good_to_know_deduped = sorted(good_to_know_map.values(), key=lambda item: item["score"], reverse=True)

        good_to_know_lines = []
        for entry in good_to_know_deduped:
            count_str = f", {int(entry['count'])} mentions" if entry.get("count") else ""
            good_to_know_lines.append(f"- **{entry['title']}**: {entry['score']}/5{count_str}")
        good_to_know_text = "\n".join(good_to_know_lines)

        positive_highlights: list[str] = []
        seen_highlights: set[str] = set()
        for highlight_group in highlight_lists:
            for highlight in highlight_group.get("highlightList") or []:
                text = highlight.get("text")
                if highlight.get("sentiment") == "pos" and text and text not in seen_highlights:
                    seen_highlights.add(text)
                    positive_highlights.append(text)
        highlights_text = "\n".join(f"- {highlight}" for highlight in positive_highlights)

        metadata: dict[str, Any] = {
            "hotelId": hotel_id,
            "hotelName": hotel_name,
            "starRating": star_rating,
            "chunkType": "reviews",
        }
        if overall_rating is not None:
            metadata["overallRating"] = overall_rating
        if total_reviews is not None:
            metadata["totalReviews"] = total_reviews

        location_str = ", ".join(part for part in (city, country) if part)
        anchor_header_parts = [
            (
                f"{hotel_name or 'This hotel'}"
                f"{f' is a {star_rating}-star property' if star_rating else ''}"
                f"{f' located in {location_str}' if location_str else ''}."
            )
        ]
        if overall_rating is not None and total_reviews is not None:
            anchor_header_parts.append(
                f"Overall guest rating: {overall_rating}/5 based on {int(total_reviews)} reviews."
            )
        anchor_header = " ".join(anchor_header_parts)

        reviews_chunk_text = "\n".join(
            part
            for part in [
                anchor_header,
                f"\n**What Guests Loved (Positive Category Reviews):**\n{categories_text}"
                if categories_text
                else "",
                f"\n**Highly Rated Aspects (Score 4.0+):**\n{good_to_know_text}" if good_to_know_text else "",
                f"\n**Positive Highlights:**\n{highlights_text}" if highlights_text else "",
            ]
            if part
        )

        if not categories_text and not good_to_know_text and not highlights_text:
            return []

        return [
            {
                "id": f"{hotel_id}_reviews",
                "text": reviews_chunk_text,
                "metadata": {
                    **metadata,
                    "text": reviews_chunk_text,
                    "images": json.dumps([]),
                },
                "images": [],
            }
        ]


_normalizer = HotelsReviewsNormalizer()


def normalize(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return _normalizer.normalize(doc)
