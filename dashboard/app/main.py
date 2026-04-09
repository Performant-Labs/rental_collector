import json
import os
import uuid
from pathlib import Path
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.app.indexing_commands import bootstrap_ingest_if_enabled
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient
from dashboard.app.search_service import (
    FACET_FIELDS,
    perform_search,
    validate_query_params,
    fallback_search_payload,
)

BASE_DIR = Path(__file__).resolve().parent
from shared.config import REPO_ROOT, SOURCE_COLORS
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("dashboard.app")



app = FastAPI(title="Todos Santos Rentals Dashboard")

# Singleton Meilisearch client — created once, reused for all requests.
# Using a module‐level instance keeps connection pooling across requests.
_search_client = MeilisearchIndexClient.from_env()

# Serve static rental listing files
app.mount("/rentals", StaticFiles(directory=str(REPO_ROOT / "rentals"), html=True), name="rentals")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info("request_complete path=%s method=%s request_id=%s", request.url.path, request.method, request_id)
    return response


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

    bootstrap_ingest_if_enabled(enabled=True, client=_search_client)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _get_last_run_time() -> str:
    last_run_path = REPO_ROOT / "rentals" / "last_run.txt"
    if last_run_path.exists():
        try:
            return last_run_path.read_text(encoding="utf-8").strip()
        except Exception:
            return "unknown"
    return "never"


def _get_ingest_stats() -> dict:
    stats_path = REPO_ROOT / "rentals" / "last_ingest_stats.json"
    try:
        return json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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
            "last_run": _get_last_run_time(),
            "source_colors": SOURCE_COLORS,
            "ingest_stats": _get_ingest_stats(),
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



def _parse_facet_filters(request: Request) -> dict:
    facet_filters = {}
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
    safe_q, safe_sort, safe_page, safe_per_page, validation_issues = validate_query_params(
        q=q, sort=sort, page=page, per_page=per_page,
    )
    facet_filters = _parse_facet_filters(request)
    request_id = getattr(request.state, "request_id", "")
    try:
        result = perform_search(
            client=_search_client,
            query=safe_q,
            facet_filters=facet_filters,
            sort_option=safe_sort,
            page=safe_page,
            per_page=safe_per_page,
        )
        result["validation_issues"] = validation_issues
        result["error_message"] = ""
        result["request_id"] = request_id
        return result
    except TimeoutError:
        logger.warning("search_timeout request_id=%s", request_id)
        return fallback_search_payload(
            query=safe_q, sort=safe_sort, page=safe_page, per_page=safe_per_page,
            facet_filters=facet_filters, validation_issues=validation_issues,
            error_message="Search temporarily unavailable. Please retry.",
            request_id=request_id,
        )
    except Exception as e:
        logger.exception("search_unexpected_error request_id=%s", request_id)
        error_str = str(e)
        if "404" in error_str and ("index" in error_str.lower() or "not found" in error_str.lower()):
            friendly_message = "Search index not found. Run ingestion first with: docker compose run --rm dashboard-ingest python -m dashboard.app.ingest_runner"
        else:
            friendly_message = "Search temporarily unavailable. Please retry later."
        return fallback_search_payload(
            query=safe_q, sort=safe_sort, page=safe_page, per_page=safe_per_page,
            facet_filters=facet_filters, validation_issues=validation_issues,
            error_message=friendly_message, request_id=request_id,
        )


@app.get("/api/search")
def search_endpoint(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20,
):
    return _run_search(request, q=q, sort=sort, page=page, per_page=per_page)
