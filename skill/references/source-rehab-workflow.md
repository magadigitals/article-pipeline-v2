# Source Rehab Workflow

Applied 2026-07-30 to fix BPD hallucinations article's sourcing.

## The problem

- 1 DOI cited 13 times across 12+ H3 sections (Leichsenring et al. 2024, a general BPD review)
- That DOI had NO entry in the Sources section
- Sources section had 1 garbage entry ("PubMed Central repository copy")
- 60-70% of claims had no inline citation at all

## The fix

1. **Audit** — counted citations per unique URL, identified the overused DOI
2. **Research** — one LLM call with PhD-researcher prompt, listing each H3 claim needing a dedicated source. Generated PubMed Boolean queries for each subtopic. Ran queries through ESearch, fetched ESummary, picked best matching PMIDs.
3. **Swap** — replaced 3 DOI inline citations with specific PubMed PMIDs (sexual hallucinations → Bayrak & Slotema 2026; dissociation → Kleine & Schäfer 2025; medication → Oluwoye et al. 2026)
4. **Rebuild Sources** — replaced 1 garbage entry with 5 proper APA 7 entries matching every inline URL
5. **Run edits** — Karpathy 31 pairs → show user → ask → No-AI-Slop tone pass

## Key rule — no source signaling

When adding new inline citations to an existing article, match the article's existing pattern. The article states claims as facts. The URL is the evidence, not the text.

**Right:** `[sexual hallucinations](https://pubmed...)` — concept link, no attribution verb
**Wrong:** `A study found that [sexual hallucinations](https://pubmed...)` — source signaling

## Number of LLM calls

- 1 call for research (PubMed Boolean queries for all 7 claim areas batched together)
- 0 calls for editing (Karpathy and No-AI-Slop run via script, not manual prompts)

Total: 1 LLM call, ~$0.01
