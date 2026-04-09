#!/usr/bin/env bash
# scripts/daily_update.sh
# ──────────────────────────────────────────────────────────────────────────────
# Daily rental data refresh — Linux / macOS / Docker host version.
#
# Design principles:
#   • The run timestamp is ALWAYS written, even when steps fail.
#   • Every step is wrapped and its exit code is captured.
#   • A structured summary (PASS / FAIL / SKIP per step) is appended to the log.
#   • The script exits non-zero only when one or more steps failed.
#
# Cron example (runs at 03:00 AM every day):
#   0 3 * * * /path/to/rental_collector/scripts/daily_update.sh
# ──────────────────────────────────────────────────────────────────────────────

# Do NOT use set -e — we want to catch individual step failures ourselves.
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_STAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/nightly_${RUN_STAMP}.log"
LAST_RUN_FILE="$PROJECT_ROOT/rentals/last_run.txt"
STATS_FILE="$PROJECT_ROOT/rentals/last_run_status.json"

mkdir -p "$LOG_DIR" "$PROJECT_ROOT/rentals"

# ── Logging helper ─────────────────────────────────────────────────────────────
log() {
    local level="${1:-INFO}"
    shift
    local msg="$*"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    local line="[$ts] [$level] $msg"
    echo "$line" | tee -a "$LOG_FILE"
}

# ── Step runner ────────────────────────────────────────────────────────────────
# Usage: run_step "Step name" command [args...]
# Returns 0 (success) or 1 (failure). All output goes to log + stdout.
declare -A STEP_RESULTS
run_step() {
    local name="$1"
    shift
    local safe_key
    safe_key=$(echo "$name" | tr ' /' '__' | tr '[:upper:]' '[:lower:]')

    log INFO ">>> BEGIN: $name"
    set +e
    "$@" 2>&1 | tee -a "$LOG_FILE"
    local rc="${PIPESTATUS[0]}"
    set -e

    if [ "$rc" -eq 0 ]; then
        log INFO "<<< END:   $name  [PASS]"
        STEP_RESULTS["$safe_key"]="PASS"
        return 0
    else
        log ERROR "<<< END:   $name  [FAIL] (exit code $rc)"
        STEP_RESULTS["$safe_key"]="FAIL"
        return 1
    fi
}

# ── Run start ──────────────────────────────────────────────────────────────────
START_TS="$(date +%s)"
log INFO "======================================================"
log INFO "NIGHTLY RENTAL PIPELINE STARTED"
log INFO "======================================================"

cd "$PROJECT_ROOT"

OVERALL="success"

# ── Step 1: Web scraper ────────────────────────────────────────────────────────
run_step "Web scraper (LLM)" \
    python3 scraper/rental_search.py --local --save \
    || OVERALL="failure"

# ── Step 2: WhatsApp scoring ───────────────────────────────────────────────────
WA_MESSAGES="$PROJECT_ROOT/wa_import/output/messages.json"
if [ -f "$WA_MESSAGES" ]; then
    run_step "WhatsApp message scoring" \
        python3 wa_import/4_find_rentals.py \
        || OVERALL="failure"
    STEP_RESULTS["whatsapp_message_scoring"]="${STEP_RESULTS["whatsapp_message_scoring"]:-PASS}"
else
    log WARN "wa_import/output/messages.json not found — skipping WA scoring."
    STEP_RESULTS["whatsapp_message_scoring"]="SKIP"
fi

# ── Step 3: Meilisearch ingest ─────────────────────────────────────────────────
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
run_step "Meilisearch ingest" \
    $COMPOSE_CMD run --rm dashboard-ingest \
        python -m dashboard.app.ingest_runner --mode full \
    || OVERALL="failure"

# ── Always: Write timestamp ────────────────────────────────────────────────────
END_TS="$(date +%s)"
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
    case "$result" in
        PASS) icon="✓" ;;
        FAIL) icon="✗" ;;
        SKIP) icon="-" ;;
    esac
    log INFO "  $icon  $(printf '%-24s' "$step") $result"
    [ "$FIRST" -eq 0 ] && STEPS_JSON+=","
    STEPS_JSON+="\"$step\":\"$result\""
    FIRST=0
done
STEPS_JSON+="}"

log INFO "RESULT: $(echo "$OVERALL" | tr '[:lower:]' '[:upper:]')"
log INFO "======================================================"

# ── Write machine-readable status JSON ────────────────────────────────────────
cat > "$STATS_FILE" <<EOF
{
  "run_at": "$RUN_AT",
  "duration_s": $DURATION_S,
  "overall": "$OVERALL",
  "steps": $STEPS_JSON,
  "log_file": "$LOG_FILE"
}
EOF

# Exit non-zero if any step failed
[ "$OVERALL" = "success" ] && exit 0 || exit 1
