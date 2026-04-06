import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dashboard.app.indexing_commands import bootstrap_ingest_if_enabled
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient

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
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Todos Santos Rentals Dashboard"},
    )
