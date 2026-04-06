from __future__ import annotations

import re
from math import ceil
from typing import Any

from dashboard.app.meilisearch_index_client import MeilisearchIndexClient

FACET_FIELDS = (
    "source",
    "price_bucket",
    "location",
    "listing_type",
    "has_photos",
    "has_contact",
)

_SORT_MAP: dict[str, list[str] | None] = {
    "relevance": None,
    "price_asc": ["price_usd:asc"],
    "price_desc": ["price_usd:desc"],
    "recent": ["scraped:desc"],
}

MAX_QUERY_LENGTH = 120


def _escape_filter_value(value: str) -> str:
    return value.replace('"', '\\"')


def sanitize_query(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", (query or "").strip())
    return cleaned[:MAX_QUERY_LENGTH]


def sanitize_facet_filters(
    facet_filters: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    safe_filters: dict[str, list[str]] = {}
    rejected: dict[str, list[str]] = {}

    for field in FACET_FIELDS:
        values = facet_filters.get(field, [])
        cleaned_values = [value.strip() for value in values if value and value.strip()]
        accepted: list[str] = []
        rejected_values: list[str] = []

        for value in cleaned_values:
            if field in {"has_photos", "has_contact"}:
                lowered = value.lower()
                if lowered in {"true", "1", "yes", "on", "false", "0", "no", "off"}:
                    accepted.append(value)
                else:
                    rejected_values.append(value)
                continue

            if len(value) > 80:
                rejected_values.append(value)
                continue
            accepted.append(value)

        safe_filters[field] = accepted
        if rejected_values:
            rejected[field] = rejected_values

    return safe_filters, rejected


def _normalise_filter_value(field: str, value: str) -> str:
    cleaned = value.strip()
    if field in {"has_photos", "has_contact"}:
        lowered = cleaned.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return "true"
        if lowered in {"false", "0", "no", "off"}:
            return "false"
        return "false"
    return f'"{_escape_filter_value(cleaned)}"'


def build_filter_expression(facet_filters: dict[str, list[str]]) -> str | None:
    groups: list[str] = []

    for field in sorted(FACET_FIELDS):
        raw_values = facet_filters.get(field, [])
        cleaned_values = sorted({value.strip() for value in raw_values if value and value.strip()})
        if not cleaned_values:
            continue

        expressions = [f"{field} = {_normalise_filter_value(field, value)}" for value in cleaned_values]
        if len(expressions) == 1:
            groups.append(expressions[0])
        else:
            groups.append("(" + " OR ".join(expressions) + ")")

    if not groups:
        return None
    return " AND ".join(groups)


def map_sort_option(sort_option: str) -> list[str] | None:
    return _SORT_MAP.get(sort_option, _SORT_MAP["relevance"])


def perform_search(
    client: MeilisearchIndexClient,
    *,
    query: str,
    facet_filters: dict[str, list[str]],
    sort_option: str,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    safe_query = sanitize_query(query)
    safe_filters, rejected_filters = sanitize_facet_filters(facet_filters)
    safe_page = max(1, page)
    safe_per_page = max(1, min(per_page, 100))
    offset = (safe_page - 1) * safe_per_page

    filter_expression = build_filter_expression(safe_filters)
    sort = map_sort_option(sort_option)

    payload = client.search_documents(
        query=safe_query,
        filter_expression=filter_expression,
        sort=sort,
        offset=offset,
        limit=safe_per_page,
        facets=list(FACET_FIELDS),
    )

    hits = payload.get("hits", [])
    total_hits = payload.get("estimatedTotalHits")
    if total_hits is None:
        total_hits = payload.get("totalHits", len(hits))

    total_pages = ceil(total_hits / safe_per_page) if total_hits else 0

    return {
        "query": safe_query,
        "results": hits,
        "total_hits": total_hits,
        "page": safe_page,
        "per_page": safe_per_page,
        "total_pages": total_pages,
        "sort": sort_option,
        "facets": payload.get("facetDistribution", {}),
        "selected_filters": {field: safe_filters.get(field, []) for field in FACET_FIELDS},
        "rejected_filters": rejected_filters,
    }
