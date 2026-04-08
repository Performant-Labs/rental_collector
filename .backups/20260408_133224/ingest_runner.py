from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from dashboard.app.ingestion import DEFAULT_RENTALS_DIR
from dashboard.app.indexing_commands import full_reindex, incremental_upsert
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient

DEFAULT_LOCK_FILE = Path("/tmp/todossantos-dashboard-ingest.lock")


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
) -> int:
    if not _acquire_lock(lock_file):
        return 2

    try:
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
    )


if __name__ == "__main__":
    raise SystemExit(main())
