"""One-shot script: delete all documents with source=='ai' from Meilisearch."""
import httpx
import time
import sys
import os

host = os.environ.get("MEILISEARCH_URL", "http://meilisearch:7700")
index = os.environ.get("MEILISEARCH_INDEX_UID", "rentals_listings")

resp = httpx.post(
    f"{host}/indexes/{index}/documents/delete",
    headers={"Content-Type": "application/json"},
    json={"filter": "source = 'ai'"},
    timeout=15,
)
print("Delete by filter response:", resp.status_code, resp.text)

if resp.status_code not in (200, 202):
    print("ERROR: unexpected status")
    sys.exit(1)

task_uid = resp.json().get("taskUid")
print(f"Waiting for task {task_uid}...")
for _ in range(20):
    time.sleep(1)
    t = httpx.get(f"{host}/tasks/{task_uid}", timeout=10)
    status = t.json().get("status")
    print(f"  task status: {status}")
    if status in ("succeeded", "failed"):
        break

# Verify
r = httpx.post(
    f"{host}/indexes/{index}/search",
    json={"q": "", "filter": "source = 'ai'", "limit": 1},
    timeout=10,
)
remaining = r.json().get("estimatedTotalHits", "?")
print(f"Remaining 'ai' docs: {remaining}")
