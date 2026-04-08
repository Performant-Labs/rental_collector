"""
scraper.scrapers — Direct web scrapers (Airbnb local, Craigslist, TodosSantos.cc).

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
from bs4 import BeautifulSoup

from shared import config as _config
from shared.config import MAX_USD
from shared.keywords import RENTAL_KEYWORDS_STRONG, RENTAL_KEYWORDS_WEAK
from shared.pricing import parse_price_usd
from scraper.normalise import normalise



HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


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
    for folder in sorted(_config.DEFAULT_RENTALS_DIR.glob("airbnb-*")):
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
        price_usd  = parse_price_usd(price_text)
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
        combined = title + " " + content
        has_strong = bool(RENTAL_KEYWORDS_STRONG.search(combined))
        has_weak   = bool(RENTAL_KEYWORDS_WEAK.search(combined))
        has_price  = parse_price_usd(combined) is not None
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

        price_usd = parse_price_usd(title + " " + content)
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
