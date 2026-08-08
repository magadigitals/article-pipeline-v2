# No-AI-Slop Integration

## Status: Implemented (2026-07-30)

The no-ai-slop tone pass has been integrated as **Phase 6b** of the article pipeline.

## Script

`~/.hermes/scripts/tone_edit_article.sh` (also in `local_worker/tone_edit_article.sh`)

Called from `run_article.sh` as Step 3b (after Step 3: Karpathy edit).

## What it does

1. Loads the `no-ai-slop` skill via Hermes
2. Passes the article with structural safety instructions
3. The LLM applies no-ai-slop editing rules (tighten prose, cut slop, human voice)
4. Structural elements (crisis line, bridge-to-care, sources, headings, links) are explicitly protected and cannot be modified
5. Outputs a summary table showing what changed and by how many

## Structural safety enforcement

The script's prompt includes explicit do-not-touch instructions for:
1. Crisis response chain (988, 911, emergency room, suicide disclaimer)
2. Bridge-to-care closing (final paragraph inviting reader action)
3. Inline links (DOI, PMC, MRS URLs)
4. H2 and H3 headings (may reword, never remove)
5. Sources section entries (formatting only, never collapse/merge)
6. YAML frontmatter
7. Key Takeaways list

## Pipeline placement

```
Phase 6a: Karpathy edit (structural rhythm, clarity, safety)
Phase 6b: No-AI-Slop tone edit (tighten prose, human voice)
```

Karpathy runs first because it's more deterministic and structurally aware. No-ai-slop runs second with safety guardrails.

## Summary output format

After the article, the script appends a summary table:

Category | Count | Examples
throat-clearing | 2 | "For a long time" → cut
bridge-to-care | kept | preserved (do-not-touch)
crisis-line | kept | preserved (do-not-touch)
