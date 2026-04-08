#!/usr/bin/env python3
"""
wa_export/convert_to_rentals.py
================================
Converts wa_export/output/rentals.json (scored WhatsApp messages produced by
4_find_rentals.py) into the canonical rental listing schema used throughout
the Todos Santos Rentals project.

Usage:
    python3 wa_export/convert_to_rentals.py               # print report only
    python3 wa_export/convert_to_rentals.py --save        # write whatsapp-YYYY-MM-DD.json + folders
    python3 wa_export/convert_to_rentals.py --diff        # --save + diff vs. last run
    python3 wa_export/convert_to_rentals.py --min-score 20

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

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE        = Path(__file__).parent                         # wa_export/
_PROJECT     = _HERE.parent                                  # Todos Santos Rentals/

WA_RENTALS_PATH = _HERE / "output" / "rentals.json"
WA_MEDIA_DIR    = _HERE / "output" / "media"
RESULTS_DIR     = _PROJECT / "rentals"

TODAY  = date.today().isoformat()

# ── Config ────────────────────────────────────────────────────────────────────

SOURCE    = "whatsapp"
MIN_SCORE = 15
MAX_USD   = 2000          # must match rental_search.py

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


# ── Price parsing (mirrors rental_search._parse_price_usd) ───────────────────

def _parse_price_usd(text: str) -> Optional[int]:
    """Extract a monthly USD price from arbitrary text. Returns None if unclear."""
    if not text:
        return None
    text = text.replace(",", "")
    m = re.search(r"\$\s*(\d{3,6})", text)
    if m:
        val = int(m.group(1))
        if val < 100:
            return None
        if val > 4_000:
            return round(val / 17.5)
        return val
    m = re.search(r"(\d{4,6})\s*(?:mxn|pesos?)", text, re.I)
    if m:
        return round(int(m.group(1)) / 17.5)
    return None


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
    """Map a single scored WA message to the canonical listing schema."""
    text = msg.get("text") or msg.get("media_title") or ""
    return {
        "title":        _extract_title(msg),
        "source":       SOURCE,
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
        "localPhotos":  [],          # populated later in Phase 3
        # Carry WA-specific fields for folder generation / media copy
        "_wa_score":      msg.get("rental_score"),
        "_wa_media_file": msg.get("media_file"),
        "_wa_id":         msg.get("id"),
    }


def load_and_filter(path: Path, min_score: int) -> List[dict]:
    """
    Load rentals.json, apply score filter, deduplicate, convert, then
    filter out listings above MAX_USD.  Returns a list of canonical dicts.
    """
    with open(path, encoding="utf-8") as f:
        messages = json.load(f)

    # 1. Score filter
    messages = [m for m in messages if (m.get("rental_score") or 0) >= min_score]

    # 2. Dedup (as early as possible — before any conversion work)
    messages = dedup_messages(messages)

    # 3. Convert to canonical schema
    listings = [convert_message(m) for m in messages]

    # 4. Price cap
    listings = [
        l for l in listings
        if l["price_usd"] is None or l["price_usd"] <= MAX_USD
    ]

    return listings


# ── Slugify / folder naming (mirrors rental_search.py) ───────────────────────

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:40]


def _folder_name(listing: dict, index: int) -> str:
    slug  = _slugify(listing.get("title") or "listing")
    price = listing.get("price_usd")
    price_part = f"{price}usd" if price else "noprice"
    return f"{SOURCE}-{index:02d}-{slug}-{price_part}"


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
    Copy the WA media file (if any) into dest_folder as photo_01.jpg.
    Returns a list of copied filenames (empty if none).
    """
    media_file = listing.get("_wa_media_file")
    if not media_file:
        return []
    src = WA_MEDIA_DIR / media_file
    if not src.exists():
        return []
    dest = dest_folder / "photo_01.jpg"
    shutil.copy2(src, dest)
    return ["photo_01.jpg"]


# ── HTML generation (reuses rental_search logic via import) ──────────────────

def _generate_listing_html(listing: dict) -> str:
    """
    Delegate to rental_search.generate_listing_html() so styling stays
    consistent across all sources.
    """
    # Import lazily to avoid hard-wiring the path at module load time
    sys.path.insert(0, str(_PROJECT / "scraper"))
    try:
        import rental_search as rs   # type: ignore
        return rs.generate_listing_html(listing)
    except ImportError:
        # Minimal fallback if rental_search isn't importable (e.g. missing deps)
        title = listing.get("title", "Listing")
        desc  = listing.get("description", "")
        price = listing.get("price_usd")
        price_str = f"${price}/mo" if price else "—"
        return (
            f"<!DOCTYPE html><html><head><meta charset='UTF-8'>"
            f"<title>{title}</title></head><body>"
            f"<h1>{title}</h1><p>{price_str}</p><pre>{desc}</pre>"
            f"</body></html>"
        )


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
        if existing_entry["price"] == listing.get("price_usd"):
            return          # unchanged — skip
        # Price changed: update info.json + listing.html, preserve photos
    else:
        folder = RESULTS_DIR / _folder_name(listing, index)
        folder.mkdir(exist_ok=True)

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

def _listing_key(listing: dict) -> str:
    title = re.sub(r"\W+", " ", (listing.get("title") or "")).lower().strip()[:60]
    return f"{listing.get('source', '')}|{title}"


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
