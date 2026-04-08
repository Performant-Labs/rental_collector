"""
Root conftest.py — ensures the project root is on sys.path so that
`shared` and all other top-level packages are importable regardless
of which subdirectory pytest is invoked from.
"""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
