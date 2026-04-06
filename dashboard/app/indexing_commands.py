from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from dashboard.app.ingestion import DEFAULT_RENTALS_DIR, build_documents_from_rentals
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient

DEFAULT_INDEX_SETTINGS: dict[str, list[str]] = {
    "filterableAttributes": [
        "source",
        "price_bucket",
        "location",
        "listing_type",
        "has_photos",
        "has_contact",
        "scraped",
    ],
    "sortableAttributes": ["price_usd", "scraped"],
    "searchableAttributes": ["title", "location", "description"],
}


def _sorted_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(documents, key=lambda item: item.get("id", ""))


def ensure_index_and_settings(
    client: MeilisearchIndexClient,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created = client.ensure_index_exists()
    task_uid = client.apply_index_settings(settings or DEFAULT_INDEX_SETTINGS)
    return {"created": created, "settings_task_uid": task_uid}


def full_reindex(
    client: MeilisearchIndexClient,
    rentals_dir: Path = DEFAULT_RENTALS_DIR,
) -> dict[str, Any]:
    documents, warnings = build_documents_from_rentals(rentals_dir)
    sorted_documents = _sorted_documents(documents)

    ensure_result = ensure_index_and_settings(client)
    clear_task_uid = client.clear_documents()
    upsert_task_uid = client.upsert_documents(sorted_documents)

    return {
        "mode": "full_reindex",
        "created_index": ensure_result["created"],
        "settings_task_uid": ensure_result["settings_task_uid"],
        "clear_task_uid": clear_task_uid,
        "upsert_task_uid": upsert_task_uid,
        "indexed_count": len(sorted_documents),
        "warnings": warnings,
    }


def incremental_upsert(
    client: MeilisearchIndexClient,
    rentals_dir: Path = DEFAULT_RENTALS_DIR,
) -> dict[str, Any]:
    documents, warnings = build_documents_from_rentals(rentals_dir)
    sorted_documents = _sorted_documents(documents)

    ensure_result = ensure_index_and_settings(client)
    upsert_task_uid = client.upsert_documents(sorted_documents)

    return {
        "mode": "incremental_upsert",
        "created_index": ensure_result["created"],
        "settings_task_uid": ensure_result["settings_task_uid"],
        "upsert_task_uid": upsert_task_uid,
        "indexed_count": len(sorted_documents),
        "warnings": warnings,
    }


def bootstrap_ingest_if_enabled(
    enabled: bool,
    client: MeilisearchIndexClient,
    rentals_dir: Path = DEFAULT_RENTALS_DIR,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    return incremental_upsert(client=client, rentals_dir=rentals_dir)


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index rental listings into Meilisearch")
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="Indexing mode",
    )
    parser.add_argument(
        "--rentals-dir",
        default=str(DEFAULT_RENTALS_DIR),
        help="Path to rentals data directory",
    )
    return parser.parse_args(argv)


def run_ingest_command(argv: list[str] | None = None) -> int:
    args = parse_cli_args(argv)
    client = MeilisearchIndexClient.from_env()
    rentals_dir = Path(args.rentals_dir)

    if args.mode == "full":
        full_reindex(client=client, rentals_dir=rentals_dir)
    else:
        incremental_upsert(client=client, rentals_dir=rentals_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_ingest_command())
