#!/usr/bin/env python3
"""
Phase 4: End-to-end tests for wa_import/convert_to_rentals.py

Runs the complete pipeline against a small fixture file and validates
all output on disk.  No network access, no real data files required.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import convert_to_rentals as cr

# Canonical field set (no internal _wa_ fields)
CANONICAL_KEYS = {
    "title", "source", "price_usd", "bedrooms", "location",
    "url", "contact", "description", "amenities", "rating",
    "listing_type", "checkin", "checkout", "scraped", "localPhotos",
}

_FIXTURE_DIR   = Path(__file__).parent / "test_fixtures"
_FIXTURE_JSON  = _FIXTURE_DIR / "rentals_fixture.json"
_FIXTURE_MEDIA = _FIXTURE_DIR / "media"


class TestEndToEndConversion(unittest.TestCase):
    """
    Fixture contents (6 messages):
      id 1001 — score 41, text-only, $18,000 MXN (~$1,028 USD), unique text
      id 1002 — score 35, DUPLICATE of 1001 (same first-200-char fingerprint) → dropped
      id 1003 — score 33, text-only, $17,000 MXN (~$971 USD), unique
      id 1004 — score 28, image with media_title (10,000 MXN ~$571 USD), has photo
      id 1005 — score 10, BELOW threshold (default 15) → excluded
      id 1006 — score 30, $3,500/month → OVER MAX_USD ($2,000) → excluded

    Expected survivors: ids 1001, 1003, 1004  (3 listings)
    """

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._results = self._tmp / "rentals"
        self._results.mkdir()

        # Redirect module globals so output goes to tmp
        self._orig_results  = cr.RESULTS_DIR
        self._orig_media    = cr.WA_MEDIA_DIR
        cr.RESULTS_DIR  = self._results
        cr.WA_MEDIA_DIR = _FIXTURE_MEDIA

        # Load + filter the fixture (min_score=15)
        self._listings = cr.load_and_filter(_FIXTURE_JSON, min_score=15)

    def tearDown(self):
        cr.RESULTS_DIR  = self._orig_results
        cr.WA_MEDIA_DIR = self._orig_media
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── Filtering & dedup ─────────────────────────────────────────────────────

    def test_correct_number_of_listings(self):
        """3 survivors: 1001 (kept over dup 1002), 1003, 1004. 1005 below score, 1006 over price."""
        self.assertEqual(len(self._listings), 3)

    def test_duplicate_removed(self):
        """id 1002 is a duplicate of 1001 with lower score — must be gone."""
        ids = [l.get("_wa_id") for l in self._listings]
        self.assertNotIn(1002, ids)

    def test_high_score_duplicate_kept(self):
        """id 1001 (score 41) beats id 1002 (score 35) and survives."""
        ids = [l.get("_wa_id") for l in self._listings]
        self.assertIn(1001, ids)

    def test_below_threshold_excluded(self):
        """id 1005 has score 10 < 15 — must be excluded."""
        ids = [l.get("_wa_id") for l in self._listings]
        self.assertNotIn(1005, ids)

    def test_over_max_usd_excluded(self):
        """id 1006 at $3,500/month exceeds MAX_USD — must be excluded."""
        ids = [l.get("_wa_id") for l in self._listings]
        self.assertNotIn(1006, ids)

    def test_no_entry_exceeds_max_usd(self):
        for listing in self._listings:
            if listing["price_usd"] is not None:
                self.assertLessEqual(listing["price_usd"], cr.MAX_USD,
                                     f"Price {listing['price_usd']} exceeds MAX_USD")

    def test_no_entry_below_min_score(self):
        for listing in self._listings:
            score = listing.get("_wa_score") or 0
            self.assertGreaterEqual(score, 15)

    # ── Schema correctness ────────────────────────────────────────────────────

    def test_all_entries_have_canonical_keys(self):
        for listing in self._listings:
            public_keys = {k for k in listing.keys() if not k.startswith("_wa_")}
            self.assertEqual(public_keys, CANONICAL_KEYS,
                             f"Schema mismatch for listing: {listing.get('title')}")

    def test_source_is_whatsapp_for_all(self):
        for listing in self._listings:
            self.assertEqual(listing["source"], "whatsapp")

    def test_mxn_price_converted(self):
        """$18,000 MXN at 17.5 → ~$1,028 USD."""
        top = next(l for l in self._listings if l.get("_wa_id") == 1001)
        self.assertIsNotNone(top["price_usd"])
        self.assertAlmostEqual(top["price_usd"], round(18000 / 17.5), delta=5)

    def test_image_listing_has_media_title_as_description(self):
        img = next(l for l in self._listings if l.get("_wa_id") == 1004)
        self.assertIn("Casita en renta", img["description"])

    # ── Summary JSON ──────────────────────────────────────────────────────────

    def test_summary_json_created(self):
        cr.save_results(self._listings, create_folders=False)
        out = self._results / f"whatsapp-{cr.TODAY}.json"
        self.assertTrue(out.exists())

    def test_summary_json_is_valid_array(self):
        cr.save_results(self._listings, create_folders=False)
        out = self._results / f"whatsapp-{cr.TODAY}.json"
        data = json.loads(out.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)

    def test_summary_no_internal_fields(self):
        cr.save_results(self._listings, create_folders=False)
        out = self._results / f"whatsapp-{cr.TODAY}.json"
        data = json.loads(out.read_text())
        for entry in data:
            for key in entry.keys():
                self.assertFalse(key.startswith("_wa_"),
                                 f"Internal field in summary JSON: {key}")

    # ── Listing folders ───────────────────────────────────────────────────────

    def test_listing_folders_created(self):
        cr.save_results(self._listings, create_folders=True)
        folders = [p for p in self._results.glob("whatsapp-*") if p.is_dir()]
        self.assertEqual(len(folders), 3)

    def test_each_folder_has_info_json(self):
        cr.save_results(self._listings, create_folders=True)
        for folder in [p for p in self._results.glob("whatsapp-*") if p.is_dir()]:
            self.assertTrue((folder / "info.json").exists(), f"Missing info.json in {folder.name}")

    def test_each_folder_has_listing_html(self):
        cr.save_results(self._listings, create_folders=True)
        for folder in [p for p in self._results.glob("whatsapp-*") if p.is_dir()]:
            self.assertTrue((folder / "listing.html").exists(), f"Missing listing.html in {folder.name}")

    def test_each_info_json_has_canonical_keys(self):
        cr.save_results(self._listings, create_folders=True)
        for folder in [p for p in self._results.glob("whatsapp-*") if p.is_dir()]:
            data = json.loads((folder / "info.json").read_text())
            self.assertEqual(set(data.keys()), CANONICAL_KEYS,
                             f"Schema mismatch in {folder.name}/info.json")

    def test_media_copied_for_image_message(self):
        cr.save_results(self._listings, create_folders=True)
        # id 1004 has media_file = "fixture_photo.jpg"
        # Find its folder by checking info.json for the matching listing
        found = False
        for folder in [p for p in self._results.glob("whatsapp-*") if p.is_dir()]:
            info = json.loads((folder / "info.json").read_text())
            if info.get("localPhotos"):
                self.assertTrue((folder / "photo_01.jpg").exists(),
                                 f"Missing photo_01.jpg in {folder.name}")
                found = True
        self.assertTrue(found, "No folder with a copied photo was found")

    def test_no_media_for_text_only_messages(self):
        cr.save_results(self._listings, create_folders=True)
        for folder in [p for p in self._results.glob("whatsapp-*") if p.is_dir()]:
            info = json.loads((folder / "info.json").read_text())
            if not info.get("localPhotos"):
                self.assertFalse((folder / "photo_01.jpg").exists(),
                                  f"Unexpected photo in text-only folder {folder.name}")

    # ── Diff behaviour ────────────────────────────────────────────────────────

    def test_diff_no_changes_on_second_run(self):
        """Writing prior-dated JSON with same listings → 0 new + 0 removed."""
        # Write a "previous run" file with a past date
        prev_file = self._results / f"whatsapp-2026-01-01.json"
        clean = [{k: v for k, v in l.items() if not k.startswith("_wa_")}
                 for l in self._listings]
        prev_file.write_text(json.dumps(clean), encoding="utf-8")

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cr.diff_against_previous(self._listings)
        output = buf.getvalue()
        self.assertIn("0 new listing", output)
        self.assertIn("0 removed", output)

    def test_diff_detects_added_listing(self):
        """Prior run had 2 listings; current has 3 → detects 1 new."""
        subset = self._listings[:2]
        clean_subset = [{k: v for k, v in l.items() if not k.startswith("_wa_")}
                        for l in subset]
        prev_file = self._results / "whatsapp-2026-01-01.json"
        prev_file.write_text(json.dumps(clean_subset), encoding="utf-8")

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cr.diff_against_previous(self._listings)   # full set has 1 extra
        self.assertIn("1 new listing", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
