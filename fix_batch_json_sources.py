#!/usr/bin/env python3
"""
fix_batch_json_sources.py
=========================
Audit and fix the 'source' field inside every rentals/*.json batch file.
These are the dated summary JSONs (e.g. local-llm-2026-04-07.json) written
by save_results(). Each contains a list of listings; we correct the source
field on each listing using the same URL-based logic as ingestion.

Also handles stale batch files named after tool names (claude-api-*, etc.)
by rewriting them with the corrected data and a filename that reflects the
dominant real channel found inside.

Safe to re-run: already-correct files are skipped.
"""
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from shared.config import DEFAULT_RENTALS_DIR

URL_CHANNEL_MAP = [
    ("airbnb.com",                  "airbnb"),
    ("amyrextodossantos.com",       "amyrex"),
    ("bajaproperties.com",          "bajaprops"),
    ("barakaentodos.com",           "baraka"),
    ("todossantosvillarentals.com", "tsvilla"),
    ("pescaderopropertymgmt.com",   "pescprop"),
    ("craigslist.org",              "craigslist"),
    ("todossantos.cc",              "todossantos"),
]

VALID_CHANNELS = {r[1] for r in URL_CHANNEL_MAP} | {"whatsapp"}

# Batch file prefixes that are tool names, not real channels
TOOL_PREFIXES = {"local-llm", "claude-cli", "claude-api", "ai", "local", "claude"}


def channel_from_url(url):
    if not url:
        return None
    host = urlparse(url).netloc.lower().replace("www.", "")
    for domain, channel in URL_CHANNEL_MAP:
        if domain in host:
            return channel
    return None


def fix_listing_source(listing: dict) -> tuple[dict, bool]:
    """Return (listing_with_correct_source, was_changed)."""
    correct = channel_from_url(listing.get("url"))
    if not correct:
        correct = listing.get("source", "")  # leave as-is if no URL
    current = listing.get("source", "")
    if current == correct:
        return listing, False
    fixed = {**listing, "source": correct}
    return fixed, True


def audit_and_fix(rentals_dir: Path, dry_run: bool = False):
    batch_files = sorted(
        f for f in rentals_dir.glob("*.json")
        if not f.name.startswith(".") and f.name not in {"last_ingest_stats.json", "last_run.txt"}
        and f.stem.count("-") >= 1  # dated batch files have at least one hyphen
    )

    any_changes = False
    for batch_file in batch_files:
        try:
            listings = json.loads(batch_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  SKIP {batch_file.name}: cannot parse ({e})")
            continue

        if not isinstance(listings, list):
            continue  # not a listing batch

        fixed_listings = []
        changes = []
        for listing in listings:
            fixed, changed = fix_listing_source(listing)
            fixed_listings.append(fixed)
            if changed:
                changes.append((listing.get("source", ""), fixed["source"], listing.get("title", "")[:40]))

        # Check if the filename itself is a tool name
        stem = batch_file.stem  # e.g. "local-llm-2026-04-07"
        parts = stem.rsplit("-", 3)  # split off YYYY-MM-DD
        if len(parts) >= 2:
            prefix = "-".join(parts[:-3]) if len(parts) > 3 else parts[0]
        else:
            prefix = stem

        needs_rename = any(prefix == tp or prefix.startswith(tp) for tp in TOOL_PREFIXES)

        if not changes and not needs_rename:
            print(f"  OK    {batch_file.name}")
            continue

        any_changes = True
        print(f"\n  {batch_file.name}")

        for old_src, new_src, title in changes:
            print(f"    \"{old_src}\" -> \"{new_src}\"  ({title})")

        if needs_rename:
            # Determine dominant real channel from fixed listings
            channel_counts = Counter(l.get("source", "") for l in fixed_listings if l.get("source"))
            dominant = channel_counts.most_common(1)[0][0] if channel_counts else "unknown"
            # Extract date portion: last 3 hyphen-parts = YYYY-MM-DD
            date_part = "-".join(stem.split("-")[-3:])
            new_name = f"{dominant}-{date_part}.json"
            print(f"    rename -> {new_name}  (dominant channel: {dominant}, {len(changes)} source fix(es))")
        else:
            new_name = batch_file.name
            if changes:
                print(f"    {len(changes)} source field(s) corrected in-place")

        if not dry_run:
            new_path = rentals_dir / new_name
            new_path.write_text(
                json.dumps(fixed_listings, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if needs_rename and new_name != batch_file.name:
                batch_file.unlink()

    if not any_changes:
        print("All batch JSON files are consistent. Nothing to do.")
    elif dry_run:
        print("\n(dry-run — no files written)")
    else:
        print("\nDone.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rentals-dir", default=str(DEFAULT_RENTALS_DIR))
    args = parser.parse_args()
    audit_and_fix(Path(args.rentals_dir), dry_run=args.dry_run)
