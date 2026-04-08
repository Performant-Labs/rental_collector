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

# Path to the WhatsApp converter, relative to the repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WA_CONVERTER = _REPO_ROOT / "wa_export" / "convert_to_rentals.py"
_WA_MIN_SCORE = int(os.environ.get("WA_MIN_SCORE", "15"))


def run_wa_export_conversion(min_score: int = _WA_MIN_SCORE) -> bool:
    """
    Run wa_export/convert_to_rentals.py --save before ingestion so that
    WhatsApp listings are deposited into rentals/ and picked up by the
    Meilisearch indexer in the same run.

    Returns True on success, False if the converter is unavailable or fails.
    Failures are non-fatal: the rest of ingestion proceeds regardless.
    """
    if not _WA_CONVERTER.exists():
        logger.warning("wa_export: converter not found at %s — skipping", _WA_CONVERTER)
        return False

    wa_rentals = _WA_CONVERTER.parent / "output" / "rentals.json"
    if not wa_rentals.exists():
        logger.info(
            "wa_export: %s not found — run 4_find_rentals.py first, skipping",
            wa_rentals,
        )
        return False

    cmd = [sys.executable, str(_WA_CONVERTER), "--save", "--min-score", str(min_score)]
    logger.info("wa_export: running %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_REPO_ROOT),
        )
        if result.stdout:
            logger.info("wa_export stdout:\n%s", result.stdout.strip())
        if result.returncode != 0:
            logger.error(
                "wa_export: converter exited %d — stderr: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False
        logger.info("wa_export: conversion complete")
        return True
    except subprocess.TimeoutExpired:
        logger.error("wa_export: converter timed out after 120 s")
        return False
    except Exception as exc:
        logger.error("wa_export: unexpected error running converter: %s", exc)
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
    skip_wa_export: bool = False,
) -> int:
    if not _acquire_lock(lock_file):
        return 2

    try:
        # Step 1: deposit WhatsApp listings into rentals/ before indexing
        if not skip_wa_export:
            try:
                run_wa_export_conversion()
            except Exception as exc:
                logger.error("wa_export: unexpected error during conversion (non-fatal): %s", exc)

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
        skip_wa_export=args.skip_wa_export,
    )


if __name__ == "__main__":
    raise SystemExit(main())
