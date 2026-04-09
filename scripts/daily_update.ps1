# scripts/daily_update.ps1
# ──────────────────────────────────────────────────────────────────────────────
# Daily rental data refresh — Windows Task Scheduler version.
#
# Design principles:
#   • The run timestamp is ALWAYS written, even when steps fail.
#   • Every step is wrapped in try/catch and its exit code is captured.
#   • A structured summary (PASS / FAIL per step) is appended to the log.
#   • The script exits with code 0 only when ALL steps succeed.
# ──────────────────────────────────────────────────────────────────────────────

$ProjectRoot = "c:\Users\aange\Projects\rental_collector"
$LogDir      = "$ProjectRoot\logs"
$RunStamp    = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile     = "$LogDir\nightly_$RunStamp.log"
$LastRunFile = "$ProjectRoot\rentals\last_run.txt"
$StatsFile   = "$ProjectRoot\rentals\last_run_status.json"

# Ensure dirs exist
New-Item -ItemType Directory -Force -Path $LogDir       | Out-Null
New-Item -ItemType Directory -Force -Path "$ProjectRoot\rentals" | Out-Null

# ── Logging helper ─────────────────────────────────────────────────────────────
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

# ── Step runner ────────────────────────────────────────────────────────────────
# Runs a script block, captures its exit code, returns $true/$false.
# All stdout/stderr from the block is tee'd to the log.
function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Block
    )
    Write-Log ">>> BEGIN: $Name"
    $ok = $true
    try {
        & $Block 2>&1 | Tee-Object -FilePath $LogFile -Append
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Write-Log "    Exit code: $LASTEXITCODE" "WARN"
            $ok = $false
        }
    }
    catch {
        Write-Log "    EXCEPTION: $_" "ERROR"
        $ok = $false
    }
    $status = if ($ok) { "PASS" } else { "FAIL" }
    Write-Log "<<< END:   $Name  [$status]"
    return $ok
}

# ── Run start ──────────────────────────────────────────────────────────────────
$StartTime = Get-Date
Write-Log "======================================================"
Write-Log "NIGHTLY RENTAL PIPELINE STARTED"
Write-Log "======================================================"

Set-Location $ProjectRoot

# Track per-step outcomes
$Results = [ordered]@{}

# ── Step 1: Scraper ────────────────────────────────────────────────────────────
$Results["scraper"] = Invoke-Step "Web scraper (LLM)" {
    & python scraper/rental_search.py --local --save --model openai/gemma-4-26B-A4B-it
}

# ── Step 2: WhatsApp scoring ───────────────────────────────────────────────────
$WaMessages = "$ProjectRoot\wa_import\output\messages.json"
if (Test-Path $WaMessages) {
    $Results["wa_scoring"] = Invoke-Step "WhatsApp message scoring" {
        & python wa_import/4_find_rentals.py
    }
} else {
    Write-Log "wa_import/output/messages.json not found — skipping WA scoring." "WARN"
    $Results["wa_scoring"] = $null   # null = skipped (not a failure)
}

# ── Step 3: Meilisearch ingest ─────────────────────────────────────────────────
$Results["ingest"] = Invoke-Step "Meilisearch ingest (podman)" {
    & podman compose run --rm dashboard-ingest `
        python -m dashboard.app.ingest_runner --mode full
}

# ── Always: Write timestamp ────────────────────────────────────────────────────
$EndTime   = Get-Date
$RunAt     = $EndTime.ToString("yyyy-MM-dd HH:mm:ss")
$DurationS = [int]($EndTime - $StartTime).TotalSeconds

Write-Log "Recording run timestamp: $RunAt"
$RunAt | Out-File -FilePath $LastRunFile -Encoding utf8 -NoNewline

# ── Summary ────────────────────────────────────────────────────────────────────
$AllPassed = $true
Write-Log "======================================================"
Write-Log "PIPELINE SUMMARY  (duration: ${DurationS}s)"
Write-Log "======================================================"

$StatusMap = @{}
foreach ($step in $Results.Keys) {
    $val = $Results[$step]
    if ($null -eq $val) {
        $label = "SKIP"
    } elseif ($val) {
        $label = "PASS"
    } else {
        $label = "FAIL"
        $AllPassed = $false
    }
    $StatusMap[$step] = $label
    $icon = switch ($label) { "PASS" { "✓" } "FAIL" { "✗" } "SKIP" { "-" } }
    Write-Log "  $icon  $($step.PadRight(20)) $label"
}

if ($AllPassed) {
    Write-Log "RESULT: SUCCESS — all steps passed"
} else {
    Write-Log "RESULT: FAILURE — one or more steps failed (see above)"
}
Write-Log "======================================================"

# ── Write machine-readable status JSON ────────────────────────────────────────
$JsonStatus = [ordered]@{
    run_at      = $RunAt
    duration_s  = $DurationS
    overall     = if ($AllPassed) { "success" } else { "failure" }
    steps       = $StatusMap
    log_file    = $LogFile
} | ConvertTo-Json -Depth 3
$JsonStatus | Out-File -FilePath $StatsFile -Encoding utf8

# Exit non-zero if any step failed (so Task Scheduler records a failure)
exit $(if ($AllPassed) { 0 } else { 1 })
