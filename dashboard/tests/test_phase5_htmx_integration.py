from fastapi.testclient import TestClient

from dashboard.app.main import app

client = TestClient(app)


def _search_payload(query="", selected_filters=None):
    if selected_filters is None:
        selected_filters = {
            "source": [],
            "price_bucket": [],
            "location": [],
            "listing_type": [],
            "has_photos": [],
            "has_contact": [],
        }

    return {
        "query": query,
        "results": [
            {
                "id": "listing-1",
                "title": "Casa Mar",
                "location": "Las Tunas",
                "source": "airbnb",
                "price_usd": 1400,
                "listing_path": "rentals/airbnb-01-casa-mar/listing.html",
            }
        ],
        "total_hits": 1,
        "page": 1,
        "per_page": 20,
        "total_pages": 1,
        "sort": "relevance",
        "facets": {"source": {"airbnb": 1}},
        "selected_filters": selected_filters,
    }


def test_htmx_results_partial_updates_from_search(monkeypatch):
    monkeypatch.setattr(
        "dashboard.app.main._run_search",
        lambda request, **kwargs: _search_payload(query=kwargs.get("q", "")),
    )

    response = client.get("/partials/search", params={"q": "casa"})

    assert response.status_code == 200
    assert "Casa Mar" in response.text
    assert 'id="results-panel"' in response.text


def test_htmx_facet_selection_updates_results_and_counts(monkeypatch):
    monkeypatch.setattr(
        "dashboard.app.main._run_search",
        lambda request, **kwargs: _search_payload(
            selected_filters={
                "source": ["airbnb"],
                "price_bucket": [],
                "location": [],
                "listing_type": [],
                "has_photos": [],
                "has_contact": [],
            }
        ),
    )

    response = client.get("/partials/search", params=[("source", "airbnb")])

    assert response.status_code == 200
    assert "airbnb" in response.text
    assert "checked" in response.text


def test_htmx_url_state_roundtrip_for_search_and_filters(monkeypatch):
    monkeypatch.setattr(
        "dashboard.app.main._run_search",
        lambda request, **kwargs: _search_payload(query=kwargs.get("q", "")),
    )

    response = client.get("/", params=[("q", "mar"), ("source", "airbnb")])

    assert response.status_code == 200
    assert 'hx-push-url="true"' in response.text
    assert 'name="q"' in response.text
    assert 'value="mar"' in response.text
    assert 'id="active-filters"' in response.text
