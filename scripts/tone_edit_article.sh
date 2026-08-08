#!/usr/bin/env bash
# tone_edit_article.sh — Phase 6b: No-AI-Slop tone pass after Karpathy edits.
# Usage: bash tone_edit_article.sh <article.md>

set -euo pipefail
ARTICLE="${1:?Usage: $0 <article.md>}"
[ -f "$ARTICLE" ] || { echo "File not found: $ARTICLE"; exit 1; }

echo "=== No-AI-Slop Tone Edit ==="
echo "  Article: $ARTICLE"
echo ""

hermes chat -q "Load the no-ai-slop skill. Edit the article at $ARTICLE for tone, voice, and slop removal.

CRITICAL — do NOT modify these structural elements:
1. Crisis response chain — any line with \"988\", \"911\", \"emergency room\", \"call or text\" at the top
2. Bridge-to-care closing paragraph — standalone paragraph at end inviting reader to reach out. Do NOT collapse into a bullet.
3. Inline links — all DOI, PMC, PubMed, and internal clinic URLs. Do not remove or alter.
4. All H2 and H3 headings — do not remove or merge sections
5. Sources section entries — do not collapse, merge, or remove spacing between entries
6. YAML frontmatter (the --- block at top) — do not modify
7. Key Takeaways bullet list — do not collapse into prose

Edit the file in-place and save it." \
  -s no-ai-slop \
  -m deepseek-v4-flash --provider deepseek
