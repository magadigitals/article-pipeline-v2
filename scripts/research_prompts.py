"""Narrow prompts for Stage 3 (clinical brief) and Stage 4 (dumbed-down) of the research pipeline.

Stages 1 and 2 are deterministic Python — no prompts needed.
"""

# ─── Stage 3: Clinical Research Brief ─────────────────────────────────────

CLINICAL_BRIEF_PROMPT = """Write a Clinical Research Brief from the approved outline and evidence below.

OUTLINE (headings only — do not change):
{outline}

AVAILABLE EVIDENCE:

PUBMED STUDIES (per-section):
{pubmed_evidence}

GOVERNMENT AND CLINICAL SOURCES (grouped by section — each has a source type in brackets like [CDC], [NIH], [NAMI], [State education guidance], etc. These are authoritative clinical consensus sources):
{supplementary_sources}

OUTPUT FORMAT (strict):

# Clinical Research Brief: [Topic]

For each H3 section from the outline (use the EXACT same H3 heading):
### [H3 heading]
- **Claim boundary:** [one sentence]
- **Safety boundary:** [one sentence]
- **Key studies:**
  - PMID 1234567 (Author, Year): [one-sentence finding]. https://pubmed.ncbi.nlm.nih.gov/1234567/
  - [Source type] — [one-sentence finding]. [raw URL]
- **Strength:** [Strong/Moderate/Limited/None]

Then:
## Sources
- Author, A. (Year). Title. *Journal*, Volume(Issue), Pages. https://doi.org/xxx
- Author, A. (Year). Title. *Journal*. https://pubmed.ncbi.nlm.nih.gov/xxxxx/
- Organization. (Year). *Title*. https://www.gov-url/

RULES:
- Every source must be in APA 7th edition format: Author. (Year). *Title*. Source. URL
- For PubMed: use Author, A. (Year). *Title in italics*. Journal Name. URL — no "PMC" or "repository copy" in the citation
- For .gov/.edu: use Organization Name. (Year). *Title*. URL
- Raw visible URLs. No [PubMed](url) or [Source](url) hiding.
- No "University or academic resource (n.d.)" — use the actual institution name
- No "PubMed Central repository copy" — use the journal or publisher name
- No "Unknown safety and efficacy" as a title — use the actual article title
- Sources must be in a single alphabetical list A-Z by first author's last name (or organization name). No sub-grouping.
"""

# ─── Stage 4: Dumbed-Down Brief ──────────────────────────────────────────

DUMBED_DOWN_PROMPT = """Read the research brief below. Rewrite it at Grade 8 reading level — the language a smart 13-year-old or a parent at a coffee shop would understand immediately.

RESEARCH BRIEF:
{research_brief}

CRITICAL RULES:
1. PRESERVE EVERY H3 sub-section from the research brief. Do NOT merge, flatten, skip, or reorder any H3.
2. Each H3 block gets its OWN Source URLs field — only sources that support THAT sub-section's claims.
3. Keep EVERY PubMed URL and government source URL exactly as-is.
4. Preserve every claim accurately — just say it in plain words.
5. Replace jargon with plain English.
6. Every H2 section must have a short framing paragraph (1-2 sentences) before its H3 blocks.
7. Make every sentence pass the 'parent at a coffee shop' test.
8. Do NOT add new information or remove approved claims.
9. Remove research-method labels and source-led wording. Never write 'research shows', 'studies find', 'evidence suggests', 'the evidence is limited', 'the evidence is mixed'. If you write 'the evidence says' anything, stop and rewrite — say what the finding is instead.
10. Every H3 block MUST have a Lead URL field with a single raw URL. No exceptions. The writer needs this to add hyperlinks. If you skip it, the article will have no citations.
11. Do not search the web. Use only the evidence provided in the research brief above.
12. **A source being listed in CAN CLAIM does not mean it's the best source for that section.** Use your judgment to pick the most relevant sources for each section's specific claims. Government and clinical sources (CDC, NIH, NIMH, NAMI, etc.) carry guideline-level authority.
13. **Return ONLY the markdown brief. Do NOT save to any file. Do NOT explain what you did.** Output must start with `# Dumbed-Down Research Brief:` on the very first line. No preamble, no commentary, no file saving.
14. Put `<!-- GOLDEN_DUMBED_DOWN_BRIEF -->` on the second line, exactly as written.
15. Preserve evidence class exactly. `Indirect component-supported` means the source supports only an ingredient, symptom, warning sign, or care option in another context. It does NOT prove efficacy for the article's main condition.
16. Never turn traditional use, biological plausibility, a source title, or evidence from another condition into `may help`, `targets`, `supports recovery`, `works best`, `protects`, or `is generally safe` for the article topic.
17. Preserve every medication interaction, supplement warning, pregnancy/breastfeeding qualifier, poisoning/overdose instruction, withdrawal warning, and emergency route from the clinical brief.

OUTPUT TEMPLATE (strict):

# Dumbed-Down Research Brief: [Topic]
<!-- GOLDEN_DUMBED_DOWN_BRIEF -->

## What the article must do

* **Main point:** [One plain sentence that states the article's central idea.]
* **Reader need:** [What the reader should understand or be able to do.]
* **Important difference:** [A distinction the writer must keep clear.]

## Claim and safety boundaries

* **The article may say:** [Plain-English claims supported by the research brief.]
* **The article must not say:** [Unsupported, absolute, or unsafe claims.]
* **Use this safety wording:** [Exact action language for urgent risks, when relevant.]

## [H2 section heading from outline]

[One or two plain-language sentences framing this section.]

### [H3 sub-section from outline]

* **Reader job:** [What this sub-section helps the reader understand or decide.]
* **Lead URL:** [The single best URL for this section's main claim. URL ONLY — no citation text, no author names. Pick the most relevant source from the research brief.]
* **Plain facts:** [All approved facts in short, direct Grade 8 language.]
* **Everyday example:** [A concrete daily-life example tied to this sub-section's claims.]
* **Safe wording:** [Reader-ready wording with the correct claim strength.]
* **Do not overclaim:** [The exact boundary the writer must preserve.]
* **Source URLs:** [First URL = Lead source from the research brief, then supplementary sources. If Lead source is empty, list sources by relevance. Only sources that support THIS sub-section's claims.]

[Repeat H3 block for every H3 in this H2 section. Do not skip any.]

[Repeat H2+H3 block for every H2 section. Do not skip any.]

## Sources

[Copy the complete APA 7 Sources section from the research brief verbatim. Every source cited in any H3 block above must appear here exactly once.]"""
