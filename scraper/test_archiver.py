#!/usr/bin/env python3
"""
scraper/test_archiver.py
========================
Phase 3 tests for archive_gone_listings().
"""

import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from shared.config import TODAY
from scraper.archiver import archive_gone_listings, _days_since, _grace_days


# ── helpers ───────────────────────────────────────────────────────────────────

def _isodate(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _make_folder(
    rentals_dir: Path,
    name: str,
    *,
    url: str | None = "https://example.com/listing",
    status: str = "active",
    last_checked: str | None = None,
    archived_date: str | None = None,
    price: int = 1000,
) -> Path:
    """Create a minimal listing folder with info.json (and stub listing.html)."""
    folder = rentals_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    info = {
        "title": name,
        "source": name.split("-")[0],
        "status": status,
        "price_usd": price,
        "url": url,
        "description": "Test listing",
        "amenities": [],
        "scraped": "2026-01-01",
        "last_checked": last_checked or TODAY,
        "last_updated": last_checked or TODAY,
    }
    if archived_date:
        info["archived_date"] = archived_date
    (folder / "info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "listing.html").write_text("<html></html>", encoding="utf-8")
    return folder


# ── unit tests ────────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_grace_days_default(self):
        self.assertEqual(_grace_days("airbnb"), 7)
        self.assertEqual(_grace_days("craigslist"), 7)
        self.assertEqual(_grace_days("unknown_source"), 7)

    def test_grace_days_whatsapp(self):
        self.assertEqual(_grace_days("whatsapp"), 30)

    def test_days_since_today(self):
        self.assertEqual(_days_since(TODAY), 0)

    def test_days_since_8_days_ago(self):
        self.assertEqual(_days_since(_isodate(8)), 8)

    def test_days_since_none(self):
        self.assertIsNone(_days_since(None))

    def test_days_since_bad_string(self):
        self.assertIsNone(_days_since("not-a-date"))


# ── integration tests ─────────────────────────────────────────────────────────

class TestArchiveGoneListings(unittest.TestCase):

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── safety gate ───────────────────────────────────────────────────────────

    def test_safety_gate_blocks_archive_on_zero_results(self):
        """0 active_urls → safety gate fires, nothing archived."""
        _make_folder(self._tmp, "airbnb-01-old", last_checked=_isodate(10))

        result = archive_gone_listings("airbnb", [], self._tmp, grace_days=7, min_results=3)

        self.assertTrue(result.get("skipped"))
        self.assertEqual(result["archived"], 0)
        info = json.loads((self._tmp / "airbnb-01-old" / "info.json").read_text())
        self.assertEqual(info["status"], "active")

    def test_safety_gate_blocks_archive_below_min_results(self):
        """Fewer than min_results URLs → safety gate fires."""
        result = archive_gone_listings(
            "airbnb", ["https://x.com/a", "https://x.com/b"], self._tmp,
            grace_days=7, min_results=3,
        )
        self.assertTrue(result.get("skipped"))

    def test_safety_gate_allows_when_enough_results(self):
        """Exactly min_results active URLs → safety gate does NOT fire."""
        result = archive_gone_listings(
            "airbnb",
            ["https://x.com/a", "https://x.com/b", "https://x.com/c"],
            self._tmp,
            grace_days=7,
            min_results=3,
        )
        self.assertNotIn("skipped", result)

    # ── archiving ─────────────────────────────────────────────────────────────

    def test_archives_after_grace_period(self):
        """last_checked 8 days ago, not in active_urls → archived."""
        _make_folder(
            self._tmp, "airbnb-01-stale",
            url="https://example.com/stale",
            last_checked=_isodate(8),
        )

        result = archive_gone_listings(
            "airbnb",
            ["https://example.com/other1", "https://example.com/other2",
             "https://example.com/other3"],
            self._tmp,
            grace_days=7,
        )

        info = json.loads((self._tmp / "airbnb-01-stale" / "info.json").read_text())
        self.assertEqual(info["status"], "archived")
        self.assertEqual(info["archived_date"], TODAY)
        self.assertEqual(result["archived"], 1)

    def test_does_not_archive_within_grace_period(self):
        """last_checked 3 days ago → still within 7-day grace, not archived."""
        _make_folder(
            self._tmp, "airbnb-01-fresh",
            url="https://example.com/fresh",
            last_checked=_isodate(3),
        )

        archive_gone_listings(
            "airbnb",
            ["https://example.com/other1", "https://example.com/other2",
             "https://example.com/other3"],
            self._tmp,
            grace_days=7,
        )

        info = json.loads((self._tmp / "airbnb-01-fresh" / "info.json").read_text())
        self.assertEqual(info["status"], "active")

    def test_does_not_rearchive_already_archived(self):
        """A listing already marked archived is not touched again."""
        _make_folder(
            self._tmp, "airbnb-01-old",
            url="https://example.com/old",
            status="archived",
            archived_date="2026-01-01",
            last_checked=_isodate(20),
        )

        result = archive_gone_listings(
            "airbnb",
            ["https://example.com/other1", "https://example.com/other2",
             "https://example.com/other3"],
            self._tmp,
            grace_days=7,
        )

        self.assertEqual(result["archived"], 0)

    # ── restoration ──────────────────────────────────────────────────────────

    def test_restores_when_listing_returns(self):
        """Archived listing reappears in active_urls → restored to active."""
        url = "https://example.com/returning"
        _make_folder(
            self._tmp, "airbnb-01-return",
            url=url,
            status="archived",
            archived_date="2026-01-01",
            last_checked=_isodate(15),
        )

        result = archive_gone_listings(
            "airbnb",
            [url, "https://example.com/other1", "https://example.com/other2"],
            self._tmp,
            grace_days=7,
        )

        info = json.loads((self._tmp / "airbnb-01-return" / "info.json").read_text())
        self.assertEqual(info["status"], "active")
        self.assertIsNone(info.get("archived_date"))
        self.assertEqual(info["last_checked"], TODAY)
        self.assertEqual(result["restored"], 1)

    # ── no-URL immunity ───────────────────────────────────────────────────────

    def test_no_url_never_archived(self):
        """Listings without a URL are never archived, even past the grace period."""
        _make_folder(
            self._tmp, "whatsapp-01-nourl",
            url=None,
            last_checked=_isodate(60),
        )

        result = archive_gone_listings(
            "whatsapp",
            ["https://example.com/x", "https://example.com/y",
             "https://example.com/z"],
            self._tmp,
            grace_days=30,
        )

        info = json.loads((self._tmp / "whatsapp-01-nourl" / "info.json").read_text())
        self.assertEqual(info["status"], "active")
        self.assertEqual(result["skipped_no_url"], 1)
        self.assertEqual(result["archived"], 0)

    # ── WhatsApp 30-day grace ─────────────────────────────────────────────────

    def test_whatsapp_grace_29_days_not_archived(self):
        """29 days ago → within WhatsApp 30-day grace, not archived."""
        _make_folder(
            self._tmp, "whatsapp-01-recent",
            url="https://example.com/wa-recent",
            last_checked=_isodate(29),
        )

        archive_gone_listings(
            "whatsapp",
            ["https://example.com/other1", "https://example.com/other2",
             "https://example.com/other3"],
            self._tmp,
            grace_days=_grace_days("whatsapp"),
        )

        info = json.loads((self._tmp / "whatsapp-01-recent" / "info.json").read_text())
        self.assertEqual(info["status"], "active")

    def test_whatsapp_grace_31_days_archived(self):
        """31 days ago → past WhatsApp 30-day grace, archived."""
        _make_folder(
            self._tmp, "whatsapp-01-stale",
            url="https://example.com/wa-stale",
            last_checked=_isodate(31),
        )

        result = archive_gone_listings(
            "whatsapp",
            ["https://example.com/other1", "https://example.com/other2",
             "https://example.com/other3"],
            self._tmp,
            grace_days=_grace_days("whatsapp"),
        )

        info = json.loads((self._tmp / "whatsapp-01-stale" / "info.json").read_text())
        self.assertEqual(info["status"], "archived")
        self.assertEqual(result["archived"], 1)

    # ── listing.html regenerated ──────────────────────────────────────────────

    def test_listing_html_regenerated_on_archive(self):
        """listing.html is rewritten when status changes."""
        _make_folder(
            self._tmp, "airbnb-01-html",
            url="https://example.com/html",
            last_checked=_isodate(10),
        )
        before = (self._tmp / "airbnb-01-html" / "listing.html").read_text()

        archive_gone_listings(
            "airbnb",
            ["https://example.com/other1", "https://example.com/other2",
             "https://example.com/other3"],
            self._tmp,
            grace_days=7,
        )

        after = (self._tmp / "airbnb-01-html" / "listing.html").read_text()
        self.assertNotEqual(before, after)  # HTML was regenerated

    def test_listing_html_regenerated_on_restore(self):
        """listing.html is rewritten when a listing is restored."""
        url = "https://example.com/restore-html"
        _make_folder(
            self._tmp, "airbnb-01-restore",
            url=url,
            status="archived",
            archived_date="2026-01-01",
            last_checked=_isodate(10),
        )
        before = (self._tmp / "airbnb-01-restore" / "listing.html").read_text()

        archive_gone_listings(
            "airbnb",
            [url, "https://example.com/other1", "https://example.com/other2"],
            self._tmp,
            grace_days=7,
        )

        after = (self._tmp / "airbnb-01-restore" / "listing.html").read_text()
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
