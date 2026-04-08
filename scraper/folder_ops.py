"""
scraper.folder_ops — Listing folder management (create, update, scan, dedup).

Extracted from rental_search.py to keep the monolith manageable.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

import requests

from shared import config as _config
from shared.keywords import RENTAL_KEYWORDS_STRONG
from shared.listing_io import slugify, folder_name, listing_key
from shared.listing_html import generate_listing_html
from scraper.scrapers import get_soup, HEADERS



# Backward-compat aliases
_folder_name = folder_name
_listing_key = listing_key
_RENTAL_KEYWORDS_STRONG = RENTAL_KEYWORDS_STRONG


def _scan_existing(source: str) -> dict:
    """Scan saved folders for a source and return a lookup keyed by both URL
    and title_key.  Each value: {"folder": Path, "price": int|None}.

    URLs that appear in more than one folder (e.g. a shared classifieds-page
    URL used by every todossantos.cc listing) are NOT added to the URL index —
    only title_key dedup is used for those.
    """
    # First pass: collect entries and count how many folders share each URL.
    entries = []
    url_counts: dict = {}
    for folder in _config.DEFAULT_RENTALS_DIR.glob(f"{source}-*/"):
        if not folder.is_dir():
            continue
        info_path = folder / "info.json"
        if not info_path.exists():
            continue
        try:
            d = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entry = {"folder": folder, "price": d.get("price_usd"), "data": d}
        entries.append(entry)
        if d.get("url"):
            url_counts[d["url"]] = url_counts.get(d["url"], 0) + 1

    # Second pass: build the lookup index.
    index: dict = {}
    for entry in entries:
        d = entry.pop("data")
        url = d.get("url")
        # Only use URL as a key when it uniquely identifies one folder.
        if url and url_counts.get(url, 0) == 1:
            index[url] = entry
        tkey = _listing_key(d)
        if tkey:
            index.setdefault(tkey, entry)   # URL takes priority; don't overwrite
    return index


def _next_index(source: str) -> int:
    """Return the next available numeric index for a source's folders."""
    pattern = re.compile(rf"^{re.escape(source)}-(\d+)-")
    indices = []
    for p in _config.DEFAULT_RENTALS_DIR.glob(f"{source}-[0-9][0-9]-*/"):
        if not p.is_dir():
            continue
        m = pattern.match(p.name)
        if m:
            indices.append(int(m.group(1)))
    return (max(indices) + 1) if indices else 1


def fetch_photos(url: str, folder: Path, max_photos: int = 6) -> List[str]:
    """Download photos from a listing page into folder. Returns list of local filenames."""
    soup = get_soup(url)
    if not soup:
        return []

    saved = []
    seen_urls: set = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src.startswith("http"):
            continue
        if src in seen_urls:
            continue
        # Skip tiny icons / logos (heuristic: skip URLs with "icon", "logo", "avatar")
        if any(x in src.lower() for x in ("icon", "logo", "avatar", "sprite", "pixel")):
            continue
        seen_urls.add(src)

        local_name = f"photo_{len(saved)+1:02d}.jpg"
        local_path = folder / local_name
        try:
            req = requests.get(src, headers=HEADERS, timeout=15)
            req.raise_for_status()
            if len(req.content) < 2000:   # too small → probably an icon
                continue
            local_path.write_bytes(req.content)
            saved.append(local_name)
            time.sleep(0.3)
        except Exception:
            continue

        if len(saved) >= max_photos:
            break

    return saved


def save_listing_folder(listing: dict, index: int) -> Path:
    """Create a complete listing folder: info.json + listing.html + photos."""
    folder = _config.DEFAULT_RENTALS_DIR / _folder_name(listing, index)
    folder.mkdir(exist_ok=True)

    # 1. Use photo_url if the LLM extracted it directly (works for Airbnb)
    local_photos = listing.get("localPhotos") or []
    photo_url = listing.get("photo_url")
    if not local_photos and photo_url and photo_url.startswith("http"):
        print(f"    \u2193 downloading cover photo from LLM-extracted URL \u2026")
        local_name = "photo_01.jpg"
        local_path = folder / local_name
        try:
            req = requests.get(photo_url, headers=HEADERS, timeout=15)
            req.raise_for_status()
            if len(req.content) >= 2000:
                local_path.write_bytes(req.content)
                local_photos = [local_name]
                print(f"    \u2192 cover photo saved")
        except Exception as e:
            print(f"    \u2717 photo download failed: {e}")

    # 2. Fall back to scraping the listing page (works for non-Airbnb sites)
    if not local_photos and listing.get("url") and "airbnb.com" not in (listing.get("url") or ""):
        print(f"    \u2193 fetching photos from {listing['url']} \u2026")
        local_photos = fetch_photos(listing["url"], folder)
        if local_photos:
            print(f"    \u2192 {len(local_photos)} photo(s) saved")

    # Write info.json (normalised schema + localPhotos)
    info = {**listing, "localPhotos": local_photos}
    (folder / "info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write listing.html
    html_listing = {**listing, "localPhotos": local_photos}
    (folder / "listing.html").write_text(
        generate_listing_html(html_listing), encoding="utf-8"
    )

    print(f"  \u2192 folder: {folder.name}/")
    return folder


def update_listing_folder(folder: Path, listing: dict, old_price: Optional[int]):
    """Rewrite info.json and listing.html in an existing folder with a new price."""
    try:
        existing_info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    except Exception:
        existing_info = {}

    local_photos = existing_info.get("localPhotos") or []
    updated = {**listing, "localPhotos": local_photos}

    (folder / "info.json").write_text(
        json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "listing.html").write_text(
        generate_listing_html(updated), encoding="utf-8"
    )
    new_price = listing.get("price_usd")
    print(f"  \u21ba price update: ${old_price} \u2192 ${new_price}  ({folder.name}/)")


# Phrases that indicate a listing page is no longer active.
# Checked case-insensitively against the full response body.
_DEAD_PHRASES = [
    "this posting has been deleted",
    "this posting has expired",
    "this posting has been flagged for removal",
    "this posting has been removed",
    "no longer available",
    "listing not found",
    "listing has been removed",
    "page not found",
    "404 not found",
]


def is_listing_active(url: str) -> bool:
    """Fetch the listing URL and return False if the page signals it is gone.

    Returns True when there is no URL (can't check), on network errors (assume
    live — connectivity problems shouldn't suppress a listing), and whenever
    none of the dead-listing phrases are found in the response body.
    """
    if not url:
        return True
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if r.status_code == 404:
            return False
        body = r.text.lower()
        return not any(phrase in body for phrase in _DEAD_PHRASES)
    except Exception:
        return True   # network error \u2260 deleted listing


def save_listing_folders(listings: List[dict]):
    """For each listing: verify it is active AND looks like a rental, then create/update/skip its folder."""
    source = listings[0].get("source", "unknown") if listings else "unknown"
    existing = _scan_existing(source)
    start_index = _next_index(source)

    new_count = updated_count = skipped_count = 0
    for listing in listings:
        url   = listing.get("url")
        tkey  = _listing_key(listing)
        match = existing.get(url) or existing.get(tkey)

        # Determine if this is actually a rental (not a tour/activity)
        # Keep if: has valid price OR has strong rental keywords
        price = listing.get("price_usd")
        has_valid_price = price is not None and isinstance(price, int) and price > 0

        title_desc = f"{listing.get('title', '')} {listing.get('description', '')}".lower()
        has_rental_keywords = bool(_RENTAL_KEYWORDS_STRONG.search(title_desc))

        if not has_valid_price and not has_rental_keywords:
            # Likely a tour/activity without monthly rent price
            print(f"  \u2717 no rent price + no rental keywords \u2014 skipping: {listing.get('title', '')[:60]}")
            skipped_count += 1
            continue

        if match is None:
            if not is_listing_active(url):
                print(f"  \u2717 inactive \u2014 skipping: {listing.get('title', '')[:60]}")
                skipped_count += 1
                continue
            save_listing_folder(listing, start_index + new_count)
            new_count += 1
        elif listing.get("price_usd") != match["price"]:
            if not is_listing_active(url):
                print(f"  \u2717 inactive \u2014 skipping price update: {listing.get('title', '')[:60]}")
                skipped_count += 1
                continue
            update_listing_folder(match["folder"], listing, match["price"])
            updated_count += 1
        # else: identical — skip

    parts = []
    if new_count:
        parts.append(f"{new_count} new")
    if updated_count:
        parts.append(f"{updated_count} updated")
    if skipped_count:
        parts.append(f"{skipped_count} skipped")
    if not parts:
        parts.append("no changes")
    print(f"  [{source}] {', '.join(parts)}")
