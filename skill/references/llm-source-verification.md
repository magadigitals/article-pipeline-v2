# LLM Source Verification with Self-Correction

Added 2026-07-29 as Stage 2c in `run_research_pipeline()`.

## Why

The keyword-based relevance filter (`_web_result_relevant`) matches words, not concepts.
A biology paper titled "Fear-of-intimacy-mediated zinc transport is required for drosophila fat body endoreplication"
passes the keyword filter for a "fear of intimacy" section because the phrase "fear-of-intimacy" appears in the title.
But the paper is about fruit fly genetics — completely irrelevant to a clinical psychology article.

## How

### Verification step

1. `_llm_verify_sources()` runs AFTER claim-based search (Stage 2b) but BEFORE packet assembly (Stage 3)
2. Collects every section that has BOTH claims and sources
3. Sends ONE Hermes call with all sections, their claims, and source titles/snippets
4. LLM returns a JSON dict: `{"section heading": ["identifier_to_remove", ...]}`
5. Sources matching any remove identifier (by pmid, url, or title prefix) are silently dropped

### Self-correction step

For any section that lost ALL sources:

1. LLM generates replacement PubMed AND DDG queries, informed by what was wrong
   (e.g. "all previous candidates were cell biology — find psychology sources instead")
2. PubMed queries run through NCBI ESearch API (`esearch.fcgi`)
3. DDG queries run through `ddgs.DDGS.text()`
4. New results are added to the section's articles/web_sources
5. Results from trusted domains only (same `_is_trusted_web_source` check)

### Properties

- One LLM call per research run (all sections batched in one prompt)
- Zero cost if no sections have both claims and sources
- Self-correction fires a second LLM call only for sections that lost all sources
- Fails gracefully: if the LLM call fails, no sources are removed, pipeline continues
- Total cost: ~$0.01 per topic with DeepSeek V4 Flash

## Location

- Function: `_llm_verify_sources()` in `research_pipeline.py`
- Call site: `run_research_pipeline()` between Stage 2b and Stage 3 (line ~4027)
