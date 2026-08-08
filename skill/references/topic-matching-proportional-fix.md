# Topic Matching Proportional Threshold Fix (2026-07-29)

## Problem

`_topic_matches_text()` used `required = max(1, (len(topic_terms) * 3 + 4) // 5)` which required almost ALL topic terms. For "dysphoria vs dysmorphia" (2 terms), it required both terms (2/2). A .gov page about gender dysphoria alone doesn't mention "dysmorphia" — so every result was rejected.

## Root cause chain

1. `topic_or` = only the exact phrase `"dysphoria vs dysmorphia"` — no .gov site uses that exact phrase
2. `concept_or` = empty `("")` when `_preferred_phrases()` returned nothing — broke all search queries
3. `_topic_matches_text` needed 2/2 terms — no single source covers both "dysphoria" and "dysmorphia"

## Fix

**`topic_or` construction (research_pipeline.py:3195):**
```python
topic_words = [w for w in topic.split() if len(w) >= 4 and w.lower() not in STOP_WORDS]
all_topic_terms = list(dict.fromkeys(topic_phrases + topic_words))[:10]
topic_or = "(" + " OR ".join(f'"{p}"' for p in all_topic_terms) + ")"
```

**`concept_or` fallback (research_pipeline.py:3188):**
```python
if not concept_terms:
    concept_terms = h3_kw[:6]
```

**`_topic_matches_text` proportional threshold (research_pipeline.py:1358):**
```python
# Was: required = max(1, (len(topic_terms) * 3 + 4) // 5)
required = max(1, (len(topic_terms) + 1) // 2)
```

For 2 terms → need 1 (majority). For 3 terms → need 2. For 4 terms → need 2.

## Impact

Dysphoria vs dysmorphia went from 0 results on every attempt to finding sources for most H3s. The 3 fixes together improved source discovery for ALL multi-word topics, not just this one.

## Test

```python
from research_pipeline import _topic_matches_text
# Before: required=2 for 2 terms → False
# After: required=1 for 2 terms → True
assert _topic_matches_text("dysphoria vs dysmorphia", "gender dysphoria report")
```
