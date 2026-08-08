# JSON Code Fence Stripping (2026-07-29)

## Problem

The LLM (DeepSeek V4 Flash) frequently wraps JSON responses in markdown code fences:

```json
{
  "ddg": [...],
  "pubmed": [...]
}
```

When this output reaches `json.loads()`, it fails because the string starts with `` ```json `` not `{`. The error is silently caught in the try/except, and the H3 gets **0 sources with no visible error**.

## Fix

In `research_pipeline.py` `search_one_section()`, strip code fences before parsing:

```python
cleaned = stdout.strip()
if cleaned.startswith("```"):
    cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
if cleaned.endswith("```"):
    cleaned = cleaned.rsplit("```", 1)[0]
llm_result = json.loads(cleaned.strip())
```

## Apply to any new LLM call

If adding a new `_hermes_call()` that expects JSON response, always include code fence stripping. Without it, the call silently returns nothing.

## Detection

If an H3 has 0 sources and `queries_attempted` shows `[LLM]` entries but no sources, the JSON likely failed to parse due to code fences. Check by printing raw stdout before parsing.
