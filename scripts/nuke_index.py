"""Delete the Meilisearch index entirely and rebuild it from scratch."""
import httpx, os, time

host = os.environ.get("MEILISEARCH_URL", "http://meilisearch:7700")
index_uid = os.environ.get("MEILISEARCH_INDEX_UID", "rentals_listings")

# 1. Delete the entire index
print(f"Deleting index '{index_uid}'...")
r = httpx.delete(f"{host}/indexes/{index_uid}", timeout=15)
print(f"  Response: {r.status_code} {r.text}")

if r.status_code in (200, 202):
    task_uid = r.json().get("taskUid")
    print(f"  Waiting for task {task_uid}...")
    for _ in range(30):
        time.sleep(1)
        t = httpx.get(f"{host}/tasks/{task_uid}", timeout=10)
        status = t.json().get("status")
        print(f"  status: {status}")
        if status in ("succeeded", "failed"):
            break

# 2. Verify gone
r2 = httpx.get(f"{host}/indexes/{index_uid}", timeout=10)
print(f"\nIndex exists? {r2.status_code} (404 = good)")
