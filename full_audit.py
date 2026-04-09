#!/usr/bin/env python3
"""Full data consistency audit for the rental_collector pipeline."""
import json, re, sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding='utf-8')

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
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
    ("bajasurfcasitas.com",         "bajasurfcasitas"),
    ("craigslist.org",              "craigslist"),
    ("todossantos.cc",              "todossantos"),
]
VALID_CHANNELS = {r[1] for r in URL_CHANNEL_MAP} | {"whatsapp"}
_FOLDER_RE = re.compile(r'^(.+?)-(\d{2})-')

def channel_from_url(url):
    if not url: return None
    host = urlparse(url).netloc.lower().replace("www.", "")
    for domain, channel in URL_CHANNEL_MAP:
        if domain in host:
            return channel
    return None

def channel_from_folder(name):
    m = _FOLDER_RE.match(name)
    return m.group(1).lower() if m else name.split("-", 1)[0].lower()

def expected_channel(folder_name, url):
    return channel_from_url(url) or channel_from_folder(folder_name)

rentals = DEFAULT_RENTALS_DIR

# ── 1. Folder names ───────────────────────────────────────────────────────────
print("=" * 60)
print("1. FOLDER NAMES")
print("=" * 60)
folder_prefix_counts = defaultdict(int)
non_channel_folders = []
for f in sorted(rentals.iterdir()):
    if not f.is_dir(): continue
    prefix = channel_from_folder(f.name)
    folder_prefix_counts[prefix] += 1
    if prefix not in VALID_CHANNELS:
        non_channel_folders.append(f.name)

for prefix, count in sorted(folder_prefix_counts.items()):
    status = "OK" if prefix in VALID_CHANNELS else "*** NOT A REAL CHANNEL ***"
    print(f"  {prefix:<20} {count:>4} folders  {status}")

if non_channel_folders:
    print(f"\n  PROBLEM: {len(non_channel_folders)} folders with non-channel prefix:")
    for n in non_channel_folders:
        print(f"    {n}")
else:
    print(f"\n  All {sum(folder_prefix_counts.values())} folder names: CLEAN")

# ── 2. info.json source fields ────────────────────────────────────────────────
print()
print("=" * 60)
print("2. INFO.JSON SOURCE FIELDS")
print("=" * 60)
info_source_counts = defaultdict(int)
info_mismatches = []

for f in sorted(rentals.iterdir()):
    if not f.is_dir() or not (f / "info.json").exists(): continue
    info = json.loads((f / "info.json").read_text(encoding="utf-8"))
    src = info.get("source") or ""
    expected = expected_channel(f.name, info.get("url"))
    info_source_counts[src] += 1
    if src != expected:
        info_mismatches.append((f.name, src, expected))

for src, count in sorted(info_source_counts.items()):
    status = "OK" if src in VALID_CHANNELS else "*** NOT A REAL CHANNEL ***"
    label = '"' + src + '"' if src else '(empty)'
    print(f"  {label:<24} {count:>4} files  {status}")

if info_mismatches:
    print(f"\n  PROBLEM: {len(info_mismatches)} info.json files have wrong source:")
    for folder, actual, wanted in info_mismatches:
        print(f"    {folder}: \"{actual}\" -> should be \"{wanted}\"")
else:
    print(f"\n  All {sum(info_source_counts.values())} info.json source fields: CLEAN")

# ── 3. Batch JSON files ───────────────────────────────────────────────────────
print()
print("=" * 60)
print("3. BATCH JSON FILES (rentals/*.json)")
print("=" * 60)
batch_issues = []
batch_ok = []

for jf in sorted(rentals.glob("*.json")):
    if jf.name.startswith(".") or jf.name in {"last_ingest_stats.json"}:
        continue
    try:
        listings = json.loads(jf.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(listings, list):
        continue

    # Derive file channel prefix (strip trailing YYYY-MM-DD)
    parts = jf.stem.split("-")
    if len(parts) >= 4:
        channel_parts = parts[:-3]
    else:
        channel_parts = [parts[0]]
    file_prefix = "-".join(channel_parts)
    prefix_ok = file_prefix in VALID_CHANNELS

    wrong = []
    for l in listings:
        ch = channel_from_url(l.get("url"))
        src = l.get("source") or ""
        if ch and src != ch:
            wrong.append((src, ch, (l.get("title") or "")[:35]))
        elif not ch and src not in VALID_CHANNELS:
            wrong.append((src, "?", (l.get("title") or "")[:35]))

    if wrong or not prefix_ok:
        batch_issues.append((jf.name, file_prefix, prefix_ok, wrong))
    else:
        batch_ok.append(jf.name)

for name in batch_ok:
    print(f"  OK    {name}")

for name, prefix, prefix_ok, wrong in batch_issues:
    label = " *** BAD FILENAME PREFIX ***" if not prefix_ok else ""
    print(f"  FAIL  {name}{label}")
    for src, ch, title in wrong:
        print(f"        \"{src}\" should be \"{ch}\"  ({title})")

if not batch_issues:
    print(f"\n  All {len(batch_ok)} batch files: CLEAN")
else:
    print(f"\n  {len(batch_issues)} batch file(s) have issues.")

# ── 4. Meilisearch ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("4. MEILISEARCH INDEX")
print("=" * 60)
try:
    import httpx
    r = httpx.post(
        "http://localhost:7700/indexes/rentals_listings/search",
        json={"q": "", "facets": ["source"], "limit": 0},
        timeout=5,
    )
    d = r.json()
    total = d.get("estimatedTotalHits", 0)
    dist = d.get("facetDistribution", {}).get("source", {})
    print(f"  Total documents: {total}")
    for src, n in sorted(dist.items()):
        status = "OK" if src in VALID_CHANNELS else "*** NOT A REAL CHANNEL ***"
        print(f"    {src:<24} {n:>4}  {status}")
    non_ch = [s for s in dist if s not in VALID_CHANNELS]
    if not non_ch:
        print(f"\n  All sources in Meilisearch: CLEAN")
    else:
        print(f"\n  PROBLEM: {non_ch} are not real channel labels")
except Exception as e:
    print(f"  Could not query Meilisearch: {e}")

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
total_issues = len(non_channel_folders) + len(info_mismatches) + len(batch_issues)
if total_issues == 0:
    print("RESULT: CLEAN - all folders, info.json files, and batch files consistent.")
else:
    print(f"RESULT: {total_issues} issue group(s) found - see above.")
print("=" * 60)
