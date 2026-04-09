"""Print the actual Meilisearch config the FastAPI app uses."""
import os
from dashboard.app.meilisearch_index_client import MeilisearchIndexClient

print("MEILISEARCH_URL env:", os.environ.get("MEILISEARCH_URL", "(not set)"))
print("MEILISEARCH_INDEX_UID env:", os.environ.get("MEILISEARCH_INDEX_UID", "(not set)"))

client = MeilisearchIndexClient.from_env()
print("Client host_url:", client.host_url)
print("Client index_uid:", client.index_uid)

# Now actually search and show what we get
results = client.search_documents("casita de luna", limit=1)
for h in results.get("hits", []):
    print("Hit source:", h.get("source"), "title:", h.get("title"))

facets = client.search_documents("", limit=1, facets=["source"])
print("Facets:", facets.get("facetDistribution", {}).get("source"))
