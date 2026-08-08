# Tone Edit Script (No-AI-Slop integration)

**Script:** `tone_edit_article.sh` in working dir and `~/.hermes/scripts/tone_edit_article.sh`

**Purpose:** Phase 6b — runs after Karpathy edits to tighten prose using the no-ai-slop editing rules while preserving structural safety elements.

## How it works

1. Uses `hermes chat -q` (same reliable pattern as `edit_article.sh`) — reads the file, edits in-place, saves.
2. Loads the no-ai-slop skill for editing rules.
3. Structural safety instructions embedded in the prompt:
   - Crisis response chain (988, 911, emergency room) — do not touch
   - Bridge-to-care closing — do not collapse into a bullet
   - All inline links (DOI, PMC, MRS) — do not remove or restructure
   - H2/H3 headings — may reword but never remove
   - Sources section entries — formatting only, never merge or collapse
   - YAML frontmatter — do not modify
   - Key Takeaways — do not collapse into prose

## Output

Hermes edits the file in-place and reports what changed. No summary table appended (the `hermes chat -q` approach outputs results to stdout, not a separate file).

## Running standalone

```bash
bash ~/.hermes/scripts/tone_edit_article.sh "runs/{slug}/article.md"
```

Or directly:

```bash
hermes chat -q "Load the no-ai-slop skill. Edit the article at /path/to/article.md for tone and slop removal. [structural safety instructions]. Edit the file in-place and save it." -s no-ai-slop
```

## Avoiding conda noise

Using `hermes chat -q` (persistent session mode) avoids shell init overhead entirely and doesn't trigger conda plugin errors. This is the recommended approach over `hermes -z` one-shot mode which inherits the shell's conda init scripts.

## Structural safety enforcement

The hard constraint is in the prompt, not the code — the chat command embeds a 7-item do-not-touch list in the Hermes instruction. The no-ai-slop skill also has its own structural safety section in SKILL.md. Both must agree. If a structural element gets modified despite the instructions, fix the prompt text, not the script — prompt changes are cheaper.

## Pitfalls

- **Do NOT pipe article content via heredoc.** The heredoc approach (`cat <<HEREDOC ... $CONTENT ... HEREDOC`) introduces quoting bugs, variable expansion issues, and conda noise. Use `hermes chat -q` with the file path instead — Hermes reads the file itself.
- **No-AI-Slop can strip links if structural safety rules are not explicit enough.** Always include the full 7-item do-not-touch list in the prompt. If links are stripped, the prompt was too weak — add explicit protection for "modernrecoveryservices.com URLs."
- **Show Karpathy result before running No-AI-Slop.** Do not auto-advance. The user must approve the Karpathy-edited article before the tone pass runs.
