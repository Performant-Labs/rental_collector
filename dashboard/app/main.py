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
from dashboard.app.search_service import FACET_FIELDS, perform_search

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent  # dashboard/app -> dashboard -> repo root
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("dashboard.app")

ALLOWED_SORT_OPTIONS = {"relevance", "price_asc", "price_desc", "recent"}
MAX_PER_PAGE = 100
MIN_PER_PAGE = 1

app = FastAPI(title="Todos Santos Rentals Dashboard")

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

    client = MeilisearchIndexClient.from_env()
    bootstrap_ingest_if_enabled(enabled=True, client=client)


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


def _validate_query_params(
    *,
    q: str,
    sort: str,
    page: int,
    per_page: int,
) -> tuple[str, str, int, int, dict[str, str]]:
    issues: dict[str, str] = {}
    safe_q = q

    safe_sort = sort
    if safe_sort not in ALLOWED_SORT_OPTIONS:
        issues["sort"] = "invalid_sort"
        safe_sort = "relevance"

    safe_page = page
    if safe_page < 1:
        issues["page"] = "out_of_range"
        safe_page = 1

    safe_per_page = per_page
    if safe_per_page < MIN_PER_PAGE or safe_per_page > MAX_PER_PAGE:
        issues["per_page"] = "out_of_range"
        safe_per_page = max(MIN_PER_PAGE, min(per_page, MAX_PER_PAGE))

    return safe_q, safe_sort, safe_page, safe_per_page, issues


def _fallback_search_payload(
    *,
    request: Request,
    query: str,
    sort: str,
    page: int,
    per_page: int,
    facet_filters: dict[str, list[str]],
    validation_issues: dict[str, str],
    error_message: str,
) -> dict[str, object]:
    return {
        "query": query,
        "results": [],
        "total_hits": 0,
        "page": page,
        "per_page": per_page,
        "total_pages": 0,
        "sort": sort,
        "facets": {},
        "selected_filters": {field: facet_filters.get(field, []) for field in FACET_FIELDS},
        "rejected_filters": {},
        "validation_issues": validation_issues,
        "error_message": error_message,
        "request_id": getattr(request.state, "request_id", ""),
    }


def _run_search(
    request: Request,
    *,
    q: str,
    sort: str,
    page: int,
    per_page: int,
):
    safe_q, safe_sort, safe_page, safe_per_page, validation_issues = _validate_query_params(
        q=q,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    facet_filters = _parse_facet_filters(request)
    client = MeilisearchIndexClient.from_env()
    try:
        result = perform_search(
            client=client,
            query=safe_q,
            facet_filters=facet_filters,
            sort_option=safe_sort,
            page=safe_page,
            per_page=safe_per_page,
        )
        result["validation_issues"] = validation_issues
        result["error_message"] = ""
        result["request_id"] = getattr(request.state, "request_id", "")
        return result
    except TimeoutError:
        logger.warning("search_timeout request_id=%s", getattr(request.state, "request_id", ""))
        return _fallback_search_payload(
            request=request,
            query=safe_q,
            sort=safe_sort,
            page=safe_page,
            per_page=safe_per_page,
            facet_filters=facet_filters,
            validation_issues=validation_issues,
            error_message="Search temporarily unavailable. Please retry.",
        )
    except Exception as e:
        logger.exception("search_unexpected_error request_id=%s", getattr(request.state, "request_id", ""))
        error_str = str(e)
        if "404" in error_str and ("index" in error_str.lower() or "not found" in error_str.lower()):
            friendly_message = "Search index not found. Run ingestion first with: docker compose run --rm dashboard-ingest python -m dashboard.app.ingest_runner"
        else:
            friendly_message = "Search temporarily unavailable. Please retry later."
        return _fallback_search_payload(
            request=request,
            query=safe_q,
            sort=safe_sort,
            page=safe_page,
            per_page=safe_per_page,
            facet_filters=facet_filters,
            validation_issues=validation_issues,
            error_message=friendly_message,
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
