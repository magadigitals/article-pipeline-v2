# `_safe_cite` — No More Garbage Citations

Added 2026-07-29 (v2). Changed from "fallback to URL" to "raise ValueError".

## What it was (v1, broken)

```python
def _safe_cite(source: dict) -> str:
    try:
        return _apa7_cite(source)
    except ValueError:
        title = source.get("title", "Untitled").rstrip(". ")
        url = source.get("url", "")
        return f"{title}. {url}" if url else title
```

This produced garbage like `(n.d.). *(PDF) fear of intimacy - academia.edu ...*` — no author, no journal, no year. It was a leaky band-aid that dressed bad sources as citations instead of rejecting them.

## What it is now (v2, fixed)

```python
def _safe_cite(source: dict) -> str:
    """Format a citation. Raises ValueError if APA metadata is missing."""
    return _apa7_cite(source)
```

No more fallback. If a source can't produce valid APA metadata (authors, year, journal for PubMed articles; organization + date for web sources), `ValueError` is raised and the source is silently skipped at the call site.

## Call sites

Every `_safe_cite()` call in `_format_research_packet` is wrapped in try/except ValueError:
```python
try:
    cite = _safe_cite(art)
except ValueError:
    continue
```

This means bad sources are simply dropped from the research brief instead of crashing the pipeline OR producing garbage.

## Key tradeoff

The raise-and-skip approach is correct but means the research brief may have fewer sources than DDG found. That's acceptable — a brief with 5 good APA citations is better than one with 7 including 2 garbage entries.
