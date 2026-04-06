from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dashboard.app.search_service import (
    build_filter_expression,
    map_sort_option,
    perform_search,
)


@dataclass
class SearchSpyClient:
    last_call: dict[str, Any] | None = None

    def search_documents(
        self,
        query: str,
        *,
        filter_expression: str | None = None,
        sort: list[str] | None = None,
        offset: int = 0,
        limit: int = 20,
        facets: list[str] | None = None,
    ) -> dict[str, Any]:
        self.last_call = {
            "query": query,
            "filter_expression": filter_expression,
            "sort": sort,
            "offset": offset,
            "limit": limit,
            "facets": facets,
        }
        return {
            "hits": [{"id": "listing-1"}],
            "estimatedTotalHits": 1,
            "facetDistribution": {"source": {"airbnb": 1}},
        }


def test_empty_query_returns_first_page():
    client = SearchSpyClient()

    result = perform_search(
        client=client,
        query="",
        facet_filters={},
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    assert result["page"] == 1
    assert result["total_hits"] == 1
    assert result["results"] == [{"id": "listing-1"}]


def test_text_query_passed_to_search_engine():
    client = SearchSpyClient()

    perform_search(
        client=client,
        query="casita todos santos",
        facet_filters={},
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    assert client.last_call is not None
    assert client.last_call["query"] == "casita todos santos"


def test_multiple_facets_build_correct_filter_expression():
    expression = build_filter_expression(
        {
            "source": ["airbnb", "craigslist"],
            "price_bucket": ["<1000"],
            "has_photos": ["true"],
        }
    )

    assert expression is not None
    assert '(source = "airbnb" OR source = "craigslist")' in expression
    assert 'price_bucket = "<1000"' in expression
    assert "has_photos = true" in expression


def test_sort_option_maps_to_search_sort():
    assert map_sort_option("price_asc") == ["price_usd:asc"]
    assert map_sort_option("price_desc") == ["price_usd:desc"]
    assert map_sort_option("recent") == ["scraped:desc"]
    assert map_sort_option("relevance") is None


def test_pagination_offsets_are_correct():
    client = SearchSpyClient()

    perform_search(
        client=client,
        query="",
        facet_filters={},
        sort_option="relevance",
        page=3,
        per_page=25,
    )

    assert client.last_call is not None
    assert client.last_call["offset"] == 50
    assert client.last_call["limit"] == 25
