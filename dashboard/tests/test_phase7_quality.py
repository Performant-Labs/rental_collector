from fastapi.testclient import TestClient

from dashboard.app.main import _validate_query_params, app
from dashboard.app.search_service import perform_search


class SearchStubClient:
    def __init__(self):
        self.last_call = None

    def search_documents(self, query, *, filter_expression=None, sort=None, offset=0, limit=20, facets=None):
        self.last_call = {
            "query": query,
            "filter_expression": filter_expression,
            "sort": sort,
            "offset": offset,
            "limit": limit,
            "facets": facets,
        }
        return {"hits": [], "estimatedTotalHits": 0, "facetDistribution": {}}


client = TestClient(app)


def test_invalid_filter_values_are_rejected_or_ignored_safely():
    stub = SearchStubClient()

    result = perform_search(
        client=stub,
        query="  casa   mar  ",
        facet_filters={
            "source": ["airbnb", " "],
            "has_photos": ["maybe"],
            "location": ["x" * 120],
        },
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    assert result["query"] == "casa mar"
    assert result["selected_filters"]["source"] == ["airbnb"]
    assert result["selected_filters"]["has_photos"] == []
    assert "has_photos" in result["rejected_filters"]
    assert "location" in result["rejected_filters"]


def test_search_backend_timeout_returns_safe_error_state(monkeypatch):
    def boom(*args, **kwargs):
        raise TimeoutError("timeout")

    monkeypatch.setattr("dashboard.app.main.perform_search", boom)

    response = client.get("/api/search", params={"q": "casa"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"] == []
    assert "temporarily unavailable" in payload["error_message"].lower()


def test_unexpected_search_error_is_handled_without_500_template_crash(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("dashboard.app.main.perform_search", boom)

    response = client.get("/")

    assert response.status_code == 200
    assert "temporarily unavailable" in response.text.lower()


def test_query_param_validation_rules():
    safe_q, safe_sort, safe_page, safe_per_page, issues = _validate_query_params(
        q="query",
        sort="bad-value",
        page=0,
        per_page=999,
    )

    assert safe_q == "query"
    assert safe_sort == "relevance"
    assert safe_page == 1
    assert safe_per_page == 100
    assert issues == {
        "sort": "invalid_sort",
        "page": "out_of_range",
        "per_page": "out_of_range",
    }
