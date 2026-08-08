# Content Update Tool — Design (2026-07-30)

## Purpose
One command, one output file. Takes a URL or `.md` path, produces an improved version in `GWF/content-update/{slug}.md`.

## Phases
### Phase 0: Gap Analysis (free, no API)
1. DDG search for article's main keyword
2. Scrape top 5 results → extract H2s/H3s (reuse preflight scraper)
3. Compare against article's existing H2s → build gap list
4. One LLM call decides for each missing heading:
   → Belongs in existing H3 prose → weave keyword sentence
   → Needs new H3 → research + write section
   → Already covered → skip

### Phase 1: Content Audit
Parse article into H2/H3 sections. For each:
- RED: section has claims but no inline citations → research needed
- RED: claim has no supporting source in Sources list → research needed
- YELLOW: inline link anchor text doesn't describe source → fix anchor
- YELLOW: source in Sources never cited inline → remove or cite

### Phase 2: Research (Auto-Fix for RED flags)
Same PhD-level pipeline research (LLM Boolean queries → PubMed → DDG).
Stage 2c verifier catches wrong-subtype sources.
Returns best 1-2 sources + APA citation.

### Phase 3: Rewrite + Output
- Rewrite RED sections with proper citations (no source-signaling language)
- Write new H3s for gaps identified in Phase 0
- Fix YELLOW anchor text
- Run Karpathy 31 pairs + No-AI-Slop tone pass
- Save to GWF/content-update/{slug}.md

## Key rules
- No DataForSEO until account is funded ($50 min)
- Keywords woven into prose must sound natural — no stuffing
- Edit passes must not strip added keywords
- Uses same pipeline quality standard (Karpathy + No-AI-Slop)
- Source citations follow natural concept link pattern (no signaling language)

## Scripts needed
1. `phase0_gap_analysis.py` (~50 lines) — reuse preflight scraper
2. `phase1_audit.py` (~100 lines) — parse + flag
3. `phase2_research.py` (~80 lines) — call existing research pipeline
4. `phase3_fix.py` (~120 lines) — rewrite + apply
5. `content_update.sh` (~20 lines) — orchestrator

## Status
NOT YET BUILT. Design approved, scripts not written. Blocked on time allocation.
