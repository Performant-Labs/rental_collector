from fastapi.testclient import TestClient

from dashboard.app.main import app

client = TestClient(app)


def _search_payload(**overrides):
    payload = {
        "query": "",
        "results": [
            {
                "id": "listing-1",
                "title": "Casita Sol",
                "location": "Centro",
                "source": "airbnb",
                "price_usd": 1200,
                "listing_path": "rentals/airbnb-01-casita/listing.html",
            }
        ],
        "total_hits": 1,
        "page": 1,
        "per_page": 20,
        "total_pages": 1,
        "sort": "relevance",
        "facets": {
            "source": {"airbnb": 1},
            "price_bucket": {"1000-1499": 1},
        },
        "selected_filters": {
            "source": ["airbnb"],
            "price_bucket": ["1000-1499"],
            "location": [],
            "listing_type": [],
            "has_photos": [],
            "has_contact": [],
        },
    }
    payload.update(overrides)
    return payload


def test_results_partial_renders_listing_cards(monkeypatch):
    monkeypatch.setattr("dashboard.app.main._run_search", lambda *args, **kwargs: _search_payload())

    response = client.get("/partials/results")

    assert response.status_code == 200
    assert "Casita Sol" in response.text
    assert "airbnb" in response.text


def test_facet_partial_renders_counts(monkeypatch):
    monkeypatch.setattr("dashboard.app.main._run_search", lambda *args, **kwargs: _search_payload())

    response = client.get("/partials/facets")

    assert response.status_code == 200
    assert "airbnb" in response.text
    assert ">1<" in response.text


def test_selected_filters_are_marked_active(monkeypatch):
    monkeypatch.setattr("dashboard.app.main._run_search", lambda *args, **kwargs: _search_payload())

    response = client.get("/partials/facets")

    assert response.status_code == 200
    assert "checked" in response.text
    assert 'data-facet-field="source"' in response.text
    assert 'data-facet-value="airbnb"' in response.text


def test_empty_state_message_renders(monkeypatch):
    monkeypatch.setattr(
        "dashboard.app.main._run_search",
        lambda *args, **kwargs: _search_payload(results=[], total_hits=0, facets={}),
    )

    response = client.get("/partials/results")

    assert response.status_code == 200
    assert "No results found for the current filters." in response.text


def test_listing_card_link_points_to_local_listing_html(monkeypatch):
    monkeypatch.setattr("dashboard.app.main._run_search", lambda *args, **kwargs: _search_payload())

    response = client.get("/partials/results")

    assert response.status_code == 200
    assert 'href="/rentals/airbnb-01-casita/listing.html"' in response.text


def test_static_rental_listing_files_are_served():
    import pathlib

    # Dynamically find any listing folder that contains listing.html
    rentals_dir = pathlib.Path("/app/rentals") if pathlib.Path("/app/rentals").exists() else pathlib.Path(__file__).resolve().parents[2] / "rentals"
    listing_htmls = list(rentals_dir.glob("*/listing.html"))
    if not listing_htmls:
        pytest.skip("No listing.html files in rentals/ — run scraper first")

    # Use the first one found
    rel_path = listing_htmls[0].relative_to(rentals_dir.parent)
    response = client.get(f"/{str(rel_path).replace(chr(92), '/')}")

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/html")
    assert "<!DOCTYPE html>" in response.text or "<html" in response.text.lower()
