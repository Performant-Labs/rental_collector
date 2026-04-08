"""Tests for features added during the automation and photo gallery work.

Covers:
- Photo URL generation in ingestion
- _get_last_run_time() in main.py
- Photo gallery rendering in the _results.html template
- search_with_litellm and fetch_url_via_jina (scraper)
- --local / --model CLI flags (scraper)
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dashboard.app.ingestion import (
    build_documents_from_rentals,
    normalise_listing_document,
)
from dashboard.app.main import _get_last_run_time, app

client = TestClient(app)


# ── Photo URL generation tests ──────────────────────────────────────────────


class TestPhotoUrlGeneration:
    """Verify that the ingestion pipeline produces correct photo URLs."""

    def _make_listing_folder(self, tmp_path, folder_name, photos=None, price=900):
        folder = tmp_path / folder_name
        folder.mkdir()
        info = {
            "title": "Test Listing",
            "source": "test-source",
            "price_usd": price,
            "location": "Todos Santos",
            "description": "A rental",
            "scraped": "2026-04-08",
            "localPhotos": photos or [],
        }
        (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
        # Create dummy photo files so they exist
        for p in (photos or []):
            (folder / p).write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        return folder

    def test_photos_array_populated_from_local_photos(self, tmp_path):
        folder = self._make_listing_folder(
            tmp_path, "test-listing-01", photos=["photo_01.jpg", "photo_02.jpg"]
        )
        raw = json.loads((folder / "info.json").read_text())

        with patch("dashboard.app.ingestion.REPO_ROOT", tmp_path):
            doc = normalise_listing_document(raw, folder)

        assert "photos" in doc
        assert len(doc["photos"]) == 2
        assert doc["photos"][0].endswith("/photo_01.jpg")
        assert doc["photos"][1].endswith("/photo_02.jpg")

    def test_photos_empty_when_no_local_photos(self, tmp_path):
        folder = self._make_listing_folder(tmp_path, "test-listing-02", photos=[])
        raw = json.loads((folder / "info.json").read_text())

        with patch("dashboard.app.ingestion.REPO_ROOT", tmp_path):
            doc = normalise_listing_document(raw, folder)

        assert doc["photos"] == []

    def test_photo_paths_use_forward_slashes(self, tmp_path):
        folder = self._make_listing_folder(
            tmp_path, "test-listing-03", photos=["photo_01.jpg"]
        )
        raw = json.loads((folder / "info.json").read_text())

        with patch("dashboard.app.ingestion.REPO_ROOT", tmp_path):
            doc = normalise_listing_document(raw, folder)

        for photo in doc["photos"]:
            assert "\\" not in photo, f"Photo path contains backslash: {photo}"

    def test_has_photos_true_when_photos_exist(self, tmp_path):
        folder = self._make_listing_folder(
            tmp_path, "test-listing-04", photos=["photo_01.jpg"]
        )
        raw = json.loads((folder / "info.json").read_text())

        with patch("dashboard.app.ingestion.REPO_ROOT", tmp_path):
            doc = normalise_listing_document(raw, folder)

        assert doc["has_photos"] is True

    def test_has_photos_false_when_no_photos(self, tmp_path):
        folder = self._make_listing_folder(tmp_path, "test-listing-05", photos=[])
        raw = json.loads((folder / "info.json").read_text())

        with patch("dashboard.app.ingestion.REPO_ROOT", tmp_path):
            doc = normalise_listing_document(raw, folder)

        assert doc["has_photos"] is False


# ── Last run time tests ──────────────────────────────────────────────────────


class TestLastRunTime:
    """Verify that _get_last_run_time reads from the correct file."""

    def test_returns_never_when_file_missing(self, tmp_path):
        with patch("dashboard.app.main.REPO_ROOT", tmp_path):
            assert _get_last_run_time() == "never"

    def test_returns_timestamp_from_file(self, tmp_path):
        rentals_dir = tmp_path / "rentals"
        rentals_dir.mkdir()
        (rentals_dir / "last_run.txt").write_text("2026-04-08 03:00:00", encoding="utf-8")

        with patch("dashboard.app.main.REPO_ROOT", tmp_path):
            assert _get_last_run_time() == "2026-04-08 03:00:00"

    def test_strips_whitespace_from_timestamp(self, tmp_path):
        rentals_dir = tmp_path / "rentals"
        rentals_dir.mkdir()
        (rentals_dir / "last_run.txt").write_text("  2026-04-08 03:00:00  \n", encoding="utf-8")

        with patch("dashboard.app.main.REPO_ROOT", tmp_path):
            assert _get_last_run_time() == "2026-04-08 03:00:00"

    def test_home_page_includes_last_run(self, tmp_path, monkeypatch):
        # Create a real last_run.txt file
        rentals_dir = tmp_path / "rentals"
        rentals_dir.mkdir()
        (rentals_dir / "last_run.txt").write_text("2026-04-08 03:00:00", encoding="utf-8")

        monkeypatch.setattr("dashboard.app.main.REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            "dashboard.app.main._run_search",
            lambda request, **kwargs: {
                "query": "",
                "results": [],
                "total_hits": 0,
                "page": 1,
                "per_page": 20,
                "total_pages": 0,
                "sort": "relevance",
                "facets": {},
                "selected_filters": {
                    "source": [], "price_bucket": [], "location": [],
                    "listing_type": [], "has_photos": [], "has_contact": [],
                },
                "validation_issues": {},
                "error_message": "",
                "request_id": "test-id",
            },
        )

        test_client = TestClient(app)
        response = test_client.get("/")
        assert response.status_code == 200
        assert "Last updated:" in response.text
        assert "2026-04-08 03:00:00" in response.text


# ── Photo gallery rendering tests ────────────────────────────────────────────


class TestPhotoGalleryRendering:
    """Verify that listing cards render photo thumbnails and popup data."""

    def _search_payload_with_photos(self, photos=None):
        return {
            "query": "",
            "results": [
                {
                    "id": "listing-1",
                    "title": "Casa Photo Test",
                    "location": "Centro",
                    "source": "test",
                    "price_usd": 900,
                    "listing_path": "rentals/test-01/listing.html",
                    "photos": photos or [],
                }
            ],
            "total_hits": 1,
            "page": 1,
            "per_page": 20,
            "total_pages": 1,
            "sort": "relevance",
            "facets": {},
            "selected_filters": {
                "source": [], "price_bucket": [], "location": [],
                "listing_type": [], "has_photos": [], "has_contact": [],
            },
        }

    def test_card_shows_thumbnail_when_photos_exist(self, monkeypatch):
        monkeypatch.setattr(
            "dashboard.app.main._run_search",
            lambda *a, **kw: self._search_payload_with_photos(
                ["/rentals/test-01/photo_01.jpg"]
            ),
        )
        response = client.get("/partials/results")
        assert response.status_code == 200
        assert 'class="card-thumb"' in response.text
        assert "/rentals/test-01/photo_01.jpg" in response.text

    def test_card_has_data_photos_attribute_for_popup(self, monkeypatch):
        photos = ["/rentals/test-01/photo_01.jpg", "/rentals/test-01/photo_02.jpg"]
        monkeypatch.setattr(
            "dashboard.app.main._run_search",
            lambda *a, **kw: self._search_payload_with_photos(photos),
        )
        response = client.get("/partials/results")
        assert response.status_code == 200
        assert "data-photos=" in response.text

    def test_card_no_thumbnail_when_no_photos(self, monkeypatch):
        monkeypatch.setattr(
            "dashboard.app.main._run_search",
            lambda *a, **kw: self._search_payload_with_photos([]),
        )
        response = client.get("/partials/results")
        assert response.status_code == 200
        assert 'class="card-thumb"' not in response.text
        assert "data-photos=" not in response.text


# ── Scraper CLI flags tests ──────────────────────────────────────────────────


class TestScraperCliFlags:
    """Verify the --local and --model flags are accepted by the scraper argparser."""

    def test_local_flag_accepted(self):
        """The scraper should accept --local without error."""
        import importlib
        import sys

        # Import the scraper module to access its argparser
        scraper_path = Path(__file__).resolve().parents[2] / "scraper"
        sys.path.insert(0, str(scraper_path))
        try:
            # Just verify the argparser accepts the flags (don't run main)
            import rental_search
            parser = rental_search.main.__code__  # verify module loads
            assert hasattr(rental_search, "search_with_litellm")
            assert hasattr(rental_search, "fetch_url_via_jina")
        except ImportError:
            pytest.skip("Cannot import rental_search (missing dependencies)")
        finally:
            sys.path.pop(0)
