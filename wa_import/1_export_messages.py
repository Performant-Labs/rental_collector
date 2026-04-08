#!/usr/bin/env python3
"""
Step 1: Export all messages from WhatsApp channel to JSON + CSV.
Target session: 189 (A Community of Todos Santos)
"""

import sqlite3
import json
import csv
import os
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH     = os.path.join(os.path.dirname(__file__), "ChatStorage.sqlite")
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
SESSION_ID  = 189          # ZWACHATSESSION.Z_PK for "A Community of Todos Santos"
COREDATA_EPOCH_OFFSET = 978307200  # seconds between 1970-01-01 and 2001-01-01

MESSAGE_TYPES = {
    0:  "text",
    1:  "image",
    2:  "video",
    3:  "audio",
    4:  "document",
    5:  "contact",
    6:  "location",
    7:  "status_update",
    8:  "group_notification",
    10: "call",
    11: "unknown_11",
    12: "link_preview",
    13: "unknown_13",
    14: "sticker",
    15: "unknown_15",
    26: "poll",
    46: "unknown_46",
    54: "unknown_54",
    59: "unknown_59",
    63: "unknown_63",
    66: "reaction",
}

def ts_to_iso(coredata_ts):
    if coredata_ts is None:
        return None
    unix_ts = coredata_ts + COREDATA_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Connecting to {DB_PATH} ...")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    query = """
    SELECT
        m.Z_PK                  AS id,
        m.ZSTANZAID             AS stanza_id,
        m.ZMESSAGETYPE          AS type_int,
        m.ZMESSAGEDATE          AS date_raw,
        m.ZSENTDATE             AS sent_date_raw,
        m.ZFROMJID              AS from_jid,
        m.ZPUSHNAME             AS sender_name,
        m.ZISFROMME             AS is_from_me,
        m.ZTEXT                 AS text,
        m.ZMESSAGESTATUS        AS status,
        m.ZSTARRED              AS starred,
        m.ZFLAGS                AS flags,
        m.ZPARENTMESSAGE        AS reply_to_id,

        -- media fields (NULL if no media)
        mi.Z_PK                 AS media_id,
        mi.ZMEDIAURL            AS media_url,
        mi.ZMEDIALOCALPATH      AS media_local_path,
        mi.ZTHUMBNAILLOCALPATH  AS thumbnail_local_path,
        mi.ZFILESIZE            AS media_file_size,
        mi.ZMOVIEDURATION       AS media_duration,
        mi.ZTITLE               AS media_title,
        mi.ZCLOUDSTATUS         AS media_cloud_status,
        mi.ZMEDIAURLDATE        AS media_url_date_raw,
        mi.ZLATITUDE            AS latitude,
        mi.ZLONGITUDE           AS longitude,
        mi.ZVCARDNAME           AS vcard_name,
        mi.ZVCARDSTRING         AS vcard_string,

        -- has media key (1/0 — don't export raw bytes to JSON)
        CASE WHEN mi.ZMEDIAKEY IS NOT NULL THEN 1 ELSE 0 END AS has_media_key

    FROM ZWAMESSAGE m
    LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM
    WHERE m.ZCHATSESSION = ?
    ORDER BY m.ZMESSAGEDATE ASC
    """

    print(f"Querying messages for session {SESSION_ID} ...")
    cur.execute(query, (SESSION_ID,))
    rows = cur.fetchall()
    print(f"  → {len(rows):,} messages found")

    messages = []
    for row in rows:
        d = dict(row)
        # Convert timestamps
        d["timestamp"]          = ts_to_iso(d.pop("date_raw"))
        d["sent_at"]            = ts_to_iso(d.pop("sent_date_raw"))
        d["media_url_date"]     = ts_to_iso(d.pop("media_url_date_raw"))
        d["type"]               = MESSAGE_TYPES.get(d["type_int"], f"unknown_{d['type_int']}")
        d["is_from_me"]         = bool(d["is_from_me"])
        d["starred"]            = bool(d["starred"])
        messages.append(d)

    # ── Write JSON ───────────────────────────────────────────────────────────
    json_path = os.path.join(OUTPUT_DIR, "messages.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    print(f"  → JSON written: {json_path}  ({os.path.getsize(json_path)/1024/1024:.1f} MB)")

    # ── Write CSV  ───────────────────────────────────────────────────────────
    csv_path = os.path.join(OUTPUT_DIR, "messages.csv")
    if messages:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=messages[0].keys())
            writer.writeheader()
            writer.writerows(messages)
        print(f"  → CSV  written: {csv_path}  ({os.path.getsize(csv_path)/1024/1024:.1f} MB)")

    # ── Summary stats ────────────────────────────────────────────────────────
    type_counts = {}
    for m in messages:
        type_counts[m["type"]] = type_counts.get(m["type"], 0) + 1
    print("\n Message type breakdown:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<25} {c:>6,}")

    media_msgs   = sum(1 for m in messages if m["media_url"] is not None)
    cached_media = sum(1 for m in messages if m["media_local_path"] is not None)
    needs_dl     = media_msgs - cached_media
    print(f"\n Media summary:")
    print(f"    Messages with CDN URL:   {media_msgs:>6,}")
    print(f"    Already cached locally:  {cached_media:>6,}")
    print(f"    Need download + decrypt: {needs_dl:>6,}")

    con.close()
    print("\nDone. Run 2_download_media.py next.")

if __name__ == "__main__":
    main()
