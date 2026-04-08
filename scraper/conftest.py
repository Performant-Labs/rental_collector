"""
scraper/conftest.py — ensures the scraper package dir is also on sys.path
so that `import rental_search` works when pytest is invoked from the
project root.
"""

import sys
from pathlib import Path

_SCRAPER_DIR = str(Path(__file__).resolve().parent)
if _SCRAPER_DIR not in sys.path:
    sys.path.insert(0, _SCRAPER_DIR)
