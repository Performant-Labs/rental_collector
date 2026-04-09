#!/bin/bash
# nightly_pipeline.sh
# ──────────────────────────────────────────────────────────────────────────────
# Nightly rental pipeline — WA export + scoring + ingest.
# Designed to run via Linux/WSL cron at 03:00 AM daily.
#
# Cron entry (WSL):
#   0 3 * * * /mnt/c/Users/aange/Projects/rental_collector/nightly_pipeline.sh
#
# Design principles:
#   • The run timestamp is ALWAYS written, even when steps fail.
#   • Every step is captured; failures do NOT abort the remaining steps.
#   • A PASS/FAIL/SKIP summary is appended to the log.
#   • Machine-readable last_run_status.json is written every run.
# ──────────────────────────────────────────────────────────────────────────────

# Do NOT use set -e — we capture individual step exits ourselves.
set -uo pipefail

REPO="/mnt/c/Users/aange/Projects/rental_collector"
COMPOSE="/usr/bin/podman-compose -f ${REPO}/docker-compose.yml"
RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="${REPO}/logs/nightly_${RUN_STAMP}.log"
LAST_RUN_FILE="${REPO}/rentals/last_run.txt"
STATS_FILE="${REPO}/rentals/last_run_status.json"

mkdir -p "${REPO}/logs" "${REPO}/rentals"

# Redirect ALL output (stdout + stderr) to the log, and also to the terminal.
exec > >(tee -a "$LOG") 2>&1

# ── Logging helper ─────────────────────────────────────────────────────────────
log() {
    local level="${1:-INFO}"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
}

# ── Step runner ────────────────────────────────────────────────────────────────
declare -A STEP_RESULTS
run_step() {
    local name="$1"
    shift
    local key
    key=$(echo "$name" | tr ' /' '__' | tr '[:upper:]' '[:lower:]')

    log INFO ">>> BEGIN: $name"
    set +e
    "$@"
    local rc=$?
    set -e

    if [ "$rc" -eq 0 ]; then
        log INFO "<<< END:   $name  [PASS]"
        STEP_RESULTS["$key"]="PASS"
    else
        log ERROR "<<< END:   $name  [FAIL] (exit code $rc)"
        STEP_RESULTS["$key"]="FAIL"
    fi
    return $rc
}

# ── Run start ──────────────────────────────────────────────────────────────────
START_TS=$(date +%s)
log INFO "======================================================"
log INFO "NIGHTLY RENTAL PIPELINE STARTED"
log INFO "======================================================"

OVERALL="success"

# ── Step 1: Pull new WhatsApp messages via Baileys ────────────────────────────
run_step "WA exporter" \
    ${COMPOSE} --profile wa run --rm wa-exporter \
    || OVERALL="failure"

# ── Step 1.5: Score messages → rentals.json ───────────────────────────────────
# Must run right after Baileys while fresh CDN URLs are still valid.
# Output: wa_import/output/rentals.json
run_step "WA rental scoring" \
    ${COMPOSE} run --rm dashboard-ingest \
        python wa_import/4_find_rentals.py \
    || OVERALL="failure"

# ── Step 1.6: Convert WA rentals → listing folders + copy media ───────────────
# Reads rentals.json + messages.json, copies photos into whatsapp-*/
# folders inside rentals/.  Must happen before the ingest step so
# Meilisearch gets has_photos=true and the photo URLs.
run_step "WA folder conversion" \
    ${COMPOSE} run --rm dashboard-ingest \
        python -m wa_import.convert_to_rentals --save \
    || OVERALL="failure"

# ── Step 2: Score messages + ingest to Meilisearch ───────────────────────────
run_step "Ingest pipeline" \
    ${COMPOSE} run --rm dashboard-ingest \
        python -m dashboard.app.ingest_runner --mode full \
    || OVERALL="failure"

# ── Step 3: Verify document count ────────────────────────────────────────────
log INFO ">>> BEGIN: Meilisearch verify"
DOCS=$(podman exec rental_collector-dashboard-api-1 \
    curl -s http://meilisearch:7700/indexes/rentals_listings/stats 2>/dev/null \
    | grep -o '"numberOfDocuments":[0-9]*' | cut -d: -f2 || echo "unknown")
log INFO "    Meilisearch has ${DOCS} documents indexed"
if [ "${DOCS:-0}" -gt 0 ] 2>/dev/null; then
    log INFO "<<< END:   Meilisearch verify  [PASS]"
    STEP_RESULTS["meilisearch_verify"]="PASS"
else
    log ERROR "<<< END:   Meilisearch verify  [FAIL] (${DOCS} documents)"
    STEP_RESULTS["meilisearch_verify"]="FAIL"
    OVERALL="failure"
fi

# ── Always: Write timestamp ────────────────────────────────────────────────────
END_TS=$(date +%s)
RUN_AT="$(date '+%Y-%m-%d %H:%M:%S')"
DURATION_S=$(( END_TS - START_TS ))

log INFO "Recording run timestamp: $RUN_AT"
echo -n "$RUN_AT" > "$LAST_RUN_FILE"

# ── Summary ────────────────────────────────────────────────────────────────────
log INFO "======================================================"
log INFO "PIPELINE SUMMARY  (duration: ${DURATION_S}s)"
log INFO "======================================================"

STEPS_JSON="{"
FIRST=1
for step in "${!STEP_RESULTS[@]}"; do
    result="${STEP_RESULTS[$step]}"
    icon="?"
    case "$result" in PASS) icon="✓";; FAIL) icon="✗";; SKIP) icon="-";; esac
    log INFO "  $icon  $(printf '%-28s' "$step") $result"
    [ "$FIRST" -eq 0 ] && STEPS_JSON+=","
    STEPS_JSON+="\"$step\":\"$result\""
    FIRST=0
done
STEPS_JSON+="}"

log INFO "RESULT: $(echo "$OVERALL" | tr '[:lower:]' '[:upper:]')"
log INFO "======================================================"

# ── Machine-readable status JSON ──────────────────────────────────────────────
cat > "$STATS_FILE" <<EOF
{
  "run_at": "$RUN_AT",
  "duration_s": $DURATION_S,
  "overall": "$OVERALL",
  "steps": $STEPS_JSON,
  "log_file": "$LOG"
}
EOF

# ── Housekeeping: keep only last 30 days of logs ──────────────────────────────
find "${REPO}/logs" -name "nightly_*.log" -mtime +30 -delete 2>/dev/null || true

[ "$OVERALL" = "success" ] && exit 0 || exit 1
