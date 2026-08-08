# Code Changes — 2026-07-29 Pipeline Session

## Files Modified

### 1. `outline_prompts.py` — H2 field constraint + Pass field fix

**H2 field constraint:** H2s with subsections now only produce `heading`, `purpose`, and `subsections`. No type/depth/shape/claims/model/fail/pass — those belong on H3s only. Bridge H2 (final section, no H3s) still gets all 7 fields.

Changed lines 142-144 from:
```
EVERY H2 AND H3 must have all 7 fields below. H2 fields govern the whole
section; H3 fields govern the subsection. The final bridge H2 still needs all
7 fields even though it has no H3s.
```
To:
```
EVERY H3 must have all 7 fields below. H2s WITH subsections
only need heading, purpose, and subsections — no type/depth/shape/claims/model/fail/pass.
The final bridge H2 (no H3s) still needs all 7 fields.
```

Also removed type/depth/shape/claims/model/fail/pass from the H2 example in the JSON structure (lines 173-179).

**Pass field fix:** Changed from vague "What the reader should feel" to explicit "NEVER start with 'The reader' followed by recognizes, realizes, accepts, admits" to avoid the reader-assumption validator rejection.

### 2. `research_pipeline.py` — DuckDuckGo swap + broader search strategies

**DuckDuckGo swap:** Replaced SerpAPI `requests.get()` (lines 2867-2878) with DDGS call in `_call_web_sources`. Results reshaped to match `organic_results` structure.

**Broader search strategies:** Added two new fallback strategies (5 and 6) after the existing 4:
- Strategy 5: `(government_sites) {concept_or}` — concept-only search on .gov/.edu
- Strategy 6: `{concept_or}` — broad concept-only search (no domain filter)

Bumped `max_queries` default from 4 to 6 to reach the new strategies.

**Removed SERPAPI_KEY check:** The `api_key` variable and "no key = skip" guard were removed since DDG needs no API key.

### 3. `research_validators.py` — UNVERIFIED non-fatal

Changed `validate_clinical_brief()` to treat `UNVERIFIED — BLOCK DRAFTING` as a non-fatal warning instead of a blocking error. The section keeps its status marker but the stage passes through. This allows practical H3s without PubMed evidence (e.g. "Documentation and communication with the court") to generate a clinical brief with whatever web sources were found.

### 4. `article-pipeline` skill (this file) — Skill updates

- Added DuckDuckGo as the web search backend for research phase
- Added UNVERIFIED non-fatal fix documentation
- Added parallel execution pitfall (debug dir overwrites)
- Updated SERPAPI key to new value

### 5. `research_pipeline.py` — Codex migration batch (in progress)

Porting 16 fixes from Codex-validated scripts at `~/Desktop/Golden writing framework/Active/Codex_Article_Pipeline/scripts/core/`.

Completed during this session:
- DuckDuckGo swap (SerpAPI → DDGS free, no key)
- Broader search strategies (5 and 6, max_queries 4→6)
- UNVERIFIED non-fatal in clinical validator (temp workaround)

Migrating via subagents (2026-07-29 ongoing):
- Outline parser: support `- **Type:**` format alongside `**Type:**`
- All PubMed queries anchored to article topic (no topic-free component searches)
- Independent claim searches retain topic
- `_web_result_relevant` rejects source when topic is absent (removes OR fallback that admitted unrelated PCOS, GLP-1, diverticulitis, sickle-cell etc.)
- Neurodivergence topic expansion in SCHOLARLY_TOPIC_EXPANSIONS
- Web search targets only missing/weak H3s, not all H3s
- Source reuse across H3s validated per-target before attaching
- Deterministic retrieval runs before LLM query repair
- APA 7 journal, website, and Bookshelf citation formatting (up to 20 authors, no et al., real metadata from EFetch)
- PubMed/PMC URL hydration before citation
- Webpage citations reject generic "U.S. Government resource" labels
- SerpAPI key rotation client (serpapi_client.py)
- UNVERIFIED validator to be restored to strict mode after root cause fix
- Alphabetized/deduplicated final Sources list
- Regression test suite

Source files for porting:
```
~/Desktop/Golden writing framework/Active/Codex_Article_Pipeline/scripts/core/research_pipeline.py
~/Desktop/Golden writing framework/Active/Codex_Article_Pipeline/scripts/core/serpapi_client.py
~/Desktop/Golden writing framework/Active/Codex_Article_Pipeline/scripts/config_loader.py
~/Desktop/Golden writing framework/Active/Scripts/collect_pubmed_evidence.py
```
