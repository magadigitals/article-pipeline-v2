# Outline Validator-Prompt Sync (2026-07-29)

## The gap

The outline prompt (`outline_prompts.py`) was changed so H2s with subsections
only need `heading` + `purpose` + `subsections` — dropping Type/Depth/Shape/
Model/Fail/Pass/Claims fields. But `outline_validators.py` still required all
7 fields on every H2 via `validate_contract()`. This caused every outline run
to fail its own validation, wasting retries and API credits.

## The fix

`outline_validators.py` `validate_outline()` (line 306-309): H2s with
subsections now skip `validate_contract()`. Bridge H2s (no subsections)
still require all 7 fields.

```python
for i, section in enumerate(data.outline):
    if section.subsections:
        if len(section.purpose.strip()) < 40:
            errors.append(...)
    else:
        validate_contract(f'H2 "{section.heading[:40]}"', section)
    for j, sub in enumerate(section.subsections):
        validate_contract(f'H3 "{sub.heading[:40]}"', sub)
```

## The rule

**When changing prompt rules, always update validators in the same change.**
A prompt rule that produces output the validator rejects is worse than no
change at all — every topic wastes 3 retries × full pipeline cost before
failing.

## Related

- `outline_prompts.py` — `OUTLINE_SYNTHESIS_PROMPT` "Pass" field clarified
  to forbid "The reader recognizes/realizes/accepts/admits" patterns.
- `outline_validators.py` — `min_urls` default lowered from 5 to 4 for DDG
  (niche topics return fewer results).
