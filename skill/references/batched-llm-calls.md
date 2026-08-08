# Batched PubMed LLM query generation (2026-07-30)

## What changed

Replaced per-H3 `_llm_generate_pubmed_queries()` (one LLM call per H3) with `_llm_generate_all_pubmed_queries()` — one LLM call for ALL H3s.

## Why

12 H3s × 1 call each = 12 LLM calls → ~5 minutes wall-clock. All 12 H3s in one call = 1 LLM call → ~30 seconds.

## Design

The function takes a list of (heading, section_type, parent_h2, claims) tuples and returns a dict mapping each heading to its 2-3 query strings.

The prompt sends all H3s in one structured block with sections numbered 1-N. Each H3 gets its own key in the returned JSON. Fallback per-H3 using `_build_pubmed_queries_v3()` for any section the LLM didn't handle.
