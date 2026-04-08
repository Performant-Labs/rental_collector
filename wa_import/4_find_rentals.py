#!/usr/bin/env python3
"""
Step 4: Extract rental/housing listings from messages.json
Scores each message against English-primary, Spanish-secondary keyword sets.
Writes output/rentals.json with score, matched keywords, and all original fields.
"""

import json, os, re
from datetime import timezone

INPUT    = os.path.join(os.path.dirname(__file__), "output", "messages.json")
OUTPUT   = os.path.join(os.path.dirname(__file__), "output", "rentals.json")
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "output", "media")

# ── Extension map (mirrors 2_download_media.py) ──────────────────────────────
TYPE_EXT = {1: ".jpg", 2: ".mp4", 3: ".ogg", 4: "", 7: ".mp4", 14: ".webp", 15: ".webp"}

# ── Keyword scoring ───────────────────────────────────────────────────────────
# Tier weights: strong=4, property=2, price=2, availability=2, general=1
KEYWORDS = {
    "strong": {
        # EN
        "for rent", "for lease", "for monthly rent", "available for rent",
        "available to rent", "renting out", "long term rental", "short term rental",
        "vacation rental", "nightly rental", "furnished rental", "unfurnished rental",
        "month to month", "looking for renters", "place to rent",
        # ES
        "se renta", "se alquila", "en renta", "en alquiler", "renta mensual",
        "renta disponible", "se arrienda", "en arriendo",
    },
    "property": {
        # EN
        "bedroom", "bathroom", "studio", "apartment", "apt", "house", "home",
        "condo", "penthouse", "bungalow", "cottage", "villa", "room", "cabin",
        "guesthouse", "guest house", "guest room", "airbnb", "vrbo",
        # ES
        "casita", "casa", "cuarto", "habitación", "habitacion", "departamento",
        "depto", "recámara", "recamara", "baño", "bano", "estudio",
    },
    "price": {
        "$", "usd", "mxn", "pesos", "per month", "per week", "per night",
        "/month", "/week", "/night", "monthly", "weekly", "nightly",
        "mensual", "semanal", "por noche", "por mes",
    },
    "availability": {
        "available", "disponible", "immediate", "immediately", "move in",
        "move-in", "starting", "from january", "from february", "from march",
        "from april", "from may", "from june", "from july", "from august",
        "from september", "from october", "from november", "from december",
        "vacant", "empty", "utilities included", "all inclusive",
        "furnished", "unfurnished", "pets ok", "pet friendly",
    },
    "general": {
        "rent", "renta", "rental", "lease", "alquiler", "alquil", "landlord",
        "tenant", "listing", "sqft", "sq ft", "square feet", "square foot",
        "inquire", "dm me", "message me", "whatsapp me", "call me",
        "contact me", "interested", "interesado",
    },
}

WEIGHTS = {"strong": 4, "property": 2, "price": 2, "availability": 2, "general": 1}
MIN_SCORE = 3   # must score at least this to be included

# ── Helpers ───────────────────────────────────────────────────────────────────

def score_message(text: str):
    """Return (score, matched_keywords_list)"""
    if not text:
        return 0, []
    lower = text.lower()
    matched, score = [], 0
    for tier, words in KEYWORDS.items():
        w = WEIGHTS[tier]
        for kw in words:
            if kw in lower:
                matched.append(kw)
                score += w
    return score, list(set(matched))


def phone_from_jid(jid: str) -> str:
    """Extract phone number string from 'number@s.whatsapp.net'"""
    if jid and "@" in jid:
        return "+" + jid.split("@")[0]
    return jid or ""


def media_filename(media_id, type_int):
    if media_id is None:
        return None
    ext = TYPE_EXT.get(type_int, ".bin")
    if type_int == 4:   # document — scan for any file with that prefix
        for f in os.listdir(MEDIA_DIR):
            if f.startswith(str(media_id) + "_") or f.startswith(str(media_id) + "."):
                return f
        return None
    candidate = f"{media_id}{ext}"
    return candidate if os.path.exists(os.path.join(MEDIA_DIR, candidate)) else None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Loading {INPUT} ...")
    with open(INPUT, encoding="utf-8") as f:
        messages = json.load(f)
    print(f"  → {len(messages):,} messages loaded")

    results = []
    skipped_types = {"reaction", "group_notification", "location", "call",
                     "contact", "status_update", "poll"}

    for m in messages:
        # Skip non-content message types
        if m.get("type") in skipped_types:
            continue

        text = m.get("text") or m.get("media_title") or ""
        score, matched = score_message(text)

        if score < MIN_SCORE:
            continue

        # Enrich with derived fields
        m["rental_score"]    = score
        m["rental_keywords"] = matched
        m["phone"]           = phone_from_jid(m.get("from_jid", ""))
        m["media_file"]      = media_filename(m.get("media_id"), m.get("type_int", 0))

        results.append(m)

    # Sort by score desc, then date desc within same score
    results.sort(key=lambda m: (-m["rental_score"], m.get("timestamp") or ""))

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n  → {len(results):,} rental-related messages found")
    print(f"  → Written to {OUTPUT}")

    # Score distribution
    buckets = {}
    for r in results:
        b = (r["rental_score"] // 2) * 2
        buckets[b] = buckets.get(b, 0) + 1
    print("\n  Score distribution:")
    for s in sorted(buckets):
        print(f"    score ≥ {s:<4} {buckets[s]:>5,} messages")

    # Top keyword hits
    from collections import Counter
    kw_counts = Counter(kw for r in results for kw in r["rental_keywords"])
    print("\n  Top keywords matched:")
    for kw, n in kw_counts.most_common(15):
        print(f"    {kw:<30} {n:>5,}")

if __name__ == "__main__":
    main()
