# PhD Researcher Query Generation Prompt

Used by `_call_web_sources()` (for DDG) and `_llm_generate_pubmed_queries()` (for PubMed) in `research_pipeline.py`. Replaces all regex-based query construction.

## Web search prompt (DDG)

```python
f"You are a PhD-level clinical researcher conducting a systematic literature search.\n"
f"\n"
f"Article topic: {topic}\n"
f"H3 heading: {h3}\n"
f"H2 context: {parent_h2}\n"
f"Section type: {section_type}\n"
f"Approved claims: {'; '.join(claims[:4])}\n"
f"\n"
f"Construct a query ladder of INCREASING BROADNESS. Think step by step:\n"
f"1. First, identify the PRECISE clinical/diagnostic term for this concept\n"
f"2. Then identify its synonyms, narrower terms, and broader umbrella terms\n"
f"3. Finally, identify adjacent constructs and related conditions\n"
f"\n"
f"A PhD scholar would never search for the lay wording of an H3 as-is. "
f"They would use the exact clinical terminology that appears in the literature.\n"
f"\n"
f"Return ONLY a JSON object:\n"
f'- "ddg": list of 4 DDG query strings, narrow to broad, using clinical terms\n'
f'- "pubmed": list of 2 PubMed Boolean strings (narrow then broad) with MeSH, [Title/Abstract], year ranges\n'
f'- "clinical_terms_used": list of precise clinical terms and synonyms used\n'
```

## PubMed search prompt

```python
f"You are a PhD-level clinical researcher conducting a systematic PubMed search.\n"
f"\nArticle topic: {topic}\nH3 heading: {heading}\nH2 context: {parent_h2}\n"
f"Section type: {section_type}\nApproved claims: {claims_str}\n\n"
f"Construct 2-3 PubMed Boolean query strings of INCREASING BROADNESS. "
f"Map the H3 to its precise clinical/diagnostic term and MeSH. "
f"Use [Title/Abstract] and [MeSH] field tags. "
f'Apply a 7-year filter: AND (\"2019\"[Date - Publication]:\"3000\"[Date - Publication]) '
f"A PhD scholar uses exact clinical terminology, not lay wording.\n\n"
f"Return ONLY a JSON list: [\"query1\", \"query2\"]"
```

## Key design rules

1. **No topic-specific examples in the prompt.** Examples anchor the LLM toward specific terms (e.g., showing "autophobia" for "phobia of being alone" makes the LLM search for "autophobia" even for unrelated topics). The instruction to "identify the PRECISE clinical/diagnostic term" is enough — the LLM already knows clinical vocabulary.

2. **Step-by-step reasoning.** The 3-step chain (precise term → synonyms → adjacent constructs) forces the LLM to map before generating, producing better queries.

3. **JSON code fence handling.** The LLM frequently wraps JSON in ```json...``` blocks. The code strips these before json.loads(). See `references/json-code-fence-fix.md`.

4. **Single pass, no retries.** The LLM generates a query ladder (narrow → broad) in one call. Each query is tried in order. If the first is too narrow, the broader ones catch it. No remakes.

5. **Both search engines in one response** (for the web prompt). The LLM returns PubMed AND DDG queries together, so the code can try PubMed first, fall back to DDG.
