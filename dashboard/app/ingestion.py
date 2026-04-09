import hashlib
import json
import re
from urllib.parse import urlparse
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


# Folder name format: {source}-{NN}-{slug}-{price}
# Regex extracts everything before the first two-digit index segment.
_FOLDER_SOURCE_RE = re.compile(r'^(.+?)-(\d{2})-')

# Tool-name prefixes used in older folder names — these are NOT real channels.
_TOOL_NAME_PREFIXES = {"local-llm", "claude-cli", "claude-api", "ai", "local", "claude"}

# Maps listing URL hostname → real channel label.
# Used to recover the true source for legacy folders that were named after the
# tool (local-llm-*, claude-cli-*, ai-*) instead of the originating website.
_URL_CHANNEL_MAP: list[tuple[str, str]] = [
    ("airbnb.com",                  "airbnb"),
    ("amyrextodossantos.com",        "amyrex"),
    ("bajaproperties.com",           "bajaprops"),
    ("barakaentodos.com",            "baraka"),
    ("todossantosvillarentals.com",  "tsvilla"),
    ("pescaderopropertymgmt.com",    "pescprop"),
    ("bajasurfcasitas.com",          "bajasurfcasitas"),
    ("craigslist.org",               "craigslist"),
    ("todossantos.cc",               "todossantos"),
]


def _channel_from_url(url: str | None) -> str | None:
    """Return the real channel label for a listing URL, or None if unrecognised."""
    if not url:
        return None
    host = urlparse(url).netloc.lower().replace("www.", "")
    for domain, channel in _URL_CHANNEL_MAP:
        if domain in host:
            return channel
    return None


def _normalise_source(raw_source: Any, folder_name: str, url: str | None = None) -> str:
    """Return the real channel label for a listing.

    Priority:
    1. URL-based detection — the listing URL reveals which website it came from
       and is used whenever the folder prefix is a tool name (legacy folders).
    2. Folder prefix — for new folders created after the fix, the prefix already
       is the real channel label (amyrex, bajaprops, whatsapp, craigslist, …).
    """
    m = _FOLDER_SOURCE_RE.match(folder_name)
    prefix = m.group(1).strip().lower() if m else folder_name.split("-", 1)[0].strip().lower()

    if prefix in _TOOL_NAME_PREFIXES:
        # Legacy folder — recover real channel from the listing URL
        return _channel_from_url(url) or prefix

    return prefix


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
    url = raw.get("url")
    source = _normalise_source(raw.get("source"), folder.name, url=url)
    title = str(raw.get("title") or "").strip()
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

    # Backward-compat defaults for new fields: existing info.json files that
    # pre-date this change will be missing these keys.
    scraped = str(raw.get("scraped") or "").strip() or None
    status = str(raw.get("status") or "active").strip()
    last_checked = str(raw.get("last_checked") or scraped or "").strip() or None
    last_updated = str(raw.get("last_updated") or scraped or "").strip() or None
    archived_date = str(raw.get("archived_date") or "").strip() or None

    return {
        "id": listing_id,
        "title": title,
        "description": str(raw.get("description") or "").strip(),
        "source": source,
        "status": status,
        "price_usd": price_usd,
        "price_bucket": compute_price_bucket(price_usd),
        "location": _normalise_location(raw.get("location")),
        "listing_type": str(raw.get("listing_type") or "").strip() or None,
        "has_photos": len(local_photos) > 0,
        "has_contact": has_contact,
        "scraped": scraped,
        "last_checked": last_checked,
        "last_updated": last_updated,
        "archived_date": archived_date,
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
