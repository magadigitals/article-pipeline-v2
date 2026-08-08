# No-AI-Slop Structural Safety Rules (updated 2026-07-30)

## Bridge-to-care rule (CRITICAL — softened this session)

**Previous rule:** "Do NOT modify the bridge-to-care closing paragraph. Its meaning, length, and standalone paragraph status must be preserved exactly."

**Problem:** This was too strict. The editor couldn't tighten or improve the bridge-to-care prose, leaving filler and source-signaling language intact. The user explicitly asked to edit the bridge-to-care for tone and clarity.

**Current rule:** "You MAY edit the bridge-to-care for tone and clarity — tighten, reword, remove filler — but KEEP it as a standalone closing paragraph. Do NOT collapse it into a bullet point, merge it with another paragraph, or delete it."

## All structural safety elements

1. **Bridge-to-care closing** — editable for tone, must remain standalone paragraph
2. **Crisis response chain** (988, 911, emergency room, call or text) — untouched
3. **Inline links** (DOI, PMC, PubMed, internal clinic URLs) — not removed or altered
4. **H2 and H3 headings** — not removed or merged; may reword for clarity
5. **Sources section entries** — formatting only, never collapse or merge
6. **YAML frontmatter** — untouched
7. **Key Takeaways bullet list** — not collapsed into prose

## Edit-in-place rule (added 2026-07-30)

The no-ai-slop skill now has a "How to edit" section that explicitly says:
- Edit the file at the provided path directly — do not ask for the article
- Save to the SAME file — never create separate output files
- Do not make structural changes — structural safety rules are hard constraints
