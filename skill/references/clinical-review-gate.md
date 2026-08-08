# Clinical Review Gate

Added 2026-07-29 as an optional post-edit QA step. Script: `clinical_review_gate.py` in the working dir.

## Purpose

Catches what automated fix gates and Karpathy edits cannot: clinical inaccuracy. The script reads the article, resolves inline DOIs/PMC URLs to abstracts via Crossref and NCBI E-utilities, and sends one bounded LLM call to check:

1. **Claim-source mismatch** — Does the cited source actually say what the article claims it says?
2. **Efficacy overstatement** — "treats" vs "may help", "cures" vs "reduces symptoms"
3. **Missing caveats** — Risks, side effects, or limitations not mentioned alongside treatment claims
4. **Safety gaps** — Crisis resources missing from sections discussing severe symptoms or suicidal ideation
5. **Dual-concept confusion** — Two distinct conditions treated as identical when sources distinguish them

## Usage

```bash
python3 clinical_review_gate.py "runs/{slug}/article.md" --output "runs/{slug}/clinical-review.json"
```

## Output

JSON report with:
- `verdict`: `"PASS"` | `"WARN"` | `"FLAG"`
- `flags[]`: Array of issues found, each with `severity` (CRITICAL/MODERATE/INFO), `section`, `issue`, `recommendation`
- `summary`: One-sentence verdict for a human editor
- Metadata: `article_path`, `topic`, `citations_found`, `citations_resolved`

## Integration

Not yet wired into `fix_article.sh`. Run manually as a QA step after Edit, before publishing.

## Limitations

- Cannot resolve all DOIs to full abstracts — some paywalled sources return titles only
- LLM is the same model family as the writer+editor (DeepSeek V4 Flash) — same blind spots
- Internal MRS links are excluded from citation checking
