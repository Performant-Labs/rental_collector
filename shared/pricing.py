"""
shared.pricing — Price extraction from free-text listing descriptions.

Canonical implementation of _parse_price_usd() used by both the scraper
and the WhatsApp converter.  Handles USD, MXN, and "pesos" notations
common in Baja California Sur rental listings.
"""

from __future__ import annotations

import re
from typing import Optional


def parse_price_usd(text: str) -> Optional[int]:
    """Extract a monthly USD price from arbitrary text.

    Returns ``None`` when the text is empty or no price pattern is found.

    Currency heuristics for Baja California:
      - Values ≤ $4,000 are assumed USD.
      - Values > $4,000 with a ``$`` sign are assumed MXN and converted at 17.5.
      - Explicit ``MXN`` / ``pesos`` suffix always triggers conversion.
    """
    if not text:
        return None
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
