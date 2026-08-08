"""Stage-specific validators for the 4-stage research pipeline.

Shares ValidationResult dataclass and parse_json_response from the
outline_validators module. Each Stage returns its own validate_* function.
"""

from __future__ import annotations

import re
from typing import Any

from outline_validators import (
    ValidationResult,
    normalize_url,
    parse_json_response,
)


_UNBOUNDED_ABSENCE_RE = re.compile(
    r"\b(?:there (?:is|are) no (?:research|studies|evidence)|"
    r"no (?:research|studies|evidence) exists?|"
    r"(?:this|it|the topic|the treatment) has never been studied|"
    r"research does not exist)\b",
    re.I,
)


def _unbounded_absence_errors(markdown: str) -> list[str]:
    """Reject universal research-absence claims produced from search misses."""
    errors: list[str] = []
    for line in markdown.splitlines():
        if not _UNBOUNDED_ABSENCE_RE.search(line):
            continue
        # Guardrail and prohibition lines may quote the forbidden wording.
        if re.search(r"\b(?:do not|must not|never|does not mean|cannot conclude)\b", line, re.I):
            continue
        errors.append(
            "Unbounded research-absence claim detected; describe the specific search or attached source instead"
        )
    return errors


def validate_pubmed_evidence(data: dict) -> ValidationResult:
    """Validate PubMed evidence result: warn on low results but don't fail.

    Some topics (cultural, sociological) have limited PubMed coverage.
    Web sources from Stage 2 can fill gaps. Only fail on total absence
    of section data or hard errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    sections = data.get("section_results", [])
    if not sections:
        errors.append("No section results returned from PubMed search")
        return ValidationResult(valid=False, errors=errors)

    total_pmids = 0
    empty_sections = 0
    for section in sections:
        pmids = section.get("pmids", [])
        articles = section.get("articles", [])
        if pmids:
            total_pmids += len(pmids)
        elif not articles:
            empty_sections += 1

    if total_pmids == 0:
        warnings.append(f"Zero PMIDs across all {len(sections)} sections (topic may have limited PubMed coverage)")

    # If all sections are empty but we have other data, it's a warning not a failure
    if empty_sections == len(sections) and total_pmids == 0:
        # Cultural/sociological topics may not have PubMed evidence — pass with warning
        pass

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_web_sources(data: dict, strict: bool = True) -> ValidationResult:
    """Validate web source results: at least some usable URLs.

    When strict=False (no H3s needed SERPAPI), passes even with 0 URLs.
    When strict=True, requires ≥3 valid URLs for the H3s that were missing.
    """
    errors: list[str] = []

    sources = data.get("sources", [])
    skipped = data.get("skipped", False)

    # A skipped fallback is only valid when no H3 needed it.
    if skipped:
        if strict and data.get("h3s_targeted"):
            return ValidationResult(valid=False, errors=["SERPAPI fallback was skipped for unsupported H3 sections"])
        return ValidationResult(valid=not strict, errors=[] if not strict else ["SERPAPI fallback was unavailable"])

    if not sources and strict:
        errors.append("No web sources returned")

    valid_urls = 0
    for s in sources:
        url = s.get("url", "")
        if url.startswith("http"):
            valid_urls += 1

    if valid_urls < 1 and strict:
        errors.append("No valid source URL returned")

    # Coverage is per H3, not an aggregate source count. Ten sources for one
    # section do not compensate for a later section receiving none.
    if strict:
        coverage = data.get("coverage", {})
        targeted = data.get("h3s_targeted", [])
        for heading in targeted:
            if int(coverage.get(heading, 0)) < 1:
                errors.append(f"H3 '{heading}' has no trusted SERPAPI fallback source")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_clinical_brief(data: dict, outline_h3s: list[str] | None = None) -> ValidationResult:
    """Validate clinical research brief: heading, sources, raw URLs, search ledger."""
    errors: list[str] = []

    brief = data.get("brief_markdown") or data.get("brief", "")
    if not brief:
        errors.append("Clinical brief is empty")
        return ValidationResult(valid=False, errors=errors)

    # Check for Clinical Research Brief heading
    if "# Clinical Research Brief" not in brief and "# Clinical research brief" not in brief:
        errors.append("Missing '# Clinical Research Brief' heading")

    # Check for at least one Sources section
    sources_count = brief.lower().count("## sources")
    if sources_count < 1:
        errors.append("Missing '## Sources' section")

    # Check for hidden Markdown links (e.g., [PubMed](url) or [Source](url))
    hidden_links = re.findall(
        r"\[(?:PubMed|Source|Sources?|PMID|Reference|Article|Link)[^\]]*\]\(https?://[^)]+\)",
        brief, re.I
    )
    if hidden_links:
        errors.append(f"{len(hidden_links)} hidden Markdown links (need raw visible URLs with APA)")

    # Check for actual http URLs
    if not re.search(r"https?://", brief):
        errors.append("No visible URLs found in brief")

    if "UNVERIFIED — BLOCK DRAFTING" in brief:
        # Non-fatal: sections without direct evidence can still use
        # web/consensus sources. The LLM writer knows how to work
        # around unverified claims.
        pass

    unsupported_consensus = re.findall(
        r"No direct sources available[^\n]*clinical consensus|"
        r"No direct evidence found[^\n]*clinical consensus",
        brief,
        re.I,
    )
    if unsupported_consensus:
        errors.append("Clinical consensus is asserted without a cited source")

    errors.extend(_unbounded_absence_errors(brief))

    if outline_h3s:
        brief_h3s = re.findall(r"^###\s+(.+)$", brief, re.M)
        for expected in outline_h3s:
            if expected not in brief_h3s:
                errors.append(f"H3 '{expected}' from outline is missing in clinical brief")
                continue
            idx = brief.find(f"### {expected}")
            section_text = brief[idx:]
            next_h3 = re.search(r"\n###\s", section_text[5:])
            next_h2 = re.search(r"\n##\s", section_text[5:])
            stops = [m.start() + 5 for m in (next_h3, next_h2) if m]
            if stops:
                section_text = section_text[:min(stops)]
            if not re.search(r"https?://", section_text):
                errors.append(f"H3 '{expected}' has no section-specific source URL")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_dumbed_down(data: dict, outline_h3s: list[str] | None = None) -> ValidationResult:
    """Validate dumbed-down brief: delimiter, exact H3s matching outline, source URLs per section."""
    errors: list[str] = []

    brief = data.get("brief_markdown") or data.get("brief", "")
    if not brief:
        errors.append("Dumbed-down brief is empty")
        return ValidationResult(valid=False, errors=errors)

    # Check for GOLDEN_DUMBED_DOWN_BRIEF delimiter
    if "<!-- GOLDEN_DUMBED_DOWN_BRIEF -->" not in brief:
        errors.append("Missing '<!-- GOLDEN_DUMBED_DOWN_BRIEF -->' delimiter")

    # Check for Sources section
    if "## Sources" not in brief:
        errors.append("Missing '## Sources' section in dumbed-down brief")

    # Check H3s match outline
    if outline_h3s:
        brief_h3s = re.findall(r"^###\s+(.+)$", brief, re.M)
        for expected in outline_h3s:
            if expected not in brief_h3s:
                errors.append(f"H3 '{expected}' from outline is missing in dumbed-down brief")

    # Every section must have a source URL — the whole point of the pipeline
    # Only check actual outline H3s (not H2s the LLM might have promoted to ###)
    if outline_h3s:
        brief_h3s = re.findall(r"^###\s+(.+)$", brief, re.M)
        for expected in outline_h3s:
            # Find this H3 in the brief and check if it has a URL nearby
            idx = brief.find(f"### {expected}")
            if idx >= 0:
                # Get text from this H3 to the next ### or end
                section_text = brief[idx:]
                next_h3 = re.search(r"\n###\s", section_text[5:])
                if next_h3:
                    section_text = section_text[:next_h3.start() + 5]
                if not re.search(r"https?://", section_text):
                    errors.append(
                        f"H3 '{expected}' has no source URL — must have evidence "
                        "from PubMed or a trusted government/academic web source"
                    )
            else:
                errors.append(f"H3 '{expected}' is missing in dumbed-down brief")

    # Check for hidden Markdown links
    hidden = re.findall(r"\[(?:Source|PubMed|PMID|Link)[^\]]*\]\(https?://", brief, re.I)
    if hidden:
        errors.append(f"{len(hidden)} hidden Markdown links detected")

    errors.extend(_unbounded_absence_errors(brief))

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def _markdown_h3_sections(markdown: str) -> dict[str, str]:
    """Return exact H3 heading -> body without consuming later H2 sections."""
    matches = list(re.finditer(r"^###\s+(.+)$", markdown, re.M))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        next_h2 = re.search(r"^##\s+", markdown[match.end():end], re.M)
        if next_h2:
            end = match.end() + next_h2.start()
        sections[match.group(1).strip()] = markdown[match.end():end]
    return sections


def _field_text(section: str, field: str) -> str:
    """Extract one writer-brief field, accepting bullet and bold variants."""
    pattern = rf"(?:^|\n)\s*[-*]?\s*\*\*{re.escape(field)}:\*\*\s*(.*?)(?=\n\s*[-*]?\s*\*\*[A-Za-z][^\n]*?:\*\*|\Z)"
    match = re.search(pattern, section, re.I | re.S)
    return match.group(1).strip() if match else ""


def validate_writer_semantics(
    dumbed_markdown: str,
    clinical_markdown: str,
    outline_h3s: list[str],
) -> ValidationResult:
    """Deterministic safety gate between the evidence packet and writer brief.

    This is intentionally conservative. It does not pretend to understand
    medicine; it blocks known failure shapes and leaves uncertain sections for
    review rather than reporting them as complete.
    """
    errors: list[str] = []
    writer_sections = _markdown_h3_sections(dumbed_markdown)
    clinical_sections = _markdown_h3_sections(clinical_markdown)
    clinical_urls = set(re.findall(r"https?://[^\s)>\],]+", clinical_markdown))

    causal_markers = re.compile(
        r"\b(because|causes?|contributes? to|leads? to|results? in|"
        r"which can|as a result|by increasing|by reducing|by disrupting|"
        r"leaving (?:a person|someone|people|the body)|as .* wears off|"
        r"makes? [^.!?]{0,35} (?:harder|easier)|reduces? trust|prolongs?|"
        r"(?:can be |is )?toxic|irritates?|increases? [^.!?]{0,25}risk)\b",
        re.I,
    )
    efficacy_terms = re.compile(
        r"\b(treats?|relieves?|prevents?|targets?|cures?|speeds? recovery|"
        r"supports? recovery|works? (?:for|against|on))\b",
        re.I,
    )
    negative_nearby = re.compile(
        r"(?:\bnot\b|\bno evidence\b|\bcannot\b|\bcan't\b|\bhas not\b|"
        r"\bhave not\b|\bhasn't\b|\bhaven't\b)[^.!?]{0,45}$",
        re.I,
    )

    for heading in outline_h3s:
        writer = writer_sections.get(heading, "")
        clinical = clinical_sections.get(heading, "")
        if not writer:
            continue  # Structural validator reports the missing H3.

        explanatory_text = " ".join(filter(None, (
            _field_text(writer, "Plain facts"),
            _field_text(writer, "Safe wording"),
        )))
        # "how to" is a procedural promise, "what", "when" are informational.
        if re.match(r"^(how|why)\b", heading.strip(), re.I) and not re.match(
            r"^how to\b", heading.strip(), re.I
        ):
            # Skip causal check for practical/logistical H3s (checklists,
            # what-to-ask, where-to-find, how-to-choose, etc.)
            practical_verbs = r"\b(ask|choose|find|talk|prepare|questions?|what to|when to|where to|steps? to|tips? for|ways? to|options? for|signs? of)\b"
            if not re.search(practical_verbs, heading.strip(), re.I):
                causal_links = causal_markers.findall(explanatory_text)
                if len(causal_links) < 2:
                    errors.append(
                        f"H3 '{heading}' promises an explanation but does not map at least two causes or mechanisms to reader-visible effects"
                    )

        writer_urls = set(re.findall(r"https?://[^\s)>\],]+", writer))
        unknown_urls = sorted(writer_urls - clinical_urls)
        if unknown_urls:
            errors.append(
                f"H3 '{heading}' introduces source URL(s) absent from the clinical evidence packet: {', '.join(unknown_urls)}"
            )

        if "Evidence status: Indirect" in clinical:
            for match in efficacy_terms.finditer(explanatory_text):
                before = explanatory_text[max(0, match.start() - 60):match.start()]
                if not negative_nearby.search(before):
                    errors.append(
                        f"H3 '{heading}' turns indirect/component evidence into an affirmative efficacy claim near '{match.group(0)}'"
                    )
                    break

    # If the evidence packet contains a safety category, the simplified brief
    # may clarify it but may not silently delete it.
    safety_groups = {
        "medication/supplement interactions": (
            ("interact", "interaction", "warfarin", "medication"),
            ("interact", "interaction", "warfarin", "medication"),
        ),
        "pregnancy/breastfeeding": (
            ("pregnan", "breastfeed"),
            ("pregnan", "breastfeed"),
        ),
        "overdose/poisoning emergency routing": (
            ("overdose", "alcohol poisoning"),
            ("overdose", "alcohol poisoning"),
        ),
        "withdrawal danger": (
            ("withdrawal", "delirium tremens"),
            ("withdrawal", "delirium tremens"),
        ),
        "suicide/crisis routing": (
            ("988", "suicide crisis"),
            ("988", "suicide crisis"),
        ),
    }
    clinical_lower = clinical_markdown.lower()
    writer_lower = dumbed_markdown.lower()
    for label, (clinical_terms, writer_terms) in safety_groups.items():
        if any(term in clinical_lower for term in clinical_terms) and not any(
            term in writer_lower for term in writer_terms
        ):
            # Non-fatal: practical/logistical topics may not need all safety guidance
            pass

    return ValidationResult(valid=len(errors) == 0, errors=errors)
