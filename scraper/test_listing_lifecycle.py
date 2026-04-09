#!/usr/bin/env python3
"""
scraper/test_listing_lifecycle.py
==================================
End-to-end test demonstrating the full lifecycle of a rental listing:

  1.  NEW        listing appears in scrape → folder created, status=active
  2.  UNCHANGED  re-scraped with same data → last_checked bumped, last_updated unchanged
  3.  UPDATED    price changes → last_updated bumped, last_checked bumped
  4.  GONE       listing absent from scrape, within grace period → still active
  5.  ARCHIVED   listing absent past grace period → status=archived, archived_date set
  6.  RESTORED   listing reappears → status=active, archived_date cleared
"""

import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from shared.config import TODAY
from scraper.normalise import normalise
from scraper.folder_ops import save_listing_folder, update_listing_folder
from scraper.archiver import archive_gone_listings


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _read_info(folder: Path) -> dict:
    return json.loads((folder / "info.json").read_text(encoding="utf-8"))


class TestFullListingLifecycle(unittest.TestCase):
    """Walk a single listing through its complete lifecycle."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        # Patch the config so folder_ops and archiver use our temp dir
        self._patcher = patch("shared.config.DEFAULT_RENTALS_DIR", self._tmp)
        self._patcher.start()
        # Also patch inside scraper.folder_ops (it imports _config at module level)
        import scraper.folder_ops as fo
        self._orig_dir = fo._config.DEFAULT_RENTALS_DIR
        fo._config.DEFAULT_RENTALS_DIR = self._tmp

    def tearDown(self):
        self._patcher.stop()
        import scraper.folder_ops as fo
        fo._config.DEFAULT_RENTALS_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _listing(self, **overrides) -> dict:
        base = {
            "title": "Beach Studio Pescadero",
            "source": "airbnb",
            "price_usd": 1200,
            "bedrooms": "1BR",
            "location": "Pescadero",
            "url": "https://airbnb.com/rooms/12345",
            "contact": None,
            "description": "Cozy beachside studio.",
            "amenities": ["WiFi", "AC"],
            "rating": None,
            "listing_type": None,
            "checkin": None,
            "checkout": None,
            "photo_url": None,
        }
        base.update(overrides)
        return normalise(base, "airbnb")

    def _find_folder(self) -> Path:
        folders = [f for f in self._tmp.iterdir() if f.is_dir() and f.name.startswith("airbnb-")]
        self.assertEqual(len(folders), 1, f"Expected exactly 1 airbnb folder, found: {[f.name for f in folders]}")
        return folders[0]

    # ── Step 1: New listing ───────────────────────────────────────────────────

    def test_1_new_listing_created_as_active(self):
        """A newly scraped listing is saved with status=active."""
        listing = self._listing()
        save_listing_folder(listing, index=1)

        folder = self._find_folder()
        info = _read_info(folder)

        self.assertEqual(info["status"], "active")
        self.assertEqual(info["price_usd"], 1200)
        self.assertEqual(info["last_checked"], TODAY)
        self.assertEqual(info["scraped"], TODAY)
        self.assertTrue((folder / "listing.html").exists())

    # ── Step 2: Re-scraped unchanged ─────────────────────────────────────────

    def test_2_unchanged_rescrape_only_bumps_last_checked(self):
        """Same data re-scraped → last_checked updated, last_updated unchanged."""
        # Simulate an old listing (scraped + last_updated = 5 days ago)
        old_date = _days_ago(5)
        old_info = self._listing()
        old_info["scraped"] = old_date
        old_info["last_checked"] = old_date
        old_info["last_updated"] = old_date

        folder = self._tmp / "airbnb-01-beach-studio-pescadero-1200usd"
        folder.mkdir()
        (folder / "info.json").write_text(
            json.dumps(old_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")

        # Re-scrape with identical data
        same_listing = self._listing()
        changed = update_listing_folder(folder, same_listing, old_info)

        info = _read_info(folder)
        self.assertFalse(changed)
        self.assertEqual(info["last_checked"], TODAY)      # bumped
        self.assertEqual(info["last_updated"], old_date)  # unchanged
        self.assertEqual(info["scraped"], old_date)        # immutable

    # ── Step 3: Price change ──────────────────────────────────────────────────

    def test_3_price_change_bumps_last_updated(self):
        """Price change → both last_checked and last_updated updated."""
        old_date = _days_ago(3)
        old_info = self._listing(price_usd=1200)
        old_info["scraped"] = old_date
        old_info["last_checked"] = old_date
        old_info["last_updated"] = old_date

        folder = self._tmp / "airbnb-01-beach-studio-pescadero-1200usd"
        folder.mkdir()
        (folder / "info.json").write_text(
            json.dumps(old_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")

        new_listing = self._listing(price_usd=950)  # price dropped
        changed = update_listing_folder(folder, new_listing, old_info)

        info = _read_info(folder)
        self.assertTrue(changed)
        self.assertEqual(info["price_usd"], 950)
        self.assertEqual(info["last_checked"], TODAY)
        self.assertEqual(info["last_updated"], TODAY)  # bumped because price changed
        self.assertEqual(info["scraped"], old_date)    # still immutable

    # ── Step 4: Gone but within grace period ─────────────────────────────────

    def test_4_absent_within_grace_period_not_archived(self):
        """Listing absent for 3 days (< 7-day grace) → still active."""
        recent = _days_ago(3)
        info = self._listing()
        info["last_checked"] = recent

        folder = self._tmp / "airbnb-01-beach-studio-pescadero-1200usd"
        folder.mkdir()
        (folder / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")

        # Scrape returns other listings — not this one
        other_urls = [
            "https://airbnb.com/rooms/99991",
            "https://airbnb.com/rooms/99992",
            "https://airbnb.com/rooms/99993",
        ]
        result = archive_gone_listings("airbnb", other_urls, self._tmp, grace_days=7)

        info = _read_info(folder)
        self.assertEqual(info["status"], "active")  # grace period not expired
        self.assertEqual(result["archived"], 0)

    # ── Step 5: Archived after grace period ───────────────────────────────────

    def test_5_absent_past_grace_period_archived(self):
        """Listing absent for 8 days (> 7-day grace) → archived."""
        stale = _days_ago(8)
        info = self._listing()
        info["last_checked"] = stale

        folder = self._tmp / "airbnb-01-beach-studio-pescadero-1200usd"
        folder.mkdir()
        (folder / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")

        other_urls = [
            "https://airbnb.com/rooms/99991",
            "https://airbnb.com/rooms/99992",
            "https://airbnb.com/rooms/99993",
        ]
        result = archive_gone_listings("airbnb", other_urls, self._tmp, grace_days=7)

        info = _read_info(folder)
        self.assertEqual(info["status"], "archived")
        self.assertEqual(info["archived_date"], TODAY)
        self.assertEqual(result["archived"], 1)
        # HTML is regenerated with archived status
        self.assertTrue((folder / "listing.html").exists())

    # ── Step 6: Restored when listing reappears ───────────────────────────────

    def test_6_restored_when_listing_reappears(self):
        """Archived listing reappears in scrape → status=active, archived_date cleared."""
        url = "https://airbnb.com/rooms/12345"
        info = self._listing()
        info["status"] = "archived"
        info["archived_date"] = _days_ago(5)
        info["last_checked"] = _days_ago(13)

        folder = self._tmp / "airbnb-01-beach-studio-pescadero-1200usd"
        folder.mkdir()
        (folder / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")

        # This listing URL is back in the scrape results
        active_urls = [url, "https://airbnb.com/rooms/99991", "https://airbnb.com/rooms/99992"]
        result = archive_gone_listings("airbnb", active_urls, self._tmp, grace_days=7)

        info = _read_info(folder)
        self.assertEqual(info["status"], "active")
        self.assertIsNone(info.get("archived_date"))
        self.assertEqual(info["last_checked"], TODAY)
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["archived"], 0)

    # ── Full chained narrative ────────────────────────────────────────────────

    def test_full_lifecycle_chain(self):
        """
        Run all lifecycle stages in sequence on a single folder:
        create → unchanged → price-change → grace → archive → restore
        """
        url = "https://airbnb.com/rooms/12345"
        others = ["https://airbnb.com/rooms/x1", "https://airbnb.com/rooms/x2",
                  "https://airbnb.com/rooms/x3"]

        # ── 1. Create ────────────────────────────────────────────────────────
        listing_v1 = self._listing(price_usd=1200)
        folder = self._tmp / "airbnb-01-beach-studio-pescadero-1200usd"
        folder.mkdir()
        listing_v1["last_checked"] = _days_ago(10)
        listing_v1["last_updated"] = _days_ago(10)
        listing_v1["scraped"]      = _days_ago(10)
        (folder / "info.json").write_text(
            json.dumps(listing_v1, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (folder / "listing.html").write_text("<html></html>", encoding="utf-8")

        info = _read_info(folder)
        self.assertEqual(info["status"], "active")

        # ── 2. Re-scraped unchanged ──────────────────────────────────────────
        same = self._listing(price_usd=1200)
        update_listing_folder(folder, same, listing_v1)
        info = _read_info(folder)
        self.assertEqual(info["last_checked"], TODAY)
        self.assertEqual(info["last_updated"], _days_ago(10))  # not bumped

        # ── 3. Price change ──────────────────────────────────────────────────
        cheaper = self._listing(price_usd=950)
        update_listing_folder(folder, cheaper, listing_v1)
        info = _read_info(folder)
        self.assertEqual(info["price_usd"], 950)
        self.assertEqual(info["last_updated"], TODAY)

        # ── 4. Gone within grace period ──────────────────────────────────────
        # Simulate last_checked 3 days ago so grace period hasn't expired
        info["last_checked"] = _days_ago(3)
        (folder / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        archive_gone_listings("airbnb", others, self._tmp, grace_days=7)
        info = _read_info(folder)
        self.assertEqual(info["status"], "active")  # still active

        # ── 5. Archived after grace period ───────────────────────────────────
        info["last_checked"] = _days_ago(8)
        (folder / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        result = archive_gone_listings("airbnb", others, self._tmp, grace_days=7)
        info = _read_info(folder)
        self.assertEqual(info["status"], "archived")
        self.assertEqual(result["archived"], 1)

        # ── 6. Restored ──────────────────────────────────────────────────────
        result = archive_gone_listings("airbnb", [url] + others, self._tmp, grace_days=7)
        info = _read_info(folder)
        self.assertEqual(info["status"], "active")
        self.assertIsNone(info.get("archived_date"))
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["archived"], 0)


if __name__ == "__main__":
    unittest.main()
