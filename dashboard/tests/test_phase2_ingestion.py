import json
from pathlib import Path

from dashboard.app.ingestion import (
    build_documents_from_rentals,
    compute_price_bucket,
    discover_listing_folders,
    idempotent_upsert_documents,
    normalise_listing_document,
    stable_listing_id,
)


def _make_listing_folder(
    base: Path,
    folder_name: str,
    info: dict,
) -> Path:
    folder = base / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
    (folder / "listing.html").write_text("<html></html>", encoding="utf-8")
    return folder


def test_discovers_listing_folders(tmp_path: Path):
    _make_listing_folder(
        tmp_path,
        "airbnb-01-example-1000usd",
        {"title": "One", "source": "airbnb"},
    )
    not_a_listing = tmp_path / "misc-folder"
    not_a_listing.mkdir()

    folders = discover_listing_folders(tmp_path)

    assert len(folders) == 1
    assert folders[0].name == "airbnb-01-example-1000usd"


def test_parses_info_json_to_document(tmp_path: Path):
    folder = _make_listing_folder(
        tmp_path,
        "craigslist-01-studio-900usd",
        {
            "title": "Studio Centro",
            "source": "craigslist",
            "price_usd": 900,
            "location": "Centro",
            "description": "Quiet studio",
            "localPhotos": ["photo_01.jpg"],
            "contact": "example@email.com",
            "scraped": "2026-04-06",
        },
    )

    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    document = normalise_listing_document(raw, folder)

    assert document["title"] == "Studio Centro"
    assert document["source"] == "craigslist"
    assert document["price_usd"] == 900
    assert document["price_bucket"] == "<1000"
    assert document["has_photos"] is True
    assert document["has_contact"] is True


def test_generates_stable_document_id(tmp_path: Path):
    folder = _make_listing_folder(
        tmp_path,
        "airbnb-01-casita-1200usd",
        {
            "title": "Casita",
            "source": "airbnb",
            "url": "https://example.com/listing/1",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))

    first = normalise_listing_document(raw, folder)
    second = normalise_listing_document(raw, folder)

    assert first["id"] == second["id"]
    assert first["id"] == stable_listing_id("airbnb", "https://example.com/listing/1", "Casita", folder.name)


def test_skips_invalid_listing_without_crashing(tmp_path: Path):
    _make_listing_folder(
        tmp_path,
        "airbnb-01-valid-1000usd",
        {"title": "Valid Title", "source": "airbnb"},
    )
    _make_listing_folder(
        tmp_path,
        "airbnb-02-invalid-1000usd",
        {"source": "airbnb"},
    )

    documents, warnings = build_documents_from_rentals(tmp_path)

    assert len(documents) == 1
    assert documents[0]["title"] == "Valid Title"
    assert len(warnings) == 1
    assert warnings[0]["folder"] == "airbnb-02-invalid-1000usd"


def test_price_extraction_supports_both_camel_and_snake_case(tmp_path: Path):
    # Test usdPerMonth (camelCase from scraper)
    folder_camel = _make_listing_folder(
        tmp_path,
        "airbnb-01-camel-1200usd",
        {"title": "CamelCase Price", "usdPerMonth": 1200},
    )
    raw_camel = json.loads((folder_camel / "info.json").read_text(encoding="utf-8"))
    doc_camel = normalise_listing_document(raw_camel, folder_camel)
    assert doc_camel["price_usd"] == 1200
    assert doc_camel["price_bucket"] == "1000-1499"

    # Test price_usd (snake_case fallback)
    folder_snake = _make_listing_folder(
        tmp_path,
        "airbnb-02-snake-1100usd",
        {"title": "SnakeCase Price", "price_usd": 1100},
    )
    raw_snake = json.loads((folder_snake / "info.json").read_text(encoding="utf-8"))
    doc_snake = normalise_listing_document(raw_snake, folder_snake)
    assert doc_snake["price_usd"] == 1100
    assert doc_snake["price_bucket"] == "1000-1499"


def test_price_bucket_computation():
    assert compute_price_bucket(None) == "unknown"
    assert compute_price_bucket(999) == "<1000"
    assert compute_price_bucket(1000) == "1000-1499"
    assert compute_price_bucket(1499) == "1000-1499"
    assert compute_price_bucket(1500) == "1500-2000"


def test_idempotent_upsert_documents():
    existing = [
        {"id": "listing-1", "title": "Old Title", "price_usd": 900},
        {"id": "listing-2", "title": "Keep", "price_usd": 1100},
    ]
    updates = [
        {"id": "listing-1", "title": "New Title", "price_usd": 950},
        {"id": "listing-3", "title": "Added", "price_usd": 1200},
    ]

    merged = idempotent_upsert_documents(existing, updates)

    assert [doc["id"] for doc in merged] == ["listing-1", "listing-2", "listing-3"]
    assert merged[0]["title"] == "New Title"
    assert merged[1]["title"] == "Keep"
    assert merged[2]["title"] == "Added"
