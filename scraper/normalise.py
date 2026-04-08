"""
scraper.normalise — Coerce any raw listing dict to the canonical schema.

Extracted from rental_search.py to keep the monolith manageable.
"""

from __future__ import annotations

from shared.config import TODAY


def normalise(raw: dict, source: str) -> dict:
    """Coerce any listing dict to the canonical schema."""
    price = raw.get("price_usd") or raw.get("usdPerMonth")
    if price is not None:
        try:
            price = int(price)
        except (ValueError, TypeError):
            price = None

    description = (
        raw.get("description")
        or raw.get("notes")
        or ""
    )
    amenities = raw.get("amenities") or []
    if isinstance(amenities, str):
        amenities = [a.strip() for a in amenities.split(",") if a.strip()]

    return {
        "title":        raw.get("title") or "",
        "source":       source,
        "price_usd":    price,
        "bedrooms":     raw.get("bedrooms"),
        "location":     raw.get("location") or "Todos Santos",
        "url":          raw.get("url") or raw.get("link"),
        "contact":      raw.get("contact"),
        "description":  description,
        "amenities":    amenities,
        "rating":       raw.get("rating"),
        "listing_type": raw.get("listingType") or raw.get("listing_type"),
        "checkin":      raw.get("checkin"),
        "checkout":     raw.get("checkout"),
        "scraped":      raw.get("scraped") or TODAY,
        "photo_url":    raw.get("photo_url"),
    }
