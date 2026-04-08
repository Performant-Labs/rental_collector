#!/usr/bin/env python3
"""
Step 2b: Re-attempt decryption for items that downloaded OK but failed crypto.
These failed because ZMEDIAKEY has a 2-byte protobuf prefix we weren't stripping.
This script re-downloads and decrypts only those items.
"""

import sqlite3, os, sys, hmac, hashlib, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests
from tqdm import tqdm
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DB_PATH    = os.path.join(os.path.dirname(__file__), "ChatStorage.sqlite")
LOG_PATH   = os.path.join(os.path.dirname(__file__), "output", "media_download_log.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "media")
LOG_OUT    = os.path.join(os.path.dirname(__file__), "output", "retry_decrypt_log.json")
COREDATA_OFFSET = 978307200
MAX_WORKERS = 8
RETRY_LIMIT = 3

APP_INFO = {
    1:  b"WhatsApp Image Keys",
    2:  b"WhatsApp Video Keys",
    3:  b"WhatsApp Audio Keys",
    4:  b"WhatsApp Document Keys",
    7:  b"WhatsApp Video Keys",
    14: b"WhatsApp Image Keys",
    15: b"WhatsApp Image Keys",
}
TYPE_EXT = {1: ".jpg", 2: ".mp4", 3: ".ogg", 4: "", 7: ".mp4", 14: ".webp", 15: ".webp"}

def derive_keys(media_key, app_info):
    hkdf = HKDF(algorithm=hashes.SHA256(), length=112, salt=None, info=app_info)
    km = hkdf.derive(media_key)
    return km[:16], km[16:48], km[48:80]

def decrypt_wa_media(encrypted_bytes, media_key, app_info):
    iv, cipher_key, mac_key = derive_keys(media_key, app_info)
    mac_suffix = encrypted_bytes[-10:]
    ciphertext = encrypted_bytes[:-10]
    expected = hmac.new(mac_key, iv + ciphertext, digestmod=hashlib.sha256).digest()[:10]
    if not hmac.compare_digest(mac_suffix, expected):
        raise ValueError("HMAC verification failed")
    cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    pad = plaintext[-1]
    return plaintext[:-pad]

def safe_filename(media_id, msg_type, title):
    ext = TYPE_EXT.get(msg_type, ".bin")
    if msg_type == 4 and title:
        safe = "".join(c for c in title if c.isalnum() or c in "._- ")[:80]
        name = f"{media_id}_{safe}"
        return name if "." in safe else name + ".bin"
    return f"{media_id}{ext}"

def process(item):
    media_id = item["media_id"]
    url      = item["media_url"]
    key_blob = item["media_key"]
    msg_type = item["msg_type"]
    title    = item["title"]
    result   = {"media_id": media_id, "status": None, "path": None, "error": None}

    app_info = APP_INFO.get(msg_type)
    if not app_info:
        result["status"] = "skipped_no_appinfo"; return result

    # Extract 32-byte key from protobuf wrapper (bytes 2:34)
    raw_key = key_blob[2:34] if key_blob and len(key_blob) >= 34 else None
    if not raw_key:
        result["status"] = "skipped_bad_key"; return result

    fname    = safe_filename(media_id, msg_type, title)
    out_path = os.path.join(OUTPUT_DIR, fname)
    if os.path.exists(out_path):
        result["status"] = "already_exists"; result["path"] = out_path; return result

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code in (403, 404):
                result["status"] = f"expired_{resp.status_code}"; return result
            resp.raise_for_status()
            encrypted = resp.content; break
        except requests.RequestException as e:
            if attempt == RETRY_LIMIT:
                result["status"] = "download_failed"; result["error"] = str(e); return result
            time.sleep(attempt * 2)

    try:
        plaintext = decrypt_wa_media(encrypted, raw_key, app_info)
    except Exception as e:
        result["status"] = "decrypt_failed"; result["error"] = str(e); return result

    with open(out_path, "wb") as f:
        f.write(plaintext)
    result["status"] = "downloaded"; result["path"] = out_path
    return result

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load only the decrypt_failed items from previous run
    with open(LOG_PATH) as f:
        log = json.load(f)
    failed_ids = {r["media_id"] for r in log if r["status"] == "decrypt_failed"}
    print(f"decrypt_failed items to retry: {len(failed_ids):,}")

    # Fetch their details from DB
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT mi.Z_PK, mi.ZMEDIAURL, mi.ZMEDIAKEY, mi.ZTITLE, m.ZMESSAGETYPE
        FROM ZWAMEDIAITEM mi
        JOIN ZWAMESSAGE m ON m.ZMEDIAITEM = mi.Z_PK
        WHERE mi.Z_PK IN ({})
    """.format(",".join("?" * len(failed_ids))), list(failed_ids))
    rows = cur.fetchall(); con.close()

    items = [{"media_id": r[0], "media_url": r[1],
              "media_key": bytes(r[2]) if r[2] else None,
              "title": r[3], "msg_type": r[4]} for r in rows]

    results = []; status_count = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process, item): item for item in items}
        with tqdm(total=len(futures), unit="file", desc="Retrying decrypt_failed") as pbar:
            for fut in as_completed(futures):
                res = fut.result(); results.append(res)
                s = res["status"]; status_count[s] = status_count.get(s, 0) + 1
                pbar.set_postfix(status_count); pbar.update(1)

    with open(LOG_OUT, "w") as f:
        json.dump(results, f, indent=2)

    print("\n── Result summary ───────────────────────────────────")
    for s, c in sorted(status_count.items(), key=lambda x: -x[1]):
        print(f"  {s:<30} {c:>6,}")
    print(f"\nSaved to {LOG_OUT}")

if __name__ == "__main__":
    main()
