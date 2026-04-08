# Todos Santos Rentals

A local database of long-term rentals in Todos Santos, Baja California Sur, Mexico — under $2,000/month. Listings are scraped from multiple sources, normalized to a common format, and saved as browsable HTML cards alongside structured JSON for analysis.

---

## AI Guidance References

When implementing dashboard/search work, follow these guidance docs in `docs/ai_guidance/`:

- `docs/ai_guidance/search/MEILISEARCH_GUIDE.md`
- `docs/ai_guidance/data/INGESTION_PIPELINE_RULES.md`
- `docs/ai_guidance/frontend/HTMX_PATTERNS.md`
- `docs/ai_guidance/devops/DOCKER_COMPOSE_WORKFLOW.md`
- `docs/ai_guidance/python/PYTEST_BACKEND_TESTING.md`

General subtree and repository-wide guidance:

- `docs/ai_guidance/README.md`
- `docs/ai_guidance/NAMING.md`
- `docs/ai_guidance/technical_writing/documentation_guidance.md`

---

## Typical workflow

**Weekly search for new listings:**
```bash
python3 scraper/rental_search.py --diff   # search, save, and show what's new
```

**Browse a listing:**
Open any `rentals/{source}-*/listing.html` in a browser.

**After adding a new Airbnb listing manually:**
```bash
python3 scraper/download_photos.py        # pull photos from CDN, rewrite listing.html
```

**Analyze listings across sources:**
```python
import json, pathlib

listings = []
for f in pathlib.Path("rentals").glob("*-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"):
    listings.extend(json.loads(f.read_text()))

under_1k = [l for l in listings if l["price_usd"] and l["price_usd"] < 1000]
```

---

## Setup

### 1. Install Python dependencies

```bash
pip install anthropic requests beautifulsoup4
```

### 2. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add it to `~/.zshrc` (or `~/.bashrc`) to persist across sessions.

### 3. Confirm the Claude CLI is available

```bash
claude --version
```

If not found, install it:

```bash
npm install -g @anthropic-ai/claude-code
```

### 4. Dashboard dev (containerized)

```bash
# Start dashboard API + Meilisearch
docker compose up -d dashboard-api meilisearch

# Open dashboard
open http://localhost:8000

# Health check
curl http://localhost:8000/health
```

Run Phase 1 dashboard tests in the container:

```bash
docker compose run --rm dashboard-api python -m pytest dashboard/tests/test_phase1_app.py -v
```

---

## Scripts

### `scraper/rental_search.py` — find and save listings

```bash
# Print a combined report (uses Claude API + web search)
python3 scraper/rental_search.py

# Use the local claude CLI instead of the Python SDK
python3 scraper/rental_search.py --cli

# Scrape only — no Claude call, no API key needed
python3 scraper/rental_search.py --no-claude

# Save per-source JSON files + listing folders
python3 scraper/rental_search.py --save

# Save + show what's new or removed vs. the previous run
python3 scraper/rental_search.py --diff
```

Flags can be combined: `python3 scraper/rental_search.py --cli --diff`

**Sources searched:**

| Source | Method |
|---|---|
| Airbnb | Reads existing local folders in `rentals/` |
| Craigslist Baja Sur | Direct HTTP scrape |
| TodosSantos.cc | Direct HTTP scrape (classifieds, housing, rentals pages) |
| Claude web search | Claude API or CLI with `web_search` tool — hits Amy Rex, Facebook groups, local agencies, and anything else it can find |
| **WhatsApp** | `wa_import/convert_to_rentals.py` — converts scored messages from the WhatsApp group pipeline |

**Duplicate handling:** when a listing already has a folder on disk, it is skipped if the price is unchanged, or its `info.json` and `listing.html` are updated in place (photos preserved) if the price has changed.

---

### `wa_import/convert_to_rentals.py` — push WhatsApp listings into `rentals/`

Reads `wa_import/output/rentals.json` (produced by `4_find_rentals.py`) and converts scored WhatsApp messages into canonical rental listings, deduplicating repeat posts and copying media into listing folders.

```bash
# Dry run — print report only
python3 wa_import/convert_to_rentals.py

# Save dated JSON + listing folders
python3 wa_import/convert_to_rentals.py --save

# Save + show what's new vs. the previous run
python3 wa_import/convert_to_rentals.py --diff

# Raise the confidence bar (default is 15)
python3 wa_import/convert_to_rentals.py --diff --min-score 20
```

---

### `scraper/download_photos.py` — download Airbnb photos

Run this after adding new Airbnb listings manually to pull photos from the CDN into each listing folder and rewrite `listing.html` to use local paths.

```bash
python3 scraper/download_photos.py
```

Run from inside the project folder. Each listing folder gets up to 6 photos (`photo_01.jpg` … `photo_06.jpg`).

---

## What's in the box

```
Todos Santos Rentals/
├── scraper/
│   ├── rental_search.py          # Main search + scrape script
│   ├── download_photos.py        # Download Airbnb photos to local folders
│   └── test_rental_search.py     # Unit tests
├── wa_import/                     # WhatsApp message export pipeline
│   ├── 1_export_messages.py      # Export from ChatStorage.sqlite → output/messages.json
│   ├── 4_find_rentals.py         # Score messages → output/rentals.json
│   ├── convert_to_rentals.py     # Convert WA rentals → canonical schema in rentals/
│   ├── test_convert_to_rentals.py
│   ├── test_e2e_convert.py
│   └── README.md
├── dashboard/                     # Dashboard API + Meilisearch
└── rentals/
    ├── airbnb-01-studio-1339usd/       # One folder per listing
    │   ├── info.json                   # Normalized metadata
    │   ├── listing.html                # Rendered card (open in browser)
    │   ├── photo_01.jpg
    │   └── …
    ├── whatsapp-01-…/                  # Same structure for WhatsApp listings
    ├── craigslist-01-…/
    ├── airbnb-2026-04-05.json          # Per-source summary for analysis/diffing
    ├── whatsapp-2026-04-08.json
    ├── craigslist-2026-04-05.json
    └── …
```

Each listing — regardless of source — is stored in a **folder** and a **summary JSON file**:

- **Folder** (`{source}-{n}-{slug}-{price}usd/`) — for browsing. Open `listing.html` in any browser.
- **Summary JSON** (`{source}-YYYY-MM-DD.json`) — a flat array of all listings from that source on that date, for scripting, diffing, and analysis.

---

## Listing schema

Every `info.json` — across all sources — uses the same fields:

| Field | Type | Notes |
|---|---|---|
| `title` | string | Listing name |
| `source` | string | `airbnb` · `craigslist` · `todossantos` · `claude-api` · `claude-cli` |
| `price_usd` | integer \| null | Monthly price in USD; null if unknown |
| `bedrooms` | string \| null | e.g. `"1 BR · 2 beds · 1 bath"` |
| `location` | string | Neighborhood or area within Todos Santos |
| `url` | string \| null | Direct link to original listing |
| `contact` | string \| null | Email or phone if publicly listed |
| `description` | string | Full listing text |
| `amenities` | array | e.g. `["WiFi", "Kitchen", "AC"]`; `[]` if unavailable |
| `rating` | string \| null | e.g. `"4.78 (119 reviews)"` |
| `listing_type` | string \| null | e.g. `"Entire rental unit"` |
| `checkin` | string \| null | Date or policy |
| `checkout` | string \| null | Date or policy |
| `scraped` | string | ISO date the listing was collected (`YYYY-MM-DD`) |
| `localPhotos` | array | Filenames of downloaded photos, e.g. `["photo_01.jpg"]` |

MXN prices are converted to USD at **17.5 MXN/USD**. Listings over $2,000/month are excluded automatically.

---

## Running tests

```bash
python3 -m pytest scraper/test_rental_search.py -v
```

```bash
docker compose run --rm dashboard-api python -m pytest dashboard/tests/test_phase1_app.py -v
```

All network calls and subprocess calls are mocked — tests run offline with no API key required.
