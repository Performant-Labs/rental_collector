#!/usr/bin/env python3
"""
migrate_legacy_folders.py
=========================
Rename legacy tool-named folders (local-llm-*, claude-cli-*, ai-*) to their
real channel prefix (airbnb-*, amyrex-*, etc.), update info.json source field,
and regenerate listing.html.

Safe to re-run: skips folders that have already been renamed.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from shared.config import DEFAULT_RENTALS_DIR
from shared.listing_io import slugify
from shared.listing_html import generate_listing_html

# ── Config ────────────────────────────────────────────────────────────────────

LEGACY_PREFIXES = {"local-llm", "claude-cli", "ai"}

URL_CHANNEL_MAP = [
    ("airbnb.com",                 "airbnb"),
    ("amyrextodossantos.com",      "amyrex"),
    ("bajaproperties.com",         "bajaprops"),
    ("barakaentodos.com",          "baraka"),
    ("todossantosvillarentals.com","tsvilla"),
    ("pescaderopropertymgmt.com",  "pescprop"),
    ("craigslist.org",             "craigslist"),
    ("todossantos.cc",             "todossantos"),
]

_FOLDER_SOURCE_RE = re.compile(r'^(.+?)-(\d{2})-')

# ── Helpers ───────────────────────────────────────────────────────────────────

def real_channel_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc.lower().replace("www.", "")
    for domain, channel in URL_CHANNEL_MAP:
        if domain in host:
            return channel
    return None


def next_index(rentals_dir: Path, prefix: str, reserved: dict[str, int]) -> int:
    """Return the next available index for a channel prefix.

    `reserved` is a mutable dict keyed by prefix that persists across calls
    within a single migration run, so sequential folders get sequential indices.
    """
    if prefix not in reserved:
        pattern = re.compile(rf'^{re.escape(prefix)}-(\d+)-')
        indices = []
        for p in rentals_dir.iterdir():
            if p.is_dir():
                m = pattern.match(p.name)
                if m:
                    indices.append(int(m.group(1)))
        reserved[prefix] = (max(indices) + 1) if indices else 1
    idx = reserved[prefix]
    reserved[prefix] += 1
    return idx


def build_new_folder_name(channel: str, index: int, info: dict) -> str:
    slug = slugify(info.get("title") or "listing")
    price = info.get("price_usd")
    price_part = f"{price}usd" if price else "noprice"
    return f"{channel}-{index:02d}-{slug}-{price_part}"


def is_legacy(folder_name: str) -> bool:
    m = _FOLDER_SOURCE_RE.match(folder_name)
    prefix = m.group(1).lower() if m else folder_name.split("-", 1)[0].lower()
    return prefix in LEGACY_PREFIXES


# ── Migration ─────────────────────────────────────────────────────────────────

def migrate(rentals_dir: Path, dry_run: bool = False) -> None:
    legacy_folders = sorted(
        f for f in rentals_dir.iterdir()
        if f.is_dir() and is_legacy(f.name) and (f / "info.json").exists()
    )

    if not legacy_folders:
        print("No legacy folders found. Filesystem is already clean.")
        return

    print(f"Found {len(legacy_folders)} legacy folder(s) to migrate.\n")

    reserved: dict[str, int] = {}     # channel -> next available index
    seen_keys: set[str] = set()        # deduplicate same listing across multiple legacy origins

    for folder in legacy_folders:
        info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
        url  = info.get("url")
        channel = real_channel_from_url(url)

        if not channel:
            print(f"  SKIP  {folder.name}  (cannot determine channel — no URL match)")
            continue

        # Dedup key: channel + URL (same listing scraped by two different tools)
        dedup_key = f"{channel}|{url or info.get('title', '')}"
        if dedup_key in seen_keys:
            print(f"  DUPE  {folder.name}")
            print(f"        -> same listing already migrated under '{channel}' — deleting")
            if not dry_run:
                shutil.rmtree(folder)
            else:
                print(f"        (dry-run — no changes made)")
            continue
        seen_keys.add(dedup_key)

        idx      = next_index(rentals_dir, channel, reserved)
        new_name = build_new_folder_name(channel, idx, info)
        new_path = rentals_dir / new_name

        print(f"  RENAME  {folder.name}")
        print(f"       -> {new_name}  [source: {channel}]")

        if dry_run:
            print(f"          (dry-run — no changes made)")
            continue

        # 1. Move folder
        shutil.move(str(folder), str(new_path))

        # 2. Update info.json source field
        info["source"] = channel
        (new_path / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 3. Regenerate listing.html with correct source
        try:
            html = generate_listing_html(info)
            (new_path / "listing.html").write_text(html, encoding="utf-8")
        except Exception as e:
            print(f"          WARNING: could not regenerate listing.html: {e}")

        print(f"          OK")

    print(f"\nDone. Run ingest_runner --mode full to sync Meilisearch.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate legacy tool-named rental folders to real channel names.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument("--rentals-dir", default=str(DEFAULT_RENTALS_DIR))
    args = parser.parse_args()

    migrate(Path(args.rentals_dir), dry_run=args.dry_run)
