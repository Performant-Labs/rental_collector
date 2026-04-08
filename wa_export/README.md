# WhatsApp Export Pipeline (`wa_export/`)

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
wa_export/
└── ChatStorage.sqlite    ← copy here from your iOS backup / WAExport location
```

Or symlink it:

```bash
ln -s /path/to/your/ChatStorage.sqlite wa_export/ChatStorage.sqlite
```

### Python dependencies

```bash
pip install better-sqlite3    # only for Node scripts; Python scripts use stdlib sqlite3
```

### Node dependencies (for steps 3+)

```bash
cd wa_export
npm install
```

---

## Running the pipeline

```bash
# Step 1 — export messages
python3 wa_export/1_export_messages.py

# Step 2 — download media
python3 wa_export/2_download_media.py

# Step 4 — score messages, find rentals
python3 wa_export/4_find_rentals.py

# Convert to canonical rental listings and push into rentals/
python3 wa_export/convert_to_rentals.py --diff
```

---

## Pushing results into the main listing database

`convert_to_rentals.py` reads `wa_export/output/rentals.json` and writes:

- **`rentals/whatsapp-YYYY-MM-DD.json`** — dated summary JSON in the canonical rental schema
- **`rentals/whatsapp-NN-slug-Nusd/`** — one folder per unique listing, with `info.json`, `listing.html`, and any copied media photos

```bash
# Dry run — print report only
python3 wa_export/convert_to_rentals.py

# Save output
python3 wa_export/convert_to_rentals.py --save

# Save + see what's new vs. the last run
python3 wa_export/convert_to_rentals.py --diff

# Raise the minimum rental-confidence score
python3 wa_export/convert_to_rentals.py --diff --min-score 20
```

---

## What's gitignored

Large files are excluded from git — see `wa_export/.gitignore`:

```
ChatStorage.sqlite   output/   Media/   node_modules/
.baileys_auth/       .playwright_session/
```
