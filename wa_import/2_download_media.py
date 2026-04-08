#!/usr/bin/env python3
"""
Step 2: Download & decrypt all media not yet cached locally.

How decryption works
────────────────────
WhatsApp's end-to-end encryption protects messages *in transit*.  When a
message arrives at your Desktop app the app itself stores the decryption key
(ZMEDIAKEY) in the local SQLite database so it can display the media.  The
CDN only serves an encrypted blob.  We are the key-holder, so we can decrypt.

Process per media item
──────────────────────
1. Read ZMEDIAURL  → CDN endpoint for the encrypted file
2. Read ZMEDIAKEY  → 32-byte raw key stored by YOUR app in YOUR DB
3. HKDF-SHA256(mediaKey, appInfo, 112 bytes) → IV | cipherKey | macKey
4. GET encrypted bytes from CDN
5. Strip 10-byte MAC suffix, verify HMAC-SHA256, decrypt AES-256-CBC
6. Remove PKCS7 padding, save plaintext file
"""

import sqlite3
import os
import sys
import hmac
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from tqdm import tqdm
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ── Config ───────────────────────────────────────────────────────────────────
DB_PATH      = os.path.join(os.path.dirname(__file__), "ChatStorage.sqlite")
MEDIA_SRC    = os.path.join(os.path.dirname(__file__), "Media")   # our copied cache
OUTPUT_DIR   = os.path.join(os.path.dirname(__file__), "output", "media")
LOG_PATH     = os.path.join(os.path.dirname(__file__), "output", "media_download_log.json")
SESSION_ID   = 189        # "A Community of Todos Santos"
MAX_WORKERS  = 8          # parallel download threads
RETRY_LIMIT  = 3
COREDATA_OFFSET = 978307200

# ── WhatsApp app-info strings by ZMESSAGETYPE ─────────────────────────────────
APP_INFO = {
    1:  b"WhatsApp Image Keys",    # image
    2:  b"WhatsApp Video Keys",    # video
    3:  b"WhatsApp Audio Keys",    # audio / PTT
    4:  b"WhatsApp Document Keys", # document
    7:  b"WhatsApp Video Keys",    # status video
    14: b"WhatsApp Image Keys",    # sticker (treated as image)
    15: b"WhatsApp Image Keys",    # animated sticker
}

# Default extension by message type
TYPE_EXT = {
    1:  ".jpg",
    2:  ".mp4",
    3:  ".ogg",
    4:  "",       # use filename from ZTITLE
    7:  ".mp4",
    14: ".webp",
    15: ".webp",
}

# ── Crypto helpers ────────────────────────────────────────────────────────────

def derive_keys(media_key: bytes, app_info: bytes):
    """HKDF-SHA256 → (iv, cipher_key, mac_key)"""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=112,
        salt=None,   # WA uses no salt (RFC 5869 §2.2: salt = zeros)
        info=app_info,
    )
    km = hkdf.derive(media_key)
    return km[:16], km[16:48], km[48:80]   # iv, cipher_key, mac_key


def decrypt_wa_media(encrypted_bytes: bytes, media_key: bytes, app_info: bytes) -> bytes:
    iv, cipher_key, mac_key = derive_keys(media_key, app_info)

    mac_suffix = encrypted_bytes[-10:]
    ciphertext = encrypted_bytes[:-10]

    # Verify integrity
    expected = hmac.new(mac_key, iv + ciphertext, digestmod=hashlib.sha256).digest()[:10]
    if not hmac.compare_digest(mac_suffix, expected):
        raise ValueError("HMAC verification failed — key mismatch or corrupt file")

    # Decrypt
    cipher    = Cipher(algorithms.AES(cipher_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    # Remove PKCS7 padding
    pad = plaintext[-1]
    if pad < 1 or pad > 16:
        raise ValueError(f"Invalid PKCS7 padding byte: {pad}")
    return plaintext[:-pad]


# ── Download helpers ──────────────────────────────────────────────────────────

def safe_filename(media_id: int, msg_type: int, title: str | None) -> str:
    ext = TYPE_EXT.get(msg_type, ".bin")
    if msg_type == 4 and title:                # document — use original name
        safe = "".join(c for c in title if c.isalnum() or c in "._- ")[:80]
        name = f"{media_id}_{safe}"
        return name if "." in safe else name + ".bin"
    return f"{media_id}{ext}"


def find_local_copy(local_path: str) -> str | None:
    """
    ZMEDIALOCALPATH is an absolute macOS path like:
      /Users/.../Group Containers/.../Media/Image/...
    Try to locate the equivalent file inside our copied Media/ folder.
    """
    if not local_path:
        return None
    # Extract the part after "/Media/"
    idx = local_path.find("/Media/")
    if idx == -1:
        return None
    rel = local_path[idx + len("/Media/"):]
    candidate = os.path.join(MEDIA_SRC, rel)
    return candidate if os.path.exists(candidate) else None


def download_and_decrypt(item: dict) -> dict:
    """Process a single media item. Returns a result dict."""
    media_id  = item["media_id"]
    url       = item["media_url"]
    key_blob  = item["media_key"]       # raw bytes from SQLite BLOB
    msg_type  = item["msg_type"]
    title     = item["title"]
    result    = {"media_id": media_id, "url": url, "status": None, "path": None, "error": None}

    # Skip if already in our local cache
    local = find_local_copy(item["local_path"] or "")
    if local:
        result["status"] = "already_cached"
        result["path"]   = local
        return result

    # Determine app info
    app_info = APP_INFO.get(msg_type)
    if app_info is None:
        result["status"] = "skipped_no_appinfo"
        result["error"]  = f"No app_info mapping for msg type {msg_type}"
        return result

    if not key_blob or len(key_blob) < 32:
        result["status"] = "skipped_no_key"
        result["error"]  = f"ZMEDIAKEY is missing or too short ({len(key_blob) if key_blob else 0} bytes)"
        return result

    # Determine output path
    fname    = safe_filename(media_id, msg_type, title)
    out_path = os.path.join(OUTPUT_DIR, fname)
    if os.path.exists(out_path):
        result["status"] = "already_downloaded"
        result["path"]   = out_path
        return result

    # Download with retries
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp = requests.get(url, timeout=30, stream=False)
            if resp.status_code == 404:
                result["status"] = "expired_url_404"
                result["error"]  = "CDN returned 404 — URL likely expired"
                return result
            if resp.status_code == 403:
                result["status"] = "expired_url_403"
                result["error"]  = "CDN returned 403 — URL likely expired"
                return result
            resp.raise_for_status()
            encrypted = resp.content
            break
        except requests.RequestException as e:
            if attempt == RETRY_LIMIT:
                result["status"] = "download_failed"
                result["error"]  = str(e)
                return result
            time.sleep(attempt * 2)

    # Decrypt
    try:
        plaintext = decrypt_wa_media(encrypted, key_blob, app_info)
    except Exception as e:
        result["status"] = "decrypt_failed"
        result["error"]  = str(e)
        return result

    # Save
    try:
        with open(out_path, "wb") as f:
            f.write(plaintext)
        result["status"] = "downloaded"
        result["path"]   = out_path
    except OSError as e:
        result["status"] = "write_failed"
        result["error"]  = str(e)

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    print(f"Connecting to {DB_PATH} ...")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
        SELECT
            mi.Z_PK            AS media_id,
            mi.ZMEDIAURL       AS media_url,
            mi.ZMEDIAKEY       AS media_key,
            mi.ZMEDIALOCALPATH AS local_path,
            mi.ZTITLE          AS title,
            mi.ZFILESIZE       AS file_size,
            mi.ZMEDIAURLDATE   AS url_date_raw,
            m.ZMESSAGETYPE     AS msg_type
        FROM ZWAMEDIAITEM mi
        JOIN ZWAMESSAGE   m  ON m.ZMEDIAITEM = mi.Z_PK
        WHERE m.ZCHATSESSION = ?
          AND mi.ZMEDIAURL IS NOT NULL
        ORDER BY mi.Z_PK ASC
    """, (SESSION_ID,))

    rows = cur.fetchall()
    con.close()
    print(f"  → {len(rows):,} media items with CDN URLs found")

    items = [
        {
            "media_id":   r[0],
            "media_url":  r[1],
            # ZMEDIAKEY is protobuf-wrapped: 0A (field1,LEN) + 20 (len=32) + 32-byte key + more fields
            # Strip the 2-byte prefix to get the raw 32-byte AES key
            "media_key":  bytes(r[2])[2:34] if r[2] and len(bytes(r[2])) >= 34 else None,
            "local_path": r[3],
            "title":      r[4],
            "file_size":  r[5],
            "url_date":   (datetime.fromtimestamp(r[6] + COREDATA_OFFSET, tz=timezone.utc).isoformat()
                           if r[6] else None),
            "msg_type":   r[7],
        }
        for r in rows
    ]

    # ── Run downloads ──────────────────────────────────────────────────────
    results      = []
    status_count = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_and_decrypt, item): item for item in items}
        with tqdm(total=len(futures), unit="file", desc="Downloading media") as pbar:
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                s = res["status"]
                status_count[s] = status_count.get(s, 0) + 1
                pbar.set_postfix({k: v for k, v in status_count.items()})
                pbar.update(1)

    # ── Write log ─────────────────────────────────────────────────────────
    with open(LOG_PATH, "w") as f:
        json.dump(results, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n── Result summary ──────────────────────────────────────────")
    for status, count in sorted(status_count.items(), key=lambda x: -x[1]):
        print(f"  {status:<30} {count:>6,}")

    expired = status_count.get("expired_url_403", 0) + status_count.get("expired_url_404", 0)
    ok      = status_count.get("downloaded", 0) + status_count.get("already_cached", 0) + \
              status_count.get("already_downloaded", 0)
    print(f"\n  ✅ Recovered:      {ok:,}")
    print(f"  ⚠️  Expired URLs:   {expired:,}  → see output/media_download_log.json")
    print(f"\nAll files saved to: {OUTPUT_DIR}")

    if expired > 0:
        print("\nNext step: run 3_baileys_fetch_expired.js to recover expired-URL items using")
        print("an active WhatsApp Web session (QR scan required for that step only).")

if __name__ == "__main__":
    main()
