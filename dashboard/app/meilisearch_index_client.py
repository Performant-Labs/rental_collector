from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class HttpTransport(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: int) -> Any: ...

    def post(self, url: str, headers: dict[str, str], json: Any, timeout: int) -> Any: ...

    def patch(self, url: str, headers: dict[str, str], json: Any, timeout: int) -> Any: ...

    def delete(self, url: str, headers: dict[str, str], timeout: int) -> Any: ...


class HttpxTransport:
    def __init__(self):
        self._client = httpx.Client()

    def get(self, url: str, headers: dict[str, str], timeout: int) -> Any:
        return self._client.get(url, headers=headers, timeout=timeout)

    def post(self, url: str, headers: dict[str, str], json: Any, timeout: int) -> Any:
        return self._client.post(url, headers=headers, json=json, timeout=timeout)

    def patch(self, url: str, headers: dict[str, str], json: Any, timeout: int) -> Any:
        return self._client.patch(url, headers=headers, json=json, timeout=timeout)

    def delete(self, url: str, headers: dict[str, str], timeout: int) -> Any:
        return self._client.delete(url, headers=headers, timeout=timeout)


@dataclass
class MeilisearchIndexClient:
    host_url: str
    index_uid: str
    api_key: str | None = None
    timeout_seconds: int = 15
    transport: HttpTransport | None = None

    @classmethod
    def from_env(cls) -> "MeilisearchIndexClient":
        return cls(
            host_url=os.environ.get("MEILISEARCH_URL", "http://meilisearch:7700"),
            index_uid=os.environ.get("MEILISEARCH_INDEX_UID", "rentals_listings"),
            api_key=os.environ.get("MEILISEARCH_API_KEY"),
        )

    @property
    def _transport(self) -> HttpTransport:
        if self.transport is None:
            self.transport = HttpxTransport()
        return self.transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _index_url(self) -> str:
        return f"{self.host_url}/indexes/{self.index_uid}"

    def ensure_index_exists(self) -> bool:
        response = self._transport.get(
            self._index_url(),
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        if response.status_code == 200:
            return False
        if response.status_code != 404:
            raise RuntimeError(f"Failed to check index: {response.status_code} {response.text}")

        create_response = self._transport.post(
            f"{self.host_url}/indexes",
            headers=self._headers(),
            json={"uid": self.index_uid, "primaryKey": "id"},
            timeout=self.timeout_seconds,
        )
        if create_response.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"Failed to create index: {create_response.status_code} {create_response.text}"
            )
        return True

    def apply_index_settings(self, settings: dict[str, Any]) -> int | None:
        response = self._transport.patch(
            f"{self._index_url()}/settings",
            headers=self._headers(),
            json=settings,
            timeout=self.timeout_seconds,
        )
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Failed to apply settings: {response.status_code} {response.text}")
        payload = response.json() if hasattr(response, "json") else {}
        return payload.get("taskUid")

    def clear_documents(self) -> int | None:
        response = self._transport.delete(
            f"{self._index_url()}/documents",
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Failed to clear documents: {response.status_code} {response.text}")
        payload = response.json() if hasattr(response, "json") else {}
        return payload.get("taskUid")

    def upsert_documents(self, documents: list[dict[str, Any]]) -> int | None:
        response = self._transport.post(
            f"{self._index_url()}/documents",
            headers=self._headers(),
            json=documents,
            timeout=self.timeout_seconds,
        )
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Failed to upsert documents: {response.status_code} {response.text}")
        payload = response.json() if hasattr(response, "json") else {}
        return payload.get("taskUid")

    def search_documents(
        self,
        query: str,
        *,
        filter_expression: str | None = None,
        sort: list[str] | None = None,
        offset: int = 0,
        limit: int = 20,
        facets: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "q": query,
            "offset": offset,
            "limit": limit,
            "facets": facets or [],
        }
        if filter_expression:
            payload["filter"] = filter_expression
        if sort:
            payload["sort"] = sort

        response = self._transport.post(
            f"{self._index_url()}/search",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Failed to search index: {response.status_code} {response.text}")
        return response.json() if hasattr(response, "json") else {}
