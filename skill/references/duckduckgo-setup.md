# DuckDuckGo Search Setup (ddgs)

Free search API replacement for SerpAPI in research_pipeline.py.

## Why

SerpAPI free tier caps at 100 requests/month and rate-limits aggressively (429 errors on parallel queries). DuckDuckGo is free, unlimited, and requires no API key.

## Package

The Python package was renamed from `duckduckgo-search` to `ddgs` in 2026.

```bash
pip install ddgs
```

The old `duckduckgo_search` namespace is deprecated and raises a RuntimeWarning.

## Usage

```python
from ddgs import DDGS
ddg = DDGS()
results = list(ddg.text("your search query", max_results=5))
for r in results:
    print(r["title"])    # str
    print(r["href"])     # str (URL)
    print(r["body"])     # str (snippet)
```

## Integration in research_pipeline.py

Replaced `requests.get("https://serpapi.com/search", ...)` in `_call_web_sources` (line ~2867). The DDG results are reshaped to match the `organic_results` structure:

```python
from ddgs import DDGS
ddg = DDGS()
ddg_results = list(ddg.text(query, max_results=5))
data = {"organic_results": []}
for r in ddg_results:
    data["organic_results"].append({
        "link": r.get("href", ""),
        "title": r.get("title", ""),
        "snippet": r.get("body", ""),
    })
```

## Notes

- No API key needed — the `SERPAPI_KEY` check in `_call_web_sources` was removed (2026-07-29).
- DDG works with the same search query syntax as SerpAPI (site: filters, boolean operators, quotes).
- DDG is slightly slower than SerpAPI but has no rate limit for reasonable usage (5 queries per H3 × 10 H3s = 50 queries per topic).
- Installed on both Anaconda Python 3.12 and system Python 3.9 via pip3.
