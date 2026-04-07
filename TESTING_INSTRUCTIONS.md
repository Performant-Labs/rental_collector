# Testing Instructions

This document covers how to run and verify every layer of the Todos Santos Rentals project —
scraper unit tests, dashboard ingestion/search tests, and manual smoke checks.

---

## Quick reference

| Layer | Command | Requires Docker? |
|---|---|---|
| Scraper unit tests | `python3 -m pytest scraper/test_rental_search.py -v` | No |
| Dashboard unit tests (no FastAPI) | `python3 -m pytest dashboard/tests/test_phase2_ingestion.py dashboard/tests/test_phase3_indexing.py dashboard/tests/test_phase4_search.py dashboard/tests/test_phase6_ingest_runner.py dashboard/tests/test_phase6_operations_integration.py dashboard/tests/test_ingestion_schema_regression.py -v` | No |
| Dashboard full suite (incl. FastAPI routes) | `docker compose run --rm dashboard-api python -m pytest dashboard/tests/ -v` | Yes |
| Live smoke check | `curl http://localhost:8000/health` | Yes (stack running) |

---

## 1. Scraper tests

These tests live in `scraper/test_rental_search.py` and run entirely offline — all network
and subprocess calls are mocked.

```bash
python3 -m pytest scraper/test_rental_search.py -v
```

**What is covered:**
- `normalise()` — canonical schema coercion for all sources
- `_parse_price_usd()` — USD/MXN extraction from free text
- `merge_listings()` — URL-based and title-based deduplication
- `generate_listing_html()` — correct source label, scraped date, CTA link, and photo block
- `scrape_airbnb_local()` — reading raw Airbnb `info.json` (handles `link` key, null `source`, null `scraped`)
- `_scan_existing()` — existing folder detection and index building
- `save_listing_folder()` / `update_listing_folder()` — folder write/update logic

---

## 2. Dashboard tests — without Docker

Several test modules only import the pure Python ingestion and search layers (no FastAPI),
so they run locally without the container.

```bash
python3 -m pytest \
  dashboard/tests/test_phase2_ingestion.py \
  dashboard/tests/test_phase3_indexing.py \
  dashboard/tests/test_phase4_search.py \
  dashboard/tests/test_phase6_ingest_runner.py \
  dashboard/tests/test_phase6_operations_integration.py \
  dashboard/tests/test_ingestion_schema_regression.py \
  -v
```

**What is covered:**

| File | Coverage |
|---|---|
| `test_phase2_ingestion.py` | Folder discovery, `info.json` parsing, stable ID generation, camelCase/snake_case price fields, price buckets, idempotent upsert |
| `test_phase3_indexing.py` | Meilisearch index creation, settings, upsert, full-reindex, idempotency |
| `test_phase4_search.py` | Query → Meilisearch mapping, facet filter expressions, sort, pagination |
| `test_phase6_ingest_runner.py` | CLI flag parsing, lock-file concurrency guard, fatal failure exit code |
| `test_phase6_operations_integration.py` | End-to-end: scrape artifact → ingest → search index flow (mocked) |
| `test_ingestion_schema_regression.py` | Ingests real `rentals/*/info.json` files to guard against schema drift |

> **Note:** `test_ingestion_schema_regression.py` reads actual listing folders from `rentals/`.
> It will be skipped automatically if no folders exist yet.

---

## 3. Dashboard tests — with Docker (full suite)

Tests that import `fastapi.testclient.TestClient` require the dashboard dependencies installed
in the container. Run the full suite via Docker Compose:

```bash
docker compose run --rm dashboard-api python -m pytest dashboard/tests/ -v
```

**Additional files covered by Docker run:**

| File | Coverage |
|---|---|
| `test_phase1_app.py` | App starts, `/health` returns 200 |
| `test_phase4_api_integration.py` | `/api/search` and `/partials/search` route contracts |
| `test_phase5_htmx_integration.py` | HTMX-specific response headers and partial rendering |
| `test_phase5_ui.py` | UI template structure, ARIA attributes, accessibility |
| `test_phase7_quality.py` | Response shape, error handling, request-ID propagation |
| `test_phase7_release_integration.py` | Release smoke: health check, search error UI, core user flow |

---

## 4. Running the full dashboard stack locally

```bash
# Start the API and Meilisearch
docker compose up -d dashboard-api meilisearch

# Ingest listing folders into the search index
docker compose run --rm dashboard-ingest

# Open in browser
open http://localhost:8000

# Health check
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Meilisearch health
curl http://localhost:7700/health
# Expected: {"status":"available"}
```

---

## 5. Manual smoke checklist

After any significant change to ingestion, routing, or templates, verify:

- [ ] `GET /health` → `{"status":"ok"}`
- [ ] Homepage loads at `http://localhost:8000` with listing cards visible
- [ ] Search box filters results as you type (HTMX partial reloads)
- [ ] Facet checkboxes (source, price, location) narrow results; unchecking re-expands them
- [ ] Pagination controls work across multiple pages
- [ ] Clicking a listing card opens `listing.html` in a new tab
- [ ] Each `listing.html` shows correct source label (e.g. "Airbnb"), scraped date in `YYYY-MM-DD` format, and a working "View on …" CTA button

---

## 6. Regenerating Airbnb listing HTML

If you update `generate_listing_html()` in `scraper/rental_search.py`, regenerate all
existing Airbnb static pages so they pick up the changes:

```bash
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scraper')
import rental_search as rs

rentals_dir = Path('rentals')
updated = 0
for folder in sorted(rentals_dir.glob('airbnb-*/')):
    info_path = folder / 'info.json'
    if not info_path.exists():
        continue
    raw = json.loads(info_path.read_text(encoding='utf-8'))
    local_photos = raw.get('localPhotos') or []
    html = rs.generate_listing_html({**raw, 'localPhotos': local_photos})
    (folder / 'listing.html').write_text(html, encoding='utf-8')
    updated += 1
    print(f'  ✓ {folder.name}')

print(f'Done — {updated} listing.html files regenerated.')
"
```

---

## 7. Adding a new Airbnb listing

1. Create a folder under `rentals/` following the naming convention `airbnb-{n}-{slug}-{price}usd/`
2. Add `info.json` with the listing data (see schema in `README.md`)
3. Run `python3 scraper/download_photos.py` to pull photos and rewrite `listing.html`
4. Run `docker compose run --rm dashboard-ingest` to add it to the search index
5. Verify it appears in the dashboard search results

---

## 8. Known environment notes

- Tests that need `fastapi` or `meilisearch-python` **must run inside the Docker container** — these packages are not installed in the system Python environment.
- Tests that only use stdlib + the `ingestion.py`/`search.py` modules run fine with the system Python (`python3`).
- All tests mock external services (Meilisearch, Airbnb CDN, Claude API) — no network access or API keys needed to run the test suite.
