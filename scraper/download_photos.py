#!/usr/bin/env python3
"""
Download listing photos from Airbnb CDN into each listing folder.

Run this script from inside your "Todos Santos Rentals" folder:
    cd ~/Projects/Todos Santos\ Rentals
    python3 download_photos.py

Each listing folder will get: photo_01.jpg, photo_02.jpg, … photo_06.jpg
The listing.html files will then be updated to use those local images.
"""
import json, os, sys, time, urllib.request, shutil, re
from pathlib import Path

BASE = Path(__file__).parent / "rentals"   # listings live in rentals/airbnb-*/
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.airbnb.com/",
}


def download_photo(url: str, dest: Path) -> bool:
    """Download one photo. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            with open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        size = dest.stat().st_size
        if size < 2000:          # suspiciously small → probably an error page
            dest.unlink()
            return False
        return True
    except Exception as e:
        print(f"    ✗ {e}")
        if dest.exists():
            dest.unlink()
        return False


def patch_html(html_path: Path, photo_map: dict):
    """Replace CDN URLs in listing.html with local filenames."""
    text = html_path.read_text(encoding="utf-8")
    for cdn_url, local_name in photo_map.items():
        # Strip query string from the CDN url for matching
        base_url = cdn_url.split("?")[0]
        # Replace with just the filename (works because html is in same folder)
        text = text.replace(cdn_url, local_name)
        text = text.replace(base_url, local_name)
    html_path.write_text(text, encoding="utf-8")


def process_folder(folder: Path):
    info_file = folder / "info.json"
    html_file  = folder / "listing.html"
    if not info_file.exists():
        return

    with open(info_file) as f:
        info = json.load(f)

    urls = info.get("photoUrls", [])
    if not urls:
        print(f"  ⚠  no photoUrls in {folder.name}")
        return

    photo_map = {}   # cdn_url → local filename
    downloaded = 0
    for i, url in enumerate(urls[:6], start=1):
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        local_name = f"photo_{i:02d}{ext}"
        local_path = folder / local_name

        if local_path.exists() and local_path.stat().st_size > 2000:
            print(f"    • {local_name} already exists — skipping")
            photo_map[url] = local_name
            downloaded += 1
            continue

        print(f"    ↓  {local_name} …", end=" ", flush=True)
        ok = download_photo(url, local_path)
        if ok:
            kb = local_path.stat().st_size // 1024
            print(f"✓ ({kb} KB)")
            photo_map[url] = local_name
            downloaded += 1
        else:
            print("failed")

        time.sleep(0.3)   # be polite to the CDN

    # Patch the HTML so it references local files
    if downloaded > 0 and html_file.exists():
        patch_html(html_file, photo_map)
        info["localPhotos"] = list(photo_map.values())
        with open(info_file, "w") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

    print(f"  → {downloaded}/{len(urls[:6])} photos saved\n")


def main():
    folders = sorted(
        d for d in BASE.iterdir()
        if d.is_dir() and d.name.startswith("airbnb-")
    )
    if not folders:
        print("No Airbnb listing folders found in rentals/.")
        print("Make sure you're running this from inside the 'Todos Santos Rentals' folder.")
        sys.exit(1)

    print(f"Found {len(folders)} listing folders.\n")
    for folder in folders:
        print(f"📂  {folder.name}")
        process_folder(folder)

    print("Done! Open any listing.html in your browser to see the local photos.")


if __name__ == "__main__":
    main()
