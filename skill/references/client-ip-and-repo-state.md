# Client IP & Repo State (checked 2026-08-08)

## Repo audit — github.com/oghenemaga/article-pipeline (PRIVATE)
- One commit: "Article pipeline: ClickUp → Outline → Research → Write → Fix → Edit → GWF"; pushed from /Users/mac/Documents/Codex/2026-07-14/ca/local_worker
- CONTAINS CLIENT WORK PRODUCT (bad): runs/ (202 tracked files incl. client articles like native-american-substance-abuse, teen-self-harm, bpd-hallucinations), clinic_profiles/ (modern_recovery_services.json, averys_house.json, roots_renewal_ranch.json), avery-house-output/, anxiety-output/, exam-anxiety-output/
- JUNK: .research_cache/ PubMed JSON blobs, .backups/, __pycache__/, *.bak, *.db — and NO .gitignore
- MISSING (uncommitted/untracked): clinical_review_gate.py, tone_edit_article.sh, modified research_pipeline.py / editorial_karpathy.md / run_article.sh / test_research_regressions.py
- LEGACY dashboard-era files tracked: app.py, dashboard.py, server.py, worker.py, clickup_delivery.py, index.html, pipeline.py, run.py

## Current vs legacy process
- CURRENT (user's words): paste topics in chat → agent loads article-pipeline skill → runs stages in PARALLEL across topics (ClickUp → Outline → Research → Write → Fix → Edit → GWF) with a confirmation gate after every stage. No dashboard. Scripts: local_worker + ~/.hermes/scripts. Skill: ~/.hermes/skills/content/article-pipeline/ (NOT on the Desktop).
- LEGACY: dashboard UI process (the app.py/dashboard.py/server.py family). Retired.

## Desktop "Golden writing framework" = AGENCY workspace
- The Desktop folder is the AGENCY's project: its own AGENTS.md router, Active/Skills/ (golden-masterpiece-article, golden-batch-orchestrator, golden-clinic-sales-page), sales-page system, clinic profiles, STYLE_RUBRIC, etc. Treat everything in it as client property.
- The user's OWN tooling lives under ~/.hermes/ (skills/, scripts/). Keep these two worlds separate in reasoning.

## Cleanup options (user decision pending as of 2026-08-08)
1. Fresh repo matching current process (recommended): delete old repo (GitHub keeps deleted repos recoverable ~90 days), create new repo = skill folder + current scripts + chat-workflow README. Client content never enters it; no history scrub needed.
2. Surgical cleanup: .gitignore (runs/, *-output/, clinic_profiles/, .research_cache/, __pycache__, *.db, *.bak, *.pyc) + `git rm --cached` client folders (keeps files on disk) + commit new scripts. Caveat: client content stays in git HISTORY (fine while private; blocks public without history rewrite).
3. Do nothing: repo stays private/stale; dormant exposure, not active.

## Freelancing positioning rules (durable — from 2026-08-08 session)
- GWF articles are work-for-hire for the agency — NOT the user's to show. Never use them as portfolio samples, never claim authorship, never commit to repos (even private).
- Sell the SYSTEM, not outputs: "I built and operated a full editorial pipeline for behavioral-health clients — 100+ articles, clinically reviewed."
- Portfolio = fresh demo runs on FICTIONAL clinics + QA report + clinical-review report as proof of process.
- Risk-reversal offers that worked in discussion: free 300-word rewrite of the prospect's own article with citations shown; free 5-page SEO/content audit; one-article fixed-price trial with capped revisions.
- Public code proof (if ever wanted): separate sanitized demo repo with fictional clinic + sanitized skill (no client clinic names). The skill hardcodes client clinic names (Modern Recovery Services, MRS Arizona, Avery's House, Roots Renewal Ranch) — strip before sharing.
- 2026 market note: generic article writing is a race to the bottom; defensible niches are health/medical content with real citations, AI-slop rescue/rewrite, and content audits. Upwork = proposals with proof; Fiverr = 3-tier gig packages, eat the 20% fee early for reviews.
