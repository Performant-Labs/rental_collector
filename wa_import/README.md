# WhatsApp Export Pipeline (`wa_import/`)

This subfolder contains the WhatsApp message export and rental-detection pipeline, originally developed as a standalone project and brought into `Todos Santos Rentals` so its output can feed the canonical rental listing database.

---

## How it works

The pipeline is a numbered sequence of scripts. Run them in order when you have a fresh `ChatStorage.sqlite` export from the WhatsApp iOS app.

| Step | Script | What it does |
|---|---|---|
| 1 | `1_export_messages.py` | Reads `ChatStorage.sqlite` and writes `output/messages.json` + `output/messages.csv` |
| 2 | `2_download_media.py` | Downloads + decrypts media files into `output/media/` |
| 2b | `2b_retry_decrypt_failed.py` | Retries any media that failed decryption |
| 3 | `3_fetch_expired.mjs` | Fetches expired CDN URLs via Baileys/WhatsApp Web |
| 3 | `3_playwright_capture.mjs` | Playwright fallback for URLs that need a real browser |
| 3 | `3_smoke_test.mjs` | Quick sanity-check of the Playwright session |
| 4 | `4_find_rentals.py` | Scores all messages and writes `output/rentals.json` |
| 5 | `5_serve_viewer.py` | Local web viewer for `output/rentals.json` at http://localhost:9090 |

---

## Setup

### Data file

`ChatStorage.sqlite` is **not tracked in git** (it's ~100 MB). Place it alongside the scripts:

```
wa_import/
└── ChatStorage.sqlite    ← copy here from your iOS backup / WAExport location
```

Or symlink it:

```bash
ln -s /path/to/your/ChatStorage.sqlite wa_import/ChatStorage.sqlite
```

### Python dependencies

```bash
pip install better-sqlite3    # only for Node scripts; Python scripts use stdlib sqlite3
```

### Node dependencies (for steps 3+)

```bash
cd wa_import
npm install
```

---

## Running the pipeline

```bash
# Step 1 — export messages
python3 wa_import/1_export_messages.py

# Step 2 — download media
python3 wa_import/2_download_media.py

# Step 4 — score messages, find rentals
python3 wa_import/4_find_rentals.py

# Convert to canonical rental listings and push into rentals/
python3 wa_import/convert_to_rentals.py --diff
```

---

## Pushing results into the main listing database

`convert_to_rentals.py` reads `wa_import/output/rentals.json` and writes:

- **`rentals/whatsapp-YYYY-MM-DD.json`** — dated summary JSON in the canonical rental schema
- **`rentals/whatsapp-NN-slug-Nusd/`** — one folder per unique listing, with `info.json`, `listing.html`, and any copied media photos

```bash
# Dry run — print report only
python3 wa_import/convert_to_rentals.py

# Save output
python3 wa_import/convert_to_rentals.py --save

# Save + see what's new vs. the last run
python3 wa_import/convert_to_rentals.py --diff

# Raise the minimum rental-confidence score
python3 wa_import/convert_to_rentals.py --diff --min-score 20
```

---

## What's gitignored

Large files are excluded from git — see `wa_import/.gitignore`:

```
ChatStorage.sqlite   output/   Media/   node_modules/
.baileys_auth/       .playwright_session/
```

---

## Production Server Setup

The `wa_import/output/` directory is **not in git**. On every machine (local or prod) you must make it available before the ingestion pipeline can pick up WhatsApp listings.

### Option A — Symlink to existing data (recommended)

If your raw WAExport data lives elsewhere on the machine, create a symlink:

```bash
# From the project root:
ln -s /path/to/your/WAExport/output wa_import/output

# Verify:
ls -la wa_import/output/     # should show messages.json, rentals.json, media/
```

### Option B — Create the directory and copy data

```bash
mkdir -p wa_import/output
cp /path/to/WAExport/output/messages.json wa_import/output/
cp /path/to/WAExport/output/rentals.json  wa_import/output/    # optional; will be regenerated
cp -r /path/to/WAExport/output/media      wa_import/output/    # optional; for photo copying
```

### Automated ingestion

Once `output/messages.json` (and optionally `output/rentals.json`) is present, the daily update scripts handle everything automatically:

| Script | Platform |
|---|---|
| `scripts/daily_update.sh` | Linux / macOS (prod server) |
| `scripts/daily_update.ps1` | Windows (local dev) |

Phase 1.5 in each script runs `4_find_rentals.py` to score messages and produce a fresh `output/rentals.json`. The `ingest_runner` then calls `convert_to_rentals.py --save` automatically as part of the Meilisearch indexing cycle.

### Cron setup (prod server)

```bash
# Edit crontab:
crontab -e

# Add (runs daily at 03:00 AM):
0 3 * * * /path/to/rental_collector/scripts/daily_update.sh >> /path/to/rental_collector/logs/cron.log 2>&1
```
