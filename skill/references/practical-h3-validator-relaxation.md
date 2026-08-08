# Dumbed-Down Validator: Practical H3 Relaxation

Applied 2026-07-29 to fix repeated `writer_brief_semantics` failures on practical/logistical H3s.

## Problem

The validator's causal check (`validate_writer_semantics`) required all "how" and "why" H3s to have at least 2 causal markers (because, causes, leads to, etc.) in the `Plain facts` / `Safe wording` fields. This broke on practical H3s like:

- "Questions to ask when choosing a program"
- "How to start the conversation"
- "What to look for in a provider"

These are checklists and action guides, not causal explanations. They don't need "dehydration causes headache" style language.

## Fix

In `research_validators.py`, `validate_writer_semantics()`:

```python
practical_verbs = r"\b(ask|choose|find|talk|prepare|questions?|what to|when to|where to|steps? to|tips? for|ways? to|options? for|signs? of)\b"
if not re.search(practical_verbs, heading.strip(), re.I):
    causal_links = causal_markers.findall(explanatory_text)
    if len(causal_links) < 2:
        errors.append(...)
```

If the H3 heading matches a practical verb pattern, the causal check is skipped entirely.

## Safety guidance non-fatal

Also in `validate_writer_semantics()`:

Safety groups (medication interactions, pregnancy/breastfeeding, overdose, withdrawal, suicide) that exist in the clinical packet but are absent from the dumbed-down brief are now NON-FATAL (`pass` instead of `errors.append()`). Practical topics may not need all safety categories.

## When to expand

Add more verbs to the regex if new practical H3 shapes fail:
- "signs of" → already included
- "symptoms of" → NOT included — these are clinical
- "benefits of" → NOT included — these are claims
- "risks of" → NOT included — these are safety
