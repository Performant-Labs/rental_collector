"""
rental_search — Todos Santos rental finder.

This module is now a thin façade.  All functionality has been extracted
into focused sub-modules under scraper/:

    scraper/normalise.py   — normalise()
    scraper/scrapers.py    — get_soup, scrape_airbnb_local, scrape_craigslist,
                             scrape_todos_santos_cc
    scraper/llm_search.py  — Claude API/CLI, LiteLLM, Jina Reader
    scraper/folder_ops.py  — _scan_existing, save_listing_folder, etc.
    scraper/reporting.py   — print_report, save_results, diff_against_previous

Every public name is *re-exported* here so that existing callers
(e.g. test_rental_search.py) continue to work with ``import rental_search as rs``.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

# Ensure the project root is on sys.path so that `shared` is importable
# regardless of how this script is invoked (cd scraper && python rental_search.py).
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Shared imports ────────────────────────────────────────────────────────────
from shared import config as _config
from shared.config import MAX_USD, SOURCE_COLORS, TODAY, DEFAULT_RENTALS_DIR
from shared.keywords import RENTAL_KEYWORDS_STRONG, RENTAL_KEYWORDS_WEAK
from shared.pricing import parse_price_usd
from shared.listing_io import slugify, folder_name, listing_key
from shared.listing_html import generate_listing_html, _esc

# Backward-compat aliases
_parse_price_usd = parse_price_usd
_slugify = slugify
_folder_name = folder_name
_listing_key = listing_key
_RENTAL_KEYWORDS_STRONG = RENTAL_KEYWORDS_STRONG
_RENTAL_KEYWORDS_WEAK = RENTAL_KEYWORDS_WEAK

# ── Re-exports from sub-modules ──────────────────────────────────────────────
from scraper.normalise import normalise                         # noqa: F401
from scraper.scrapers import (                                  # noqa: F401
    HEADERS,
    get_soup,
    scrape_airbnb_local,
    scrape_craigslist,
    scrape_todos_santos_cc,
)
from scraper.llm_search import (                                # noqa: F401
    SYSTEM_PROMPT,
    CLAUDE_SEARCH_TASKS,
    CLAUDE_CLI_PATH,
    fetch_url_via_jina,
    search_with_litellm,
    search_with_claude_cli,
    search_with_claude_api,
    _parse_claude_output,
    anthropic,
    litellm,
)
from scraper.folder_ops import (                                # noqa: F401
    _scan_existing,
    _next_index,
    fetch_photos,
    save_listing_folder,
    update_listing_folder,
    is_listing_active,
    save_listing_folders,
    _DEAD_PHRASES,
)
from scraper.reporting import (                                 # noqa: F401
    print_report,
    save_results,
    diff_against_previous,
)

# ── Config ────────────────────────────────────────────────────────────────────

MIN_MONTHS = 5      # minimum rental term we're interested in
RESULTS_DIR = DEFAULT_RENTALS_DIR  # alias for backward compatibility


# ── Dedup + merge ─────────────────────────────────────────────────────────────

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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Todos Santos rental search")
    parser.add_argument("--save", action="store_true", help="Save per-source JSON + listing folders to rentals/")
    parser.add_argument("--diff", action="store_true", help="Save + diff each source against previous run")
    parser.add_argument("--cli", action="store_true", help="Use the `claude` CLI instead of the Python SDK")
    parser.add_argument("--no-claude", action="store_true", help="Skip Claude entirely (scrape only)")
    parser.add_argument("--local", action="store_true", help="Use a local LLM via LiteLLM + Jina Reader")
    parser.add_argument("--model", default="openai/gemma-4-26B-A4B-it", help="LiteLLM model string for --local mode")
    args = parser.parse_args()

    # Collect results per source
    source_results = {}

    print("Reading local Airbnb listings \u2026")
    source_results["airbnb"] = scrape_airbnb_local()

    print("Scraping Craigslist Baja Sur \u2026")
    source_results["craigslist"] = scrape_craigslist()

    print("Scraping TodosSantos.cc \u2026")
    source_results["todossantos"] = scrape_todos_santos_cc()

    if args.local:
        # Local LLM mode: sequential to respect GPU memory limits
        print(f"Searching via local LLM ({args.model}, {len(CLAUDE_SEARCH_TASKS)} tasks, sequential) \u2026")
        combined: List[dict] = []
        for task in CLAUDE_SEARCH_TASKS:
            try:
                combined.extend(search_with_litellm(
                    user_msg=task["user_msg"],
                    label=task["label"],
                    model=args.model,
                ))
            except Exception as e:
                print(f"  [local-llm/{task['label']}] error: {e}", file=sys.stderr)
        source_results["local-llm"] = combined

    elif not args.no_claude:
        # Cloud LLM mode (Claude API or CLI)
        api_ready = anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))
        cli_ready = os.path.isfile(CLAUDE_CLI_PATH)

        if not api_ready and not cli_ready:
            print(
                "  [claude] Skipping \u2014 neither API nor CLI is available.\n"
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

            print(f"Searching via {src_key} ({len(CLAUDE_SEARCH_TASKS)} tasks, parallel) \u2026")
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
