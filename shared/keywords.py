"""
shared.keywords — Rental-detection keyword regexes.

Canonical definitions of _RENTAL_KEYWORDS_STRONG and _RENTAL_KEYWORDS_WEAK
used by the scraper (rental_search.py), the dashboard ingestion
(ingestion.py), and any future source that needs to decide whether a
listing describes a rental property.

The "strong" list uses the expanded Spanish version (from ingestion.py)
so that all subsystems agree on what constitutes a rental.
"""

from __future__ import annotations

import re

# ── Strong keywords ───────────────────────────────────────────────────────────
# If a listing contains any of these, it is considered a rental even without
# a recognisable price.  Includes both English and Spanish phrases common in
# Baja California Sur.

RENTAL_KEYWORDS_STRONG = re.compile(
    r"\brent\b|\brental\b|\bfor\s+rent\b|\bse\s+renta\b|\bse\s+alquila\b"
    r"|\bcuarto\b|\bhabitaci[oó]n\b|\bapartment\b|\bbedroom\b"
    # Spanish phrases common in WhatsApp rental messages
    r"|\ben\s+renta\b|\ben\s+alquiler\b|\bse\s+arrienda\b|\ben\s+arriendo\b"
    r"|\bcasita\b|\bdepartamento\b|\bdepto\b|\brec[aá]mara\b"
    r"|\bdisponible\b|\brenta\s+mensual\b|\balquiler\b",
    re.I,
)

# ── Weak keywords ─────────────────────────────────────────────────────────────
# Ambiguous on their own (e.g. "casa" appears in many Todos Santos contexts,
# "studio" could be a photo studio).  A weak-only match is accepted ONLY
# when there is also a recognisable price.

RENTAL_KEYWORDS_WEAK = re.compile(
    r"\bcasa\b|\bstudio\b",
    re.I,
)
