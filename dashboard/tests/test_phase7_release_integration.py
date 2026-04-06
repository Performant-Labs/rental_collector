from fastapi.testclient import TestClient

from dashboard.app.main import app


client = TestClient(app)


def _payload(query="", error_message=""):
    return {
        "query": query,
        "results": [
            {
                "id": "listing-1",
                "title": "Casa Luna",
                "location": "Centro",
                "source": "airbnb",
                "price_usd": 1500,
                "listing_path": "rentals/airbnb-01-casa-luna/listing.html",
            }
        ],
        "total_hits": 1,
        "page": 1,
        "per_page": 20,
        "total_pages": 1,
        "sort": "relevance",
        "facets": {"source": {"airbnb": 1}},
        "selected_filters": {
            "source": [],
            "price_bucket": [],
            "location": [],
            "listing_type": [],
            "has_photos": [],
            "has_contact": [],
        },
        "rejected_filters": {},
        "validation_issues": {},
        "error_message": error_message,
        "request_id": "req-123",
    }


def test_search_error_ui_and_api_fallback_behavior(monkeypatch):
    monkeypatch.setattr(
        "dashboard.app.main._run_search",
        lambda request, **kwargs: _payload(error_message="Search backend unavailable. Showing safe fallback state."),
    )

    ui_response = client.get("/partials/search")
    api_response = client.get("/api/search")

    assert ui_response.status_code == 200
    assert "Search backend unavailable" in ui_response.text
    assert api_response.status_code == 200
    assert "Search backend unavailable" in api_response.json()["error_message"]


def test_container_smoke_dashboard_and_meilisearch_health(monkeypatch):
    monkeypatch.setattr("dashboard.app.main._run_search", lambda request, **kwargs: _payload())

    health_response = client.get("/health", headers={"X-Request-ID": "smoke-1"})
    search_response = client.get("/api/search")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert health_response.headers.get("X-Request-ID") == "smoke-1"
    assert search_response.status_code == 200


def test_release_candidate_core_user_flow(monkeypatch):
    monkeypatch.setattr(
        "dashboard.app.main._run_search",
        lambda request, **kwargs: _payload(query=kwargs.get("q", "")),
    )

    home = client.get("/", params={"q": "luna"})
    partial = client.get("/partials/search", params={"q": "luna"})

    assert home.status_code == 200
    assert partial.status_code == 200
    assert 'hx-push-url="true"' in home.text
    assert 'hx-indicator="#search-loading"' in home.text
    assert 'role="status"' in home.text
    assert 'aria-live="polite"' in home.text
    assert 'for="q"' in home.text
    assert 'for="sort"' in home.text
    assert "Casa Luna" in partial.text
    assert 'href="/rentals/airbnb-01-casa-luna/listing.html"' in partial.text
    assert 'rel="noopener noreferrer"' in partial.text
