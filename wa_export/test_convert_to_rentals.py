#!/usr/bin/env python3
"""
Tests for wa_export/convert_to_rentals.py

Phase 1: Constants and scaffold
Phase 2: Dedup, field mapping, save/diff
Phase 3: Folder generation, media copy
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Module is in the same directory; tests are run from the project root or wa_export/
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import convert_to_rentals as cr


# ── Phase 1: Constants ────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_min_score_default_is_15(self):
        self.assertEqual(cr.MIN_SCORE, 15)

    def test_source_name_is_whatsapp(self):
        self.assertEqual(cr.SOURCE, "whatsapp")

    def test_max_usd_matches_project(self):
        """Must match rental_search.py's MAX_USD so filters are consistent."""
        self.assertEqual(cr.MAX_USD, 2000)

    def test_wa_rentals_path_is_under_wa_export(self):
        """Input rentals.json must be inside wa_export/output/."""
        self.assertIn("wa_export", str(cr.WA_RENTALS_PATH))
        self.assertTrue(str(cr.WA_RENTALS_PATH).endswith("rentals.json"))

    def test_results_dir_points_to_rentals_folder(self):
        """Output goes into the shared rentals/ directory at the project root."""
        self.assertTrue(str(cr.RESULTS_DIR).endswith("rentals"))


# ── Phase 2: Text fingerprint ─────────────────────────────────────────────────

class TestTextFingerprint(unittest.TestCase):

    def test_uses_first_200_chars(self):
        msg = {"text": "A" * 300}
        self.assertEqual(len(cr._text_fingerprint(msg)), 200)

    def test_case_insensitive(self):
        a = cr._text_fingerprint({"text": "HELLO WORLD"})
        b = cr._text_fingerprint({"text": "hello world"})
        self.assertEqual(a, b)

    def test_prefers_text_over_media_title(self):
        msg = {"text": "real text", "media_title": "caption"}
        self.assertIn("real text", cr._text_fingerprint(msg))

    def test_falls_back_to_media_title_when_no_text(self):
        msg = {"text": None, "media_title": "caption text"}
        self.assertIn("caption text", cr._text_fingerprint(msg))

    def test_empty_message_returns_empty_string(self):
        self.assertEqual(cr._text_fingerprint({}), "")

    def test_strips_leading_whitespace(self):
        msg = {"text": "   hello"}
        self.assertEqual(cr._text_fingerprint(msg), "hello")


# ── Phase 2: Dedup ────────────────────────────────────────────────────────────

class TestDedup(unittest.TestCase):

    def _msg(self, text, score=20, ts="2025-01-01T00:00:00+00:00"):
        return {"text": text, "rental_score": score, "timestamp": ts}

    def test_drops_duplicate_text(self):
        msgs = [self._msg("Casa en renta"), self._msg("Casa en renta")]
        result = cr.dedup_messages(msgs)
        self.assertEqual(len(result), 1)

    def test_keeps_highest_score_among_duplicates(self):
        msgs = [self._msg("Casa en renta", score=20), self._msg("Casa en renta", score=35)]
        result = cr.dedup_messages(msgs)
        self.assertEqual(result[0]["rental_score"], 35)

    def test_different_texts_both_kept(self):
        msgs = [self._msg("House for rent $1200"), self._msg("Casita en renta $900")]
        self.assertEqual(len(cr.dedup_messages(msgs)), 2)

    def test_empty_list(self):
        self.assertEqual(cr.dedup_messages([]), [])

    def test_dedup_by_first_200_chars_not_full_text(self):
        """Two messages that share the first 200 chars should be collapsed."""
        base = "x" * 200
        msgs = [
            self._msg(base + " extra A", score=25),
            self._msg(base + " extra B", score=15),
        ]
        result = cr.dedup_messages(msgs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rental_score"], 25)

    def test_message_with_no_text_kept_without_dedup(self):
        """Image-only messages with no text should always pass through."""
        msgs = [
            {"text": None, "media_title": None, "rental_score": 20},
            {"text": None, "media_title": None, "rental_score": 18},
        ]
        result = cr.dedup_messages(msgs)
        self.assertEqual(len(result), 2)


# ── Phase 2: Score filter ─────────────────────────────────────────────────────

class TestScoreFilter(unittest.TestCase):

    def _make_input(self, scores):
        return [{"text": f"msg {s}", "rental_score": s, "timestamp": "2025-01-01T00:00:00+00:00",
                 "media_file": None} for s in scores]

    def _run(self, scores, min_score=15):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(self._make_input(scores), f)
            path = Path(f.name)
        try:
            return cr.load_and_filter(path, min_score)
        finally:
            path.unlink()

    def test_drops_below_min_score(self):
        result = self._run([10, 14, 15, 20])
        returned_descs = [l["description"] for l in result]
        self.assertNotIn("msg 10", returned_descs)
        self.assertNotIn("msg 14", returned_descs)

    def test_keeps_at_min_score(self):
        result = self._run([15])
        self.assertEqual(len(result), 1)

    def test_custom_min_score(self):
        result = self._run([15, 25, 30], min_score=25)
        self.assertEqual(len(result), 2)


# ── Phase 2: Field mapping ────────────────────────────────────────────────────

def _make_msg(text="Casa en renta $1,200/mes", score=20, ts="2025-06-01T14:00:00+00:00",
              media_file=None, phone="+526121234567"):
    return {
        "text":         text,
        "rental_score": score,
        "timestamp":    ts,
        "media_file":   media_file,
        "phone":        phone,
        "media_title":  None,
    }


class TestFieldMapping(unittest.TestCase):

    def test_canonical_keys_present(self):
        result = cr.convert_message(_make_msg())
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "localPhotos",
                    "_wa_score", "_wa_media_file", "_wa_id"}
        self.assertEqual(set(result.keys()), expected)

    def test_source_is_whatsapp(self):
        self.assertEqual(cr.convert_message(_make_msg())["source"], "whatsapp")

    def test_title_is_first_line_of_text(self):
        msg = _make_msg(text="Casa en renta\nMore details here")
        self.assertEqual(cr.convert_message(msg)["title"], "Casa en renta")

    def test_title_truncated_to_80(self):
        msg = _make_msg(text="A" * 100)
        self.assertLessEqual(len(cr.convert_message(msg)["title"]), 80)

    def test_title_falls_back_to_media_title(self):
        msg = _make_msg(text=None)
        msg["media_title"] = "Nice casita"
        self.assertEqual(cr.convert_message(msg)["title"], "Nice casita")

    def test_price_extracted_from_usd(self):
        msg = _make_msg(text="House for rent $1,500/month")
        self.assertEqual(cr.convert_message(msg)["price_usd"], 1500)

    def test_price_extracted_from_mxn(self):
        msg = _make_msg(text="Renta $18,000 pesos mensuales")
        price = cr.convert_message(msg)["price_usd"]
        self.assertIsNotNone(price)
        self.assertEqual(price, round(18000 / 17.5))

    def test_price_null_when_not_found(self):
        msg = _make_msg(text="Great house near the beach!")
        self.assertIsNone(cr.convert_message(msg)["price_usd"])

    def test_price_over_max_excluded_by_load_and_filter(self):
        """Listings over MAX_USD must be excluded at the load_and_filter level."""
        msgs = [_make_msg(text="Penthouse $3,000/month", score=20)]
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(msgs, f)
            path = Path(f.name)
        try:
            result = cr.load_and_filter(path, min_score=15)
            self.assertEqual(result, [])
        finally:
            path.unlink()

    def test_bedrooms_extracted_1br(self):
        msg = _make_msg(text="Nice 1BR studio apartment")
        self.assertIn("1", cr.convert_message(msg)["bedrooms"] or "")

    def test_bedrooms_extracted_2_bedroom(self):
        msg = _make_msg(text="2 bedroom house for rent $1,200")
        beds = cr.convert_message(msg)["bedrooms"]
        self.assertIsNotNone(beds)
        self.assertIn("2", beds)

    def test_bedrooms_null_when_not_found(self):
        msg = _make_msg(text="Great studio near the beach $800")
        self.assertIsNone(cr.convert_message(msg)["bedrooms"])

    def test_contact_extracted_from_text_phone(self):
        msg = _make_msg(text="Contact: 612-202-1988 for info")
        contact = cr.convert_message(msg)["contact"]
        self.assertIsNotNone(contact)
        self.assertIn("612", contact)

    def test_contact_falls_back_to_phone_field(self):
        msg = _make_msg(text="Call me for info", phone="+526121234567")
        contact = cr.convert_message(msg)["contact"]
        self.assertIsNotNone(contact)
        self.assertIn("526121234567", contact)

    def test_description_is_full_text(self):
        msg = _make_msg(text="Full rental description here.")
        self.assertEqual(cr.convert_message(msg)["description"], "Full rental description here.")

    def test_description_falls_back_to_media_title(self):
        msg = _make_msg(text=None)
        msg["media_title"] = "Photo caption text"
        self.assertEqual(cr.convert_message(msg)["description"], "Photo caption text")

    def test_scraped_is_date_portion_of_timestamp(self):
        msg = _make_msg(ts="2025-06-15T14:30:00+00:00")
        self.assertEqual(cr.convert_message(msg)["scraped"], "2025-06-15")

    def test_local_photos_empty_initially(self):
        self.assertEqual(cr.convert_message(_make_msg())["localPhotos"], [])

    def test_amenities_is_empty_list(self):
        self.assertEqual(cr.convert_message(_make_msg())["amenities"], [])

    def test_url_is_null(self):
        self.assertIsNone(cr.convert_message(_make_msg())["url"])

    def test_rating_is_null(self):
        self.assertIsNone(cr.convert_message(_make_msg())["rating"])

    def test_listing_type_is_null(self):
        self.assertIsNone(cr.convert_message(_make_msg())["listing_type"])

    def test_checkin_is_null(self):
        self.assertIsNone(cr.convert_message(_make_msg())["checkin"])

    def test_checkout_is_null(self):
        self.assertIsNone(cr.convert_message(_make_msg())["checkout"])


# ── Phase 2: _parse_price_usd ─────────────────────────────────────────────────

class TestParsePriceUsd(unittest.TestCase):

    def test_dollar_amount(self):
        self.assertEqual(cr._parse_price_usd("$1,200/month"), 1200)

    def test_mxn_explicit(self):
        self.assertEqual(cr._parse_price_usd("17500 MXN"), 1000)

    def test_pesos_label(self):
        self.assertEqual(cr._parse_price_usd("18000 pesos"), round(18000 / 17.5))

    def test_large_dollar_treated_as_mxn(self):
        result = cr._parse_price_usd("$55,000")
        self.assertIsNotNone(result)
        self.assertLess(result, 5000)

    def test_no_price(self):
        self.assertIsNone(cr._parse_price_usd("nice place near beach"))

    def test_none_input(self):
        self.assertIsNone(cr._parse_price_usd(None))

    def test_commas_stripped(self):
        self.assertEqual(cr._parse_price_usd("$1,400"), 1400)


# ── Phase 2: Save / diff ──────────────────────────────────────────────────────

class TestSaveAndDiff(unittest.TestCase):

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._orig_dir = cr.RESULTS_DIR
        cr.RESULTS_DIR = self._tmp

    def tearDown(self):
        cr.RESULTS_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _listing(self, title="Studio", price=1000, score=20):
        return {
            "title": title, "source": cr.SOURCE, "price_usd": price,
            "bedrooms": None, "location": "Todos Santos", "url": None,
            "contact": None, "description": title, "amenities": [],
            "rating": None, "listing_type": None, "checkin": None,
            "checkout": None, "scraped": cr.TODAY, "localPhotos": [],
            "_wa_score": score, "_wa_media_file": None, "_wa_id": 1,
        }

    def test_creates_dated_json(self):
        path = cr.save_results([self._listing()], create_folders=False)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, f"{cr.SOURCE}-{cr.TODAY}.json")

    def test_content_is_valid_json_array(self):
        cr.save_results([self._listing()], create_folders=False)
        out = self._tmp / f"{cr.SOURCE}-{cr.TODAY}.json"
        data = json.loads(out.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_wa_internal_fields_stripped_from_json(self):
        cr.save_results([self._listing()], create_folders=False)
        out = self._tmp / f"{cr.SOURCE}-{cr.TODAY}.json"
        data = json.loads(out.read_text())
        for key in data[0].keys():
            self.assertFalse(key.startswith("_wa_"),
                             f"Internal field leaked into output: {key}")

    def test_all_canonical_keys_present(self):
        cr.save_results([self._listing()], create_folders=False)
        out = self._tmp / f"{cr.SOURCE}-{cr.TODAY}.json"
        data = json.loads(out.read_text())
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "localPhotos"}
        self.assertEqual(set(data[0].keys()), expected)

    def test_diff_no_previous_no_error(self):
        cr.diff_against_previous([self._listing()])   # should not raise

    def test_diff_detects_new_listing(self):
        prev = [self._listing("Old Place")]
        (self._tmp / f"{cr.SOURCE}-2026-01-01.json").write_text(
            json.dumps(prev), encoding="utf-8"
        )
        current = [self._listing("Old Place"), self._listing("New Place")]
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cr.diff_against_previous(current)
        self.assertIn("1 new listing", buf.getvalue())

    def test_diff_detects_removed_listing(self):
        prev = [self._listing("Gone Place"), self._listing("Still Here")]
        (self._tmp / f"{cr.SOURCE}-2026-01-01.json").write_text(
            json.dumps(prev), encoding="utf-8"
        )
        current = [self._listing("Still Here")]
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cr.diff_against_previous(current)
        self.assertIn("1 removed", buf.getvalue())


# ── Phase 3: Media copy ───────────────────────────────────────────────────────

class TestCopyMedia(unittest.TestCase):

    def setUp(self):
        self._tmp       = Path(tempfile.mkdtemp())
        self._media_dir = self._tmp / "media"
        self._media_dir.mkdir()
        self._dest      = self._tmp / "listing_folder"
        self._dest.mkdir()
        self._orig_media = cr.WA_MEDIA_DIR
        cr.WA_MEDIA_DIR  = self._media_dir

    def tearDown(self):
        cr.WA_MEDIA_DIR = self._orig_media
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_media(self, filename="12345.jpg") -> Path:
        p = self._media_dir / filename
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)   # minimal JPEG header
        return p

    def test_copies_file_to_dest_folder(self):
        self._make_media("12345.jpg")
        listing = {"_wa_media_file": "12345.jpg"}
        cr._copy_media(listing, self._dest)
        self.assertTrue((self._dest / "photo_01.jpg").exists())

    def test_returns_filename_list(self):
        self._make_media("12345.jpg")
        listing = {"_wa_media_file": "12345.jpg"}
        result = cr._copy_media(listing, self._dest)
        self.assertEqual(result, ["photo_01.jpg"])

    def test_missing_source_returns_empty(self):
        listing = {"_wa_media_file": "nonexistent.jpg"}
        result = cr._copy_media(listing, self._dest)
        self.assertEqual(result, [])

    def test_msg_without_media_file_returns_empty(self):
        result = cr._copy_media({"_wa_media_file": None}, self._dest)
        self.assertEqual(result, [])

    def test_copies_regardless_of_original_extension(self):
        """WA media might be .webp, .mp4, etc. — always renamed to photo_01.jpg."""
        self._make_media("12345.webp")
        listing = {"_wa_media_file": "12345.webp"}
        result = cr._copy_media(listing, self._dest)
        self.assertEqual(result, ["photo_01.jpg"])
        self.assertTrue((self._dest / "photo_01.jpg").exists())


# ── Phase 3: Folder generation ────────────────────────────────────────────────

class TestFolderGeneration(unittest.TestCase):

    def setUp(self):
        self._tmp       = Path(tempfile.mkdtemp())
        self._media_dir = self._tmp / "media"
        self._media_dir.mkdir()
        self._orig_results = cr.RESULTS_DIR
        self._orig_media   = cr.WA_MEDIA_DIR
        cr.RESULTS_DIR     = self._tmp / "rentals"
        cr.WA_MEDIA_DIR    = self._media_dir
        cr.RESULTS_DIR.mkdir()

    def tearDown(self):
        cr.RESULTS_DIR  = self._orig_results
        cr.WA_MEDIA_DIR = self._orig_media
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _listing(self, title="Studio Pescadero", price=900, media=None):
        return {
            "title": title, "source": cr.SOURCE, "price_usd": price,
            "bedrooms": "1 bedroom", "location": "Todos Santos", "url": None,
            "contact": "612-111-2222", "description": "Nice place.",
            "amenities": [], "rating": None, "listing_type": None,
            "checkin": None, "checkout": None, "scraped": cr.TODAY,
            "localPhotos": [],
            "_wa_score": 25, "_wa_media_file": media, "_wa_id": 42,
        }

    def _make_media(self, filename):
        p = self._media_dir / filename
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        return p

    def test_creates_info_json(self):
        cr.save_listing_folder(self._listing(), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        self.assertEqual(len(folders), 1)
        self.assertTrue((folders[0] / "info.json").exists())

    def test_info_json_has_canonical_keys(self):
        cr.save_listing_folder(self._listing(), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        data = json.loads((folders[0] / "info.json").read_text())
        expected = {"title", "source", "price_usd", "bedrooms", "location",
                    "url", "contact", "description", "amenities", "rating",
                    "listing_type", "checkin", "checkout", "scraped", "localPhotos"}
        self.assertEqual(set(data.keys()), expected)

    def test_info_json_no_internal_fields(self):
        cr.save_listing_folder(self._listing(), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        data = json.loads((folders[0] / "info.json").read_text())
        for key in data.keys():
            self.assertFalse(key.startswith("_wa_"))

    def test_info_json_has_local_photos_populated(self):
        self._make_media("42.jpg")
        cr.save_listing_folder(self._listing(media="42.jpg"), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        data = json.loads((folders[0] / "info.json").read_text())
        self.assertEqual(data["localPhotos"], ["photo_01.jpg"])

    def test_creates_listing_html(self):
        cr.save_listing_folder(self._listing(), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        self.assertTrue((folders[0] / "listing.html").exists())

    def test_listing_html_contains_title(self):
        cr.save_listing_folder(self._listing(), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        html = (folders[0] / "listing.html").read_text()
        self.assertIn("Studio Pescadero", html)

    def test_listing_html_contains_price(self):
        cr.save_listing_folder(self._listing(price=900), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        html = (folders[0] / "listing.html").read_text()
        self.assertIn("900", html)

    def test_listing_html_contains_photo_img_tag(self):
        self._make_media("42.jpg")
        cr.save_listing_folder(self._listing(media="42.jpg"), 1, {})
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        html = (folders[0] / "listing.html").read_text()
        self.assertIn("photo_01.jpg", html)

    def test_skips_existing_folder_same_price(self):
        slug = cr._slugify("Studio Pescadero")
        existing_folder = cr.RESULTS_DIR / "whatsapp-01-studio-pescadero-900usd"
        existing_folder.mkdir()
        info = self._listing()
        info_clean = {k: v for k, v in info.items() if not k.startswith("_wa_")}
        (existing_folder / "info.json").write_text(json.dumps(info_clean))
        existing = {slug: {"folder": existing_folder, "price": 900}}
        # Should return without creating a new folder
        cr.save_listing_folder(self._listing(), 1, existing)
        folders = list(cr.RESULTS_DIR.glob("whatsapp-*"))
        self.assertEqual(len(folders), 1)   # still only the original

    def test_updates_existing_folder_on_price_change(self):
        slug = cr._slugify("Studio Pescadero")
        existing_folder = cr.RESULTS_DIR / "whatsapp-01-studio-pescadero-800usd"
        existing_folder.mkdir()
        old_info = {**{k: v for k, v in self._listing(price=800).items()
                       if not k.startswith("_wa_")}}
        (existing_folder / "info.json").write_text(json.dumps(old_info))
        existing = {slug: {"folder": existing_folder, "price": 800}}

        cr.save_listing_folder(self._listing(price=900), 1, existing)
        data = json.loads((existing_folder / "info.json").read_text())
        self.assertEqual(data["price_usd"], 900)

    def test_folder_name_format(self):
        listing = self._listing(title="Casa Avellana", price=1000)
        name = cr._folder_name(listing, 3)
        self.assertTrue(name.startswith("whatsapp-03-"))
        self.assertIn("1000usd", name)

    def test_folder_name_no_price(self):
        listing = self._listing(title="Casa", price=None)
        name = cr._folder_name(listing, 1)
        self.assertIn("noprice", name)


if __name__ == "__main__":
    unittest.main()
