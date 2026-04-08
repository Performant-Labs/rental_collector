"""
wa_export/conftest.py — ensures the wa_export package dir is also on
sys.path so that `import convert_to_rentals` works when pytest is
invoked from the project root.
"""

import sys
from pathlib import Path

_WA_DIR = str(Path(__file__).resolve().parent)
if _WA_DIR not in sys.path:
    sys.path.insert(0, _WA_DIR)
