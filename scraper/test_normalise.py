"""
Phase 1 tests for scraper.normalise — schema fields added in the
listing-updates-and-archiving feature.
"""
from __future__ import annotations

import pytest
from scraper.normalise import normalise


def _base_raw(**kwargs) -> dict:
    return {
        "title": "Casa Bonita",
        "url": "https://example.com/listing/1",
        "price_usd": 800,
        "location": "Todos Santos",
        "description": "Nice place",
        **kwargs,
    }


# ── New fields present ────────────────────────────────────────────────────────

def test_normalise_has_status_field():
    result = normalise(_base_raw(), "airbnb")
    assert "status" in result

def test_normalise_status_defaults_to_active():
    result = normalise(_base_raw(), "airbnb")
    assert result["status"] == "active"

def test_normalise_preserves_archived_status():
    result = normalise(_base_raw(status="archived"), "airbnb")
    assert result["status"] == "archived"

def test_normalise_has_last_checked_field():
    result = normalise(_base_raw(), "airbnb")
    assert "last_checked" in result

def test_normalise_has_last_updated_field():
    result = normalise(_base_raw(), "airbnb")
    assert "last_updated" in result

def test_normalise_last_checked_is_date_string():
    result = normalise(_base_raw(), "airbnb")
    # Should look like YYYY-MM-DD
    assert len(result["last_checked"]) == 10
    assert result["last_checked"][4] == "-"

def test_normalise_preserves_existing_last_checked():
    result = normalise(_base_raw(last_checked="2026-01-15"), "airbnb")
    assert result["last_checked"] == "2026-01-15"

def test_normalise_preserves_existing_last_updated():
    result = normalise(_base_raw(last_updated="2026-02-20"), "airbnb")
    assert result["last_updated"] == "2026-02-20"


# ── Immutability of scraped ───────────────────────────────────────────────────

def test_scraped_preserved_if_present():
    result = normalise(_base_raw(scraped="2025-12-01"), "airbnb")
    assert result["scraped"] == "2025-12-01"

def test_scraped_defaults_to_today_if_missing():
    from shared.config import TODAY
    result = normalise(_base_raw(), "airbnb")
    assert result["scraped"] == TODAY


# ── Source is always from caller, never from raw ──────────────────────────────

def test_source_not_overridable_by_raw():
    raw = _base_raw(source="ai")
    result = normalise(raw, "airbnb")
    assert result["source"] == "airbnb"

def test_source_not_overridable_by_llm_tool_name():
    for tool_name in ("claude-api", "local-llm", "claude-cli"):
        raw = _base_raw(source=tool_name)
        result = normalise(raw, "craigslist")
        assert result["source"] == "craigslist", f"source should be 'craigslist', got '{result['source']}'"


# ── All expected fields present ───────────────────────────────────────────────

EXPECTED_FIELDS = {
    "title", "source", "status", "price_usd", "bedrooms", "location",
    "url", "contact", "description", "amenities", "rating", "listing_type",
    "checkin", "checkout", "scraped", "last_checked", "last_updated", "photo_url",
}

def test_normalise_returns_all_expected_fields():
    result = normalise(_base_raw(), "whatsapp")
    missing = EXPECTED_FIELDS - result.keys()
    assert not missing, f"Missing fields in normalise() output: {missing}"
