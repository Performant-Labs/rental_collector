#!/bin/bash
# Nightly rental pipeline - runs WA export + scoring + ingest
# Designed to run via cron at 3am daily
set -euo pipefail

REPO="/mnt/c/Users/aange/Projects/rental_collector"
COMPOSE="/usr/bin/podman-compose -f ${REPO}/docker-compose.yml"
LOG="${REPO}/logs/nightly_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "${REPO}/logs"

exec > "${LOG}" 2>&1
echo "=== Nightly pipeline started at $(date -Iseconds) ==="

# Step 1: Pull new WhatsApp messages via Baileys
echo "[1/3] Running WA exporter..."
${COMPOSE} --profile wa run --rm wa-exporter || {
    echo "WARNING: WA exporter failed (may need QR re-scan)"
}

# Step 2: Score messages + generate listing folders + ingest to Meilisearch
echo "[2/3] Running ingest pipeline..."
${COMPOSE} run --rm dashboard-ingest python -m dashboard.app.ingest_runner --mode full || {
    echo "ERROR: Ingest failed"
    exit 1
}

# Step 3: Verify
DOCS=$(curl -s http://localhost:7700/indexes/rentals_listings/stats 2>/dev/null | grep -o '"numberOfDocuments":[0-9]*' | cut -d: -f2)
echo "[3/3] Meilisearch has ${DOCS:-unknown} documents indexed"

echo "=== Pipeline completed at $(date -Iseconds) ==="

# Keep only last 30 days of logs
find "${REPO}/logs" -name "nightly_*.log" -mtime +30 -delete 2>/dev/null || true
