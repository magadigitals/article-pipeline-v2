"""Stage-specific validators for the 3-stage outline pipeline.

Each validate_* function returns a ValidationResult with valid bool and
errors list. Separate invocation failures from validation failures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from outline_models import (
    Competitor,
    ExtractionResult,
    OutlineResult,
    SourceDiscoveryResult,
)


# ─── Helpers ───────────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication: lowercase, strip www, remove trailing slash."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


def parse_json_response(raw: str) -> dict:
    """Parse JSON from LLM output, handling fenced blocks and trailing text.

    Strategy: find the first '{' and last '}' to extract the JSON object,
    then strip any fenced block markers. This handles:
    - Trailing text after the JSON object
    - Fenced code blocks (```json ... ```)
    - Leading explanatory text
    """
    text = raw.strip()

    # Strip fenced code block markers
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    # Find the first '{' (or '[') and last '}' (or ']')
    start = text.find("{")
    if start == -1:
        start = text.find("[")
        end = text.rfind("]")
    else:
        end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in response (first '{{' at {start}, last '}}' at {end})")

    json_str = text[start:end + 1]
    if not json_str.strip():
        raise ValueError("Empty JSON object after extraction")

    parsed = json.loads(json_str)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a top-level JSON object")
    return parsed


# ─── Stage 1: Source Discovery ────────────────────────────────────────────────


def validate_sources(data: SourceDiscoveryResult, min_urls: int = 4) -> ValidationResult:
    """Validate a SourceDiscoveryResult. Returns errors; empty errors = valid."""
    errors: list[str] = []
    urls = [normalize_url(c.url) for c in data.competitors]
    unique_urls = list(dict.fromkeys(urls))  # preserve order, dedupe

    if len(unique_urls) < min_urls:
        errors.append(f"Only {len(unique_urls)} unique URLs, need at least {min_urls}")

    # Count domains
    domains = {}
    for c in data.competitors:
        domain = normalize_url(c.url).split("/")[2] if "//" in normalize_url(c.url) else c.domain
        domains[domain] = domains.get(domain, 0) + 1
    if len(domains) < 4:
        errors.append(f"Sources from only {len(domains)} distinct domains; need at least 4")
    dom_over = {d: c for d, c in domains.items() if c > 2}
    if dom_over:
        names = ", ".join(f"{d}({c}x)" for d, c in dom_over.items())
        errors.append(f"Domains with excessive repeats: {names} (max 2 per domain)")

    # Check all URLs are valid http(s)
    for c in data.competitors:
        if not c.url.startswith(("http://", "https://")):
            errors.append(f"Invalid URL (not http): {c.url}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


# ─── Stage 2: Competitor Extraction ────────────────────────────────────────────


def validate_extraction(
    data: ExtractionResult,
    expected_urls: list[str] | None = None,
    min_pages: int = 4,
) -> ValidationResult:
    """Validate an ExtractionResult. Pages with missing headings are warnings, not fatal."""
    errors: list[str] = []
    warnings: list[str] = []

    if len(data.pages) < min_pages:
        errors.append(f"Only {len(data.pages)} pages extracted; need at least {min_pages}")

    for page in data.pages:
        if not page.headings:
            warnings.append(f"No headings returned for {page.url}")

    # Report unexplained URLs (neither extracted nor failed)
    if expected_urls:
        extracted_urls = {normalize_url(p.url) for p in data.pages}
        failed_urls = {normalize_url(f.url) for f in data.failures}
        expected_normalized = {normalize_url(u) for u in expected_urls}
        unexplained = expected_normalized - extracted_urls - failed_urls
        if unexplained:
            errors.append(f"{len(unexplained)} URLs were neither extracted nor reported as failures")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors + (warnings if errors else []),
    )


# ─── Stage 3: Outline Synthesis ────────────────────────────────────────────────


def validate_outline(
    data: OutlineResult,
    topic: str = "",
    clinic_name: str = "",
) -> ValidationResult:
    """Validate the final outline. Python-enforceable rules only.

    This gate intentionally rejects risky outline content before research.  The
    research brief, not the outline model, is the factual authority.
    """
    errors: list[str] = []

    h2_count = len(data.outline)
    h3_count = sum(len(s.subsections) for s in data.outline)

    if not (2000 <= data.target_word_count <= 3000):
        errors.append(f"Target word count is {data.target_word_count}; required range is 2000-3000")
    if len(data.scope_rationale) < 40:
        errors.append("Scope rationale must explain the 2000-3000 word target in 40+ characters")

    # Query alignment. Compare simple stems so "anxious" and "anxiety" align.
    if topic:
        stop = {"when", "what", "does", "with", "from", "that", "this", "normal", "your", "about"}
        topic_terms = {
            re.sub(r"(ing|ed|es|s)$", "", word.lower())[:4]
            for word in re.findall(r"[A-Za-z]+", topic)
            if len(word) >= 4 and word.lower() not in stop
        }
        title_text = f"{data.recommended_title} {data.meta_title}".lower()
        missing_terms = [term for term in topic_terms if term and term not in title_text]
        if missing_terms:
            errors.append(f"Title does not preserve topic terms: {', '.join(sorted(missing_terms))}")

    # H2 budget
    if not (4 <= h2_count <= 6):
        errors.append(f"H2 count is {h2_count}; required range is 4-6")

    # H3 budget
    if not (8 <= h3_count <= 12):
        errors.append(f"H3 count is {h3_count}; required range is 8-12")

    # H3 per H2 cap
    for i, section in enumerate(data.outline):
        if len(section.subsections) > 3:
            errors.append(f"H2 \"{section.heading[:40]}\" has {len(section.subsections)} H3s; max is 3")
        if len(section.purpose.strip()) < 40:
            errors.append(f"H2 \"{section.heading[:40]}\" needs a complete section purpose (40+ chars)")

    # Meta title length
    mt = data.meta_title.strip()
    if not (50 <= len(mt) <= 60):
        errors.append(f"Meta title is {len(mt)} chars; required range is 50-60")

    # Meta description length
    md = data.meta_description.strip()
    if not (140 <= len(md) <= 160):
        errors.append(f"Meta description is {len(md)} chars; required range is 140-160")

    # Meta description must not open with an actual question. A declarative
    # sentence such as "When anxiety causes shaking, ..." is not a question.
    opening = md.split(".", 1)[0]
    if md and md.lstrip().startswith(("What", "How", "Why", "When", "Where", "Do", "Does", "Is", "Are", "Can", "Will", "Should")) and "?" in opening:
        errors.append(f"Meta description starts with a question or decision word: \"{md[:50]}...\"")

    # Meta description must not start with "Learn about" or "Discover"
    if md and re.match(r"^(Learn about|Discover|Find out|Get to know)", md, re.I):
        errors.append(f"Meta description starts with a banned phrase: \"{md[:50]}...\"")

    # Meta title must not have double periods or typos
    if ".." in data.meta_title:
        errors.append(f"Meta title contains double period: \"{data.meta_title}\"")

    # Reject guarantees and overpromises in reader-facing outline text.
    reader_facing = "\n".join(
        [data.recommended_title, data.meta_title, data.meta_description]
        + [s.heading for s in data.outline]
        + [s.purpose for s in data.outline]
        + [s.depth for s in data.outline]
        + [s.pass_field for s in data.outline]
        + [claim for s in data.outline for claim in s.claims]
        + [sub.heading for s in data.outline for sub in s.subsections]
        + [sub.depth for s in data.outline for sub in s.subsections]
        + [sub.pass_field for s in data.outline for sub in s.subsections]
        + [claim for s in data.outline for sub in s.subsections for claim in sub.claims]
    )
    overpromise = re.compile(
        r"\b(changes everything|actually works?|treatment options that work|guaranteed|"
        r"stop(?:s|ping)?\s+.{0,35}\s+right now|works? within|always works?|never fails?)\b",
        re.I,
    )
    match = overpromise.search(reader_facing)
    if match:
        errors.append(f"Reader-facing outline contains an absolute promise: \"{match.group(0)}\"")

    # Avery's House serves teens/young adults and families; prevent unrelated
    # adult life-stage examples from slipping into an otherwise valid outline.
    if "avery" in clinic_name.lower():
        drift = re.compile(r"\b(young adults?|retirees?|older adults?|postpartum|executives?|middle-aged|senior citizens?)\b", re.I)
        drift_match = drift.search(reader_facing)
        if drift_match:
            errors.append(f"Audience drift for Avery's House: \"{drift_match.group(0)}\"")
        audience_text = " ".join(
            [str(v) for v in data.search_intent.values()]
            + [s.purpose for s in data.outline]
            + [sub.depth for s in data.outline for sub in s.subsections]
        )
        if not re.search(r"\b(teens?|adolescents?|parents?|caregivers?|famil(?:y|ies)|guardians?)\b", audience_text, re.I):
            errors.append("Avery's House outline does not explicitly anchor the teen/family audience")

    # Forbidden verbs in headings
    forbidden = re.compile(r"\b(define|explain|understand|list)\b", re.I)
    for section in data.outline:
        if forbidden.search(section.heading):
            errors.append(f"Forbidden verb in H2: \"{section.heading[:60]}\"")
        for sub in section.subsections:
            if forbidden.search(sub.heading):
                errors.append(f"Forbidden verb in H3: \"{sub.heading[:60]}\"")

    # Stress test — heading length. A small buffer avoids spending an LLM retry
    # on a one-word overflow while still rejecting genuinely dense headings.
    for section in data.outline:
        if len(section.heading) > 72:
            errors.append(f"H2 too long ({len(section.heading)} chars): \"{section.heading[:60]}\"")
        for sub in section.subsections:
            if len(sub.heading) > 72:
                errors.append(f"H3 too long ({len(sub.heading)} chars): \"{sub.heading[:60]}\"")

    # Every H2 and H3 must have complete contracts and at least 3
    # evidence-safe research targets.
    research_target = re.compile(
        r"^(Research whether|Verify whether|Confirm whether|Determine whether|Compare evidence for)\b",
        re.I,
    )
    risky_fact = re.compile(
        r"(?:\b\d+(?:\.\d+)?\s*(?:%|percent|seconds?|minutes?|hours?|days?|weeks?|cycles?)\b|"
        r"\bFDA[- ]approved\b|\bwithin\s+\d+\b)",
        re.I,
    )
    def validate_contract(label: str, item: Any) -> None:
        missing = []
        if not item.type_field: missing.append("Type")
        if not item.depth: missing.append("Depth")
        if not item.shape: missing.append("Shape")
        if not item.model: missing.append("Model")
        if not item.fail: missing.append("Fail")
        if not item.pass_field: missing.append("Pass")
        if missing:
            errors.append(f"{label} missing fields: {', '.join(missing)}")
        if len(item.claims) < 3:
            errors.append(f"{label} has only {len(item.claims)} claims; need at least 3")
        for claim in item.claims:
            if not research_target.match(claim.strip()):
                errors.append(f"{label} has an asserted claim instead of a research target: \"{claim[:70]}\"")
            if risky_fact.search(claim) and not re.search(r"\b(source|study|evidence|whether|accuracy|accurate)\b", claim, re.I):
                errors.append(f"{label} contains an unsupported exact claim: \"{claim[:70]}\"")
        if re.search(r"\bthe reader (?:recognizes|realizes|accepts|admits)\b.{0,100}\b(?:they|their|have)\b", item.pass_field, re.I):
            errors.append(f"{label} Pass field assumes the reader's history: \"{item.pass_field[:80]}\"")

    for i, section in enumerate(data.outline):
        # H2s with subsections only need heading + purpose (Fix: prompt change)
        if section.subsections:
            if len(section.purpose.strip()) < 40:
                errors.append(f'H2 "{section.heading[:40]}" needs a complete section purpose (40+ chars)')
        else:
            validate_contract(f'H2 "{section.heading[:40]}"', section)
        for j, sub in enumerate(section.subsections):
            validate_contract(f'H3 "{sub.heading[:40]}"', sub)

    return ValidationResult(valid=len(errors) == 0, errors=errors)
