# Testing Instructions

This document covers how to run and verify every layer of the Todos Santos Rentals project —
scraper unit tests, dashboard ingestion/search tests, end-to-end smoke checks, and the
automated daily pipeline.

> **Runtime note:** Tests that import FastAPI (`fastapi.testclient`) must run inside the
> Podman container. Tests that only import the pure Python ingestion/search layers can run
> with the system Python, though running everything via Podman is recommended for consistency.

---

## Quick Reference

| Layer | Command | Container? |
|---|---|---|
| **Full suite (recommended)** | `podman compose run --rm --remove-orphans dashboard-api python -m pytest dashboard/tests/ -v` | Yes |
| Scraper unit tests only | `python -m pytest test_rental_search.py -v` (run from `scraper/` dir) | No |
| Dashboard unit tests (no FastAPI) | `python -m pytest dashboard/tests/test_phase2_ingestion.py dashboard/tests/test_phase3_indexing.py -v` | No |
| Live health check | `Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing` | Stack running |
| Public URL check | `Invoke-WebRequest -Uri https://rentals.performantlabs.com/health -UseBasicParsing` | Tunnel running |

---

## 1. Running the Full Test Suite

The recommended way to run all tests. This runs inside the dashboard container where all
dependencies (FastAPI, Meilisearch client, Jinja2) are installed.

```powershell
podman compose run --rm --remove-orphans dashboard-api python -m pytest dashboard/tests/ -v
```

**Expected:** 59 passed, 2 skipped, 0 failed.

> **Known issue:** `podman compose run` may exit with code 1 even when all tests pass.
> This is caused by Podman's Docker Desktop wrapper emitting an "orphan containers" warning
> to stderr, which PowerShell treats as a NativeCommandError. The exit code from pytest
> itself is 0. Check the last line of output (`X passed, Y skipped`) to confirm test results —
> do **not** rely on the shell exit code alone when running via `podman compose run`.
> Adding `--remove-orphans` reduces but may not eliminate this warning.

The 2 skipped tests are:
- `test_ingestion_handles_real_scraper_output` — skipped if no `rentals/` folders exist
- `test_scraper_cli_flags` — skipped if `litellm` is not installed in the container

---

## 2. Test Files and Coverage

### Scraper Tests

| File | What's Tested |
|---|---|
| `scraper/test_rental_search.py` | `normalise()`, `_parse_price_usd()`, `merge_listings()`, `generate_listing_html()`, `scrape_airbnb_local()`, `fetch_photos()`, `save_listing_folder()`, `update_listing_folder()`, `_scan_existing()` |

```powershell
# Must be run from the scraper/ directory
Set-Location scraper
python -m pytest test_rental_search.py -v
```

**Expected:** 147 passed.

### Dashboard Tests — Ingestion & Indexing

| File | What's Tested |
|---|---|
| `test_phase2_ingestion.py` | Folder discovery, `info.json` parsing, stable ID generation, camelCase/snake_case price fields, price bucket computation, idempotent upsert |
| `test_phase3_indexing.py` | Meilisearch index creation, settings, upsert, full-reindex, idempotency |
| `test_phase4_search.py` | Query → Meilisearch mapping, facet filter expressions, sort, pagination |
| `test_phase6_ingest_runner.py` | CLI flag parsing, lock-file concurrency guard, fatal failure exit code |
| `test_phase6_operations_integration.py` | End-to-end: scrape artifact → ingest → search index flow (mocked) |
| `test_ingestion_schema_regression.py` | Ingests real `rentals/*/info.json` files to guard against schema drift between the scraper and ingestion pipeline |

### Dashboard Tests — API & UI

| File | What's Tested |
|---|---|
| `test_phase1_app.py` | App starts, `/health` returns 200 |
| `test_phase4_api_integration.py` | `/api/search` contract: query, filters, sort, pagination params → Meilisearch calls |
| `test_phase5_htmx_integration.py` | HTMX partial responses, URL state roundtrip, facet selection |
| `test_phase5_ui.py` | Listing card rendering, facet counts, empty state message, static `listing.html` serving |
| `test_phase7_quality.py` | Response shape, error handling, request-ID propagation |
| `test_phase7_release_integration.py` | Release smoke: health check, search error UI, core user flow |

### New Feature Tests

| File | What's Tested |
|---|---|
| `test_new_features.py` | **16 tests** covering all features added during the automation and gallery work |

#### `test_new_features.py` — Breakdown

| Test Class | # Tests | Coverage |
|---|---|---|
| `TestPhotoUrlGeneration` | 5 | Photo URLs populated from `localPhotos`, empty array when no photos, forward slashes enforced (no Windows backslashes), `has_photos` boolean accuracy |
| `TestLastRunTime` | 4 | Returns `"never"` when `last_run.txt` missing, reads timestamp from file, strips whitespace, home page renders "Last updated: {timestamp}" |
| `TestPhotoGalleryRendering` | 3 | Card shows thumbnail when photos exist, `data-photos` attribute set for popup JS, no thumbnail markup when listing has no photos |
| `TestScraperCliFlags` | 1 | Verifies `search_with_litellm` and `fetch_url_via_jina` functions exist in the scraper module |

---

## 3. Running the Live Stack

### Start Services

```powershell
podman compose up -d dashboard-api meilisearch
```

### Ingest Listings

```powershell
podman compose run --rm dashboard-ingest python -m dashboard.app.ingest_runner --mode full
```

### Verify

```powershell
# Local health check (use Invoke-WebRequest — curl may hang on Windows)
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing | Select-Object -ExpandProperty Content
# Expected: {"status":"ok"}

# Meilisearch health
Invoke-WebRequest -Uri http://localhost:7700/health -UseBasicParsing | Select-Object -ExpandProperty Content
# Expected: {"status":"available"}

# Open dashboard
Start-Process http://localhost:8000
```

---

## 4. Cloudflare Tunnel Verification

The dashboard is publicly accessible via Cloudflare Tunnel at `https://rentals.performantlabs.com`.

```powershell
# Public health check
Invoke-WebRequest -Uri https://rentals.performantlabs.com/health -UseBasicParsing | Select-Object -ExpandProperty Content
# Expected: {"status":"ok"}
```

The tunnel token is stored in `.env` (not committed — listed in `.gitignore`).

To check the tunnel container:

```powershell
podman logs rental_collector-cloudflared-1 --tail 5
# Look for: "Registered tunnel connection connIndex=..."
```

---

## 5. Manual Smoke Checklist

After any significant change, verify these manually:

### Dashboard UI
- [ ] Homepage loads at `http://localhost:8000` with listing cards visible
- [ ] **"Last updated"** timestamp appears in the header below the title
- [ ] Search box filters results via HTMX partial reloads
- [ ] Facet checkboxes (source, price, location) narrow results; unchecking re-expands
- [ ] Pagination controls work across multiple pages
- [ ] Clicking "Open listing" opens `listing.html` in a new tab

### Photo Gallery
- [ ] Listings with photos show a thumbnail image at the top of the card
- [ ] Hovering over the thumbnail shows a popup with all photos
- [ ] Moving the mouse off the card dismisses the popup
- [ ] Listings without photos show no thumbnail (card looks normal)
- [ ] Photos are **unique per listing** — not the same image on every card

### Public Access
- [ ] `https://rentals.performantlabs.com` loads the full dashboard
- [ ] `https://rentals.performantlabs.com/health` returns `{"status":"ok"}`

---

## 6. Daily Automation Pipeline

The scraper runs automatically at 3:00 AM via Windows Task Scheduler.

### Manual Run

```powershell
powershell -File scripts/daily_update.ps1
```

### Verify Last Run

```powershell
# Check the log
Get-Content logs/daily_update.log -Tail 20

# Check the timestamp file
Get-Content rentals/last_run.txt

# Verify the dashboard shows the timestamp
$r = Invoke-WebRequest -Uri http://localhost:8000 -UseBasicParsing; ($r.Content -split "`n" | Select-String "Last updated")
```

### Task Scheduler

```powershell
# Check task status
Get-ScheduledTask -TaskName "RentalCollector_DailySearch" | Select-Object TaskName, State, LastRunTime, NextRunTime
```

> **Note:** `LastRunTime` and `NextRunTime` will be blank if the task has never triggered.
> After the first 3:00 AM run, both fields will populate. Use `powershell -File scripts/daily_update.ps1` for a manual trigger.

---

## 7. Scraper Modes

### Local LLM (default for automation)

Requires LM Studio running on port 1234 with the Gemma 4-26B model loaded.

```powershell
python scraper/rental_search.py --local --save --model openai/gemma-4-26B-A4B-it
```

### Scrape Only (no LLM)

Just Craigslist + TodosSantos.cc + local Airbnb folders. No AI needed.

```powershell
python scraper/rental_search.py --save --no-claude
```

### Claude API (cloud)

Requires `ANTHROPIC_API_KEY` environment variable.

```powershell
python scraper/rental_search.py --save
```

---

## 8. Nuclear Recovery

If the dashboard shows stale data, cached code, or ghost containers:

```powershell
# Full wipe and rebuild
podman compose down
Get-ChildItem -Path . -Filter __pycache__ -Recurse | Remove-Item -Force -Recurse
podman compose up -d --build

# Re-ingest
podman compose run --rm dashboard-ingest python -m dashboard.app.ingest_runner --mode full
```

---

## 9. Known Environment Notes

- **FastAPI / Meilisearch client** are only installed inside the Docker container — not in the system Python. Tests importing these must run via `podman compose run`.
- **Scraper tests must be run from the `scraper/` directory** — the test file imports `rental_search` directly as a module, which requires `scraper/` to be the working directory.
- **`curl` may hang on Windows PowerShell** — use `Invoke-WebRequest` instead for all HTTP health checks.
- **`podman compose run` exit code 1 is a known Podman wrapper issue** — it's triggered by an orphan container warning emitted to stderr by the Docker Desktop compatibility layer. The tests themselves all pass. Trust the pytest output (`X passed`), not the shell exit code.
- **Pyrefly lint warnings** about "Cannot find module `fastapi`" or "Cannot find module `rental_search`" are **false positives** — these resolve inside the container.
- **`logs/daily_update.log` and `LastRunTime` in Task Scheduler** will be absent until the task runs for the first time (3:00 AM). Use `powershell -File scripts/daily_update.ps1` for a manual trigger.
- All tests mock external services (Meilisearch, Airbnb CDN, Claude API, Jina Reader) — **no network access or API keys needed** to run the test suite.
- The 2 skipped tests will auto-enable when their prerequisites are met (listing folders exist, `litellm` installed).
