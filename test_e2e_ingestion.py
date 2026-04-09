#!/usr/bin/env python3
"""
End-to-end ingestion test.
Runs the three safe (non-LLM) scrapers, saves to a temp dir,
then checks that every folder and info.json has a real channel label.
"""
import json, re, sys, tempfile, shutil
from pathlib import Path
from urllib.parse import urlparse

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scraper.scrapers import scrape_airbnb_local, scrape_craigslist, scrape_todos_santos_cc
from scraper.folder_ops import save_listing_folders
from scraper.reporting import save_results

VALID_CHANNELS = {
    "airbnb", "amyrex", "bajaprops", "baraka", "bajasurfcasitas",
    "tsvilla", "pescprop", "craigslist", "todossantos", "whatsapp",
}

def run():
    tmp = Path(tempfile.mkdtemp(prefix="rc_test_"))
    print(f"Test output dir: {tmp}\n")
    try:
        channels = {
            "airbnb":      scrape_airbnb_local,
            "craigslist":  scrape_craigslist,
            "todossantos": scrape_todos_santos_cc,
        }

        all_ok = True
        for ch, fn in channels.items():
            print(f"=== {ch} ===")
            try:
                listings = fn()
            except Exception as e:
                print(f"  ERROR: {e}")
                all_ok = False
                continue

            print(f"  scraper returned {len(listings)} listing(s)")

            # 1. Verify source field on every listing coming out of the scraper
            bad_src = [l for l in listings if l.get("source") != ch]
            if bad_src:
                all_ok = False
                for l in bad_src:
                    print(f"  FAIL: source='{l.get('source')}' expected='{ch}'  title={l.get('title','')[:40]}")
            else:
                print(f"  source field on all {len(listings)} listings: '{ch}'  OK")

            if not listings:
                continue

            # 2. Save to temp dir and check folder names + info.json
            orig_dir = None
            try:
                from shared import config as _cfg
                orig_dir = _cfg.DEFAULT_RENTALS_DIR
                _cfg.DEFAULT_RENTALS_DIR = tmp  # patch to redirect output
            except Exception:
                pass

            save_results(listings, ch, results_dir=tmp)

            # Check saved batch file
            batch = next(tmp.glob(f"{ch}-*.json"), None)
            if batch:
                data = json.loads(batch.read_text(encoding="utf-8"))
                bad_in_batch = [l for l in data if l.get("source") != ch]
                if bad_in_batch:
                    all_ok = False
                    print(f"  FAIL: {len(bad_in_batch)} items in batch JSON have wrong source")
                else:
                    print(f"  batch JSON '{batch.name}': all sources correct  OK")

            if ch != "airbnb":
                save_listing_folders(listings, results_dir=tmp)
                folders = [f for f in tmp.iterdir() if f.is_dir() and f.name.startswith(ch + "-")]
                for folder in folders:
                    info_path = folder / "info.json"
                    if info_path.exists():
                        info = json.loads(info_path.read_text(encoding="utf-8"))
                        src = info.get("source", "")
                        if src != ch:
                            all_ok = False
                            print(f"  FAIL: {folder.name}/info.json has source='{src}' expected='{ch}'")
                if folders:
                    print(f"  {len(folders)} folder(s) created, all info.json: source='{ch}'  OK")

            if orig_dir:
                _cfg.DEFAULT_RENTALS_DIR = orig_dir

            print()

        print("=" * 50)
        print("RESULT:", "ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED")
        print("=" * 50)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    run()
