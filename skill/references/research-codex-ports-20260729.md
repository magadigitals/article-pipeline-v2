# Codex → Hermes Research Pipeline Ports (2026-07-29)

## What was ported

The following fixes from the Codex-validated `research_pipeline.py` were applied to the Hermes `research_pipeline.py` at `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/research_pipeline.py`:

### Fix 2-3: PubMed topic anchoring

All PubMed queries now include the article topic. No more topic-free component searches that return unrelated conditions (PCOS, GLP-1, diverticulitis, sleep apnea, sickle-cell).

**Before (topic-free):**
```python
f"({' OR '.join(fielded_literals[:8])}) AND (...)"
```

**After (topic-anchored):**
```python
f"({topic_fielded}) AND ({' OR '.join(fielded_literals[:8])}) AND (...)"
```

Claim-based fallback also retains the topic:
```python
if fielded_claims and topic_fielded:
    queries.append(f"({topic_fielded}) AND ({' OR '.join(fielded_claims)})")
```

Claim searches (PubMed + SerpAPI/DDG) also include topic. SerpAPI claim query includes `"(site:.gov OR site:.edu) "{topic}" (terms)"`.

### Fix 4: Reject topic-free component evidence

`_web_result_relevant()` now requires topic_match + title_anchor + at least 1 section concept hit. Removed the old OR-fallback that accepted any source with 2+ section matches even without topic relevance.

**Before:**
```python
return (topic_match and title_anchor and section_hits >= 1) or (not topic_match and section_hits >= 2)
```

**After:**
```python
return topic_match and title_anchor and section_hits >= 1
```

### Fix 5: Neurodivergence topic expansion

Added to `SCHOLARLY_TOPIC_EXPANSIONS`:
```python
"neurodivergent": ("neurodivergence", "neurodiversity", "neurodiverse"),
```

### Fix 6: Web search only for weak/missing H3s

`run_research_pipeline()` now only runs DDG web search for H3s in `set(missing_sections) | set(weak_sections)`. If no sections are weak or missing, the web search stage is completely skipped (saves API calls and time).

### Fix 9-14: APA 7 citation formatting

Replaced the old `_apa7_cite()` with the Codex version featuring:

- **NCBI Bookshelf detection:** books/NBK\d+ URLs formatted as book entries, not journal articles
- **20-author citation limit:** ≤20 authors listed fully; 21+ uses "first 19, …, last". No "et al." in reference list.
- **Sentence case titles** via `_sentence_case_title()` preserving acronyms
- **Journal title proper capitalization** via `_journal_title_case()`
- **Volume/issue/pages formatting** with en-dashes
- **DOI prefix stripping** (`https://doi.org/` removed)
- **Webpage citations** formatted as `Organization (date). Title. Site Name. URL`
- **Hard rejection** of generic author labels like "U.S. Government resource", "University or academic resource"
- **Metadata hydration** from Highwire, Dublin Core, OpenGraph tags
- **PubMed EFetch hydration:** PMID URLs resolve to real article metadata (authors, journal, volume, issue, pages)
- **PMC → PubMed resolution** via NCBI ID Converter API
- **Sources list** alphabetized and deduplicated by URL

Helper functions added:
- `_apa_author_name()` — normalizes author strings to APA surname-and-initials
- `_sentence_case_title()` — APA sentence case preserving acronyms
- `_journal_title_case()` — journal title capitalization
- `_apa_date()` — ISO dates to APA style
- `_organization_for_domain()` — domain → organization name mapping
- `_fetch_citation_metadata()` — hydrates PubMed/PMC/web page metadata
- `_CitationMetaParser` — HTML parser for Highwire/Dublin Core/OpenGraph

### DuckDuckGo (DDGS) replaces SerpAPI

The research pipeline's `_call_web_sources()` and `_search_claims_for_section()` now use DuckDuckGo (via `from ddgs import DDGS`) instead of SerpAPI. No API key needed.

**Install:** `pip install ddgs` (NOT `pip install duckduckgo-search` — the package was renamed)

**Import:** `from ddgs import DDGS`

**Note:** The outline pipeline (Phase 2) still uses SerpAPI in `_call_serpapi()` — keep the SERPAPI_KEY for that phase.

### Validator reverted

The `validate_clinical_brief()` UNVERIFIED — BLOCK DRAFTING check was reverted from non-fatal (temporary bypass) back to strict (fatal error). A proper root-cause fix is still needed: trace why `web_for_section` is empty in `_format_research_packet()` when web sources exist for that H3.

### Files modified

- `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/research_pipeline.py` — all fixes above
- `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/research_validators.py` — validator reverted
- `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/outline_prompts.py` — Pass field fix (from earlier session)

### Files deleted

- `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/serpapi_client.py` — created then deleted (SerpAPI not needed with DDG)
- `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/config_loader.py` — created then deleted
