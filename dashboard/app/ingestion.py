import hashlib
import json
import re
from pathlib import Path
from typing import Any

from shared.config import REPO_ROOT, DEFAULT_RENTALS_DIR

from shared.keywords import RENTAL_KEYWORDS_STRONG

# Backward-compat alias
_RENTAL_KEYWORDS_STRONG = RENTAL_KEYWORDS_STRONG


def discover_listing_folders(rentals_dir: Path = DEFAULT_RENTALS_DIR) -> list[Path]:
    if not rentals_dir.exists():
        return []

    folders = [
        path
        for path in rentals_dir.iterdir()
        if path.is_dir() and (path / "info.json").exists()
    ]
    return sorted(folders, key=lambda path: path.name)


def parse_listing_info(info_path: Path) -> dict[str, Any]:
    return json.loads(info_path.read_text(encoding="utf-8"))


def compute_price_bucket(price_usd: int | None) -> str:
    """Compute price bucket in $500 chunks, no upper limit."""
    if price_usd is None:
        return "unknown"
    if price_usd < 1000:
        return "<1000"
    # $500 chunks with no maximum
    bucket_start = (price_usd // 500) * 500
    return f"{bucket_start}+"


def stable_listing_id(source: str, url: str | None, title: str, folder_name: str) -> str:
    key = f"{source}|{url or ''}|{title.strip().lower()}|{folder_name}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"listing-{digest[:16]}"


def _normalise_location(raw_location: Any) -> str:
    location = str(raw_location or "Todos Santos").strip()
    return re.sub(r"\s+", " ", location)


def _normalise_source(raw_source: Any, folder_name: str) -> str:
    if raw_source and str(raw_source).strip():
        return str(raw_source).strip().lower()
    return folder_name.split("-", 1)[0].strip().lower()


def _is_valid_document(document: dict[str, Any]) -> bool:
    """Validate document is a rental (not a tour/activity).

    Valid if: has title AND (has valid price OR has strong rental keywords)
    """
    if not document.get("title"):
        return False

    price = document.get("price_usd")
    has_valid_price = price is not None and isinstance(price, int) and price > 0

    # Check for strong rental keywords in title and description
    title_desc = f"{document.get('title', '')} {document.get('description', '')}".lower()
    has_rental_keywords = bool(_RENTAL_KEYWORDS_STRONG.search(title_desc))

    # Valid if has price OR has rental keywords (allows "contact for price" rentals)
    return has_valid_price or has_rental_keywords


def normalise_listing_document(raw: dict[str, Any], folder: Path) -> dict[str, Any]:
    source = _normalise_source(raw.get("source"), folder.name)
    title = str(raw.get("title") or "").strip()
    url = raw.get("url")
    # Support both usdPerMonth (camelCase from scraper) and price_usd (snake_case fallback)
    price_raw = raw.get("usdPerMonth") or raw.get("price_usd")
    try:
        price_usd = int(price_raw) if price_raw is not None else None
    except (TypeError, ValueError):
        price_usd = None

    local_photos = raw.get("localPhotos") or []
    if not isinstance(local_photos, list):
        local_photos = []

    contact = raw.get("contact")
    has_contact = bool(str(contact).strip()) if contact is not None else False

    listing_id = stable_listing_id(source, url, title, folder.name)
    listing_html_path = folder / "listing.html"
    try:
        listing_path = str(listing_html_path.relative_to(REPO_ROOT))
    except ValueError:
        listing_path = str(listing_html_path)

    # Build photo URL paths relative to the repo root so the frontend can render them
    listing_dir = str(folder.relative_to(REPO_ROOT)) if folder.is_relative_to(REPO_ROOT) else str(folder)
    listing_dir = listing_dir.replace("\\", "/")  # normalize Windows backslashes
    photo_urls = [f"/{listing_dir}/{p}" for p in local_photos]

    return {
        "id": listing_id,
        "title": title,
        "description": str(raw.get("description") or "").strip(),
        "source": source,
        "price_usd": price_usd,
        "price_bucket": compute_price_bucket(price_usd),
        "location": _normalise_location(raw.get("location")),
        "listing_type": str(raw.get("listing_type") or "").strip() or None,
        "has_photos": len(local_photos) > 0,
        "has_contact": has_contact,
        "scraped": str(raw.get("scraped") or "").strip() or None,
        "listing_path": listing_path,
        "photos": photo_urls,
    }


def build_documents_from_rentals(
    rentals_dir: Path = DEFAULT_RENTALS_DIR,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    documents: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    for folder in discover_listing_folders(rentals_dir):
        info_path = folder / "info.json"
        try:
            raw = parse_listing_info(info_path)
            document = normalise_listing_document(raw, folder)
            if not _is_valid_document(document):
                warnings.append({"folder": folder.name, "reason": "missing title"})
                continue
            documents.append(document)
        except Exception as exc:
            warnings.append({"folder": folder.name, "reason": str(exc)})

    documents.sort(key=lambda item: item["id"])
    return documents, warnings


def idempotent_upsert_documents(
    existing_documents: list[dict[str, Any]],
    new_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        document["id"]: dict(document)
        for document in existing_documents
        if document.get("id")
    }

    for document in new_documents:
        if not document.get("id"):
            continue
        merged[document["id"]] = dict(document)

    return [merged[key] for key in sorted(merged.keys())]
