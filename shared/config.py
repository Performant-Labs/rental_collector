"""
shared.config — Project-wide constants and path definitions.

Every module that needs REPO_ROOT, DEFAULT_RENTALS_DIR, MAX_USD, or
SOURCE_COLORS should import from here instead of computing its own copy.
"""

from datetime import date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RENTALS_DIR = REPO_ROOT / "rentals"

# ── Business rules ────────────────────────────────────────────────────────────

MAX_USD = 2000          # price ceiling for all listing sources
MIN_MONTHS = 5          # minimum rental term we're interested in
TODAY = date.today().isoformat()

# ── Appearance ────────────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "airbnb":      "#ff385c",
    "craigslist":  "#cc4444",
    "todossantos": "#2d6a4f",
    "claude-api":  "#6B46C1",
    "claude-cli":  "#6B46C1",
    "whatsapp":    "#25D366",
}
