"""
shared.listing_io — Folder naming, slugification, and dedup-key generation.

Canonical implementations of _slugify(), _folder_name(), and _listing_key()
used by both the scraper (rental_search.py) and the WA converter
(convert_to_rentals.py).  Having one copy prevents silent divergence.
"""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Convert *text* to a filesystem-safe slug (max 40 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:40]


def folder_name(listing: dict, index: int) -> str:
    """Build the canonical folder name for a listing.

    Format: ``{source}-{NN}-{slug}-{price}usd``
    """
    source = listing.get("source", "unknown")
    slug = slugify(listing.get("title") or "listing")
    price = listing.get("price_usd")
    price_part = f"{price}usd" if price else "noprice"
    return f"{source}-{index:02d}-{slug}-{price_part}"


def listing_key(listing: dict) -> str:
    """Rough dedup key: normalised title + source."""
    title = re.sub(r"\W+", " ", (listing.get("title") or "")).lower().strip()[:60]
    return f"{listing.get('source', '')}|{title}"
