#!/usr/bin/env bash
# edit_article.sh — Apply 30 editorial Karpathy pairs to an article
# Usage: bash edit_article.sh <article.md>
#
# One LLM call with ~200 lines of WRONG/RIGHT examples.
# Follows all 30 pairs because examples are sharper than rules.
# Preserves all clinical facts, SEO, links, sources, metadata.

set -e
ARTICLE="$1"
KARPATHY="/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/editorial_karpathy.md"

if [ -z "$ARTICLE" ] || [ ! -f "$ARTICLE" ]; then
    echo "Usage: bash edit_article.sh <article.md>"
    exit 1
fi

echo "=== Editorial Edit (30 Karpathy pairs) ==="
echo "  Article: $ARTICLE"
echo ""

PAIRS=$(cat "$KARPATHY")

hermes chat -q "Apply all 30 editorial Karpathy pairs below to the article at $ARTICLE.

$PAIRS

Article at: $ARTICLE

Read the article. For each WRONG pattern found, replace with the RIGHT version. Then re-read. Stop when every sentence reads naturally. Preserve ALL facts, links, sources, headings, and SEO metadata. Overwrite the file at $ARTICLE with the edited version." \
  -m deepseek-v4-flash --provider deepseek
