"""
scraper.llm_search — LLM-based rental search (Claude API, CLI, LiteLLM + Jina).

Extracted from rental_search.py to keep the monolith manageable.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import List

import requests

from shared.config import MAX_USD, TODAY
from scraper.normalise import normalise
from scraper.scrapers import HEADERS  # reuse UA headers

# Lazy-import anthropic only when not using --cli
try:
    import anthropic
except ImportError:
    anthropic = None

# Lazy-import litellm for --local mode
try:
    import litellm
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None

MIN_MONTHS = 5  # minimum rental term we're interested in

SYSTEM_PROMPT = f"""You are a rental search assistant for Todos Santos, Baja California Sur, Mexico.

Your job is to find long-term rental listings with a minimum term of {MIN_MONTHS} months under ${MAX_USD} USD/month.
Do NOT include nightly, weekly, or vacation rentals — only monthly rentals available for {MIN_MONTHS}+ months.

For each listing return a JSON object with these exact keys:
  title, price_usd (integer, null if unknown), bedrooms, location (neighborhood if known),
  url (direct link or null), contact (email/phone if shown),
  description (full listing text), amenities (array, [] if unknown),
  rating (null), listing_type (null), checkin (null), checkout (null),
  scraped (today\u2019s date "{TODAY}"),
  photo_url (the direct URL of the main listing photo image if visible on the page, otherwise null)

Return ONLY a JSON array of listing objects — no prose, no markdown fences.
Exclude anything clearly over ${MAX_USD}/month. If price is in MXN, convert at 17.5 MXN/USD.
If a price is quoted per night (not per month), multiply by 30 to estimate monthly cost;
if that estimate exceeds ${MAX_USD}/month, exclude it.
If a listing has no price, include it with price_usd: null so the user can follow up.
"""


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
    _task("airbnb-live",
          "https://www.airbnb.com/s/Todos-Santos--Baja-California-Sur--Mexico/homes"
          "?refinement_paths%5B%5D=%2Fhomes&tab_id=home_tab"
          "&flexible_trip_lengths%5B%5D=one_month&monthly_start_date=2026-05-01"
          "&monthly_length=3&monthly_end_date=2026-08-01&price_filter_input_type=2"
          "&price_filter_num_nights=90&channel=EXPLORE",
          "This is an Airbnb monthly-stays search for Todos Santos. "
          "Extract each visible listing: title, nightly price (multiply by 30 for monthly), "
          "url, rating, description, and photo_url (the main listing image src). "
          "Skip listings over $2000/month when converted."),
]

CLAUDE_CLI_PATH = shutil.which("claude") or "/opt/homebrew/bin/claude"

JINA_BASE = "https://r.jina.ai/"


def fetch_url_via_jina(url: str) -> str:
    """Fetch a URL as clean markdown via Jina Reader (no JS required)."""
    try:
        resp = requests.get(
            JINA_BASE + url,
            headers={**HEADERS, "Accept": "text/plain"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text[:12000]  # cap at 12k chars to stay within LLM context
    except Exception as e:
        print(f"  [jina] {url} → {e}", file=sys.stderr)
        return ""


def search_with_litellm(user_msg: str, label: str = "", model: str = "openai/gemma-4-26B-A4B-it") -> List[dict]:
    """Use a local LLM via LiteLLM + Jina Reader to extract rental listings."""
    if litellm is None:
        print("  [litellm] litellm not installed. Run: pip install litellm", file=sys.stderr)
        return []

    tag = f"llm/{label}" if label else "llm"

    # Extract the URL from the user message
    url_match = re.search(r'https?://\S+', user_msg)
    if not url_match:
        print(f"  [{tag}] no URL found in task message", file=sys.stderr)
        return []

    url = url_match.group(0)
    print(f"  [{tag}] Fetching {url} via Jina \u2026")
    page_content = fetch_url_via_jina(url)
    if not page_content:
        return []

    prompt = f"{user_msg}\n\nPage content:\n{page_content}"
    print(f"  [{tag}] Calling local LLM ({model}) \u2026")
    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            api_base="http://localhost:1234/v1",
            api_key="lm-studio",
            temperature=0.1,
            max_tokens=4096,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        print(f"  [{tag}] LLM error: {e}", file=sys.stderr)
        return []

    results = _parse_claude_output(raw, label or "local-llm")
    print(f"  [{tag}] \u2192 {len(results)} listing(s)")
    return results


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
    print(f"  Calling claude CLI \u2014 {label or 'general'} \u2026")
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
            print(f"  [{tag}] \u26d4 rate limited \u2014 {detail}", file=sys.stderr)
        else:
            print(f"  [{tag}] exit {result.returncode}: {detail[:300]}", file=sys.stderr)
        return []

    return _parse_claude_output(result.stdout, label or "claude-cli")


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
    print(f"  Calling Claude API \u2014 {label or 'general'} \u2026")
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

    return _parse_claude_output(raw, label or "claude-api")
