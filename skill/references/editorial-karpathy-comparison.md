# Editorial Karpathy Approach vs Full Editorial Brain

## Key finding (July 2026)

The 200-line Karpathy 30-pair prompt (editorial_karpathy.md) performed significantly better than the 3,312-line editorial brain (Editorial_Brain.md + STYLE_RUBRIC.md + BANNED_PHRASES.md).

## Comparison

| Approach | Lines | Edits Made | Domains Covered | Cost |
|---|---|---|---|---|
| Full editorial brain | 3,312 | 7 | 1 (contrast templates only) | Free |
| Karpathy 30-pair | ~200 | 16 | 6 (passive, contrast, throat-clearing, em dashes, nominalization, bridge-to-care) | ~$0.06 |

## Why Karpathy works better

LLMs don't follow long instruction files. 3,312 lines of abstract rules get ignored after the first 200. The Karpathy approach uses concrete WRONG/RIGHT examples (30 pairs, each 2-4 lines) that the LLM can actually read and process in a single pass. The model explicitly checked all 30 pairs and reported which had matches and which didn't.

## File

- `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/editorial_karpathy.md` — the 30-pair prompt
- `/Users/mac/.hermes/scripts/edit_article.sh` — calls Hermes with the Karpathy prompt
