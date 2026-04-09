from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dashboard.app import indexing_commands
from dashboard.app.indexing_commands import (
    DEFAULT_INDEX_SETTINGS,
    full_reindex,
    incremental_upsert,
)
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeTransport:
    def __init__(self):
        self.calls: list[tuple[str, str, Any]] = []
        self.index_exists = False

    def get(self, url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        self.calls.append(("GET", url, None))
        if self.index_exists:
            return FakeResponse(200, {"uid": "rentals_listings"})
        return FakeResponse(404, {"code": "index_not_found"})

    def post(self, url: str, headers: dict[str, str], json: Any, timeout: int) -> FakeResponse:
        self.calls.append(("POST", url, json))
        if url.endswith("/indexes"):
            self.index_exists = True
            return FakeResponse(202, {"taskUid": 1})
        if url.endswith("/documents"):
            return FakeResponse(202, {"taskUid": 2})
        return FakeResponse(202, {"taskUid": 99})

    def patch(self, url: str, headers: dict[str, str], json: Any, timeout: int) -> FakeResponse:
        self.calls.append(("PATCH", url, json))
        return FakeResponse(202, {"taskUid": 3})

    def delete(self, url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        self.calls.append(("DELETE", url, None))
        return FakeResponse(202, {"taskUid": 4})


@dataclass
class FakeIndexClient:
    calls: list[str]
    upsert_payloads: list[list[dict[str, Any]]]

    def ensure_index_exists(self) -> bool:
        self.calls.append("ensure")
        return False

    def apply_index_settings(self, settings: dict[str, Any]) -> int:
        self.calls.append("settings")
        assert "filterableAttributes" in settings
        assert "sortableAttributes" in settings
        assert "searchableAttributes" in settings
        return 101

    def clear_documents(self) -> int:
        self.calls.append("clear")
        return 102

    def clear_documents_and_wait(self) -> None:
        self.calls.append("clear")

    def upsert_documents(self, documents: list[dict[str, Any]]) -> int:
        self.calls.append("upsert")
        self.upsert_payloads.append(documents)
        return 103


def test_creates_index_if_missing():
    transport = FakeTransport()
    client = MeilisearchIndexClient(
        host_url="http://meilisearch:7700",
        index_uid="rentals_listings",
        transport=transport,
    )

    created = client.ensure_index_exists()

    assert created is True
    assert transport.calls[0][0] == "GET"
    assert transport.calls[1][0] == "POST"
    assert transport.calls[1][1].endswith("/indexes")


def test_applies_index_settings():
    transport = FakeTransport()
    transport.index_exists = True
    client = MeilisearchIndexClient(
        host_url="http://meilisearch:7700",
        index_uid="rentals_listings",
        transport=transport,
    )

    task_uid = client.apply_index_settings(DEFAULT_INDEX_SETTINGS)

    assert task_uid == 3
    method, url, payload = transport.calls[0]
    assert method == "PATCH"
    assert url.endswith("/indexes/rentals_listings/settings")
    assert payload == DEFAULT_INDEX_SETTINGS


def test_upsert_sends_expected_documents():
    transport = FakeTransport()
    transport.index_exists = True
    client = MeilisearchIndexClient(
        host_url="http://meilisearch:7700",
        index_uid="rentals_listings",
        transport=transport,
    )
    documents = [
        {"id": "listing-2", "title": "B"},
        {"id": "listing-1", "title": "A"},
    ]

    task_uid = client.upsert_documents(documents)

    assert task_uid == 2
    method, url, payload = transport.calls[0]
    assert method == "POST"
    assert url.endswith("/indexes/rentals_listings/documents")
    assert payload == documents


def test_full_reindex_clears_then_reloads(monkeypatch):
    fake_client = FakeIndexClient(calls=[], upsert_payloads=[])

    monkeypatch.setattr(
        indexing_commands,
        "build_documents_from_rentals",
        lambda rentals_dir: (
            [
                {"id": "listing-2", "title": "Second"},
                {"id": "listing-1", "title": "First"},
            ],
            [],
        ),
    )

    result = full_reindex(fake_client, rentals_dir=Path("/tmp/rentals"))

    assert fake_client.calls == ["ensure", "settings", "clear", "upsert"]
    assert [doc["id"] for doc in fake_client.upsert_payloads[0]] == ["listing-1", "listing-2"]
    assert result["mode"] == "full_reindex"
    assert result["indexed_count"] == 2


def test_incremental_upsert_is_idempotent(monkeypatch):
    fake_client = FakeIndexClient(calls=[], upsert_payloads=[])

    monkeypatch.setattr(
        indexing_commands,
        "build_documents_from_rentals",
        lambda rentals_dir: (
            [
                {"id": "listing-2", "title": "Second"},
                {"id": "listing-1", "title": "First"},
            ],
            [],
        ),
    )

    first = incremental_upsert(fake_client, rentals_dir=Path("/tmp/rentals"))
    second = incremental_upsert(fake_client, rentals_dir=Path("/tmp/rentals"))

    assert first["indexed_count"] == second["indexed_count"] == 2
    assert fake_client.upsert_payloads[0] == fake_client.upsert_payloads[1]
    assert fake_client.calls == ["ensure", "settings", "upsert", "ensure", "settings", "upsert"]
