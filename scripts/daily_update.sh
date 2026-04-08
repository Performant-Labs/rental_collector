#!/usr/bin/env bash
# scripts/daily_update.sh
# ──────────────────────────────────────────────────────────────────────────────
# Daily rental data refresh for Linux / macOS production servers.
# Equivalent of scripts/daily_update.ps1 (Windows/PowerShell).
#
# Usage:
#   bash scripts/daily_update.sh
#
# Cron example (runs at 03:00 AM every day):
#   0 3 * * * /path/to/rental_collector/scripts/daily_update.sh >> /path/to/rental_collector/logs/cron.log 2>&1
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/daily_update.log"
mkdir -p "$PROJECT_ROOT/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "--------------------------------------------------"
log "STARTING DAILY RENTAL UPDATE"
log "--------------------------------------------------"

cd "$PROJECT_ROOT"

# ── Phase 1: Scrape Airbnb / Craigslist ──────────────────────────────────────
log "Phase 1: Scraping listings (this will take a few minutes)..."
python3 scraper/rental_search.py --local --save 2>&1 | tee -a "$LOG_FILE"

# ── Phase 1.5: Score WhatsApp messages → wa_export/output/rentals.json ───────
# convert_to_rentals.py is called automatically inside ingest_runner, but
# 4_find_rentals.py must produce rentals.json first.
log "Phase 1.5: Scoring WhatsApp messages..."
WA_MESSAGES="$PROJECT_ROOT/wa_export/output/messages.json"
if [ -f "$WA_MESSAGES" ]; then
    python3 wa_export/4_find_rentals.py 2>&1 | tee -a "$LOG_FILE"
    log "  WhatsApp scoring complete."
else
    log "  wa_export/output/messages.json not found — skipping WA scoring."
    log "  Run: python3 wa_export/1_export_messages.py  (requires ChatStorage.sqlite)"
fi

# ── Phase 2: (removed) ──────────────────────────────────────────────────────
# The scraper now writes directly to rentals/ (DEFAULT_RENTALS_DIR from
# shared/config.py), so no file-move step is needed.

# ── Phase 3: Ingest into Meilisearch ─────────────────────────────────────────
# ingest_runner automatically calls convert_to_rentals.py --save (WA conversion)
# before indexing, so no separate WA conversion step is needed here.
log "Phase 3: Ingesting into Dashboard (Meilisearch)..."
${COMPOSE_CMD:-docker compose} run --rm dashboard-ingest python -m dashboard.app.ingest_runner --mode full \
    2>&1 | tee -a "$LOG_FILE"

# ── Phase 4: Record completion timestamp ──────────────────────────────────────
log "Phase 4: Recording completion time..."
date '+%Y-%m-%d %H:%M:%S' > "$PROJECT_ROOT/rentals/last_run.txt"

log "--------------------------------------------------"
log "DAILY UPDATE COMPLETE"
log "--------------------------------------------------"
