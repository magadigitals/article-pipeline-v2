# Non-Fatal UNVERIFIED Fallback

## Problem

Some topics have H3s that simply cannot find trusted sources from DDG or PubMed.
Common cases:
- Emerging-concept topics (e.g. "is depression neurodivergent" — the intersection is too new for .gov/.edu content)
- Dual-concept requirement: topics where the groups check requires BOTH concepts in one source (depression AND neurodivergent). If no sources cover the intersection, the pipeline consistently fails.
- Practical/psychoeducational H3s so niche no trusted domain covers them (e.g. "Building comfort in your own company")

## Fix

In `research_validators.py`, the `validate_clinical_brief()` function checks for `"UNVERIFIED — BLOCK DRAFTING"` in the brief text. By default this appends a fatal error. Make it non-fatal:

```python
if "UNVERIFIED — BLOCK DRAFTING" in brief:
    # Non-fatal: sections without direct evidence can still use
    # web/consensus sources. The LLM writer knows how to work
    # around unverified claims.
    pass
```

## When to use

- ONLY as emergency fallback after preferred methods (LLM query repair, proportional threshold, topic word expansion) have failed
- After re-running at least 3 times with all search fixes applied
- Document which H3s are UNVERIFIED so the writer knows to skip or soften those sections
- Revert to blocking mode once the search fix resolves the root cause

## Recovery

The briefs save to `/tmp/research_debug/` before the `writer_brief_semantics` validation but NOT before `validate_clinical_brief()`. With non-fatal UNVERIFIED:
1. Clinical brief is generated and saved to debug dir
2. Dumbed-down brief is generated (Hermes call)
3. Briefs saved to debug dir after dumbed-down
4. `writer_brief_semantics` may still fail — briefs are at debug dir regardless

Always verify topic: `head -3 /tmp/research_debug/research-brief.md`

## Prevention order (preferred fixes first)

1. LLM query repair (generates better DDG queries using clinical synonyms)
2. Proportional topic threshold (needs majority, not all terms)
3. Individual topic words in topic_or (not just exact phrase)
4. Empty concept_terms fallback (use h3_kw when _preferred_phrases returns nothing)
5. Expanded trusted domains (psychologytoday, psychcentral, etc.)
6. Non-fatal UNVERIFIED (last resort)
