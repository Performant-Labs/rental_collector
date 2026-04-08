# Rental Collector Daily Update Script

$ProjectRoot = "c:\Users\aange\Projects\rental_collector"
$LogFile = "$ProjectRoot\logs\daily_update.log"

function Write-Log {
    param([string]$Message)
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$Timestamp] $Message"
    Write-Host "[$Timestamp] $Message"
}

cd $ProjectRoot

Write-Log "--------------------------------------------------"
Write-Log "STARTING DAILY RENTAL SEARCH"
Write-Log "--------------------------------------------------"

# 1. Run the scraper with the Local LLM (Gemma 4)
Write-Log "Phase 1: Scraping listings (this will take a few minutes)..."
& python scraper/rental_search.py --local --save --model openai/gemma-4-26B-A4B-it 2>&1 | Add-Content -Path $LogFile

# 1.5. Score WhatsApp messages → output/rentals.json
#      (convert_to_rentals.py is called automatically inside ingest_runner,
#       but 4_find_rentals.py must be run first to build rentals.json)
Write-Log "Phase 1.5: Scoring WhatsApp messages..."
if (Test-Path "$ProjectRoot\wa_import\output\messages.json") {
    & python wa_import/4_find_rentals.py 2>&1 | Add-Content -Path $LogFile
    Write-Log "  WhatsApp scoring complete."
} else {
    Write-Log "  wa_import/output/messages.json not found — skipping WA scoring."
    Write-Log "  Run: python wa_import/1_export_messages.py  (requires ChatStorage.sqlite)"
}

# 2. (removed) — scraper now writes directly to rentals/ (DEFAULT_RENTALS_DIR
#    from shared/config.py), so no file-move step is needed.

# 3. Synchronize with Meilisearch
Write-Log "Phase 3: Ingesting into Dashboard..."
& podman compose run --rm dashboard-ingest python -m dashboard.app.ingest_runner --mode full 2>&1 | Add-Content -Path $LogFile

# 4. Save timestamp for the dashboard
Write-Log "Phase 4: Recording completion time..."
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$Timestamp | Out-File -FilePath "$ProjectRoot\rentals\last_run.txt" -Encoding utf8 -NoNewline

Write-Log "--------------------------------------------------"
Write-Log "DAILY UPDATE COMPLETE"
Write-Log "--------------------------------------------------"
