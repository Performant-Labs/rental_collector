from __future__ import annotations

import json
from datetime import datetime, timezone
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


def _load_previous_ids(rentals_dir: Path) -> set[str]:
    """Load the set of document IDs from the previous ingest run."""
    snapshot_path = rentals_dir / ".last_ingest_snapshot.json"
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return set(data.get("ids", []))
    except Exception:
        return set()


def _save_ingest_artifacts(rentals_dir: Path, documents: list[dict[str, Any]], previous_ids: set[str]) -> None:
    """Write snapshot + per-source stats after a successful ingest."""
    current_ids = [d["id"] for d in documents]
    new_docs = [d for d in documents if d["id"] not in previous_ids]

    by_source: dict[str, int] = {}
    for doc in new_docs:
        src = doc.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    stats = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(documents),
        "total_new": len(new_docs),
        "by_source": by_source,
        "first_run": len(previous_ids) == 0,
    }

    try:
        snapshot_path = rentals_dir / ".last_ingest_snapshot.json"
        snapshot_path.write_text(json.dumps({"ids": current_ids}), encoding="utf-8")
    except Exception:
        pass

    try:
        stats_path = rentals_dir / "last_ingest_stats.json"
        stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except Exception:
        pass


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

    previous_ids = _load_previous_ids(rentals_dir)

    ensure_result = ensure_index_and_settings(client)
    client.clear_documents_and_wait()  # block until clear is confirmed before upserting
    upsert_task_uid = client.upsert_documents(sorted_documents)

    _save_ingest_artifacts(rentals_dir, sorted_documents, previous_ids)

    return {
        "mode": "full_reindex",
        "created_index": ensure_result["created"],
        "settings_task_uid": ensure_result["settings_task_uid"],
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



# NOTE: This module is a library — use `python -m dashboard.app.ingest_runner`
# as the CLI entry point.  ingest_runner adds the WhatsApp pre-step and a
# concurrency lock that this module does not provide.
