#!/usr/bin/env python3
"""
Todos Santos Rental Search
===========================
Scrapes known sources + uses Claude (with web_search) to find long-term
rentals in Todos Santos under $2,000 USD/month.

Usage:
    python3 rental_search.py              # print report (uses Claude API)
    python3 rental_search.py --cli        # use the `claude` CLI instead of SDK
    python3 rental_search.py --save       # save per-source JSON + listing folders
    python3 rental_search.py --diff       # save + diff each source against previous run
    python3 rental_search.py --no-claude  # scrape only, skip Claude entirely

Output layout (rentals/):
    airbnb-YYYY-MM-DD.json          ← summary JSON for analysis / diffing
    craigslist-YYYY-MM-DD.json
    todossantos-YYYY-MM-DD.json
    claude-api-YYYY-MM-DD.json  |  claude-cli-YYYY-MM-DD.json

    airbnb-01-studio-1339usd/       ← complete listing folder (already exists)
        info.json                   ← normalised schema
        listing.html                ← rendered card
        photo_01.jpg …

    craigslist-01-beach-studio-950usd/   ← same structure for new sources
        info.json
        listing.html
        photo_01.jpg …  (fetched when available)

Canonical listing schema (all sources):
    title        str
    source       str   "airbnb" | "craigslist" | "todossantos" | "claude-api" | "claude-cli"
    price_usd    int | null
    bedrooms     str | null
    location     str
    url          str | null
    contact      str | null
    description  str          full text / notes
    amenities    list[str]    [] when unavailable
    rating       str | null   "4.78 (119 reviews)" style
    listing_type str | null   e.g. "Entire rental unit"
    checkin      str | null
    checkout     str | null
    scraped      str          ISO date YYYY-MM-DD

Requirements:
    pip install anthropic requests beautifulsoup4
    claude CLI: already at /opt/homebrew/bin/claude

Set your API key:
    export ANTHROPIC_API_KEY="sk-ant-..."
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

# Lazy-import anthropic only when not using --cli
try:
    import anthropic
except ImportError:
    anthropic = None

# ── Config ────────────────────────────────────────────────────────────────────

MAX_USD   = 2000
MIN_MONTHS = 5      # minimum rental term we're interested in
RESULTS_DIR = Path(__file__).parent / "rentals"
TODAY = date.today().isoformat()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SYSTEM_PROMPT = f"""You are a rental search assistant for Todos Santos, Baja California Sur, Mexico.

Your job is to find long-term rental listings with a minimum term of {MIN_MONTHS} months under ${MAX_USD} USD/month.
Do NOT include nightly, weekly, or vacation rentals — only monthly rentals available for {MIN_MONTHS}+ months.

For each listing return a JSON object with these exact keys:
  title, price_usd (integer, null if unknown), bedrooms, location (neighborhood if known),
  source (site name), url (direct link or null), contact (email/phone if shown),
  description (full listing text), amenities (array, [] if unknown),
  rating (null), listing_type (null), checkin (null), checkout (null),
  scraped (today\u2019s date "{TODAY}")

Return ONLY a JSON array of listing objects — no prose, no markdown fences.
Exclude anything clearly over ${MAX_USD}/month. If price is in MXN, convert at 17.5 MXN/USD.
If a price is quoted per night (not per month), multiply by 30 to estimate monthly cost;
if that estimate exceeds ${MAX_USD}/month, exclude it.
If a listing has no price, include it with price_usd: null so the user can follow up.
"""

# ── Canonical schema ──────────────────────────────────────────────────────────

def normalise(raw: dict, source: str) -> dict:
    """Coerce any listing dict to the canonical schema."""
    price = raw.get("price_usd") or raw.get("usdPerMonth")
    if price is not None:
        try:
            price = int(price)
        except (ValueError, TypeError):
            price = None

    description = (
        raw.get("description")
        or raw.get("notes")
        or ""
    )
    amenities = raw.get("amenities") or []
    if isinstance(amenities, str):
        amenities = [a.strip() for a in amenities.split(",") if a.strip()]

    return {
        "title":        raw.get("title") or "",
        "source":       source,
        "price_usd":    price,
        "bedrooms":     raw.get("bedrooms"),
        "location":     raw.get("location") or "Todos Santos",
        "url":          raw.get("url") or raw.get("link"),
        "contact":      raw.get("contact"),
        "description":  description,
        "amenities":    amenities,
        "rating":       raw.get("rating"),
        "listing_type": raw.get("listingType") or raw.get("listing_type"),
        "checkin":      raw.get("checkin"),
        "checkout":     raw.get("checkout"),
        "scraped":      raw.get("scraped") or TODAY,
    }

# ── Direct scrapers ───────────────────────────────────────────────────────────

def get_soup(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [scraper] {url} → {e}", file=sys.stderr)
        return None


def scrape_airbnb_local() -> List[dict]:
    """Read existing Airbnb listing folders from rentals/ and normalise."""
    listings = []
    for folder in sorted(RESULTS_DIR.glob("airbnb-*")):
        if not folder.is_dir():
            continue
        info_file = folder / "info.json"
        if not info_file.exists():
            continue
        try:
            raw = json.loads(info_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        listing = normalise(raw, "airbnb")
        if listing["price_usd"] is not None and listing["price_usd"] > MAX_USD:
            continue
        listings.append(listing)
    return listings


def scrape_craigslist() -> List[dict]:
    """Baja Sur Craigslist long-term rentals."""
    listings = []
    url = "https://bajasur.craigslist.org/search/apa?query=todos+santos&sort=date"
    soup = get_soup(url)
    if not soup:
        return listings

    for item in soup.select("li.cl-static-search-result"):
        title_el = item.select_one(".title")
        price_el = item.select_one(".price")
        link_el  = item.select_one("a")
        if not title_el:
            continue

        title      = title_el.get_text(strip=True)
        price_text = price_el.get_text(strip=True) if price_el else ""
        price_usd  = _parse_price_usd(price_text)
        href       = link_el["href"] if link_el else None

        if price_usd is not None and price_usd > MAX_USD:
            continue

        listings.append(normalise({
            "title":       title,
            "price_usd":   price_usd,
            "url":         href,
            "description": price_text,
        }, "craigslist"))
        time.sleep(0.2)

    return listings


# Strong = unambiguously about renting; weak = common words that also appear in
# tour/event/business ads ("casa" is everywhere in Todos Santos, "studio" could
# be a photo studio, etc.).  A weak-only match is accepted only when there is
# also a recognisable price, cutting false positives like city-tour ads.
_RENTAL_KEYWORDS_STRONG = re.compile(
    r"\brent\b|\brental\b|\bfor\s+rent\b|\bse\s+renta\b|\bse\s+alquila\b"
    r"|\bcuarto\b|\bhabitaci[oó]n\b|\bapartment\b|\bbedroom\b",
    re.I,
)
_RENTAL_KEYWORDS_WEAK = re.compile(
    r"\bcasa\b|\bstudio\b",
    re.I,
)


def scrape_todos_santos_cc() -> List[dict]:
    """TodosSantos.cc classifieds — structural parse of div.classifieds_container div.item."""
    listings = []
    url = "https://todossantos.cc/classifieds/"
    soup = get_soup(url)
    if not soup:
        return listings

    for item in soup.select("div.classifieds_container div.item"):
        title_el   = item.select_one(".title")
        content_el = item.select_one(".content")
        contact_el = item.select_one(".contact")

        title   = title_el.get_text(strip=True)        if title_el   else ""
        content = content_el.get_text(" ", strip=True) if content_el else ""

        # Only keep posts that mention renting/housing.
        # Weak keywords ("casa", "studio") must be accompanied by a price to
        # avoid pulling in tour ads, events, or business listings.
        combined = title + " " + content
        has_strong = bool(_RENTAL_KEYWORDS_STRONG.search(combined))
        has_weak   = bool(_RENTAL_KEYWORDS_WEAK.search(combined))
        has_price  = _parse_price_usd(combined) is not None
        if not has_strong and not (has_weak and has_price):
            continue

        # Contact sub-fields
        contact_text = ""
        if contact_el:
            phone_el = contact_el.select_one(".phone")
            email_el = contact_el.select_one(".email")
            parts = []
            if phone_el:
                parts.append(phone_el.get_text(strip=True))
            if email_el:
                parts.append(email_el.get_text(strip=True))
            contact_text = " | ".join(parts) if parts else contact_el.get_text(" ", strip=True)

        price_usd = _parse_price_usd(title + " " + content)
        if price_usd is not None and price_usd > MAX_USD:
            continue

        listings.append(normalise({
            "title":       title or content[:80],
            "price_usd":   price_usd,
            "url":         url,   # no per-post URLs; link back to classifieds page
            "description": content,
            "contact":     contact_text or None,
        }, "todossantos"))

    time.sleep(0.5)
    return listings


def _parse_price_usd(text: str) -> Optional[int]:
    """Extract a monthly USD price from arbitrary text. Returns None if unclear."""
    text = text.replace(",", "")
    m = re.search(r"\$\s*(\d{3,6})", text)
    if m:
        val = int(m.group(1))
        if val < 100:
            return None
        # Values above $4,000 on a Baja listing are almost certainly MXN
        if val > 4_000:
            return round(val / 17.5)
        return val
    m = re.search(r"(\d{4,6})\s*(?:mxn|pesos?)", text, re.I)
    if m:
        return round(int(m.group(1)) / 17.5)
    return None


# ── Claude search (API SDK or CLI) ────────────────────────────────────────────

def _task(label: str, site: str, extra: str = "") -> dict:
    """Build a narrow single-source search task."""
    return {
        "label": label,
        "user_msg": (
            f"Fetch {site} and list every long-term rental in Todos Santos, "
            f"Baja California Sur under ${MAX_USD}/month with a minimum term "
            f"of {MIN_MONTHS} months. Exclude nightly, weekly, and vacation rentals. "
            + (extra + " " if extra else "")
            + f"Today is {TODAY}. Return the JSON array as instructed."
        ),
    }

CLAUDE_SEARCH_TASKS = [
    _task("amyrex",     "https://amyrextodossantos.com/long-term-rentals",
          "Fetch ONLY this exact URL — do NOT follow links to the homepage or "
          "vacation-rentals pages. This page may show nightly rates; if so, "
          "multiply by 30 to estimate monthly cost and exclude if over "
          f"${MAX_USD}/month. Only include true monthly long-term rentals."),
    _task("bajaprops",  "https://bajaproperties.com/todos-santos",
          "Focus on rentals, not sales."),
    _task("baraka",     "https://barakaentodos.com",
          "Focus on long-term rentals, not short-term vacation rentals."),
    _task("tsvilla-ts", "https://www.todossantosvillarentals.com/city/todos-santos/",
          "List all rentals on this page. Focus on long-term, 5+ months."),
    _task("tsvilla-pe", "https://www.todossantosvillarentals.com/city/el-pescadero/",
          "List all rentals on this page. Focus on long-term, 5+ months."),
    _task("pescprop",   "https://pescaderopropertymgmt.com/rentals",
          "List all rental listings on this page for Todos Santos / El Pescadero area."),
]


CLAUDE_CLI_PATH = shutil.which("claude") or "/opt/homebrew/bin/claude"


def _parse_claude_output(raw: str, source: str) -> List[dict]:
    """Parse a JSON array out of Claude's response text and normalise."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            print(f"  [claude] could not parse JSON. Snippet: {raw[:300]}", file=sys.stderr)
            return []
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError as e:
            print(f"  [claude] JSON parse error: {e}", file=sys.stderr)
            return []

    if not isinstance(data, list):
        return []

    clean = []
    for item in data:
        if not isinstance(item, dict):
            continue
        listing = normalise(item, source)
        if listing["price_usd"] is not None and listing["price_usd"] > MAX_USD:
            continue
        clean.append(listing)
    return clean


def search_with_claude_cli(user_msg: str, label: str = "") -> List[dict]:
    """Invoke the `claude` CLI via subprocess and return structured listings."""
    if not os.path.isfile(CLAUDE_CLI_PATH):
        print(f"  [claude-cli] binary not found at {CLAUDE_CLI_PATH}", file=sys.stderr)
        return []

    tag = f"claude-cli/{label}" if label else "claude-cli"
    print(f"  Calling claude CLI — {label or 'general'} …")
    prompt = f"{SYSTEM_PROMPT}\n\n{user_msg}"
    try:
        result = subprocess.run(
            [CLAUDE_CLI_PATH, "--print", "--dangerously-skip-permissions", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PATH": f"/opt/homebrew/bin:{os.environ.get('PATH', '')}"},
        )
    except FileNotFoundError:
        print(f"  [{tag}] could not execute {CLAUDE_CLI_PATH}", file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        print(f"  [{tag}] timed out after 120 s", file=sys.stderr)
        return []

    if result.returncode != 0:
        # Rate-limit message comes on stdout, not stderr
        out = result.stdout.strip()
        err = result.stderr.strip()
        detail = out or err or "(no output)"
        if "hit your limit" in detail or "resets" in detail:
            print(f"  [{tag}] ⛔ rate limited — {detail}", file=sys.stderr)
        else:
            print(f"  [{tag}] exit {result.returncode}: {detail[:300]}", file=sys.stderr)
        return []

    return _parse_claude_output(result.stdout, "claude-cli")


def search_with_claude_api(user_msg: str, label: str = "") -> List[dict]:
    """Use the Anthropic Python SDK with the web_search tool."""
    if anthropic is None:
        print("  [claude-api] anthropic package not installed. Run: pip install anthropic",
              file=sys.stderr)
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  [claude-api] ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return []

    tag = f"claude-api/{label}" if label else "claude-api"
    print(f"  Calling Claude API — {label or 'general'} …")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as e:
        print(f"  [{tag}] error: {e}", file=sys.stderr)
        return []

    raw = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw = block.text

    return _parse_claude_output(raw, "claude-api")


# ── Dedup + merge ─────────────────────────────────────────────────────────────

def _listing_key(l: dict) -> str:
    """Rough dedup key: normalised title + source."""
    title = re.sub(r"\W+", " ", (l.get("title") or "")).lower().strip()[:60]
    return f"{l.get('source', '')}|{title}"


def merge_listings(all_lists: List[List[dict]]) -> List[dict]:
    seen_keys: set = set()
    seen_urls: set = set()
    merged = []
    for lst in all_lists:
        for item in lst:
            # URL-based dedup: same listing found by multiple sources
            url = (item.get("url") or "").strip()
            if url and url in seen_urls:
                continue
            key = _listing_key(item)
            if key in seen_keys:
                continue
            if url:
                seen_urls.add(url)
            seen_keys.add(key)
            merged.append(item)
    merged.sort(key=lambda l: (l.get("price_usd") or 9999))
    return merged


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(listings: List[dict]):
    divider = "─" * 68
    print(f"\n{'═' * 68}")
    print(f"  TODOS SANTOS RENTALS  ·  {MIN_MONTHS}+ months  ·  under ${MAX_USD}/mo  ·  {TODAY}")
    print(f"{'═' * 68}")
    if not listings:
        print("  No listings found.")
    for i, l in enumerate(listings, 1):
        price   = f"${l['price_usd']}/mo" if l.get("price_usd") else "price unknown"
        beds    = l.get("bedrooms") or "?"
        title   = l.get("title") or "Untitled"
        src     = l.get("source") or ""
        loc     = l.get("location") or "Todos Santos"
        url     = l.get("url") or ""
        contact = l.get("contact") or ""
        desc    = l.get("description") or ""

        print(f"\n  {i:>2}. {title}")
        beds_str   = str(beds)
        beds_label = beds_str if (beds_str == "?" or re.search(r"bed|bath|BR", beds_str, re.I)) else f"{beds_str} bed"
        print(f"      {price}  ·  {beds_label}  ·  {loc}  ·  [{src}]")
        if url:
            print(f"      {url}")
        if contact:
            print(f"      Contact: {contact}")
        if desc:
            words = desc.split()
            line, lines = "", []
            for w in words:
                if len(line) + len(w) + 1 > 60:
                    lines.append(line)
                    line = w
                else:
                    line = (line + " " + w).strip()
            if line:
                lines.append(line)
            for ln in lines[:3]:
                print(f"      {ln}")

        print(f"  {divider}")

    print(f"\n  Total: {len(listings)} listing(s)  ·  scraped {TODAY}")
    print(f"\n  ⚠️  Also check manually (no API access):")
    print(f"      • Facebook: 'Todos Santos Rentals', 'Todos Santos Housing', 'Baja Sur Rentals'")
    print(f"      • Nextdoor Todos Santos")
    print()


# ── Save / diff ───────────────────────────────────────────────────────────────

def save_results(listings: List[dict], source: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{source}-{TODAY}.json"
    out.write_text(json.dumps(listings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved → {out}")
    return out


def diff_against_previous(current: List[dict], source: str):
    """Print listings that are new compared to the most recent previous run."""
    prior_files = sorted(RESULTS_DIR.glob(f"{source}-*.json"))
    prior_files = [f for f in prior_files if not f.stem.endswith(TODAY)]
    if not prior_files:
        print(f"  [{source}] No previous results to diff against.")
        return

    prev_file = prior_files[-1]
    try:
        prev = json.loads(prev_file.read_text(encoding="utf-8"))
    except Exception:
        print(f"  Could not read {prev_file}.", file=sys.stderr)
        return

    prev_keys = {_listing_key(l) for l in prev}
    new_ones  = [l for l in current if _listing_key(l) not in prev_keys]
    gone_keys = prev_keys - {_listing_key(l) for l in current}

    print(f"\n  [{source}] Diff vs {prev_file.name}:")
    print(f"  + {len(new_ones)} new listing(s)   - {len(gone_keys)} removed\n")
    if new_ones:
        print("  NEW LISTINGS:")
        print_report(new_ones)


# ── Listing folders ───────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "airbnb":      "#ff385c",
    "craigslist":  "#cc4444",
    "todossantos": "#2d6a4f",
    "claude-api":  "#6B46C1",
    "claude-cli":  "#6B46C1",
}


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:40]


def _folder_name(listing: dict, index: int) -> str:
    source = listing.get("source", "unknown")
    slug   = _slugify(listing.get("title") or "listing")
    price  = listing.get("price_usd")
    price_part = f"{price}usd" if price else "noprice"
    return f"{source}-{index:02d}-{slug}-{price_part}"


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
    for folder in RESULTS_DIR.glob(f"{source}-*/"):
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
    for p in RESULTS_DIR.glob(f"{source}-[0-9][0-9]-*/"):
        if not p.is_dir():
            continue
        m = pattern.match(p.name)
        if m:
            indices.append(int(m.group(1)))
    return (max(indices) + 1) if indices else 1


def _esc(text) -> str:
    """Minimal HTML escaping for text interpolated into HTML."""
    text = str(text)
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def generate_listing_html(listing: dict) -> str:
    source      = listing.get("source", "")
    color       = SOURCE_COLORS.get(source, "#444")
    title       = _esc(listing.get("title") or "Untitled")
    price       = listing.get("price_usd")
    price_str   = f"${price}" if price else "—"
    bedrooms    = _esc(listing.get("bedrooms") or "")
    location    = _esc(listing.get("location") or "Todos Santos")
    rating      = _esc(listing.get("rating") or "")
    listing_type = _esc(listing.get("listing_type") or "")
    description  = _esc(listing.get("description") or "")
    amenities    = listing.get("amenities") or []
    checkin      = _esc(listing.get("checkin") or "")
    checkout     = _esc(listing.get("checkout") or "")
    url          = listing.get("url") or ""
    contact      = _esc(listing.get("contact") or "")
    scraped      = _esc(listing.get("scraped") or TODAY)
    local_photos = listing.get("localPhotos") or []

    source_label = _esc(source.replace("-", " ").title())
    cta_label    = f"View on {source_label} →" if url else ""

    # Photo block
    if local_photos:
        hero = local_photos[0]
        thumbs_html = "".join(
            f'<img src="{p}" alt="" class="thumb" '
            f'onclick="document.querySelector(\'.hero-photo\').src=this.src">'
            for p in local_photos[1:]
        )
        photo_block = (
            f'<img src="{hero}" alt="{title}" class="hero-photo" '
            f'onerror="this.style.display=\'none\'">'
            f'<div class="thumbs">{thumbs_html}</div>'
        )
    else:
        photo_block = '<div class="no-photo">No photos available</div>'

    meta_parts = []
    if listing_type:
        meta_parts.append(f"<span>{listing_type}</span>")
    if bedrooms:
        meta_parts.append(f'<span class="dot">·</span><span>{bedrooms}</span>')
    if rating:
        meta_parts.append(f'<span class="dot">·</span><span class="rating">★ {rating}</span>')
    meta_html = "\n            ".join(meta_parts)

    dates_html = ""
    if checkin or checkout:
        dates_html = (
            f'<div class="dates"><p>📅 '
            f'<strong>Check-in:</strong> {checkin} &nbsp;→&nbsp; '
            f'<strong>Checkout:</strong> {checkout}</p></div>'
        )

    amenities_html = ""
    if amenities:
        items = "".join(f"<li>{a}</li>" for a in amenities)
        amenities_html = (
            f'<div class="section"><h3>Amenities</h3>'
            f'<ul class="amenities">{items}</ul></div>'
        )

    contact_html = ""
    if contact:
        contact_html = (
            f'<div class="section"><h3>Contact</h3>'
            f'<p class="desc">{contact}</p></div>'
        )

    desc_html = ""
    if description:
        desc_html = (
            f'<div class="section"><h3>About this place</h3>'
            f'<p class="desc">{description}</p></div>'
        )

    cta_html = (
        f'<a href="{url}" class="cta" target="_blank">{cta_label}</a>'
        if url else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {price_str}/mo</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f7f7f7; color: #222; }}
    .header {{ background: {color}; color: white; padding: 16px 24px; }}
    .header h1 {{ font-size: 14px; font-weight: 400; opacity: 0.9; }}
    .container {{ max-width: 860px; margin: 24px auto; padding: 0 16px; }}
    .hero-photo {{ width: 100%; max-height: 460px; object-fit: cover; border-radius: 12px; display: block; }}
    .no-photo {{ background: #e8e8e8; height: 200px; display: flex; align-items: center; justify-content: center; border-radius: 12px; font-size: 18px; color: #888; }}
    .thumbs {{ display: flex; gap: 8px; margin-top: 8px; overflow-x: auto; }}
    .thumb {{ width: 120px; height: 80px; object-fit: cover; border-radius: 8px; cursor: pointer; flex-shrink: 0; opacity: 0.8; }}
    .thumb:hover {{ opacity: 1; }}
    .info-card {{ background: white; border-radius: 12px; padding: 24px; margin-top: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
    .title-row {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }}
    h2 {{ font-size: 22px; font-weight: 700; line-height: 1.3; }}
    .price-tag {{ background: #f0fff4; border: 2px solid #22c55e; border-radius: 10px; padding: 8px 16px; text-align: center; flex-shrink: 0; }}
    .price-tag .amount {{ font-size: 26px; font-weight: 800; color: #16a34a; }}
    .price-tag .label {{ font-size: 11px; color: #666; }}
    .meta {{ display: flex; gap: 16px; margin: 12px 0; flex-wrap: wrap; }}
    .meta span {{ font-size: 14px; color: #555; }}
    .meta .dot {{ color: #ccc; }}
    .rating {{ color: {color}; font-weight: 600; }}
    .section {{ margin-top: 20px; }}
    .section h3 {{ font-size: 16px; font-weight: 600; margin-bottom: 8px; color: #333; }}
    .desc {{ font-size: 14px; line-height: 1.7; color: #444; }}
    .amenities {{ list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 6px; }}
    .amenities li {{ font-size: 13px; color: #555; padding: 4px 0; padding-left: 20px; position: relative; }}
    .amenities li::before {{ content: "✓"; position: absolute; left: 0; color: #22c55e; font-weight: bold; }}
    .dates {{ background: #f8faff; border: 1px solid #dde6ff; border-radius: 8px; padding: 12px 16px; margin-top: 8px; }}
    .dates p {{ font-size: 13px; color: #555; }}
    .cta {{ display: block; text-align: center; background: {color}; color: white; padding: 14px; border-radius: 8px; text-decoration: none; font-weight: 600; margin-top: 20px; font-size: 15px; }}
    .cta:hover {{ opacity: 0.88; }}
    .footer {{ text-align: center; font-size: 12px; color: #999; margin: 24px 0; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Todos Santos Rentals — {source_label} · Scraped {scraped} · Under ${MAX_USD}/mo</h1>
  </div>
  <div class="container">
    <div style="margin-top:0">
      {photo_block}
    </div>
    <div class="info-card">
      <div class="title-row">
        <div>
          <h2>{title}</h2>
          <div class="meta">
            {meta_html}
          </div>
        </div>
        <div class="price-tag">
          <div class="amount">{price_str}</div>
          <div class="label">/ month</div>
        </div>
      </div>
      {dates_html}
      {desc_html}
      {amenities_html}
      {contact_html}
      {cta_html}
    </div>
    <div class="footer">Scraped {scraped} · {location} · Source: {source_label}</div>
  </div>
</body>
</html>"""


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
    folder = RESULTS_DIR / _folder_name(listing, index)
    folder.mkdir(exist_ok=True)

    # Fetch photos when the listing has a URL and we don't already have any
    local_photos = listing.get("localPhotos") or []
    if not local_photos and listing.get("url"):
        print(f"    ↓ fetching photos from {listing['url']} …")
        local_photos = fetch_photos(listing["url"], folder)
        if local_photos:
            print(f"    → {len(local_photos)} photo(s) saved")

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

    print(f"  → folder: {folder.name}/")
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
    print(f"  ↺ price update: ${old_price} → ${new_price}  ({folder.name}/)")


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
        return True   # network error ≠ deleted listing


def save_listing_folders(listings: List[dict]):
    """For each listing: verify it is active, then create/update/skip its folder."""
    source = listings[0].get("source", "unknown") if listings else "unknown"
    existing = _scan_existing(source)
    start_index = _next_index(source)

    new_count = updated_count = skipped_count = 0
    for listing in listings:
        url   = listing.get("url")
        tkey  = _listing_key(listing)
        match = existing.get(url) or existing.get(tkey)

        if match is None:
            if not is_listing_active(url):
                print(f"  ✗ inactive — skipping: {listing.get('title', '')[:60]}")
                skipped_count += 1
                continue
            save_listing_folder(listing, start_index + new_count)
            new_count += 1
        elif listing.get("price_usd") != match["price"]:
            if not is_listing_active(url):
                print(f"  ✗ inactive — skipping price update: {listing.get('title', '')[:60]}")
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
        parts.append(f"{skipped_count} inactive")
    if not parts:
        parts.append("no changes")
    print(f"  [{source}] {', '.join(parts)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Todos Santos rental search")
    parser.add_argument("--save", action="store_true", help="Save per-source JSON + listing folders to rentals/")
    parser.add_argument("--diff", action="store_true", help="Save + diff each source against previous run")
    parser.add_argument("--cli", action="store_true", help="Use the `claude` CLI instead of the Python SDK")
    parser.add_argument("--no-claude", action="store_true", help="Skip Claude entirely (scrape only)")
    args = parser.parse_args()

    # Collect results per source
    source_results = {}

    print("Reading local Airbnb listings …")
    source_results["airbnb"] = scrape_airbnb_local()

    print("Scraping Craigslist Baja Sur …")
    source_results["craigslist"] = scrape_craigslist()

    print("Scraping TodosSantos.cc …")
    source_results["todossantos"] = scrape_todos_santos_cc()

    if not args.no_claude:
        # Run each focused search task in sequence.
        # Results accumulate under a single source key ("claude-cli" or
        # "claude-api") so save/diff/dedup logic is unchanged.
        api_ready = anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))
        cli_ready = os.path.isfile(CLAUDE_CLI_PATH)

        if not api_ready and not cli_ready:
            print(
                "  [claude] Skipping — neither API nor CLI is available.\n"
                "  To enable:  pip install anthropic  and set ANTHROPIC_API_KEY\n"
                "              OR  npm install -g @anthropic-ai/claude-code",
                file=sys.stderr,
            )
        else:
            if args.cli:
                src_key = "claude-cli"
                fn = search_with_claude_cli
            elif api_ready:
                src_key = "claude-api"
                fn = search_with_claude_api
            else:
                src_key = "claude-cli"
                fn = search_with_claude_cli

            print(f"Searching via {src_key} ({len(CLAUDE_SEARCH_TASKS)} tasks, parallel) …")
            combined: List[dict] = []
            with ThreadPoolExecutor(max_workers=len(CLAUDE_SEARCH_TASKS)) as pool:
                futures = {
                    pool.submit(fn, user_msg=task["user_msg"], label=task["label"]): task["label"]
                    for task in CLAUDE_SEARCH_TASKS
                }
                for future in as_completed(futures):
                    label = futures[future]
                    try:
                        combined.extend(future.result())
                    except Exception as e:
                        print(f"  [{src_key}/{label}] error: {e}", file=sys.stderr)
            source_results[src_key] = combined

    # Merge all sources for the combined report
    listings = merge_listings(list(source_results.values()))
    print_report(listings)

    # Save and/or diff per source
    if args.save or args.diff:
        for source, lst in source_results.items():
            if lst:
                save_results(lst, source)
                if source != "airbnb":   # airbnb folders already exist from download_photos.py
                    save_listing_folders(lst)
    if args.diff:
        for source, lst in source_results.items():
            if lst:
                diff_against_previous(lst, source)


if __name__ == "__main__":
    main()
