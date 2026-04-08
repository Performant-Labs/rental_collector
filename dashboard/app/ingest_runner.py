from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dashboard.app.ingestion import DEFAULT_RENTALS_DIR
from dashboard.app.indexing_commands import full_reindex, incremental_upsert
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient

DEFAULT_LOCK_FILE = Path("/tmp/todossantos-dashboard-ingest.lock")

logger = logging.getLogger(__name__)

# Paths to the WhatsApp pipeline scripts, relative to the repo root
from shared.config import REPO_ROOT as _REPO_ROOT
_WA_DIR       = _REPO_ROOT / "wa_import"
_WA_SCORER    = _WA_DIR / "4_find_rentals.py"    # messages.json → rentals.json
_WA_CONVERTER = _WA_DIR / "convert_to_rentals.py" # rentals.json  → rentals/ folders
_WA_MIN_SCORE = int(os.environ.get("WA_MIN_SCORE", "15"))


def run_wa_scoring() -> bool:
    """
    Run wa_import/4_find_rentals.py to produce output/rentals.json from
    output/messages.json.  Non-fatal; returns False if unavailable or failed.

    Prerequisite: output/messages.json must exist (produced by 1_export_messages.py
    which reads ChatStorage.sqlite).  If messages.json is missing, this step is
    skipped with an informational log — the SQLite file is machine-specific and
    cannot be automated here.
    """
    if not _WA_SCORER.exists():
        logger.warning("wa_import: scorer not found at %s — skipping", _WA_SCORER)
        return False

    messages_json = _WA_DIR / "output" / "messages.json"
    if not messages_json.exists():
        logger.info(
            "wa_import: %s not found — run 1_export_messages.py against ChatStorage.sqlite first",
            messages_json,
        )
        return False

    cmd = [sys.executable, str(_WA_SCORER)]
    logger.info("wa_import: scoring messages — running %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,           # scoring can be slow on large datasets
            cwd=str(_WA_DIR),
        )
        if result.stdout:
            logger.info("wa_import scorer stdout:\n%s", result.stdout.strip())
        if result.returncode != 0:
            logger.error(
                "wa_import: scorer exited %d — stderr: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False
        logger.info("wa_import: scoring complete")
        return True
    except subprocess.TimeoutExpired:
        logger.error("wa_import: scorer timed out after 300 s")
        return False
    except Exception as exc:
        logger.error("wa_import: unexpected error running scorer: %s", exc)
        return False


def run_wa_import_conversion(min_score: int = _WA_MIN_SCORE) -> bool:
    """
    Run wa_import/convert_to_rentals.py --save before ingestion so that
    WhatsApp listings are deposited into rentals/ and picked up by the
    Meilisearch indexer in the same run.

    If output/rentals.json is missing, run_wa_scoring() is called first to
    produce it.  Returns True on success, False on any failure (non-fatal).
    """
    if not _WA_CONVERTER.exists():
        logger.warning("wa_import: converter not found at %s — skipping", _WA_CONVERTER)
        return False

    wa_rentals = _WA_DIR / "output" / "rentals.json"
    if not wa_rentals.exists():
        logger.info("wa_import: rentals.json missing — running scorer first")
        if not run_wa_scoring():
            return False
        if not wa_rentals.exists():
            logger.error("wa_import: rentals.json still missing after scoring — aborting")
            return False

    cmd = [sys.executable, str(_WA_CONVERTER), "--save", "--min-score", str(min_score)]
    logger.info("wa_import: running %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_REPO_ROOT),
        )
        if result.stdout:
            logger.info("wa_import stdout:\n%s", result.stdout.strip())
        if result.returncode != 0:
            logger.error(
                "wa_import: converter exited %d — stderr: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False
        logger.info("wa_import: conversion complete")
        return True
    except subprocess.TimeoutExpired:
        logger.error("wa_import: converter timed out after 120 s")
        return False
    except Exception as exc:
        logger.error("wa_import: unexpected error running converter: %s", exc)
        return False


def parse_scheduler_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled dashboard ingestion")
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="Ingestion mode",
    )
    parser.add_argument(
        "--rentals-dir",
        default=str(DEFAULT_RENTALS_DIR),
        help="Path to rentals source data",
    )
    parser.add_argument(
        "--lock-file",
        default=str(DEFAULT_LOCK_FILE),
        help="Lock file path to prevent overlapping runs",
    )
    parser.add_argument(
        "--skip-wa-export",
        action="store_true",
        default=False,
        help="Skip the WhatsApp export conversion step",
    )
    return parser.parse_args(argv)


def _acquire_lock(lock_file: Path) -> bool:
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(lock_file: Path) -> None:
    try:
        lock_file.unlink()
    except FileNotFoundError:
        pass


def run_scheduled_ingest(
    *,
    mode: str,
    rentals_dir: Path,
    lock_file: Path,
    client: Any | None = None,
    skip_wa_import: bool = False,
) -> int:
    if not _acquire_lock(lock_file):
        return 2

    try:
        # Step 1: deposit WhatsApp listings into rentals/ before indexing
        if not skip_wa_import:
            try:
                run_wa_import_conversion()
            except Exception as exc:
                logger.error("wa_import: unexpected error during conversion (non-fatal): %s", exc)

        # Step 2: index everything in rentals/ into Meilisearch
        index_client = client or MeilisearchIndexClient.from_env()
        if mode == "full":
            full_reindex(client=index_client, rentals_dir=rentals_dir)
        else:
            incremental_upsert(client=index_client, rentals_dir=rentals_dir)
        return 0
    except Exception:
        return 1
    finally:
        _release_lock(lock_file)


def main(argv: list[str] | None = None) -> int:
    args = parse_scheduler_args(argv)
    return run_scheduled_ingest(
        mode=args.mode,
        rentals_dir=Path(args.rentals_dir),
        lock_file=Path(args.lock_file),
        skip_wa_import=args.skip_wa_import,
    )


if __name__ == "__main__":
    raise SystemExit(main())
