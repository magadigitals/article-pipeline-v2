# LLM Query Repair for Regex-Failed H3s

Added 2026-07-29. Unified PubMed + DDG repair (v2). Replaces the earlier DDG-only version.

## Why needed

The 6 regex-based search strategies fail on psychoeducational H3s whose vocabulary doesn't match .gov/.edu sites or PubMed MeSH terms. Regex translates the H3's exact wording into a query — it can't use clinical synonyms. This causes 0-source H3s for topics like phobia-of-being-alone (H3s: "Building comfort in your own company", "Emotional, physical, and behavioral signs").

## Implementation

In `_call_web_sources()` inside `research_pipeline.py`, after all 6 regex strategies run:

```python
if len(section_sources) < 2:
    # Brief LLM with: topic, H3, parent H2, section type, approved claims
    # LLM returns a JSON dict with TWO keys:
    #   "pubmed": list of 2 PubMed Boolean query strings (MeSH terms, clinical vocab)
    #   "ddg": list of 3 DDG query strings (clinical synonyms, no site: filters)
    # PubMed queries run through NCBI ESearch API
    # DDG queries run through ddgs library
    # Results from both accepted if from a trusted domain
```

## Prompt template

```
Article topic: {topic}
H3 heading: {h3}
H2 context: {parent_h2}
Section type: {section_type}
Approved claims: {'; '.join(claims[:4])}

The regex-based search strategies failed to find enough relevant sources
for this section. Using your clinical knowledge, generate better search
queries for BOTH PubMed and DDG.

Return ONLY a JSON object with two keys, nothing else:
- "pubmed": a list of 2 PubMed Boolean query strings using MeSH terms
  and clinical synonyms
- "ddg": a list of 3 DDG query strings using clinical terminology and
  approximate phrase matching (no site: filters)

Example: {
  "pubmed": [
    "(\"autophobia\"[Title/Abstract] OR \"monophobia\"[Title/Abstract]) AND
     (\"cognitive behavioral therapy\"[Title/Abstract] OR ...)",
    "(\"fear of being alone\"[Title/Abstract] OR ...) AND ..."
  ],
  "ddg": [
    "autophobia interpersonal relationships attachment",
    "monophobia symptoms treatment cbt",
  ]
}
```

## Design

- Only fires for H3s with <2 keyword-matched sources (~2-3 per topic)
- One bounded LLM call per H3 — no retry if it fails
- PubMed queries use NCBI ESearch API (real search, not just PMID lookup)
- DDG queries run through ddgs with max_results=5
- Results filtered by trusted domain + student repo blocklist
- Sources marked `support_scope: "llm_query"` in the output

## Known limitation

If DDG or PubMed returns 0 results (regardless of query quality), the LLM repair doesn't help. This happens for emerging-concept topics (e.g. "is depression neurodivergent") where no authoritative sources exist covering the intersection. In those cases, the non-fatal UNVERIFIED safety net is needed.

## v1 → v2 changes (2026-07-29)

- **Old (v1):** LLM only generated 3 DDG queries. PubMed was not repaired.
- **New (v2):** LLM generates 2 PubMed Boolean strings AND 3 DDG queries in a single call.
  PubMed queries hit the real NCBI ESearch endpoint.
