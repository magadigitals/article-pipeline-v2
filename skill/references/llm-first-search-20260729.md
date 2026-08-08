# LLM-First Search Strategy (2026-07-29)

## What changed

`_call_web_sources()` in `research_pipeline.py` was changed from regex-first to LLM-first.
The 6 hardcoded regex strategies (tier 1-6 with topic_or, concept_or, authority_language)
were removed. A single LLM call per H3 now generates query strings directly.

## Why

Regex could not distinguish conceptually different sources that share keywords.
For example, a study titled "The effects of head and neck cancer on relationship
intimacy in adults" passes keyword matching for "fear of intimacy" because both
contain "intimacy" and "relationship." But the source is about cancer patients,
not the psychological avoidance pattern the article is about. An LLM using
clinical synonyms makes this distinction naturally.

## How it works

For each H3:
1. One LLM call (DeepSeek V4 Flash, 30s timeout) receives topic, H3, claims, H2 context
2. LLM returns JSON: {"ddg": [4 queries, narrow→broad], "pubmed": [2 Boolean strings]}
3. DDG queries run first through ddgs.DDGS.text(), accept trusted domain results
4. If <2 results, PubMed queries run through NCBI ESearch
5. No retries, no keyword relevance filter, no regex fallback

## Cost

~$0.05 per topic. Each topic has ~8-12 H3s, each H3 fires one LLM call.
The regex was free but produced wrong results for psychoeducational, comparison,
and emerging-concept topics.

## Prompt design

The prompt instructs the LLM to generate queries of INCREASING BROADNESS:
- Query 1: narrow, specific clinical term + target
- Query 2: medium, synonyms + related constructs
- Query 3: broad, umbrella terms + adjacent concepts
- Query 4: very broad, related conditions + distant but relevant

And: "Do not return empty — always find something. Use broader umbrella terms,
adjacent constructs, exploded MeSH terms, and related conditions. A clinician
researching a niche topic would not give up — they would search for the closest
available evidence."

## Why not both (regex + LLM)?

Previous approach tried regex + LLM query repair. This created a brittle stack
where regex failed → LLM patched → source verifier caught mismatches. The LLM-first
approach removes the regex layer entirely because the LLM generates better queries
in a single pass. The regex code still exists in the file for reference but is no
longer the primary search path.
