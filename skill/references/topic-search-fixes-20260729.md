# Topic Search Fixes (2026-07-29)

## Problem
DDG returned fewer .gov/.edu results than SerpAPI for certain topic types:
- **Comparison/definitional topics** (dysphoria vs dysmorphia): The exact phrase `("dysphoria vs dysmorphia")` wouldn't match .gov pages that discuss one condition independently.
- **Lay-language topics** (phobia of being alone): No expansion to clinical terms like "autophobia".
- **Practical/psychoeducational H3s** (What gender dysphoria actually is): `_preferred_phrases()` returned empty for these headings, making `concept_or` an empty string.

## Fixes applied to `research_pipeline.py`

### Fix A: Individual topic words in search (line ~3190)
When building `topic_or`, also add individual topic words ≥4 chars (not stopwords) alongside the quoted phrases. This means `"dysphoria vs dysmorphia"` expands to `("dysphoria vs dysmorphia" OR "dysphoria" OR "dysmorphia")`.

### Fix B: Empty concept_terms fallback (line ~3187)
If `_preferred_phrases()` returns nothing for an H3, fall back to using `h3_kw` (the raw heading keywords) directly. `concept_or` is never empty.

### Fix C: Proportional topic-matching threshold (line ~1356)
`_topic_matches_text()` previously required 60%+ of topic terms to match (the `(len*3+4)//5` formula). For a 2-term topic like "dysphoria vs dysmorphia", this required BOTH terms. Changed to majority threshold: `(len+1)//2` — needs at least half. A source about "gender dysphoria" alone now matches the topic even without "dysmorphia".

## Verification
- `site:.gov gender dysphoria body dysmorphia` → 5 results from DDG
- `_topic_matches_text("dysphoria vs dysmorphia", "Gender Dysphoria Report")` → was False, now True
- `_preferred_phrases("What gender dysphoria actually is")` → was [], now falls back to h3_kw
