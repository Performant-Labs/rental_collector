"""
scraper.archiver — Automatic listing lifecycle management.

Provides ``archive_gone_listings()``, which inspects every saved folder for a
given source and:

  * **Archives** listings whose URL is no longer in the active scrape results
    AND whose ``last_checked`` date is older than the grace period.
  * **Restores** listings that reappear in the active results after being
    archived (sets ``status="active"``, clears ``archived_date``).
  * **Skips** listings with no URL (WhatsApp listings, Craigslist entries
    that never had a URL), as there is no reliable way to detect their removal.

Grace periods (from ``shared.config.ARCHIVE_GRACE_DAYS``):
  - "whatsapp": 30 days
  - everything else: 7 days

Safety gate: if the active scrape returned fewer than
``min_results`` listings the archiver refuses to run, preventing a scraper
failure from accidentally mass-archiving the entire index.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Collection, Optional

from shared.config import ARCHIVE_GRACE_DAYS, TODAY
from shared.listing_html import generate_listing_html


# ── Helpers ───────────────────────────────────────────────────────────────────

def _grace_days(source: str) -> int:
    """Return the grace-period in days for a given source channel."""
    return ARCHIVE_GRACE_DAYS.get(source, ARCHIVE_GRACE_DAYS["default"])


def _days_since(date_str: Optional[str]) -> Optional[int]:
    """Return the number of calendar days since *date_str* (ISO format).

    Returns None when the string is absent or unparseable.
    """
    if not date_str:
        return None
    try:
        then = date.fromisoformat(date_str)
        return (date.fromisoformat(TODAY) - then).days
    except ValueError:
        return None


# ── Core function ─────────────────────────────────────────────────────────────

def archive_gone_listings(
    source: str,
    active_urls: Collection[str],
    rentals_dir: Path,
    grace_days: Optional[int] = None,
    min_results: int = 3,
) -> dict[str, int]:
    """Archive or restore listings for *source* based on *active_urls*.

    Parameters
    ----------
    source:
        Channel name, e.g. ``"airbnb"`` or ``"whatsapp"``.
    active_urls:
        The set of listing URLs returned by the most recent scrape run.
        Listings *not* in this set are candidates for archiving.
    rentals_dir:
        Root directory that holds all the ``<source>-NN-slug/`` folders.
    grace_days:
        Override the grace period. Defaults to the value in
        ``ARCHIVE_GRACE_DAYS`` for this source.
    min_results:
        Safety gate: if ``len(active_urls) < min_results`` the archiver
        refuses to run and returns ``{"skipped": True}``.

    Returns
    -------
    dict with keys ``archived``, ``restored``, ``skipped_no_url``.
    ``skipped`` key is present (True) only when the safety gate fired.
    """
    # Safety gate: a scraper failure that returns 0 (or too few) results must
    # never trigger a mass-archiving event.
    active_set = set(active_urls)
    if len(active_set) < min_results:
        print(
            f"  [{source}] archiver: only {len(active_set)} active URL(s) — "
            f"safety gate engaged, skipping archive pass"
        )
        return {"archived": 0, "restored": 0, "skipped_no_url": 0, "skipped": True}

    effective_grace = grace_days if grace_days is not None else _grace_days(source)
    archived_count = restored_count = no_url_count = 0

    for folder in rentals_dir.glob(f"{source}-*/"):
        if not folder.is_dir():
            continue
        info_path = folder / "info.json"
        if not info_path.exists():
            continue

        try:
            info: dict = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        url = info.get("url")
        status = info.get("status", "active")

        # ── Listings with no URL are immune from auto-archiving ───────────────
        if not url:
            no_url_count += 1
            continue

        # ── Restore: listing reappeared in the active scrape ──────────────────
        if url in active_set:
            if status == "archived":
                updated = {
                    **info,
                    "status": "active",
                    "archived_date": None,
                    "last_checked": TODAY,
                }
                _write_info_and_html(folder, info_path, updated)
                print(f"  ✓ restored: {folder.name}/")
                restored_count += 1
            # Active listings that are still active: last_checked already
            # updated by update_listing_folder(); nothing to do here.
            continue

        # ── Archive: listing absent AND grace period expired ──────────────────
        if status == "archived":
            # Already archived — nothing to do
            continue

        age = _days_since(info.get("last_checked"))
        if age is None or age < effective_grace:
            # Within grace period — leave it alone
            continue

        updated = {
            **info,
            "status": "archived",
            "archived_date": TODAY,
            "last_checked": info.get("last_checked", TODAY),  # don't update
        }
        _write_info_and_html(folder, info_path, updated)
        print(f"  ✗ archived ({age}d since last seen): {folder.name}/")
        archived_count += 1

    return {
        "archived": archived_count,
        "restored": restored_count,
        "skipped_no_url": no_url_count,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _write_info_and_html(folder: Path, info_path: Path, data: dict) -> None:
    """Write updated info.json and regenerate listing.html."""
    info_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "listing.html").write_text(
        generate_listing_html(data), encoding="utf-8"
    )
