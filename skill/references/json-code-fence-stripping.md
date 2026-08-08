# JSON Code Fence Stripping (2026-07-29)

## The problem

DeepSeek V4 Flash frequently wraps JSON responses in markdown code fences:

```json
{
  "key": "value"
}
```

When `json.loads()` is called on this output directly, it fails with `json.JSONDecodeError` because the string starts with \`\`\``, not `{`. This causes **silent failures** — the H3 gets 0 sources with no error message.

## The fix

Strip leading and trailing \`\`\` markers before parsing:

```python
def _strip_json_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (may be ```json or just ```)
        if "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
        else:
            cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()
```

Then call `json.loads(_strip_json_fences(stdout))`.

## Where this is needed

- Every `_hermes_call()` response that's expected to return JSON
- `_call_web_sources()` — search_one_section LLM query generation
- `_call_pubmed_search()` — `_llm_generate_all_pubmed_queries()`
- `_llm_verify_sources()` — source verification prompt

## Why it happens

DeepSeek's system prompt encourages markdown formatting. A JSON-only instruction like "Return ONLY a JSON object" is treated as a content instruction, not a format constraint. The model adds \`\`\`json fences because it considers that "cleaner output."

Workaround tested: instructing "Return ONLY the raw JSON, no markdown, no code fences" reduces but does not eliminate the behavior. Stripping in post-processing is mandatory.
