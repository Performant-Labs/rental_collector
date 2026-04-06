import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dashboard.app.indexing_commands import bootstrap_ingest_if_enabled
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient
from dashboard.app.search_service import FACET_FIELDS, perform_search

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Todos Santos Rentals Dashboard")


def _bootstrap_enabled() -> bool:
    return os.environ.get("DASHBOARD_BOOTSTRAP_INGEST", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@app.on_event("startup")
def startup_bootstrap_ingest() -> None:
    if not _bootstrap_enabled():
        return

    client = MeilisearchIndexClient.from_env()
    bootstrap_ingest_if_enabled(enabled=True, client=client)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    search = _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Todos Santos Rentals Dashboard",
            "search": search,
            "facet_fields": FACET_FIELDS,
        },
    )


@app.get("/partials/search", response_class=HTMLResponse)
def partial_search(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    search = _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
    return templates.TemplateResponse(
        request=request,
        name="_search_content.html",
        context={"search": search, "facet_fields": FACET_FIELDS},
    )


@app.get("/partials/results", response_class=HTMLResponse)
def partial_results(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    search = _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
    return templates.TemplateResponse(
        request=request,
        name="_results.html",
        context={"search": search},
    )


@app.get("/partials/facets", response_class=HTMLResponse)
def partial_facets(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    search = _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
    return templates.TemplateResponse(
        request=request,
        name="_facets.html",
        context={"search": search, "facet_fields": FACET_FIELDS},
    )


@app.get("/partials/pagination", response_class=HTMLResponse)
def partial_pagination(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    search = _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
    return templates.TemplateResponse(
        request=request,
        name="_pagination.html",
        context={"search": search},
    )


def _parse_facet_filters(request: Request) -> dict[str, list[str]]:
    facet_filters: dict[str, list[str]] = {}
    for field in FACET_FIELDS:
        facet_filters[field] = request.query_params.getlist(field)
    return facet_filters


def _run_search(
    request: Request,
    *,
    q: str,
    sort: str,
    page: int,
    per_page: int,
):
    facet_filters = _parse_facet_filters(request)
    client = MeilisearchIndexClient.from_env()
    try:
        return perform_search(
            client=client,
            query=q,
            facet_filters=facet_filters,
            sort_option=sort,
            page=page,
            per_page=per_page,
        )
    except Exception:
        safe_page = max(1, page)
        safe_per_page = max(1, min(per_page, 100))
        return {
            "query": q,
            "results": [],
            "total_hits": 0,
            "page": safe_page,
            "per_page": safe_per_page,
            "total_pages": 0,
            "sort": sort,
            "facets": {},
            "selected_filters": {field: facet_filters.get(field, []) for field in FACET_FIELDS},
        }


@app.get("/api/search")
def search_endpoint(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    return _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
