from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from dashboard.app.main import app


@dataclass
class ApiSearchSpyClient:
    calls: list[dict[str, Any]]

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
        self.calls.append(
            {
                "query": query,
                "filter_expression": filter_expression,
                "sort": sort,
                "offset": offset,
                "limit": limit,
                "facets": facets,
            }
        )
        return {
            "hits": [{"id": "listing-1", "title": "Casita"}],
            "estimatedTotalHits": 7,
            "facetDistribution": {
                "source": {"airbnb": 4, "craigslist": 3},
                "price_bucket": {"<1000": 2},
            },
        }


client = TestClient(app)


def test_api_search_endpoint_returns_expected_contract(monkeypatch):
    spy = ApiSearchSpyClient(calls=[])

    monkeypatch.setattr(
        "dashboard.app.main.MeilisearchIndexClient.from_env",
        lambda: spy,
    )

    response = client.get("/api/search")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) >= {
        "query",
        "results",
        "total_hits",
        "page",
        "per_page",
        "total_pages",
        "sort",
        "facets",
        "selected_filters",
    }
    assert payload["results"][0]["id"] == "listing-1"
    assert payload["total_hits"] == 7


def test_api_search_endpoint_with_facets_and_sort(monkeypatch):
    spy = ApiSearchSpyClient(calls=[])

    monkeypatch.setattr(
        "dashboard.app.main.MeilisearchIndexClient.from_env",
        lambda: spy,
    )

    response = client.get(
        "/api/search",
        params=[
            ("q", "casita"),
            ("sort", "price_desc"),
            ("source", "airbnb"),
            ("source", "craigslist"),
            ("has_photos", "true"),
        ],
    )

    assert response.status_code == 200
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["query"] == "casita"
    assert call["sort"] == ["price_usd:desc"]
    assert '(source = "airbnb" OR source = "craigslist")' in (call["filter_expression"] or "")
    assert "has_photos = true" in (call["filter_expression"] or "")


def test_api_search_endpoint_pagination_contract(monkeypatch):
    spy = ApiSearchSpyClient(calls=[])

    monkeypatch.setattr(
        "dashboard.app.main.MeilisearchIndexClient.from_env",
        lambda: spy,
    )

    response = client.get(
        "/api/search",
        params={"page": 3, "per_page": 15},
    )

    assert response.status_code == 200
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["offset"] == 30
    assert call["limit"] == 15

    payload = response.json()
    assert payload["page"] == 3
    assert payload["per_page"] == 15
