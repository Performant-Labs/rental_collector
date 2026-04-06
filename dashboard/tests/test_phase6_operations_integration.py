import json
from pathlib import Path

from dashboard.app.ingest_runner import run_scheduled_ingest
from dashboard.app.search_service import perform_search


class InMemorySearchClient:
    def __init__(self):
        self.documents = []

    def ensure_index_exists(self):
        return False

    def apply_index_settings(self, settings):
        return 1

    def clear_documents(self):
        self.documents = []
        return 2

    def upsert_documents(self, documents):
        by_id = {doc["id"]: doc for doc in self.documents}
        for doc in documents:
            by_id[doc["id"]] = dict(doc)
        self.documents = [by_id[key] for key in sorted(by_id.keys())]
        return 3

    def search_documents(self, query, *, filter_expression=None, sort=None, offset=0, limit=20, facets=None):
        hits = self.documents
        if query:
            q = query.lower()
            hits = [d for d in hits if q in (d.get("title", "").lower() + " " + d.get("description", "").lower())]

        page_hits = hits[offset : offset + limit]
        return {
            "hits": page_hits,
            "estimatedTotalHits": len(hits),
            "facetDistribution": {
                "source": {d.get("source", "unknown"): sum(1 for x in hits if x.get("source") == d.get("source")) for d in hits}
            },
        }


def _write_listing(rentals_dir: Path, folder_name: str, title: str):
    folder = rentals_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "info.json").write_text(
        json.dumps(
            {
                "title": title,
                "source": "airbnb",
                "price_usd": 1200,
                "location": "Centro",
                "description": f"{title} description",
                "scraped": "2026-04-06",
                "localPhotos": ["photo_01.jpg"],
            }
        ),
        encoding="utf-8",
    )
    (folder / "listing.html").write_text("<html></html>", encoding="utf-8")


def test_end_to_end_scrape_artifact_to_search_index_flow(tmp_path: Path):
    rentals_dir = tmp_path / "rentals"
    _write_listing(rentals_dir, "airbnb-01-casita-1200usd", "Casita Sol")

    client = InMemorySearchClient()
    code = run_scheduled_ingest(
        mode="incremental",
        rentals_dir=rentals_dir,
        lock_file=tmp_path / "ingest.lock",
        client=client,
    )

    result = perform_search(
        client=client,
        query="casita",
        facet_filters={},
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    assert code == 0
    assert result["total_hits"] == 1
    assert result["results"][0]["title"] == "Casita Sol"


def test_cron_ingest_updates_search_without_app_restart(tmp_path: Path):
    rentals_dir = tmp_path / "rentals"
    _write_listing(rentals_dir, "airbnb-01-casa-mar-1200usd", "Casa Mar")

    client = InMemorySearchClient()
    first_code = run_scheduled_ingest(
        mode="incremental",
        rentals_dir=rentals_dir,
        lock_file=tmp_path / "ingest.lock",
        client=client,
    )

    _write_listing(rentals_dir, "airbnb-02-casa-sol-1300usd", "Casa Sol")

    second_code = run_scheduled_ingest(
        mode="incremental",
        rentals_dir=rentals_dir,
        lock_file=tmp_path / "ingest.lock",
        client=client,
    )

    result = perform_search(
        client=client,
        query="casa",
        facet_filters={},
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    assert first_code == 0
    assert second_code == 0
    assert result["total_hits"] == 2


def test_full_reindex_restores_search_after_index_clear(tmp_path: Path):
    rentals_dir = tmp_path / "rentals"
    _write_listing(rentals_dir, "airbnb-01-casa-norte-1200usd", "Casa Norte")

    client = InMemorySearchClient()
    run_scheduled_ingest(
        mode="incremental",
        rentals_dir=rentals_dir,
        lock_file=tmp_path / "ingest.lock",
        client=client,
    )

    client.clear_documents()

    empty = perform_search(
        client=client,
        query="casa",
        facet_filters={},
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    run_scheduled_ingest(
        mode="full",
        rentals_dir=rentals_dir,
        lock_file=tmp_path / "ingest.lock",
        client=client,
    )

    restored = perform_search(
        client=client,
        query="casa",
        facet_filters={},
        sort_option="relevance",
        page=1,
        per_page=20,
    )

    assert empty["total_hits"] == 0
    assert restored["total_hits"] == 1
    assert restored["results"][0]["title"] == "Casa Norte"
