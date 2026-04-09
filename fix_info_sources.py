#!/usr/bin/env python3
"""
Audit and fix source field in every info.json file.

The authoritative source is derived from:
  1. The listing URL (exact same logic as ingestion._normalise_source)
  2. The folder name prefix as fallback
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from collections import defaultdict

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

_FOLDER_SOURCE_RE = re.compile(r'^(.+?)-(\d{2})-')
VALID_CHANNELS = {r[1] for r in URL_CHANNEL_MAP} | {"whatsapp"}


def channel_from_url(url):
    if not url:
        return None
    host = urlparse(url).netloc.lower().replace("www.", "")
    for domain, channel in URL_CHANNEL_MAP:
        if domain in host:
            return channel
    return None


def channel_from_folder(folder_name):
    m = _FOLDER_SOURCE_RE.match(folder_name)
    return m.group(1).lower() if m else folder_name.split("-", 1)[0].lower()


def real_channel(folder_name, url):
    """Best-effort channel: URL wins, then folder prefix."""
    return channel_from_url(url) or channel_from_folder(folder_name)


def audit_and_fix(rentals_dir: Path, dry_run: bool = False):
    all_folders = sorted(
        f for f in rentals_dir.iterdir()
        if f.is_dir() and (f / "info.json").exists()
    )

    bad = []       # (folder, current_source, correct_source)
    ok_count = 0

    for folder in all_folders:
        info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
        current = info.get("source", "")
        correct = real_channel(folder.name, info.get("url"))
        if current != correct:
            bad.append((folder, current, correct))
        else:
            ok_count += 1

    print(f"Checked {len(all_folders)} folders.")
    print(f"  {ok_count} already correct")
    print(f"  {len(bad)} need updating\n")

    if not bad:
        print("All info.json source fields are consistent. Nothing to do.")
        return

    for folder, current, correct in bad:
        print(f"  {folder.name}")
        print(f"    source: \"{current}\" -> \"{correct}\"")
        if dry_run:
            continue
        info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
        info["source"] = correct
        (folder / "info.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"    OK")

    if dry_run:
        print("\n(dry-run — no files written)")
    else:
        print(f"\nFixed {len(bad)} file(s). Run ingest_runner --mode full to sync Meilisearch.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rentals-dir", default=str(DEFAULT_RENTALS_DIR))
    args = parser.parse_args()
    audit_and_fix(Path(args.rentals_dir), dry_run=args.dry_run)
