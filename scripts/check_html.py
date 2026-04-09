"""Check what the FastAPI server actually renders in its HTML response."""
import httpx, re
from collections import Counter

r = httpx.get("http://localhost:8000/", timeout=10)
print("Status:", r.status_code)
html = r.text

sources = re.findall(r'data-source="([^"]+)"', html)
print("data-source values in rendered HTML:", Counter(sources))

# Also check facet sidebar text
facet_matches = re.findall(r'ai\s+(\d+)', html)
print("'ai' count in html:", html.count('"ai"'), "occurrences of data-source=ai:", html.count('data-source="ai"'))
print("occurrences of data-source=local-llm:", html.count('data-source="local-llm"'))
