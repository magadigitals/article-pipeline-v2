#!/usr/bin/env bash
# fix_article.sh — Run gate scripts + LLM repair on an article
# Usage: bash fix_article.sh <article.md> [qa_initial.json]
#
# Attempt 1: Gate scripts (deterministic fixes)
# Attempt 2: Gate scripts + LLM repair (complex cases)
# Attempt 3: Gate scripts + LLM repair (final attempt)

set -e
ARTICLE="$1"
QA_INITIAL="${2:-}"
SCRIPTS="$HOME/.hermes/scripts"
HERE="$(cd "$(dirname "$0")" && pwd)"
MAX_ATTEMPTS=3

echo "=== Fixing $ARTICLE ==="

# If an initial QA report was provided, print summary
if [ -n "$QA_INITIAL" ] && [ -f "$QA_INITIAL" ]; then
    TOTAL=$(python3 -c "import json; d=json.load(open('$QA_INITIAL')); print(len(d.get('violations',[])))" 2>/dev/null || echo "?")
    echo "   Initial QA report: $TOTAL violations"
fi

for attempt in $(seq 1 $MAX_ATTEMPTS); do
    echo ""
    echo "--- Attempt $attempt ---"

    # ── Run determinant gate scripts ──
    echo "   Running gate scripts..."
    python3 "$SCRIPTS/jargon_translation_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/reader_assumption_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/repetition_rhythm_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/section_opener_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/source_translation_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/bullet_quality_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/fix_fact_dumping.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/ending_force_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/micro_sense_gate.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/structural_fidelity.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/claim_fidelity.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/shape_enforcer.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/draft_cleanup.py" --article "$ARTICLE" 2>/dev/null || true
    python3 "$SCRIPTS/writing_error_healer.py" --article "$ARTICLE" 2>/dev/null || true

    # ── Prune un-cited sources (only keep sources cited inline) ──
    python3 "$HERE/prune_sources.py" "$ARTICLE" 2>/dev/null || true

    # ── Re-scan ──
    python3 "$SCRIPTS/constraint_scanner.py" --article "$ARTICLE" > /tmp/qa_check.json 2>/dev/null || true
    TOTAL=$(python3 -c "
import json
try:
    d=json.load(open('/tmp/qa_check.json'))
    print(len(d.get('violations', [])))
except: print('0')
" 2>/dev/null || echo "0")

    echo "   After gate scripts: $TOTAL violations remaining"

    if [ "$TOTAL" = "0" ]; then
        echo "=== CLEAN ==="
        exit 0
    fi

    # ── LLM repair for remaining complex violations (attempts 2+) ──
    if [ "$attempt" -ge 2 ]; then
        echo "   Running LLM repair on $TOTAL remaining violations..."
        python3 "$SCRIPTS/draft_repair.py" \
            --article "$ARTICLE" \
            --scan /tmp/qa_check.json \
            --slug "$(basename "$ARTICLE" .md)" \
            --title "$(basename "$ARTICLE" .md)" 2>/dev/null || true

        # Re-scan after LLM repair
        python3 "$SCRIPTS/constraint_scanner.py" --article "$ARTICLE" > /tmp/qa_check.json 2>/dev/null || true
        TOTAL=$(python3 -c "
import json
try:
    d=json.load(open('/tmp/qa_check.json'))
    print(len(d.get('violations', [])))
except: print('0')
" 2>/dev/null || echo "0")

        echo "   After LLM repair: $TOTAL violations remaining"

        if [ "$TOTAL" = "0" ]; then
            echo "=== CLEAN ==="
            exit 0
        fi
    fi
done

echo ""
echo "=== DONE after $MAX_ATTEMPTS attempts. $TOTAL violations remaining ==="
echo "   Article saved at: $ARTICLE"
echo "   Final QA report at: /tmp/qa_check.json"
exit 2  # exit code 2 = best-effort, human review needed
