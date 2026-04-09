#!/usr/bin/env python3
"""
wa_import/convert_to_rentals.py
================================
Converts wa_import/output/rentals.json (scored WhatsApp messages produced by
4_find_rentals.py) into the canonical rental listing schema used throughout
the Todos Santos Rentals project.

Usage:
    python3 wa_import/convert_to_rentals.py               # print report only
    python3 wa_import/convert_to_rentals.py --save        # write whatsapp-YYYY-MM-DD.json + folders
    python3 wa_import/convert_to_rentals.py --diff        # --save + diff vs. last run
    python3 wa_import/convert_to_rentals.py --min-score 20

Canonical listing schema (all fields present in every output object):
    title        str
    source       str   always "whatsapp"
    price_usd    int | null
    bedrooms     str | null
    location     str
    url          str | null   always null (WhatsApp messages have no listing URL)
    contact      str | null
    description  str
    amenities    list[str]    always []
    rating       str | null   always null
    listing_type str | null   always null
    checkin      str | null   always null
    checkout     str | null   always null
    scraped      str          ISO date YYYY-MM-DD (from message timestamp)
    localPhotos  list[str]    filenames of copied photos inside the listing folder
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

# Ensure Unicode characters (→, ≥, etc.) don't crash on Windows cp1252 terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure the project root is on sys.path so that `shared` is importable
# regardless of how this script is invoked.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Shared imports ────────────────────────────────────────────────────────────
from shared.config import MAX_USD, TODAY, DEFAULT_RENTALS_DIR
from shared.pricing import parse_price_usd
from shared.listing_io import slugify, folder_name, listing_key
from shared.listing_html import generate_listing_html
from scraper.normalise import normalise as _normalise_listing

# Backward-compat aliases so tests using cr._parse_price_usd etc. still work
_parse_price_usd = parse_price_usd
_slugify = slugify
_folder_name = folder_name
_listing_key = listing_key

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE        = Path(__file__).parent                         # wa_import/
_PROJECT     = _HERE.parent                                  # Todos Santos Rentals/

WA_RENTALS_PATH = _HERE / "output" / "rentals.json"
WA_MEDIA_DIR    = _HERE / "output" / "media"
RESULTS_DIR     = DEFAULT_RENTALS_DIR

# ── Config ────────────────────────────────────────────────────────────────────

SOURCE    = "whatsapp"
MIN_SCORE = 15

# ── Regex helpers ─────────────────────────────────────────────────────────────

_PRICE_RE = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)"
    r"|(\d{3,6})\s*(?:mxn|pesos?)",
    re.I,
)

_BEDROOM_RE = re.compile(
    r"(\d+)\s*(?:BR|bed(?:room)?s?|habitaci[oó]n(?:es)?|cuartos?|rec[aá]mara(?:s)?)",
    re.I,
)

_PHONE_RE = re.compile(
    r"(?:\+?1?\s*[-.]?)?"
    r"(?:\(?\d{3}\)?[\s.-]?)?"
    r"\d{3}[\s.-]?\d{4}",
)

# Known Baja California Sur towns/areas that appear in WA rental messages.
# Order matters: more specific names before shorter ones (e.g. match
# "El Pescadero" before "Pescadero").
_KNOWN_LOCATIONS: List[str] = [
    "Todos Santos",
    "El Pescadero",
    "Pescadero",
    "La Paz",
    "Los Cabos",
    "Cabo San Lucas",
    "San José del Cabo",
    "San Jose del Cabo",
    "Los Barriles",
    "El Triunfo",
    "Miraflores",
    "San Pedrito",
    "Cerritos",
    "Buena Vista",
    "El Sargento",
    "La Ventana",
    "Santiago",
]
_LOCATION_RE = re.compile(
    "|".join(re.escape(loc) for loc in _KNOWN_LOCATIONS),
    re.I,
)


# _parse_price_usd — imported from shared.pricing (see top of file).


# ── Dedup ─────────────────────────────────────────────────────────────────────

def _text_fingerprint(msg: dict) -> str:
    """First 200 chars of message text (lowercased). Used for deduplication."""
    text = (msg.get("text") or msg.get("media_title") or "").lower().strip()
    return text[:200]


def dedup_messages(messages: List[dict]) -> List[dict]:
    """
    Deduplicate by text fingerprint as early as possible.
    Within duplicates, keep the one with the highest rental_score
    (ties broken by most recent timestamp, desc).
    """
    # Sort so that within each fingerprint group the best message comes first
    sorted_msgs = sorted(
        messages,
        key=lambda m: (
            -(m.get("rental_score") or 0),
            # Negate timestamp lexicographically: prefix with a tilde so later dates sort first
            # (ISO dates are lexicographically sortable; "~" > "9" so it inverts the order)
            "~" if not m.get("timestamp") else "",
            m.get("timestamp") or "",
        ),
        reverse=False,
    )
    seen: set = set()
    out: List[dict] = []
    for msg in sorted_msgs:
        fp = _text_fingerprint(msg)
        if not fp:
            # No text at all — keep (rare; image with no caption)
            out.append(msg)
            continue
        if fp in seen:
            continue
        seen.add(fp)
        out.append(msg)
    return out


# ── Field extraction ──────────────────────────────────────────────────────────

def _extract_title(msg: dict) -> str:
    """First non-blank line of text, truncated to 80 chars."""
    text = msg.get("text") or msg.get("media_title") or ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return "WhatsApp Listing"


def _extract_bedrooms(text: str) -> Optional[str]:
    """Parse bedroom count from free text, e.g. '2 bedrooms', '1BR'."""
    if not text:
        return None
    m = _BEDROOM_RE.search(text)
    if m:
        n = m.group(1)
        return f"{n} bedroom{'s' if int(n) != 1 else ''}"
    return None


def _extract_contact(msg: dict) -> Optional[str]:
    """
    Extract phone numbers from message text.  Falls back to the `phone` field
    (which is the sender's JID-derived phone number).
    """
    text = msg.get("text") or msg.get("media_title") or ""
    phones = _PHONE_RE.findall(text)
    phones = [p.strip() for p in phones if len(re.sub(r"\D", "", p)) >= 7]
    if phones:
        return " | ".join(dict.fromkeys(phones))    # preserve order, dedup
    # Fallback: sender phone from JID
    phone = msg.get("phone") or ""
    # Filter out group JIDs (contain a dash)
    if phone and "-" not in phone:
        return phone
    return None


def _extract_scraped(msg: dict) -> str:
    """ISO date (YYYY-MM-DD) from the message timestamp."""
    ts = msg.get("timestamp") or ""
    if ts and len(ts) >= 10:
        return ts[:10]
    return TODAY


def _extract_location(text: str) -> str:
    """
    Scan message text for a known Baja California town/area name.
    Returns the canonical capitalisation of the first match, or
    'Todos Santos' as the default when nothing is found.
    """
    if not text:
        return "Todos Santos"
    m = _LOCATION_RE.search(text)
    if m:
        # Return the canonical form (from _KNOWN_LOCATIONS), not whatever casing
        # happened to appear in the text.
        matched_lower = m.group(0).lower()
        for loc in _KNOWN_LOCATIONS:
            if loc.lower() == matched_lower:
                return loc
    return "Todos Santos"


# ── Conversion ────────────────────────────────────────────────────────────────

def convert_message(msg: dict) -> dict:
    """Map a single scored WA message to the canonical listing schema.

    Routes through scraper.normalise.normalise() so the canonical schema is
    enforced in one place.  WhatsApp-specific fields (_wa_*) are added after
    normalisation; photo_url is dropped since WA photos are copied from the
    media directory rather than fetched via URL.
    """
    text = msg.get("text") or msg.get("media_title") or ""

    # Build the raw dict that normalise() understands
    raw = {
        "title":        _extract_title(msg),
        "price_usd":    _parse_price_usd(text),
        "bedrooms":     _extract_bedrooms(text),
        "location":     _extract_location(text),
        "url":          None,
        "contact":      _extract_contact(msg),
        "description":  text,
        "amenities":    [],
        "rating":       None,
        "listing_type": None,
        "checkin":      None,
        "checkout":     None,
        "scraped":      _extract_scraped(msg),
    }

    # Run through the shared normaliser — source is always "whatsapp"
    listing = _normalise_listing(raw, SOURCE)

    # WA listings are never fetched via URL photo; drop photo_url from schema
    listing.pop("photo_url", None)

    # Add WhatsApp-specific fields (stripped from info.json before writing)
    listing["localPhotos"]      = []          # populated later in Phase 3
    listing["_wa_score"]        = msg.get("rental_score")
    listing["_wa_media_file"]   = msg.get("media_file")
    listing["_wa_media_files"]  = []          # populated by _find_nearby_images()
    listing["_wa_id"]           = msg.get("id")
    listing["_wa_stanza_id"]    = msg.get("stanza_id")
    listing["_wa_from_jid"]     = msg.get("from_jid")

    return listing



def _find_nearby_images(listings: List[dict], all_messages: List[dict]) -> List[dict]:
    """
    For each listing, scan all_messages for image-type messages from the same
    sender within a ±10 message window.  Attach their media filenames
    to the listing's _wa_media_files list.

    This handles the common WhatsApp pattern where a user sends a text message
    about a rental followed by several separate image messages.

    Supports two media filename conventions:
      1. ``{media_id}.jpg``  — 2_download_media.py / SQLite-based export
      2. ``{stanza_id}.jpg`` — Baileys export (stored in media_local_path
         as ``media/{stanza_id}.jpg``)
    """
    WINDOW = 10  # look ±10 messages from the listing's source message

    # Build an index: stanza_id → position in all_messages
    stanza_to_idx = {}
    for i, m in enumerate(all_messages):
        sid = m.get("stanza_id")
        if sid:
            stanza_to_idx[sid] = i

    def _resolve_media_filename(msg: dict) -> Optional[str]:
        """
        Return the filename (relative to WA_MEDIA_DIR) for this message's
        image, or None if no file exists on disk.

        Tries three sources in order:
          1. media_id  → "{media_id}.jpg"
             SQLite / 2_download_media.py convention.
          2. media_local_path → basename when it starts with "media/"
             Baileys sets this to "media/{stanza_id}.jpg" after real-time
             download during the nightly wa-exporter run.
          3. stanza_id → "{stanza_id}.jpg"
             3_playwright_capture.mjs scrolls WA Web and saves files using
             the message stanza ID, allowing retroactive photo recovery for
             all historical messages.
        """
        # Convention 1: integer media_id (SQLite / 2_download_media.py)
        media_id = msg.get("media_id")
        if media_id:
            candidate = f"{media_id}.jpg"
            if (WA_MEDIA_DIR / candidate).exists():
                return candidate

        # Convention 2: Baileys media_local_path = "media/{stanza_id}.jpg"
        local_path = msg.get("media_local_path") or ""
        if local_path.startswith("media/"):
            candidate = local_path[len("media/"):]
            if (WA_MEDIA_DIR / candidate).exists():
                return candidate

        # Convention 3: Playwright capture → "{stanza_id}.jpg"
        stanza_id = msg.get("stanza_id")
        if stanza_id:
            candidate = f"{stanza_id}.jpg"
            if (WA_MEDIA_DIR / candidate).exists():
                return candidate

        return None

    for listing in listings:
        stanza_id = listing.get("_wa_stanza_id")
        if not stanza_id or stanza_id not in stanza_to_idx:
            continue

        center = stanza_to_idx[stanza_id]
        lo = max(0, center - WINDOW)
        hi = min(len(all_messages), center + WINDOW + 1)

        media_files = []
        for j in range(lo, hi):
            m = all_messages[j]
            # type_int == 1 means image message
            if m.get("type_int") != 1:
                continue
            fname = _resolve_media_filename(m)
            if fname and fname not in media_files:
                media_files.append(fname)

        # Also include the listing's own media_file if it has one
        own = listing.get("_wa_media_file")
        if own and own not in media_files:
            media_files.insert(0, own)

        listing["_wa_media_files"] = media_files

    return listings


def load_and_filter(path: Path, min_score: int) -> List[dict]:
    """
    Load rentals.json, apply score filter, deduplicate, convert, then
    filter out listings above MAX_USD.  Also loads the full messages.json
    to find nearby images for each listing.
    """
    with open(path, encoding="utf-8") as f:
        messages = json.load(f)

    # Load all messages for nearby-image association
    messages_json_path = path.parent / "messages.json"
    all_messages = []
    if messages_json_path.exists():
        try:
            with open(messages_json_path, encoding="utf-8") as f:
                all_messages = json.load(f)
        except Exception:
            pass

    # 1. Score filter
    messages = [m for m in messages if (m.get("rental_score") or 0) >= min_score]

    # 2. Dedup (as early as possible — before any conversion work)
    messages = dedup_messages(messages)

    # 3. Convert to canonical schema
    listings = [convert_message(m) for m in messages]

    # 4. Find nearby images from the full message stream
    if all_messages:
        listings = _find_nearby_images(listings, all_messages)

    # 5. Price cap
    listings = [
        l for l in listings
        if l["price_usd"] is None or l["price_usd"] <= MAX_USD
    ]

    return listings


# _slugify, _folder_name — imported from shared.listing_io (see top of file).
# Note: _folder_name here uses SOURCE constant by wrapping shared.listing_io.folder_name.


def _scan_existing() -> dict:
    """
    Return a lookup of existing whatsapp-* folders keyed by title slug.
    Value: {"folder": Path, "price": int|None}
    """
    index: dict = {}
    for folder in RESULTS_DIR.glob(f"{SOURCE}-*/"):
        if not folder.is_dir():
            continue
        info_path = folder / "info.json"
        if not info_path.exists():
            continue
        try:
            d = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = _slugify(d.get("title") or "")
        if slug:
            index.setdefault(slug, {"folder": folder, "price": d.get("price_usd")})
    return index


def _next_index() -> int:
    pattern = re.compile(rf"^{re.escape(SOURCE)}-(\d+)-")
    indices = []
    for p in RESULTS_DIR.glob(f"{SOURCE}-[0-9][0-9]-*/"):
        if not p.is_dir():
            continue
        m = pattern.match(p.name)
        if m:
            indices.append(int(m.group(1)))
    return (max(indices) + 1) if indices else 1


# ── Media copy ────────────────────────────────────────────────────────────────

def _copy_media(listing: dict, dest_folder: Path) -> List[str]:
    """
    Copy WA media files (if any) into dest_folder as photo_01.jpg, photo_02.jpg, etc.
    Checks _wa_media_files (nearby images) first, falls back to _wa_media_file.
    Returns a list of copied filenames (empty if none).
    """
    media_files = listing.get("_wa_media_files") or []
    if not media_files:
        single = listing.get("_wa_media_file")
        if single:
            media_files = [single]
    if not media_files:
        return []

    copied = []
    for i, media_file in enumerate(media_files, 1):
        src = WA_MEDIA_DIR / media_file
        if not src.exists():
            continue
        dest_name = f"photo_{i:02d}.jpg"
        dest = dest_folder / dest_name
        shutil.copy2(src, dest)
        copied.append(dest_name)

    return copied


# ── HTML generation ────────────────────────────────────────────────────
# generate_listing_html imported from shared.listing_html (see top of file).

def _generate_listing_html(listing: dict) -> str:
    """Thin wrapper around shared.listing_html.generate_listing_html()."""
    return generate_listing_html(listing)


# ── Folder creation ───────────────────────────────────────────────────────────

def save_listing_folder(listing: dict, index: int, existing: dict):
    """
    Create or update a whatsapp-NN-slug-Nusd/ folder with info.json,
    listing.html, and any media photo.
    """
    RESULTS_DIR.mkdir(exist_ok=True)
    slug = _slugify(listing.get("title") or "listing")
    existing_entry = existing.get(slug)

    if existing_entry:
        folder = existing_entry["folder"]
        price_unchanged = existing_entry["price"] == listing.get("price_usd")
        has_photos_already = any(folder.glob("photo_*.jpg"))

        # If price unchanged AND photos already present → truly nothing to do
        if price_unchanged and has_photos_already:
            return

        # Price unchanged but no photos yet → fall through to copy photos
        # Price changed → fall through to update info.json
    else:
        folder = RESULTS_DIR / _folder_name(listing, index)
        folder.mkdir(exist_ok=True)
        has_photos_already = False

    # Copy media (only if not already there)
    if not any(folder.glob("photo_*.jpg")):
        photos = _copy_media(listing, folder)
        listing = {**listing, "localPhotos": photos}
    else:
        existing_photos = sorted(p.name for p in folder.glob("photo_*.jpg"))
        listing = {**listing, "localPhotos": existing_photos}

    # Strip internal WA fields before writing info.json
    info = {k: v for k, v in listing.items() if not k.startswith("_wa_")}
    (folder / "info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "listing.html").write_text(
        _generate_listing_html(listing), encoding="utf-8"
    )


# ── Save / diff ───────────────────────────────────────────────────────────────

# _listing_key — imported from shared.listing_io (see top of file).


def save_results(listings: List[dict], create_folders: bool = True) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    # Strip internal WA fields for the summary JSON
    clean = [{k: v for k, v in l.items() if not k.startswith("_wa_")} for l in listings]
    out = RESULTS_DIR / f"{SOURCE}-{TODAY}.json"
    out.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved → {out}")

    if create_folders:
        existing = _scan_existing()
        idx = _next_index()
        for listing in listings:
            slug = _slugify(listing.get("title") or "listing")
            if slug not in existing:
                save_listing_folder(listing, idx, existing)
                existing[slug] = {
                    "folder": RESULTS_DIR / _folder_name(listing, idx),
                    "price":  listing.get("price_usd"),
                }
                idx += 1
            else:
                save_listing_folder(listing, idx, existing)

    return out


def diff_against_previous(current: List[dict]):
    prior_files = sorted(RESULTS_DIR.glob(f"{SOURCE}-*.json"))
    prior_files = [f for f in prior_files if not f.stem.endswith(TODAY)]
    if not prior_files:
        print(f"  [{SOURCE}] No previous results to diff against.")
        return

    prev_file = prior_files[-1]
    try:
        prev = json.loads(prev_file.read_text(encoding="utf-8"))
    except Exception:
        print(f"  Could not read {prev_file}.", file=sys.stderr)
        return

    prev_keys = {_listing_key(l) for l in prev}
    curr_keys  = {_listing_key(l) for l in current}
    new_ones   = [l for l in current if _listing_key(l) not in prev_keys]
    gone_count = len(prev_keys - curr_keys)

    print(f"\n  [{SOURCE}] Diff vs {prev_file.name}:")
    print(f"  + {len(new_ones)} new listing(s)   - {gone_count} removed\n")
    if new_ones:
        print("  NEW LISTINGS:")
        _print_report(new_ones)


# ── Report ────────────────────────────────────────────────────────────────────

def _print_report(listings: List[dict]):
    divider = "─" * 68
    if not listings:
        print("  No listings found.")
        return
    for i, l in enumerate(listings, 1):
        price   = f"${l['price_usd']}/mo" if l.get("price_usd") else "price unknown"
        beds    = l.get("bedrooms") or "?"
        title   = l.get("title") or "Untitled"
        contact = l.get("contact") or ""
        desc    = (l.get("description") or "")[:220].replace("\n", " ")
        score   = l.get("_wa_score") or "?"

        print(f"\n  {i:>2}. {title}")
        print(f"      {price}  ·  {beds}  ·  [whatsapp]  ·  score {score}")
        if contact:
            print(f"      Contact: {contact}")
        if desc:
            print(f"      {desc[:120]}…" if len(desc) > 120 else f"      {desc}")
        print(f"  {divider}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert WhatsApp rental messages to canonical listing schema."
    )
    parser.add_argument("--save",      action="store_true",
                        help="Write whatsapp-YYYY-MM-DD.json and listing folders")
    parser.add_argument("--diff",      action="store_true",
                        help="--save + diff vs. the previous run")
    parser.add_argument("--min-score", type=int, default=MIN_SCORE,
                        dest="min_score",
                        help=f"Minimum rental_score to include (default: {MIN_SCORE})")
    args = parser.parse_args()

    if not WA_RENTALS_PATH.exists():
        print(f"❌  {WA_RENTALS_PATH} not found — run 4_find_rentals.py first",
              file=sys.stderr)
        sys.exit(1)

    print(f"Loading {WA_RENTALS_PATH} …")
    listings = load_and_filter(WA_RENTALS_PATH, args.min_score)
    print(f"  → {len(listings):,} unique rental listings (score ≥ {args.min_score})")

    divider = "═" * 68
    print(f"\n{divider}")
    print(f"  WHATSAPP RENTALS  ·  score ≥ {args.min_score}  ·  under ${MAX_USD}/mo  ·  {TODAY}")
    print(f"{divider}")
    _print_report(listings)
    print(f"\n  Total: {len(listings)} listing(s)")

    if args.diff or args.save:
        out = save_results(listings, create_folders=True)
        if args.diff:
            diff_against_previous(listings)
    else:
        print("\n  (Run with --save to write output files.)")


if __name__ == "__main__":
    main()
