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
            "price_usd": 1200,
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))

    first = normalise_listing_document(raw, folder)
    second = normalise_listing_document(raw, folder)

    assert first["id"] == second["id"]
    assert first["id"] == stable_listing_id("airbnb", "https://example.com/listing/1", "Casita", folder.name)


def test_skips_invalid_listing_without_crashing(tmp_path: Path):
    # Valid rental with price
    _make_listing_folder(
        tmp_path,
        "airbnb-01-valid-1000usd",
        {"title": "Valid Title", "source": "airbnb", "price_usd": 1000},
    )
    # Missing title
    _make_listing_folder(
        tmp_path,
        "airbnb-02-invalid-1000usd",
        {"source": "airbnb", "price_usd": 1000},
    )
    # Missing price (like a tour/activity)
    _make_listing_folder(
        tmp_path,
        "airbnb-03-tour-no-price",
        {"title": "City Tour", "source": "airbnb"},
    )

    documents, warnings = build_documents_from_rentals(tmp_path)

    assert len(documents) == 1
    assert documents[0]["title"] == "Valid Title"
    assert len(warnings) == 2
    warning_folders = {w["folder"] for w in warnings}
    assert "airbnb-02-invalid-1000usd" in warning_folders
    assert "airbnb-03-tour-no-price" in warning_folders


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
    assert doc_camel["price_bucket"] == "1000+"

    # Test price_usd (snake_case fallback)
    folder_snake = _make_listing_folder(
        tmp_path,
        "airbnb-02-snake-1100usd",
        {"title": "SnakeCase Price", "price_usd": 1100},
    )
    raw_snake = json.loads((folder_snake / "info.json").read_text(encoding="utf-8"))
    doc_snake = normalise_listing_document(raw_snake, folder_snake)
    assert doc_snake["price_usd"] == 1100
    assert doc_snake["price_bucket"] == "1000+"


def test_price_bucket_computation():
    assert compute_price_bucket(None) == "unknown"
    assert compute_price_bucket(999) == "<1000"
    assert compute_price_bucket(1000) == "1000+"
    assert compute_price_bucket(1499) == "1000+"
    assert compute_price_bucket(1500) == "1500+"
    assert compute_price_bucket(1999) == "1500+"
    assert compute_price_bucket(2000) == "2000+"
    assert compute_price_bucket(2999) == "2500+"
    assert compute_price_bucket(3000) == "3000+"
    assert compute_price_bucket(5000) == "5000+"
    assert compute_price_bucket(10000) == "10000+"


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


def test_spanish_only_no_price_wa_listing_is_valid(tmp_path: Path):
    """
    A WhatsApp message in Spanish with no price must survive _is_valid_document()
    when it contains strong Spanish rental keywords.
    These were previously dropped before the fix.
    """
    spanish_phrases = [
        ("En renta casita en Pescadero", "en renta"),
        ("Casa en alquiler disponible ahora", "en alquiler"),
        ("Se arrienda departamento bonito", "se arrienda"),
        ("Casita disponible en Todos Santos", "casita"),
        ("Depto de 2 recámaras en el centro", "recámara"),
        ("Renta mensual de cuarto amueblado", "renta mensual"),
    ]
    for i, (title, phrase) in enumerate(spanish_phrases):
        folder = _make_listing_folder(
            tmp_path,
            f"whatsapp-{i:02d}-spanish-noprice",
            {
                "title": title,
                "source": "whatsapp",
                "price_usd": None,
                "description": f"Listing uses phrase: {phrase}",
            },
        )
        raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
        document = normalise_listing_document(raw, folder)
        from dashboard.app.ingestion import _is_valid_document
        assert _is_valid_document(document), (
            f"Spanish listing with '{phrase}' should be valid but was rejected"
        )


def test_unrelated_spanish_text_no_price_is_invalid(tmp_path: Path):
    """A listing with Spanish text but no rental keywords and no price must be rejected."""
    folder = _make_listing_folder(
        tmp_path,
        "whatsapp-00-not-a-rental",
        {
            "title": "Se vende tabla de surf usada",
            "source": "whatsapp",
            "price_usd": None,
            "description": "Buen estado, $200 firma",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    document = normalise_listing_document(raw, folder)
    from dashboard.app.ingestion import _is_valid_document
    assert not _is_valid_document(document)


def test_whatsapp_listing_with_price_always_valid(tmp_path: Path):
    """Any WA listing with a valid price passes regardless of language."""
    folder = _make_listing_folder(
        tmp_path,
        "whatsapp-01-has-price",
        {
            "title": "Tabla de surf",
            "source": "whatsapp",
            "price_usd": 500,
            "description": "nothing rental-related in text",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    document = normalise_listing_document(raw, folder)
    from dashboard.app.ingestion import _is_valid_document
    assert _is_valid_document(document)


# ── Phase 1: status / timestamp fields ───────────────────────────────────────

def test_document_has_status_field(tmp_path: Path):
    """normalise_listing_document must always emit a status field."""
    folder = _make_listing_folder(
        tmp_path,
        "airbnb-01-status-test",
        {"title": "Casa Test", "source": "airbnb", "price_usd": 900},
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    doc = normalise_listing_document(raw, folder)
    assert "status" in doc


def test_missing_status_in_info_json_defaults_to_active(tmp_path: Path):
    """Legacy info.json without status field must read as 'active'."""
    folder = _make_listing_folder(
        tmp_path,
        "airbnb-01-legacy",
        {"title": "Legacy Listing", "source": "airbnb", "price_usd": 750},
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    assert "status" not in raw  # confirm no status in file
    doc = normalise_listing_document(raw, folder)
    assert doc["status"] == "active"


def test_archived_status_passes_through(tmp_path: Path):
    """info.json with status='archived' must produce status='archived' in the doc."""
    folder = _make_listing_folder(
        tmp_path,
        "craigslist-01-archived",
        {
            "title": "Old Rental",
            "source": "craigslist",
            "price_usd": 600,
            "status": "archived",
            "archived_date": "2026-03-01",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    doc = normalise_listing_document(raw, folder)
    assert doc["status"] == "archived"
    assert doc["archived_date"] == "2026-03-01"


def test_last_checked_defaults_to_scraped_when_missing(tmp_path: Path):
    """Legacy info.json without last_checked falls back to scraped date."""
    folder = _make_listing_folder(
        tmp_path,
        "whatsapp-01-legacy",
        {
            "title": "WA Rental",
            "source": "whatsapp",
            "price_usd": 800,
            "scraped": "2026-03-15",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    doc = normalise_listing_document(raw, folder)
    assert doc["last_checked"] == "2026-03-15"


def test_last_updated_defaults_to_scraped_when_missing(tmp_path: Path):
    """Legacy info.json without last_updated falls back to scraped date."""
    folder = _make_listing_folder(
        tmp_path,
        "whatsapp-02-legacy",
        {
            "title": "WA Rental 2",
            "source": "whatsapp",
            "price_usd": 850,
            "scraped": "2026-03-20",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    doc = normalise_listing_document(raw, folder)
    assert doc["last_updated"] == "2026-03-20"


def test_explicit_last_checked_preserved(tmp_path: Path):
    """Explicit last_checked in info.json must not be overwritten."""
    folder = _make_listing_folder(
        tmp_path,
        "airbnb-02-checked",
        {
            "title": "Updated Casita",
            "source": "airbnb",
            "price_usd": 1000,
            "scraped": "2026-01-01",
            "last_checked": "2026-04-09",
            "last_updated": "2026-04-05",
        },
    )
    raw = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    doc = normalise_listing_document(raw, folder)
    assert doc["last_checked"] == "2026-04-09"
    assert doc["last_updated"] == "2026-04-05"
    assert doc["scraped"] == "2026-01-01"  # immutable
