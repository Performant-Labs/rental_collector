"""Show the raw source field for local-llm folder documents in Meilisearch."""
import httpx, os, json

host = os.environ.get("MEILISEARCH_URL", "http://meilisearch:7700")
index = os.environ.get("MEILISEARCH_INDEX_UID", "rentals_listings")

# Get all docs, show their source and id
r = httpx.post(f"{host}/indexes/{index}/search",
    json={"q": "casita de luna", "limit": 3, "attributesToRetrieve": ["id", "title", "source"]},
    timeout=10)
print("Search 'casita de luna':")
for h in r.json().get("hits", []):
    print(f"  {h}")

# Get facets
r2 = httpx.post(f"{host}/indexes/{index}/search",
    json={"q": "", "limit": 0, "facets": ["source"]}, timeout=10)
print("\nFacets:", json.dumps(r2.json().get("facetDistribution", {}).get("source", {}), indent=2))

# Try filter by source = 'ai'
r3 = httpx.post(f"{host}/indexes/{index}/search",
    json={"q": "", "limit": 3, "filter": "source = 'ai'",
          "attributesToRetrieve": ["id", "title", "source"]}, timeout=10)
print("\nDocs with source=ai (sample):")
for h in r3.json().get("hits", []):
    print(f"  {h}")
print("  total ai:", r3.json().get("estimatedTotalHits"))

# Try filter by source = 'local-llm'
r4 = httpx.post(f"{host}/indexes/{index}/search",
    json={"q": "", "limit": 3, "filter": "source = 'local-llm'",
          "attributesToRetrieve": ["id", "title", "source"]}, timeout=10)
print("\nDocs with source=local-llm (sample):")
for h in r4.json().get("hits", []):
    print(f"  {h}")
print("  total local-llm:", r4.json().get("estimatedTotalHits"))
