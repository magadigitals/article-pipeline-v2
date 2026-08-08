# Article Pipeline v2 — Chat-Driven Process

The CURRENT article pipeline (replaces the v1 dashboard-era process). No UI.
You paste topics in chat; the agent loads the article-pipeline skill and runs
the stages in PARALLEL across all topics, with a confirmation gate after every
phase. Chat is the interface.

## Stages

1. ClickUp — create tasks (`clickup_pipeline.py`)
2. Outline — SERP-backed competitor research (`outline_pipeline.py`, SerpAPI)
3. Research — PubMed + DuckDuckGo, LLM-first query generation, source
   verification, self-correction (`research_pipeline.py`)
4. Write — `golden_writer.py`
5. Fix — gate scripts + LLM repair + source pruning (`fix_article.sh`,
   `prune_sources.py`)
6. Edit — Karpathy 32-pair editorial pass (`edit_article.sh`)
7. Tone — No-AI-Slop pass (`tone_edit_article.sh`)
8. Clinical Review Gate — claim-vs-source check, efficacy overstatement,
   missing caveats, safety gaps (`clinical_review_gate.py`)
9. Copy final article to the GWF Articles folder

Every phase transition requires explicit user approval. V2 versioning: a
"v2" of any article/brief is a NEW file alongside the original, never a
replacement.

## Layout

- `skill/` — the Hermes skill (SKILL.md + references/). Install by copying
  to `~/.hermes/skills/content/article-pipeline/`.
- `scripts/` — standalone pipeline scripts. Run from the pipeline working
  dir (`/Users/mac/Documents/Codex/2026-07-14/ca/local_worker`).
- `scripts/tests/` — regression tests.

## Usage

With the article-pipeline skill loaded, paste topics in chat:

- `Run full pipeline: <topic>, clinic: <name>`
- `Run outline for topics: <t1>, <t2>, ...` (parallel per stage)

## Tests

```
python3 -m unittest test_research_regressions
```

## Repo hygiene

- This repo contains ONLY the user's own code/skill — no client work product.
- Client articles, clinic profiles, and agency workspace content
  (~/Desktop/Golden writing framework/) must NEVER be committed here,
  even in private repos. See `skill/references/client-ip-and-repo-state.md`.
- The skill hardcodes client clinic names as defaults (Modern Recovery
  Services, MRS Arizona, Avery's House, Roots Renewal Ranch). Fine in a
  private repo; strip them before any public sharing.
