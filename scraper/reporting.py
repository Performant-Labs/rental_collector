"""
scraper.reporting — Terminal report, save-to-JSON, and diff utilities.

Extracted from rental_search.py to keep the monolith manageable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List

from shared import config as _config
from shared.config import MAX_USD, TODAY
from shared.listing_io import listing_key

MIN_MONTHS = 5


def print_report(listings: List[dict]):
    # Ensure Unicode box-drawing chars print correctly on Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    divider = "─" * 68
    double_line = "═" * 68
    print(f"\n{double_line}")
    print(f"  TODOS SANTOS RENTALS  ·  {MIN_MONTHS}+ months  ·  under ${MAX_USD}/mo  ·  {TODAY}")
    print(f"{double_line}")
    if not listings:
        print("  No listings found.")
    for i, l in enumerate(listings, 1):
        price   = f"${l['price_usd']}/mo" if l.get("price_usd") else "price unknown"
        beds    = l.get("bedrooms") or "?"
        title   = l.get("title") or "Untitled"
        src     = l.get("source") or ""
        loc     = l.get("location") or "Todos Santos"
        url     = l.get("url") or ""
        contact = l.get("contact") or ""
        desc    = l.get("description") or ""

        print(f"\n  {i:>2}. {title}")
        beds_str   = str(beds)
        beds_label = beds_str if (beds_str == "?" or re.search(r"bed|bath|BR", beds_str, re.I)) else f"{beds_str} bed"
        print(f"      {price}  \u00b7  {beds_label}  \u00b7  {loc}  \u00b7  [{src}]")
        if url:
            print(f"      {url}")
        if contact:
            print(f"      Contact: {contact}")
        if desc:
            words = desc.split()
            line, lines = "", []
            for w in words:
                if len(line) + len(w) + 1 > 60:
                    lines.append(line)
                    line = w
                else:
                    line = (line + " " + w).strip()
            if line:
                lines.append(line)
            for ln in lines[:3]:
                print(f"      {ln}")

        print(f"  {divider}")

    print(f"\n  Total: {len(listings)} listing(s)  \u00b7  scraped {TODAY}")
    print(f"\n  \u26a0\ufe0f  Also check manually (no API access):")
    print(f"      \u2022 Facebook: 'Todos Santos Rentals', 'Todos Santos Housing', 'Baja Sur Rentals'")
    print(f"      \u2022 Nextdoor Todos Santos")
    print()


def save_results(listings: List[dict], source: str) -> Path:
    _config.DEFAULT_RENTALS_DIR.mkdir(exist_ok=True)
    out = _config.DEFAULT_RENTALS_DIR / f"{source}-{TODAY}.json"
    out.write_text(json.dumps(listings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved \u2192 {out}")
    return out


def diff_against_previous(current: List[dict], source: str):
    """Print listings that are new compared to the most recent previous run."""
    prior_files = sorted(_config.DEFAULT_RENTALS_DIR.glob(f"{source}-*.json"))
    prior_files = [f for f in prior_files if not f.stem.endswith(TODAY)]
    if not prior_files:
        print(f"  [{source}] No previous results to diff against.")
        return

    prev_file = prior_files[-1]
    try:
        prev = json.loads(prev_file.read_text(encoding="utf-8"))
    except Exception:
        print(f"  Could not read {prev_file}.", file=sys.stderr)
        return

    prev_keys = {listing_key(l) for l in prev}
    new_ones  = [l for l in current if listing_key(l) not in prev_keys]
    gone_keys = prev_keys - {listing_key(l) for l in current}

    print(f"\n  [{source}] Diff vs {prev_file.name}:")
    print(f"  + {len(new_ones)} new listing(s)   - {len(gone_keys)} removed\n")
    if new_ones:
        print("  NEW LISTINGS:")
        print_report(new_ones)
