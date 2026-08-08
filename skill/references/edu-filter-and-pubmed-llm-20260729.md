# .edu Filter Tightening + Unified PubMed/DDG LLM Query Repair (2026-07-29)

Two changes made in the same session:

## 1. .edu Filter Tightening

`_is_trusted_web_source()` in `research_pipeline.py` now blocks student repository URLs before accepting `.edu` domains. See `references/student-repo-blocklist.md` for the full pattern list.

The regex is applied BEFORE the `.edu` check:
```python
if STUDENT_REPO_PATTERNS.search(url):
    return False
if host.endswith(".gov") or host.endswith(".edu"):
    return True
```

## 2. Unified PubMed + DDG LLM Query Repair

The LLM query repair for regex-failed H3s now generates queries for **BOTH PubMed AND DDG** in a single LLM call. The old version only generated DDG queries, which meant PubMed-strong topics (clinical conditions, definitions) got no LLM support.

The prompt asks for a JSON dict:
```python
{
  "pubmed": ["...Boolean query 1...", "...Boolean query 2..."],
  "ddg": ["...query 1...", "...query 2...", "...query 3..."]
}
```

PubMed queries run through NCBI ESearch API (`eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`). DDG queries run through `ddgs.DDGS.text()`. Both sets of results are accepted from trusted domains.

## Combined effect

Before these fixes, the fear-of-intimacy article had 30+ sources including student theses, academia.edu search pages, and irrelevant biology papers (Drosophila zinc transport). After:
- No student theses or repository uploads
- No search result pages or glossary pages
- No "PubMed Central repository copy" placeholders
- 7 clean APA-7 journal citations, all actually cited inline
