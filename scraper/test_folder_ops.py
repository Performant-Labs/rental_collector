#!/usr/bin/env python3
"""
scraper/test_folder_ops.py
==========================
Phase 2 tests: content-change detection and timestamp stamping in
update_listing_folder().
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.config import TODAY
import scraper.folder_ops as fo


def _make_listing(**kwargs) -> dict:
    base = {
        "title": "Beach Studio",
        "source": "craigslist",
        "status": "active",
        "price_usd": 1000,
        "bedrooms": "1BR",
        "location": "Todos Santos",
        "url": "https://craigslist.org/abc",
        "contact": None,
        "description": "Nice studio near the beach.",
        "amenities": ["WiFi"],
        "rating": None,
        "listing_type": None,
        "checkin": None,
        "checkout": None,
        "scraped": "2026-01-01",
        "last_checked": "2026-01-01",
        "last_updated": "2026-01-01",
        "photo_url": None,
        "localPhotos": [],
    }
    base.update(kwargs)
    return base


def _write_info_json(folder: Path, data: dict) -> None:
    (folder / "info.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


class TestUpdateListingFolderTimestamps(unittest.TestCase):

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── last_checked always stamped ───────────────────────────────────────────

    def test_last_checked_always_written(self):
        """Identical data → last_checked updated to TODAY, last_updated unchanged."""
        old = _make_listing(last_checked="2026-01-01", last_updated="2026-01-01")
        _write_info_json(self._tmp, old)

        changed = fo.update_listing_folder(self._tmp, _make_listing(), old)

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["last_checked"], TODAY)
        self.assertEqual(data["last_updated"], "2026-01-01")  # unchanged
        self.assertFalse(changed)

    def test_last_checked_written_even_on_new_listing(self):
        """Even when existing_info is empty, last_checked = TODAY."""
        _write_info_json(self._tmp, {})

        changed = fo.update_listing_folder(self._tmp, _make_listing(), {})

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["last_checked"], TODAY)

    # ── content-change detection ──────────────────────────────────────────────

    def test_price_change_sets_last_updated(self):
        """Price differs → last_updated = TODAY and returns True."""
        old = _make_listing(price_usd=800, last_updated="2026-01-01")
        _write_info_json(self._tmp, old)

        new = _make_listing(price_usd=1000)  # price changed
        changed = fo.update_listing_folder(self._tmp, new, old)

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["last_updated"], TODAY)
        self.assertTrue(changed)

    def test_description_change_sets_last_updated(self):
        """Description differs → last_updated bumped."""
        old = _make_listing(description="Old description.", last_updated="2026-01-01")
        _write_info_json(self._tmp, old)

        new = _make_listing(description="New description!")
        changed = fo.update_listing_folder(self._tmp, new, old)

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["last_updated"], TODAY)
        self.assertTrue(changed)

    def test_amenities_change_sets_last_updated(self):
        """Amenities list change → last_updated bumped."""
        old = _make_listing(amenities=["WiFi"], last_updated="2026-01-01")
        _write_info_json(self._tmp, old)

        new = _make_listing(amenities=["WiFi", "Pool"])
        changed = fo.update_listing_folder(self._tmp, new, old)

        self.assertTrue(changed)

    def test_photo_url_change_sets_last_updated(self):
        """photo_url change → last_updated bumped."""
        old = _make_listing(photo_url=None, last_updated="2026-01-01")
        _write_info_json(self._tmp, old)

        new = _make_listing(photo_url="https://example.com/photo.jpg")
        changed = fo.update_listing_folder(self._tmp, new, old)

        self.assertTrue(changed)

    def test_no_tracked_change_returns_false(self):
        """No tracked field changed → returns False."""
        listing = _make_listing()
        _write_info_json(self._tmp, listing)

        changed = fo.update_listing_folder(self._tmp, listing, listing)
        self.assertFalse(changed)

    # ── scraped is immutable ──────────────────────────────────────────────────

    def test_scraped_is_immutable(self):
        """scraped field must never be overwritten by update."""
        old = _make_listing(scraped="2026-01-01")
        _write_info_json(self._tmp, old)

        # New listing claims different scraped date
        new = _make_listing(scraped="2099-12-31")
        fo.update_listing_folder(self._tmp, new, old)

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["scraped"], "2026-01-01")  # preserved from disk

    # ── status is the archiver's job ──────────────────────────────────────────

    def test_status_not_touched_by_update(self):
        """update_listing_folder must not change an archived status to active."""
        old = _make_listing(status="archived")
        _write_info_json(self._tmp, old)

        # Incoming listing says active (e.g. normalise default)
        new = _make_listing(status="active")
        fo.update_listing_folder(self._tmp, new, old)

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "archived")  # preserved

    # ── localPhotos preserved ─────────────────────────────────────────────────

    def test_local_photos_preserved(self):
        """Existing photos on disk must not be wiped by update."""
        old = _make_listing(localPhotos=["photo_01.jpg", "photo_02.jpg"])
        _write_info_json(self._tmp, old)

        new = _make_listing(localPhotos=[])  # incoming has no photos
        fo.update_listing_folder(self._tmp, new, old)

        data = json.loads((self._tmp / "info.json").read_text(encoding="utf-8"))
        self.assertEqual(data["localPhotos"], ["photo_01.jpg", "photo_02.jpg"])

    # ── listing.html is rewritten ─────────────────────────────────────────────

    def test_listing_html_written(self):
        """listing.html must be created/updated alongside info.json."""
        listing = _make_listing()
        _write_info_json(self._tmp, listing)

        fo.update_listing_folder(self._tmp, listing, listing)

        self.assertTrue((self._tmp / "listing.html").exists())


if __name__ == "__main__":
    unittest.main()
