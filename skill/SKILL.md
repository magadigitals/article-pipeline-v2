---
name: article-pipeline
description: "Full article production pipeline: ClickUp → Outline → Research → Write → Fix → Edit → GWF. Run any topic. All scripts standalone."
version: 3.3.0
tags: [pipeline, writing, editing, golden-writing-framework]
---

# Article Pipeline

Run the full pipeline for one or more topics. Default clinic: Modern Recovery Services.

## Interaction Protocol (CRITICAL)

When the user says "I need..." or "what about..." or "I'm thinking of..." — do NOT build. Do NOT open a text editor. Ask: "Want me to build this or just discuss?" Building before understanding the scope has been the #1 source of frustration.

When the user gives a direct command ("run stage by stage", "proceed to write", "run outlines", "run it"), just execute immediately — don't re-ask.

**CRITICAL: Stage by stage means CONFIRM EVERY PHASE TRANSITION.** After each phase completes, report results and explicitly ask "Proceed to [next phase]?" Do NOT auto-advance — even for well-defined follow-up phases like Fix after Write or Edit after Fix. **This extends to sub-stages within editing: after Karpathy edit completes, show the result and ask "Ready for No-AI-Slop tone pass?" before running it.** The user must see and approve each intermediate result. Breaking this rule (auto-advancing through Fix → Edit → GWF without asking, or Karpathy → No-AI-Slop without review) caused significant frustration. When in doubt, ask.

**CRITICAL: Never revert changes the user asked for.** When the user requests a change and you've made it, do NOT undo it unless they explicitly say "revert that" or "undo it." If they critique how you implemented something (e.g., "lead-ins should be part of edit process, not manual patches"), that means improve the process, not revert the work. Reverting work the user asked for is worse than never having done it.

**CRITICAL: Implement the FULL request, not half.** The user has corrected this multiple times: (a) LLM must generate queries for BOTH PubMed AND DDG, not just DDG; (b) one batched call for all H3s, not one per H3; (c) replace regex entirely, don't add LLM as a patch on top. When told to replace X with Y, replace it everywhere X was used — don't leave the old path intact. Before finishing, ask: "Did I do what they actually asked, or just the easy part?"

When the user says "lets plan" or "lets troubleshoot and plan", STOP. Do NOT dispatch subagents, make changes, or execute anything. Discuss scope first. Get explicit approval. This means: no terminal commands, no file edits, no delegation — only questions and a written plan.

When running batch topics, run the current stage in PARALLEL for all topics (DDG has no rate limits). Notify on complete for each.

When validation fails repeatedly (>2 retries consuming API credits for same stage/topic), say what failed and why (one sentence), offer 2 options: "re-run with fix" vs "skip/manual route". Let the user choose.

Prefer direct tool calls for pipeline stages over delegation (subagents lose session context).

## Reference files

- `references/editorial-karpathy.md` — 32 BEFORE/AFTER editing pairs (was 30). Pairs #31 (bullet list lead-ins with colon endings) and #32 (source-attribution anchor text: link IS the claim, not a wrapper attributing it to evidence) added 2026-07-30. Used by edit_article.sh.
- `references/lead-in-colons.md` — Lead-in sentence ending with colon before bullet lists. Editorial pattern to apply during Edit phase: every bullet list should have a preceding sentence that sets context and ends with a colon. Vary the language so it doesn't feel formulaic.
- `references/topic-search-fixes-20260729.md` — Topic matching & search query fixes (proportional threshold, individual words, concept fallback).
- `references/research-pipeline-codex-ports-20260729.md` — All research pipeline ports (APA 7, PubMed topic anchoring, DDG migration, dumbed-down validation fixes).
- `references/batched-llm-calls.md` — Batched LLM calls: one call for all H3s instead of per-H3. Applied to PubMed query generation.
- `references/json-code-fence-stripping.md` — DeepSeek wraps JSON in ```json...``` fences. Strip before json.loads() or parse fails silently.
- `references/llm-first-search-20260729.md` — LLM replaces regex as the primary web search strategy. One call per H3 generates 4 DDG + 2 PubMed queries. PhD-researcher prompt.
- `references/llm-query-repair-20260729.md` — (Legacy) Previous approach: LLM patched regex failures. Now replaced by LLM-first search.
- `references/student-repo-blocklist.md` — Student repository URL patterns blocked (academia.edu, digital.library, honors theses, bitstreams, etc.).
- `references/safe-cite-fix-20260729.md` — _safe_cite() now raises ValueError instead of producing garbage (n.d.) citations. Bad sources are silently skipped.
- `references/source-attribution-anchor-text.md` — Karpathy pair #32: link anchor IS the claim.: bridge-to-care (editable but standalone), crisis line, inline links, headings, sources, frontmatter, Key Takeaways. Updated 2026-07-30 with softened bridge-to-care rule.
- `references/v2-versioning.md` — When user says "do a v2", create slug-v2.md alongside the original. Never replace.
- `references/content-update-tool-design.md` — Content audit + fix engine design. For retrofitting existing published pages with better sources, missing sections, and keyword gaps. Not yet built.

## Which Pipeline Is This?

There are TWO article pipeline skills. This one is the **stage-by-stage, human-in-the-loop** mode: confirmation gate after every phase (ClickUp → Outline → Research → Write → Fix → Edit → GWF), plus Karpathy + No-AI-Slop editing passes. Output: `runs/{slug}/article.md`.

The **golden-content-pipeline** (`content/golden-content-pipeline/`) is the automated BATCH engine: one-call draft via golden_writer.py v2, artifacts `article.raw.md` / `.cleaned.md` / `.compiled.md` / `.qa.initial.json`. Use it when the user wants many topics at once; use this skill when they want stage-by-stage control.

When the user asks "which pipeline made X": check `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/runs/{slug}/` artifact names. Batch runs may not appear in session_search — they execute outside Hermes chat sessions.

## Quick Start

Two modes:

**Full auto** — say: `"Run full pipeline: [topic], clinic: [name]"`
  → Runs all phases. Reports when done. Article in GWF/Articles/.

**Stage by stage** — say: `"Load article-pipeline. Run outline: [topic]"`
  → After ClickUp: paste task link for verification. Confirm before proceeding.
  → Order: ClickUp (verify link) → Outline → Research → Write → Fix → Edit → Copy to GWF
  → **After each phase, report results and ask "Proceed to [next phase]?" Do NOT auto-advance — every transition needs user approval, even in later phases (Fix, Edit, GWF).**

**Batch (N topics, stage by stage)** — say: `"Run outline for topics: [t1], [t2], ..."`
  → Run the current stage in parallel for all topics. Then report results and ask to proceed to next stage.

## Canonical status — do not confuse with golden-content-pipeline

This skill is THE canonical skill for article work. The `golden-content-pipeline` skill is the OLDER batch system (scripts underneath, batch_pipeline era) — do not use it for new article work.

Both skills call the SAME shared scripts (golden_writer.py, etc.), so run-folder artifact names (article.raw.md, article.compiled.md, article.qa.initial.json) do NOT distinguish which skill drove a run. To identify which skill produced a batch: check session history, and check the skill's own content — this skill documents batch topics by name in its Pitfalls (e.g. "is depression neurodivergent", dual-concept topics), which is direct evidence it ran that batch. Misidentifying the driver (2026-08) caused user frustration; trust the user's memory of which workflow they built.

## Topics
- TOPIC: the article topic
- CLINIC: "Modern Recovery Services" (or "MRS Arizona", "Avery's House", "Roots Renewal Ranch")
- SLUG: derived from topic (lowercase, spaces to hyphens, remove special chars)

## File paths

| Type | Path |
|---|---|
| Working dir | `/Users/mac/Documents/Codex/2026-07-14/ca/local_worker` |
| Outlines | `~/Desktop/Golden writing framework/outlines/outline_{slug}_preflight.md` |
| Research brief | `~/Desktop/Golden writing framework/Briefs/{slug}_Research_Brief.md` |
| Dumbed-down brief | `~/Desktop/Golden writing framework/Briefs/{slug}_Research_Brief_Dumbed.md` |
| Article (working) | `runs/{slug}/article.md` |
| Article (final) | `~/Desktop/Golden writing framework/Articles/{slug}.md` |

## Phase 1: ClickUp

Create ClickUp tasks for all topics in parallel.

```bash
python3 ~/.hermes/scripts/clickup_pipeline.py create \
  --name "{topic}" --space MRS --keyword "{topic}" \
  --sheet-row 0 --tab Pipeline --sheet-id pipeline
```

Timeout: 30s. Paste all task URLs for user verification before proceeding.

## Phase 2: Outline

Generate outline via outline_pipeline. Uses SerpAPI for competitor discovery (outline_pipeline.py still uses SerpAPI — NOT switched to DDG). Run topics in PARALLEL via background processes.

**Known issues:**
- SerpAPI 429: if running many in parallel, some may hit rate limit. Re-run failed ones solo.
- DeepSeek malformed JSON: re-running usually resolves it.
- Niche topics may get <5 competitor URLs. Validator lowered to min 4.

```bash
CONDA_NO_PLUGINS=true python3 -c "
import os, sys, sqlite3, uuid
from pathlib import Path
sys.path.insert(0, '$PWD')
os.environ['SERPAPI_KEY'] = '<key>'
from outline_pipeline import configure_pipeline, run_outline_pipeline
configure_pipeline(hermes_bin=Path.home()/'.local/bin/hermes', model='deepseek-v4-flash', provider='deepseek', db_path=Path('/tmp/outline_state.db'), hermesscripts=Path.home()/'.hermes/scripts')
db = sqlite3.connect('/tmp/serp_cache.db'); db.execute('PRAGMA journal_mode=WAL')
result = run_outline_pipeline(topic='{topic}', db=db, article_id=str(uuid.uuid4()), clinic_name='Modern Recovery Services', clinic_brand='MRS')
Path.home().joinpath('Desktop/Golden writing framework/outlines/outline_{slug}_preflight.md').write_text(result); db.close()
print(f'Outline done: {len(result)} chars')
"
```

Timeout: 600s.

## Phase 3: Research

Generate clinical + dumbed-down briefs via research_pipeline. Includes an **LLM source verification** step (Stage 2c) that filters out sources that don't actually support the section's claims.

⚠️ Create debug dir first: `mkdir -p /tmp/research_debug`

**Web source search:** Uses DuckDuckGo (free, no API key). Install: `pip install ddgs`. The SERPAPI_KEY env var is ignored by research stage.

```bash
mkdir -p /tmp/research_debug
python3 -c "
import os, sys, sqlite3, uuid
from pathlib import Path
sys.path.insert(0, '$PWD')
os.environ['RESEARCH_DEBUG_DIR'] = '/tmp/research_debug'
Path('/tmp/research_debug').mkdir(parents=True, exist_ok=True)
from research_pipeline import run_research_pipeline
from outline_pipeline import configure_pipeline
configure_pipeline(hermes_bin=Path.home()/'.local/bin/hermes', model='deepseek-v4-flash', provider='deepseek', db_path=Path('/tmp/research_state.db'), hermesscripts=Path.home()/'.hermes/scripts')
outline = Path.home().joinpath('Desktop/Golden writing framework/outlines/outline_{slug}_preflight.md').read_text()
db = sqlite3.connect('/tmp/research_cache.db'); db.execute('PRAGMA journal_mode=WAL')
clinical, dumbed = run_research_pipeline(topic='{topic}', outline_markdown=outline, db=db, article_id=str(uuid.uuid4()))
Path.home().joinpath(f'Desktop/Golden writing framework/Briefs/{slug}_Research_Brief.md').write_text(clinical)
Path.home().joinpath(f'Desktop/Golden writing framework/Briefs/{slug}_Research_Brief_Dumbed.md').write_text(dumbed)
db.close()
print(f'Research done: Clinical {len(clinical)} + Dumbed {len(dumbed)} chars')
"
```

Timeout: 600s.

⚠️ `/tmp/research_debug/` is SHARED across parallel processes. Always verify topic heading after recovery: `head -3 /tmp/research_debug/research-brief.md`. If wrong topic, re-run affected topic solo.

**Recovery by failure type:**
- `writer_brief_semantics` → files save to debug dir. Copyable.
- `web_sources` → NO files saved. Must fix outline or skip research.
- `clinical_brief` (UNVERIFIED) → NO files saved. Apply non-fatal UNVERIFIED pass, re-run, then briefs save to debug dir (may still fail on writer_brief_semantics).

## Phase 4: Write

```bash
python3 golden_writer.py \
  --topic "{topic}" --clinic "{clinic}" \
  --outline "~/Desktop/Golden writing framework/outlines/outline_{slug}_preflight.md" \
  --brief "~/Desktop/Golden writing framework/Briefs/{slug}_Research_Brief_Dumbed.md" \
  --output "runs/{slug}/article.md"
```

Timeout: 600s.

⚠️ Some runs write to `output/{slug}-article.md` instead. If article <10k chars, check `output/`.

## Phase 5: Fix

Runs gate scripts + LLM repair + source pruning (prune_sources.py removes sources not cited inline).

```bash
bash fix_article.sh "runs/{slug}/article.md"
```

Timeout: 600s.

⚠️ Source pruning: `prune_sources.py` runs automatically during fix. It removes any `## Sources` entry whose URL does not appear as an inline citation in the article body. This prevents research-brief dumps from leaking into the final article and keeps the Sources list to only what's actually cited. See `prune_sources.py` in the working dir.

## Phase 6: Edit

```bash
bash ~/.hermes/scripts/edit_article.sh "runs/{slug}/article.md"
```

Timeout: 600s.

## Phase 6b: Tone Edit (No-AI-Slop)

After Karpathy edits, run the no-ai-slop tone pass for tighter, more human prose. See `references/tone-edit-script.md` for the full design and pitfalls.

```bash
bash ~/.hermes/scripts/tone_edit_article.sh "runs/{slug}/article.md"
```

Timeout: 300s.

The wrapper script loads the no-ai-slop skill, passes the article with structural safety instructions, and outputs a summary table showing categories changed and counts. Structural safety elements (crisis line, bridge-to-care, sources, headings, links) are explicitly protected and will NOT be modified.

See `references/no-ai-slop-integration.md` and `references/tone-edit-script.md` for the full design. See also the no-ai-slop skill (`content/no-ai-slop/SKILL.md`) for the editing rule set and structural safety section.

## Phase 7: Copy to GWF

```bash
cp "runs/{slug}/article.md" \
   "~/Desktop/Golden writing framework/Articles/{slug}.md"
```

## Phase 8: Clinical Review Gate (optional, LLM-based)

Run after Edit, before publish. One LLM call per article via DeepSeek API directly (~30s). Reads the article, resolves inline DOIs/PMC URLs to abstracts, and checks:
1. Claim-source mismatch — does each cited source actually support the claim?
2. Efficacy overstatement — "treats" vs "may help"
3. Missing caveats — risks, side effects, limitations not mentioned
4. Safety gaps — crisis resources missing from severe-symptom sections

Outputs a JSON report with verdict: PASS / WARN / FLAG. Does NOT modify the article.

```bash
DEEPSEEK_API_KEY=$(grep DEEPSEEK_API_KEY ~/.hermes/.env | cut -d= -f2) python3 clinical_review_gate.py "runs/{slug}/article.md" --output "runs/{slug}/clinical-review.json"
```

**Note:** The DeepSeek API key is stored in `~/.hermes/.env`, not set as an environment variable. Always export it or inline it as shown above when running this script. The key uses the `DEEPSEEK_API_KEY` env var name (configured in `~/.hermes/config.yaml` under `providers.deepseek.api_key_env`).

Report path: `runs/{slug}/clinical-review.json`.

## Distribution

The pipeline lives (PRIVATE, stale) at:
**https://github.com/oghenemaga/article-pipeline** — `git clone https://github.com/oghenemaga/article-pipeline.git`

⚠️ **Repo state (checked 2026-08-08): STALE and DIRTY — NOT the canonical backup.** It is a single-commit dump of the OLD dashboard-era process that also contains client work product (runs/ articles, clinic_profiles/, *-output/ folders, .research_cache/, .backups/) and has NO .gitignore. It is MISSING the current scripts (clinical_review_gate.py, tone_edit_article.sh, updated research_pipeline.py, editorial_karpathy.md, run_article.sh, test_research_regressions.py). See `references/client-ip-and-repo-state.md` for the full audit and cleanup options.

**Current process is chat-driven (this skill), NOT the dashboard.** Legacy dashboard-era files in the working dir (app.py, dashboard.py, server.py, worker.py, clickup_delivery.py, index.html, pipeline.py, run.py) belong to the retired UI process — never mistake them for the current workflow.

If the repo is ever rebuilt to match the current process: include ONLY the skill folder + current scripts + a README documenting the chat-driven workflow; keep it PRIVATE; never include client content. Install the skill on a new machine by copying `~/.hermes/skills/content/article-pipeline/` into the target machine's Hermes skills directory.

## Technical notes

### Research pipeline changes (2026-07-29)
See `references/research-pipeline-codex-ports-20260729.md` for full detail on all ports and `references/safe-cite-fix-20260729.md` for the APA crash fix:
- PubMed topic anchoring (Fix 2-3)
- Topic-free component evidence rejection (Fix 4)
- Neurodivergence expansion (Fix 5)
- Web search only for weak H3s (Fix 6)
- APA 7 citation formatting (Fix 10-14)
- Dumbed-down validation relaxed for practical H3s
- DDG replaces SerpAPI for research web fallback
- 6 search strategy tiers (was 4) — broader fallbacks for practical H3s

### Outline pipeline changes (2026-07-29)
- `outline_prompts.py`: H2s with subsections only need heading + purpose + subsections (not all 7 fields). Bridge H2 still needs all 7.
- `outline_prompts.py`: Pass field now explicitly forbids "The reader recognizes/realizes/accepts/admits" patterns.
- `outline_validators.py`: validate_contract skips H2s that have subsections. min_urls lowered from 5 to 4.
- Existing outlines from before this change may have redundant H2 fields — safe to strip manually.

### Dumbed-down validator practical H3 relaxation
`research_validators.py`: `validate_writer_semantics()` skips causal check for H3s matching practical verbs (ask, choose, find, talk, prepare, questions, what to, when to, where to, steps to, tips for, ways to, options for, signs of). Safety guidance dropping is non-fatal. See `references/practical-h3-validator-relaxation.md`.

### DDG limitations for certain topic types
DDG returns fewer .gov/.edu results than SerpAPI. Definitional/comparison topics (dysphoria vs dysmorphia) consistently return 0 trusted sources. See `references/ddg-limitations.md`. Options: add trusted domains, skip research, merge H3s, or modify search strategies.

**Fixed (2026-07-29):** Three root causes were identified and fixed:
1. **topic_or used only the exact topic phrase** like `"dysphoria vs dysmorphia"` — .gov sites don't use that phrase. Fix: add individual topic words as OR terms.
2. **concept_or was empty** when `_preferred_phrases()` returned nothing — made the search query `("")` which matched nothing. Fix: fallback to h3_kw.
3. **`_topic_matches_text` required ALL topic terms** (2/2) — "dysphoria" and "dysmorphia" both needed in source text. A .gov page about gender dysphoria alone was rejected. Fix: proportional threshold `(len+1)//2` — needs majority, not all.

### Topic search fixes (2026-07-29)
Three fixes applied to `research_pipeline.py` to improve DDG source discovery:
- **Individual topic words** in topic_or (not just exact phrase) — at line 3195
- **Empty concept_terms fallback** to h3_kw when `_preferred_phrases()` returns nothing — at line 3188
- **Proportional topic-matching threshold** — `(len+1)//2` instead of `(len*3+4)//5` (needs majority, not all) — `_topic_matches_text()` at line 1358
See `references/topic-search-fixes-20260729.md`.

### Trusted clinical domains expanded (2026-07-29)
Added 16 new non-.gov trusted domains to `TRUSTED_CLINICAL_DOMAINS` in `research_pipeline.py`:
`psychologytoday.com`, `goodtherapy.org`, `psychcentral.com`, `verywellmind.com`, `nationaleatingdisorders.org`, `eatingdisorderhope.com`, `thetrend.clinic`, `equalhope.org`, `anxietycanada.com`, `brown.edu`, `mcleanhospital.org`, `childmind.org`, `reachout.com`, `health.harvard.edu`, `med.stanford.edu`, `hopkinsmedicine.org`
These are needed because DDG returns fewer .gov/.edu results than SerpAPI, and practical/psychoeducational H3s (signs checklists, building comfort, comparison guides) aren't covered by government content.

### `_safe_cite` must reject not dress up garbage (CRITICAL — updated 2026-07-29)
The APA 7 formatter (`_apa7_cite()`) raises `ValueError` when a source lacks authors/year/journal metadata. **`_safe_cite()` must NOT fall back to URL-only** — that produces `(n.d.). *Title fragment*. URL` for student theses, repository uploads, and search result pages. This was the original bug that produced the garbage citations in the fear-of-intimacy article.

Fix: `_safe_cite()` is now a bare call to `_apa7_cite()` — it raises ValueError. All call sites in `_format_research_packet` are wrapped in try/except ValueError (skip that source, continue). A source that cannot produce valid APA metadata is silently dropped. See `references/safe-cite-garbage-fix.md`.

When adding new `_safe_cite()` calls, ALWAYS wrap in try/except ValueError. A bare `_safe_cite()` on an unhydrated PMC URL crashes the entire brief at packet assembly. Search `_safe_cite(` in `_format_research_packet` and guard every call.

### LLM query generation — Unified PubMed + DDG (2026-07-30)
For every H3, the LLM generates a query ladder: 4 DDG queries + 2 PubMed Booleans in one call. This is the PRIMARY search path, not a fallback. Regex is not used in the primary path for either search engine.

### LLM source verification with self-correction (Stage 2c — 2026-07-29)
After sources are collected, `_llm_verify_sources()` runs one bounded LLM call that reads each section's claims alongside its candidate sources and identifies irrelevant matches (e.g. a biology paper about a gene named after a psychological concept, OR a source about a different subtype of the same broad condition — like coronaphobia when the topic is autophobia). **The verifier prompt must use generic "different clinical construct" language, not hardcoded examples** — otherwise it misses novel mismatches. See `references/verifier-generic-prompt.md`. Irrelevant sources are silently dropped from the section.

**Self-correction:** For sections that lose ALL their sources, the LLM generates replacement PubMed AND DDG queries informed by what was rejected — e.g., "all previous results were about cell biology, find psychological studies instead." These queries run through NCBI ESearch and DDGS, and results are added back to the section. This completes the verify → remove → re-search → re-add cycle automatically. One LLM call per research run (all sections batched). Zero cost if sections have no claims or no sources. Fails gracefully.

See `references/llm-source-verification.md`.
When the LLM query generation runs for a weak H3, it generates improved queries for **BOTH PubMed AND DDG** using clinical synonyms and conceptual vocabulary. The old version of this prompt only asked for DDG queries — that was wrong. The LLM must generate search strings for both engines in one call.

Prompt asks for a JSON dict with two keys:
- `"pubmed"`: 2 PubMed Boolean query strings using MeSH terms, field tags, and clinical synonyms
- `"ddg"`: 3 DDG query strings using approximate phrase matching (no site: filters)

PubMed queries run through NCBI ESearch API. DDG queries run through `ddgs.DDGS.text()`. Results from either source are accepted if from a trusted domain. No retry if LLM call fails.

Only fires for weak H3s (~2-3 per topic). See `references/llm-query-repair-20260729.md`. Replaces the earlier DDG-only LLM repair which missed the PubMed side of the problem entirely.

### Validator sync with prompt changes
When changing outline prompts (e.g. stripping H2 fields), always update `outline_validators.py` in the same change. Otherwise outlines pass prompt rules but fail validator rules — wasting retries and API credits.
### PubMed search — LLM-first with batched generation (2026-07-30)

The PubMed query generation (`_call_pubmed_search()`) uses `_llm_generate_all_pubmed_queries()` — one LLM call for ALL H3s, not one per H3. Each call generates 2-3 PubMed Boolean query strings per H3 of increasing broadness, using the same PhD-researcher prompt as the web search.

The LLM maps each H3 to precise clinical/diagnostic terms, MeSH headings, and [Title/Abstract] field tags — never the lay wording. Regex `_build_pubmed_queries_v3()` is kept as a silent fallback if the LLM call fails.

**Combined fallback chain for each H3 (no retries, single pass):**
1. LLM generates PubMed queries + DDG queries in one call
2. PubMed queries run via NCBI ESearch (narrow → broad)
3. If PubMed returns 0 results, DDG queries run (narrow → broad) via ddgs
4. Trusted domain filter only — no keyword relevance filter
5. If still empty, section gets whatever was found (or empty)

**Complete search architecture (2026-07-30):**
- PubMed: `_llm_generate_pubmed_queries()` → NCBI ESearch
- Web: `_call_web_sources()` LLM query ladder → DDG
- Both use the same PhD-researcher prompt style
- No regex in the primary path for either engine
- Regex (`_build_pubmed_queries_v3`, 6-strategy tiers) only fires as fallback if LLM call fails
- Total cost: ~$0.05-0.10 per topic

### Search strategy — LLM-first, regex removed as primary path (2026-07-29)

The web source search (`_call_web_sources()`) now uses **LLM-generated queries as the primary path**, not regex. For each H3, a single Hermes call generates 4 DDG queries of increasing broadness + 2 PubMed Boolean strings.

**Prompt framing (critical for source quality):** The LLM is instructed as a "PhD-level clinical researcher conducting a systematic literature search." It is told to identify precise clinical/diagnostic terminology before generating queries — never search for the lay wording of an H3 as-is. **Never hardcode topic-specific examples in prompts** (e.g., "like autophobia" or "like coronaphobia") — that anchors the LLM toward those specific terms and defeats the purpose of the PhD-researcher framing. Generic instructions with step-by-step reasoning work better. Use a reasoning chain instead:
1. Identify the PRECISE clinical/diagnostic term for this concept
2. Identify synonyms, narrower terms, and broader umbrella terms
3. Identify adjacent constructs and related conditions

**JSON parsing pitfall:** The LLM often wraps JSON in markdown code fences (\`\`\`json...\`\`\`). The code strips these before json.loads(). Without this strip, the parse silently fails and the H3 gets 0 sources. See research_pipeline.py search_one_section().

**Fallback chain (no retries, single pass per H3):**
1. LLM generates query ladder (narrow → broad)
2. DDG queries run; trusted-domain results accepted
3. If <2 DDG results, PubMed queries run via NCBI ESearch
4. If still empty, section gets whatever was found (or empty)

**Cost:** ~$0.05 per topic (one LLM call per H3, ~8-12 H3s per topic).

### DDG inline import pattern
- **Golden writer model cutoff:** If `golden_writer.py` returns <5k chars, DeepSeek likely cut off mid-generation. Re-run. The Hermes call may have returned partial stdout. No article under 5k chars is usable.
- **Proportional topic-matching threshold:** `_topic_matches_text()` uses `(len+1)//2` instead of `(len*3+4)//5` — needs a majority of topic terms, not all. This fixed comparison topics (dysphoria vs dysmorphia) where a .gov page about "gender dysphoria" doesn't mention "dysmorphia" — now needs 1 of 2 terms instead of all 2.
- **LLM query generation prompt (unified PubMed + DDG, used for every H3):** The primary prompt, not a fallback. One call per H3 generates the query ladder. Uses PhD-researcher framing — no topic-specific examples. ```python
  f"You are a PhD-level clinical researcher conducting a systematic literature search.\\n"
  f"\\n"
  f"Article topic: {topic}\\n"
  f"H3 heading: {h3}\\n"
  f"H2 context: {parent_h2}\\n"
  f"Section type: {section_type}\\n"
  f"Approved claims: {'; '.join(claims[:4])}\\n"
  f"\\n"
  f"Construct a query ladder of INCREASING BROADNESS. Think step by step:\\n"
  f"1. First, identify the PRECISE clinical/diagnostic term for this concept\\n"
  f"2. Then identify its synonyms, narrower terms, and broader umbrella terms\\n"
  f"3. Finally, identify adjacent constructs and related conditions\\n"
  f"\\n"
  f"A PhD scholar would never search for the lay wording of an H3 as-is. "
  f"They would use the exact clinical terminology that appears in the literature.\\n"
  f"\\n"
  f"Return ONLY a JSON object:\\n"
  f'- "ddg": list of 4 DDG query strings, narrow to broad, using clinical terms\\n'
  f'- "pubmed": list of 2 PubMed Boolean strings (narrow then broad) with MeSH, [Title/Abstract], year ranges\\n'
  f'- "clinical_terms_used": list of precise clinical terms and synonyms used\\n'
  ```
  See `references/llm-first-search-20260729.md`.
- **DDG inline import pattern:** `from ddgs import DDGS; DDGS().text(query, max_results=5)`. Package: `ddgs` (not `duckduckgo-search`). Install: `pip install ddgs`. Mock: `patch('ddgs.DDGS', mock_ddgs)` with MagicMock (not `patch('ddgs.DDGS.text')` — patch the class, not the method).

### Test suite
43 tests in `test_research_regressions.py`. Run: `python3 -m unittest test_research_regressions`.
Also 13 dedicated regression tests for topic anchoring, relevance rejection, APA formatting, web targeting, and validator behavior.

### Conda plugin noise
Prepend `CONDA_NO_PLUGINS=true`. Harmless, just annoying.

**New effect (2026-07-29):** The conda plugin error gets CAPTURED in `_hermes_call()`'s stdout because it uses `subprocess.run(..., shell=True, capture_output=True)`. The conda error is written to stderr by the shell init script, but `subprocess.run(capture_output=True)` captures both stdout and stderr into `result.stdout` on some shells. This means Hermes output from `_hermes_call()` may have conda noise prepended.

Workaround: when parsing `_hermes_call()` output, find the first `{` (for JSON) or skip lines starting with `#`, spaces, or containing `conda`/`anaconda`. The conda noise is always at the beginning of output and always starts with a `#` character.

### ClickUp routing force-rules
Add to `~/.hermes/scripts/clickup_routing_rules.json`.

## Writing process rules — source citation (no signaling language)

The article's inline citations must follow the **natural concept link** pattern. NO:
  - "A [2026 study found](https://...) that..."
  - "[Research shows](https://...) that..."
  - "The [evidence supports](https://...) this approach"
  - Any verb attributing the claim to a source (shows, found, confirms, indicates, suggests)

YES — concept is the anchor text, no attribution verb:
  - `[sexual hallucinations](https://...)` ✓
  - `[dissociation–hallucination connection](https://...)` ✓
  - `[pattern of insight](https://...)` ✓

Match the existing article's citation pattern when adding new sources. No PMIDs visible in inline text. When replacing an overused source, change only the URL — keep the anchor text identical or use an equally natural noun phrase.

### Source Rehab

When an article has poor sourcing — one DOI cited 10+ times, missing Sources entries, `(n.d.)` entries, or claims without inline citations — use the **source-rehab** skill (loaded via /skill source-rehab or skill_view).

This skill audits inline citations, runs the pipeline's LLM-first research to find specific replacement sources for overused URLs, swaps URLs with natural concept-link anchor text (no source signaling), and rebuilds the Sources section. It does NOT rewrite prose or add new sections. Works on any `.md` file.

If the article needs NEW sections added or existing sections rewritten (not just better sources), see the content update tool design (references/content-update-tool-design.md).

### Do NOT write from training data

When adding content to an existing article, follow the approved outline's structure for that section. Do not write new paragraphs from training data. Use the existing article's H3 headings, tone, and sentence patterns as a template. If the outline doesn't specify the content, do not invent it.

## Script locations

- `tone_edit_article.sh` — in working dir and `~/.hermes/scripts/`. No-AI-Slop pass, after Karpathy.
- `golden_writer.py`, `fix_article.sh`, `editorial_karpathy.md` — in working dir
- `clinical_review_gate.py` — in working dir. LLM-based clinical accuracy check, run after Edit.
- `outline_pipeline.py`, `outline_prompts.py`, `outline_validators.py` — in working dir
- `research_pipeline.py`, `research_validators.py` — in working dir
- `test_research_regressions.py` — in working dir
- Gate scripts in `~/.hermes/scripts/`

## Clinic site mapping

- "Modern Recovery Services" → MRS
- "MRS Arizona" → MRS Arizona
- "Avery's House" → Avery's House
- "Roots Renewal Ranch" → Roots Renewal Ranch

## Client IP boundary (CRITICAL)

- **All pipeline outputs are agency work-for-hire — NOT the user's property:** final articles, runs/ folders, research briefs, clinic_profiles/, and the Desktop "Golden writing framework" workspace (the AGENCY's own project with its AGENTS.md, sales-page system, clinic profiles, etc.).
- **Never** commit client content to any git repo (even private), never use it as portfolio samples, never claim authorship of agency articles.
- Freelance/portfolio proof = fresh demo runs on FICTIONAL clinics + the QA and clinical-review reports. Sell the SYSTEM, not the outputs. Experience line: "operated a 100+ article editorial pipeline for behavioral-health clients."
- The skill file hardcodes client clinic names as defaults (Modern Recovery Services, MRS Arizona, Avery's House, Roots Renewal Ranch) — fine for private use; sanitize to a fictional default clinic before ever sharing the skill or repo publicly.
- Skill location: `~/.hermes/skills/content/article-pipeline/` — NOT on the Desktop. The Desktop only holds the agency workspace + pipeline outputs.

## Pitfalls

- **Stage by stage means ask before EVERY phase transition:** After each phase (ClickUp, Outline, Research, Write, Fix, Edit, GWF), report results and say "Proceed to [next phase]?" Do NOT auto-advance. **This includes sub-stages within editing: after Karpathy edit, show result and ask before running No-AI-Slop.** The user expects a confirmation gate between every stage.
- **V2 versioning (CRITICAL — do NOT replace the original):** When user requests a "v2" of an article or brief, create `{slug}-v2.md` alongside the original. Do NOT overwrite the original file. The user needs to compare versions side by side and explicitly chose versioning over replacement. "Replace" is never the right answer when someone asks for a v2. See `references/v2-versioning.md`.
- **`_safe_cite()` must reject, not dress up garbage (FIXED 2026-07-29):** Now raises ValueError on bad sources. Sources missing APA metadata are silently skipped. See `references/safe-cite-garbage-fix.md`.
- **.edu filter too broad (FIXED 2026-07-29):** Student repository patterns (honorstheses, bitstreams, scholarworks, stars.library, mcnair, jewlscholar, digital.library, /ark:/, academia.edu, /theses/, /dissertations/) are blocked in `_is_trusted_web_source()`. See `references/student-repo-blocklist.md`.
- **Parallel debug dir:** `/tmp/research_debug/` is shared. Verify topic after recovery.
- **Parallel outlines:** SerpAPI free tier may 429. Re-run failed ones solo.
- **Practical/service H3s with no research:** Broader search strategies help. If still failing, merge H3s or skip research.
- **Outline H2 validation:** Stripped H2 fields (prompt change 2026-07-29). Existing outlines fine, new ones have lean format.
- **golden_writer output path:** May go to `output/{slug}-article.md`. Check if article <10k chars.
- **Outline-to-validator sync gap:** Changing outline prompts (e.g. stripping H2 fields) without updating `outline_validators.py` wastes retries. Always patch both files in one change.
- **Dual-concept topics (is depression neurodivergent):** Topics requiring two separate concept groups (like "depression" AND "neurodivergent") are the hardest. The groups check in `_topic_matches_text()` requires BOTH groups to have at least one match. If no sources cover the intersection (common for emerging concepts), research consistently fails. Options: skip research, broaden the outline, or use non-fatal UNVERIFIED fallback.
- **Source signaling language when adding sources to existing articles:** When adding new inline citations to an existing article, match the article's existing citation pattern — natural concept links with no attribution verbs. Do NOT write 'A 2026 study found that...' or '[Research shows](url) that...' Use `[concept name](url)` pattern. No PMID numbers visible in text. Violating this breaks the article's voice. Pair #32 (source-attribution anchor text) was added to Karpathy specifically to catch patterns like 'The [evidence supports X](url)' — the link anchor should be the claim itself, not an attribution wrapper.
- **LLM wraps JSON in markdown code fences (CRITICAL — fixed 2026-07-29):** The LLM frequently wraps its JSON responses in ```json...``` blocks. If this is not stripped before json.loads(), the parse fails silently and the H3 gets 0 sources with no error message. The code in `search_one_section()` strips leading ``` and trailing ``` before parsing. If adding a new LLM call that expects JSON, always include code fence stripping.
- **Parallel debug dir corruption:** Parallel research runs both write to `/tmp/research_debug/`. One overwrites the other's clinical brief. Verify `head -3 /tmp/research_debug/research-brief.md` matches expected topic before finalizing.
- **Non-fatal UNVERIFIED is a band-aid, not a fix:** Making UNVERIFIED non-fatal produces briefs with unverified sections. Fix the source discovery instead.
- **Editor model:** Both write+edit use DeepSeek Flash — same-model editing can't catch own blind spots. Manual deep edit is still needed for subtle patterns: importance puffery ('well established', 'well documented', 'real and meaningful'), throat-clearing ('None of this is meant to scare', 'For some people'), clichés ('gold standard', 'sits at the intersection', 'orbits relationships'), and dramatic fragments ('A flicker. A shape.'). These are partially covered by Karpathy and No-AI-Slop but consistently missed. When the user asks for a final polish, read the article line by line and fix each remaining pattern manually, then re-run Karpathy + No-AI-Slop.
- **Plan before executing:** When user says "lets plan", stop. No subagents or changes until approved.
- **Outline synthesis "reader assumption" failure:** Fixed in prompt. Pass field forbids "The reader recognizes..." patterns.
