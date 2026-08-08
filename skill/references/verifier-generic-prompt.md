# Verifier prompt — never hardcode examples (2026-07-30)

## The problem

The Stage 2c verifier (`_llm_verify_sources`) had hardcoded examples in its prompt:
```
(e.g. coronaphobia when the topic is autophobia, or kinesiophobia when the topic is fear of being alone)
```

This broke in two ways:
1. The LLM only looked for those EXACT patterns and missed novel mismatches (gelotophobia, nomophobia)
2. The examples anchored the LLM toward those specific terms instead of teaching the general principle

## The fix

Replace hardcoded examples with a generic instruction:

> "A source is irrelevant if the claim is about a psychological/clinical topic and the source is about a **different clinical construct, different population, different condition subtype, or different diagnostic category** than what the H3 and claims describe — even if both share the same broad category (e.g., both are 'phobias' but one is about fear of being alone and the source is about a different phobia type)."

## General principle for all LLM prompts

Never hardcode topic-specific examples in any prompt. Generic instructions with reasoning steps work better:

1. They don't anchor the LLM toward specific patterns
2. They generalize to any topic without modification
3. They catch unexpected edge cases the programmer didn't anticipate

This applies to every prompt in the pipeline: query generation, source verification, clinical review, and brief generation. If you're tempted to add an example, add a reasoning step instead.
