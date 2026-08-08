#!/usr/bin/env python3
"""Golden Writer v2 — Unified single-call article drafting system.

Changes v2:
  1. Anchor IDs: [[anchor]{id=N}] format for unambiguous link resolution
  2. Curated link set: 10-25 topic-relevant links, not full catalogue
  3. Section markers: <!-- SECTION:h3_N:START/END --> for surgical repair
  4. Exemplar fragments: 5 blocks (intro, mixed section, bridge, takeaways, crisis)
  5. Prompt order: bans + shapes + exemplar BEFORE research brief (cache optimization)

Process:
  Write (1 Hermes call) → Validate (constraint scanner) → Compile (sources + links)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
GWF_ROOT = Path(os.environ.get("GWF_ROOT", "/Users/mac/Desktop/Golden writing framework"))


def _atomic_write_text(path: Path, text: str) -> None:
    """Durably replace a text file without exposing a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _write_checkpoint(path: Path, text: str, preserve_existing: bool = True) -> Path:
    """Write a checkpoint, versioning a different existing artifact."""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == text:
            return path
        if preserve_existing:
            attempt = 2
            while True:
                candidate = path.with_name(f"{path.stem}.attempt-{attempt:02d}{path.suffix}")
                if not candidate.exists():
                    _atomic_write_text(candidate, text)
                    return candidate
                attempt += 1
    _atomic_write_text(path, text)
    return path


def _article_headings(text: str) -> list[str]:
    return [m.group(0).strip() for m in re.finditer(r"^#{1,3}\s+.+$", text, re.MULTILINE)]


def _repair_integrity_errors(before: str, after: str) -> list[str]:
    """Return reasons an LLM repair is unsafe to promote."""
    problems: list[str] = []
    before_headings = _article_headings(before)
    after_headings = _article_headings(after)
    missing = [heading for heading in before_headings if heading not in after_headings]
    if missing:
        problems.append(f"missing headings: {', '.join(missing[:5])}")
    ordered_positions = [after.find(heading) for heading in before_headings if heading in after]
    if ordered_positions != sorted(ordered_positions):
        problems.append("heading order changed")
    if len(after) < len(before) * 0.85:
        problems.append(f"content shrank from {len(before)} to {len(after)} characters")
    for required in ("Key Takeaways", "Sources"):
        if required.lower() in before.lower() and required.lower() not in after.lower():
            problems.append(f"missing required block: {required}")
    crisis_terms = ("call 911", "988", "crisis")
    for term in crisis_terms:
        if term in before.lower() and term not in after.lower():
            problems.append(f"missing crisis content containing: {term}")
    if after.rstrip().endswith(("*", "-", ":", ",", ";")):
        problems.append("output appears to end mid-thought")
    return problems


def _scan_classification(violation: dict[str, Any]) -> str:
    """Classify scanner output without treating editorial lint as corruption."""
    category = str(violation.get("category", "")).lower()
    severity = str(violation.get("severity", "")).lower()
    if severity == "warning":
        return "WARNING"
    if category == "safety_enforcement":
        return "SAFETY"
    if category == "key_takeaways":
        return "STRUCTURAL"
    if category == "em_dashes":
        return "DETERMINISTIC"
    return "EDITORIAL"

# ── Prompt builder (Karpathy order — cache-optimized) ─────────────────────

def _parse_research_by_section(dumb_down_brief: str) -> dict[str, dict]:
    """Parse the dumb-down brief into per-H3 evidence.

    Returns dict mapping H3 heading → {plain_facts, source_urls, do_not_overclaim,
                                       everyday_example, safe_wording, reader_job,
                                       lead_url}
    """
    sections: dict[str, dict] = {}
    current_h3 = ""
    current_facts: list[str] = []
    current_urls: list[str] = []
    current_overclaim = ""
    current_example = ""
    current_safe = ""
    current_reader_job = ""
    current_lead_url = ""
    in_urls = False

    for line in dumb_down_brief.splitlines():
        h3 = re.match(r"^###\s+(.+)$", line)
        if h3:
            if current_h3:
                sections[current_h3] = {
                    "plain_facts": current_facts,
                    "source_urls": current_urls,
                    "do_not_overclaim": current_overclaim,
                    "everyday_example": current_example,
                    "safe_wording": current_safe,
                    "reader_job": current_reader_job,
                    "lead_url": current_lead_url,
                }
            current_h3 = h3.group(1).strip()
            current_facts = []
            current_urls = []
            current_overclaim = ""
            current_example = ""
            current_safe = ""
            current_reader_job = ""
            current_lead_url = ""
            in_urls = False
            continue

        if re.match(r"\* \*\*Plain facts:\*\*\s*(.*)", line):
            m = re.match(r"\* \*\*Plain facts:\*\*\s*(.*)", line)
            if m and m.group(1).strip():
                current_facts.append(m.group(1).strip())
            in_urls = False
        elif re.match(r"\* \*\*Source URLs:\*\*", line):
            in_urls = True
        elif re.match(r"\* \*\*Lead URL:\*\*\s*(.*)", line):
            m = re.match(r"\* \*\*Lead URL:\*\*\s*(.*)", line)
            if m:
                raw = m.group(1).strip()
                # Extract just the URL — LLM sometimes includes full APA citation
                url_match = re.search(r"https?://[^\s\)]+", raw)
                current_lead_url = url_match.group(0) if url_match else raw
            in_urls = False
        elif re.match(r"\* \*\*Do not overclaim:\*\*\s*(.*)", line):
            m = re.match(r"\* \*\*Do not overclaim:\*\*\s*(.*)", line)
            if m:
                current_overclaim = m.group(1).strip()
            in_urls = False
        elif re.match(r"\* \*\*Everyday example:\*\*\s*(.*)", line):
            m = re.match(r"\* \*\*Everyday example:\*\*\s*(.*)", line)
            if m:
                current_example = m.group(1).strip()
            in_urls = False
        elif re.match(r"\* \*\*Safe wording:\*\*\s*(.*)", line):
            m = re.match(r"\* \*\*Safe wording:\*\*\s*(.*)", line)
            if m:
                current_safe = m.group(1).strip()
            in_urls = False
        elif re.match(r"\* \*\*Reader job:\*\*\s*(.*)", line):
            m = re.match(r"\* \*\*Reader job:\*\*\s*(.*)", line)
            if m:
                current_reader_job = m.group(1).strip()
            in_urls = False
        elif in_urls:
            url_match = re.search(r"https?://[^\s\)]+", line)
            if url_match:
                current_urls.append(url_match.group(0))

    if current_h3:
        sections[current_h3] = {
            "plain_facts": current_facts,
            "source_urls": current_urls,
            "do_not_overclaim": current_overclaim,
            "everyday_example": current_example,
            "safe_wording": current_safe,
            "reader_job": current_reader_job,
            "lead_url": current_lead_url,
        }

    return sections


def _parse_outline_sections(outline_md: str) -> list[dict]:
    """Parse outline into ordered list of H2 blocks with their H3s.

    Returns [{
        h2: str,
        opener: str,
        is_bridge: bool,
        h3s: [{heading, type, shape, claims, fail, pass}]
    }]
    """
    blocks: list[dict] = []
    current_h2 = ""
    current_opener = ""
    current_h3s: list[dict] = []
    current_h3 = ""
    current_type = ""
    current_shape = ""
    current_model = ""
    current_depth = ""
    current_claims: list[str] = []
    current_fail = ""
    current_pass = ""
    in_claims = False

    for line in outline_md.splitlines():
        h2 = re.match(r"^##\s+(.+)$", line)
        if h2:
            if current_h3:
                current_h3s.append({
                    "heading": current_h3, "type": current_type,
                    "shape": current_shape, "model": current_model,
                    "depth": current_depth, "claims": current_claims,
                    "fail": current_fail, "pass": current_pass,
                })
            if current_h2:
                blocks.append({
                    "h2": current_h2, "opener": current_opener,
                    "h3s": current_h3s, "is_bridge": len(current_h3s) == 0 or current_h2.startswith("When to seek") or current_h2.startswith("Bridge"),
                })
            current_h2 = h2.group(1).strip()
            current_opener = ""
            current_h3s = []
            current_h3 = ""
            current_type = ""
            current_shape = ""
            current_model = ""
            current_depth = ""
            current_claims = []
            current_fail = ""
            current_pass = ""
            in_claims = False
            continue

        opener = re.match(r"\*{2}Opener direction:\*{2}\s*(.+)", line, re.I)
        if opener:
            current_opener = opener.group(1).strip()
            in_claims = False
            continue

        h3 = re.match(r"^###\s+(.+)$", line)
        if h3:
            if current_h3:
                current_h3s.append({
                    "heading": current_h3, "type": current_type,
                    "shape": current_shape, "model": current_model,
                    "depth": current_depth, "claims": current_claims,
                    "fail": current_fail, "pass": current_pass,
                })
            current_h3 = h3.group(1).strip()
            current_type = ""
            current_shape = ""
            current_model = ""
            current_depth = ""
            current_claims = []
            current_fail = ""
            current_pass = ""
            in_claims = False
            continue

        t2 = re.match(r"-?\s*\*{2}Type:\*{2}\s*(.+)", line, re.I)
        if t2 and current_h3:
            current_type = t2.group(1).strip()
            in_claims = False
            continue
        d2 = re.match(r"-?\s*\*{2}Depth:\*{2}\s*(.+)", line, re.I)
        if d2 and current_h3:
            current_depth = d2.group(1).strip()
            in_claims = False
            continue
        m2 = re.match(r"-?\s*\*{2}Model:\*{2}\s*(.+)", line, re.I)
        if m2 and current_h3:
            current_model = m2.group(1).strip()
            in_claims = False
            continue
        s2 = re.match(r"-?\s*\*{2}Shape:\*{2}\s*(.+)", line, re.I)
        if s2 and current_h3:
            current_shape = s2.group(1).strip()
            in_claims = False
            continue
        f2 = re.match(r"-?\s*\*{2}Fail:\*{2}\s*(.+)", line, re.I)
        if f2 and current_h3:
            current_fail = f2.group(1).strip()
            in_claims = False
            continue
        p2 = re.match(r"-?\s*\*{2}Pass:\*{2}\s*(.+)", line, re.I)
        if p2 and current_h3:
            current_pass = p2.group(1).strip()
            in_claims = False
            continue

        if re.match(r"-?\s*\*{2}Claims:\*{2}", line, re.I):
            in_claims = True
            continue
        claim = re.match(r"^-\s+(.+)", line)
        if claim and current_h3 and in_claims:
            current_claims.append(claim.group(1).strip())
        else:
            in_claims = False

    if current_h3:
        current_h3s.append({
            "heading": current_h3, "type": current_type,
            "shape": current_shape, "model": current_model,
            "depth": current_depth, "claims": current_claims,
            "fail": current_fail, "pass": current_pass,
        })
    if current_h2:
        blocks.append({
            "h2": current_h2, "opener": current_opener,
            "h3s": current_h3s, "is_bridge": len(current_h3s) == 0 or "when to seek" in current_h2.lower() or "bridge" in current_h2.lower(),
        })

    return blocks


def build_write_prompt(
    dumb_down_brief: str,
    outline_md: str,
    clinic_name: str = "",
    pairs_block: str = "",
    exemplar_fragments: str = "",
    curated_links: str = "",
    section_briefs_block: str = "",
) -> str:
    """Assemble the write prompt using assembly-line design.

    Structure:
      1. Persona + priority order (from Golden_Masterpiece_Writing_Prompt)
      2. Boss-approved exemplar article (the model's last read before writing)
      3. Article template with {{slots}}
      4. Per-section assembly line: brief + shape template inline
      5. Write instruction
    """
    # Parse outline + research into per-section data
    blocks = _parse_outline_sections(outline_md)
    research = _parse_research_by_section(dumb_down_brief)

    # 1. Persona + priority (concise — from Golden_Masterpiece_Writing_Prompt)
    persona = """You are an elite clinical content writer. Every sentence you write must sound human, not templated.

ABSOLUTE PRIORITY ORDER (when rules conflict):
1. Safety and clinical accuracy
2. Evidence alignment with the research brief
3. Reader comprehension
4. Emotional truth
5. Literary force (never at the expense of accuracy)

PRINCIPLES:
- No source signaling. Never "research shows," "studies find," "according to," "data shows," "government sources say," "SAMHSA data shows," or any year-labeled study mention ("A 2025 study," "A 2021 review"). The URL IS the citation.
  - WRONG: "According to SAMHSA data, Native Americans are three times as likely to meet criteria for a substance use disorder."
  - RIGHT: "Native Americans are roughly three times as likely to meet criteria for a substance use disorder."
  - WRONG: "Government sources show that alcohol-related deaths affect Native Americans at five times the rate of the white population."
  - RIGHT: "Alcohol-related deaths affect Native Americans at five times the rate of the white population."
  - WRONG: "One study found that NSAIDs did not show clear benefits for hangover headaches."
  - RIGHT: "NSAIDs did not show clear benefits for hangover headaches."
  - WRONG: "A recent study found that B vitamin supplementation may help with hangover recovery."
  - RIGHT: "B vitamin supplementation may help with hangover recovery, though research is still preliminary."
  - WRONG: "Ginger contains compounds that are known to help with nausea in general, but evidence for alcohol-related stomach upset specifically is limited."
  - RIGHT: "Ginger helps with nausea generally. Whether it works for hangover nausea specifically is not well-studied."
  - WRONG link anchor: [A 2025 study found that glutathione metabolism may protect the liver]
  - WRONG link anchor: [Research shows that ginger settles the stomach]
  - RIGHT link anchor: [Glutathione metabolism may protect the liver]
  - RIGHT link anchor: [Ginger settles the stomach]
  Note: The source signaling ban applies to BOTH prose AND link anchor text. A link anchor must read like a natural part of the sentence, not like an academic citation.
- NO reader assumptions. Never write "you [feel/know/sense/wonder/reach/take/notice]." Instead: "some people," "many people," "it is common to," or state directly.
  - WRONG: "You sense that what you are doing is not the same as drug addiction."
  - RIGHT: "Some people sense that what they are doing is not the same as drug addiction."
  - WRONG: "You reach for your magnesium gummies every night."
  - RIGHT: "Many people who take magnesium gummies do so every night."
  - WRONG: "You wonder if any of it is actually helping."
  - RIGHT: "It is common to wonder whether any of it is actually helping."
- Natural flow. Each sentence develops the previous thought. No jump-cuts.
- No fabricated authority. Never "tested" or "proven" unless the brief says so.
- Intro closes on the promise. No clinic link in the intro.
- Clinic links allowed in body sections as natural recommendations. Bridge is the main location. One clinic mention. 1-2 programs max.
- Bridge to care: understated, 4-6 sentences. Clinic name once. 1-2 linkable programs max."""

    # 2. Exemplar article — boss-approved article
    exemplar_path = Path.home() / "Downloads" / "Self Harm Relapse - Single Call.md"
    exemplar_text = "No exemplar available."
    if exemplar_path.exists():
        exemplar_text = exemplar_path.read_text(encoding="utf-8")

    # 3. Start building the prompt
    sections_list = [persona]

    sections_list.append(
        f"\n\n═══ TOPIC ═══\n"
        f"Clinic: {clinic_name or 'Editorial (no clinic)'}\n"
    )

    sections_list.append(
        f"═══ EXEMPLAR ARTICLE — STUDY THIS VOICE AND STRUCTURE ═══\n"
        f"This is a boss-approved article. Match its register, citation style, "
        f"section structure, and reader address.\n\n"
        f"{exemplar_text}\n"
        f"\n═══ END EXEMPLAR ═══\n"
    )

    # 2b. Section exemplars — 10 edited H3 sections showing perfect writing + links
    exemplar_sections_path = Path("exemplar_sections.md")
    if not exemplar_sections_path.exists():
        exemplar_sections_path = Path("/Users/mac/Desktop/Golden writing framework/exemplar_sections.md")
    if exemplar_sections_path.exists():
        sections_list.append(
            f"\n\n═══ SECTION EXEMPLARS — STUDY THESE FOR TONE, LINK STYLE, "
            f"AND READER ADDRESS ═══\n"
            f"These are edited, boss-approved H3 sections from multiple articles. "
            f"Study how they weave links naturally, present claims without source "
            f"signaling, and maintain a human voice while citing evidence.\n\n"
            f"{exemplar_sections_path.read_text(encoding='utf-8')}\n"
        )

    # 3. Article template — pre-fill meta title/description from outline
    outline_meta = re.search(r'---\s*\nmeta_title:\s*["\']?(.+?)["\']?\s*\nmeta_description:\s*["\']?(.+?)["\']?\s*\n---', outline_md, re.DOTALL)
    template_title = outline_meta.group(1).strip() if outline_meta else "Title"
    template_desc = outline_meta.group(2).strip() if outline_meta else "Description"
    
    sections_list.append(
        f"\n\n═══ ARTICLE TO WRITE — FILL EVERY {{SLOT}} ═══\n"
        f"{get_article_template(template_title, template_desc)}\n"
    )

    # 4. Per-section assembly line with shape templates inline
    sections_list.append("\n\n═══ PER-SECTION BRIEFS — USE THESE TO FILL THE TEMPLATE ═══\n")

    for block in blocks:
        h2 = block["h2"]
        opener = block["opener"]
        h3s = block["h3s"]
        is_bridge = block["is_bridge"]

        sections_list.append(f"\n## {h2}")
        if opener and not is_bridge:
            sections_list.append(f"  ▶ Write this opener as the first 1-3 sentences: {opener[:200]}")
        sections_list.append("")

        if is_bridge:
            sections_list.append(
                "[BRIDGE TO CARE — Write understated, 4-6 sentences. "
                f"Mention {clinic_name or 'the clinic'} naturally once. "
                "1-2 linkable programs max. No H3s.]"
            )
            sections_list.append("")
            continue

        for h3 in h3s:
            heading = h3["heading"]
            shape = h3.get("shape", "mixed section")
            model = h3.get("model", "")
            depth = h3.get("depth", "")
            type_field = h3.get("type", "")

            sections_list.append(f"\n### {heading}")

            # Compact brief — writing content comes ONLY from dumbed-down research
            brief_parts = []
            if model:
                brief_parts.append(f"Model: {model[:200]}")
            if depth:
                brief_parts.append(f"Depth: {depth[:200]}")
            if type_field:
                brief_parts.append(f"Type: {type_field[:100]}")
            if brief_parts:
                sections_list.append(" | ".join(brief_parts))

            # Research-driven fields from dumbed-down brief (not outline Claims)
            r = research.get(heading, {})
            r_parts = []
            everyday = r.get("everyday_example", "")
            if everyday:
                r_parts.append(f"Everyday example: {everyday[:300]}")
            safe = r.get("safe_wording", "")
            if safe:
                r_parts.append(f"Safe wording: {safe[:300]}")
            reader_job = r.get("reader_job", "")
            if reader_job:
                r_parts.append(f"Reader job: {reader_job[:200]}")
            lead_url = r.get("lead_url", "")
            if lead_url:
                r_parts.append(f"Lead URL: {lead_url}")
            if r_parts:
                sections_list.append(" | ".join(r_parts))

            # Shape template — the forcing function
            sections_list.append(get_shape_template(shape))
            sections_list.append("")

    # 5. Write instruction
    sections_list.append("")

    # Internal links catalog — placed just before writing, after all context
    if curated_links.strip():
        sections_list.append(
            f"═══ CLINIC INTERNAL LINKS ═══\n"
            f"Use these when mentioning clinic programs, services, or conditions:\n"
            f"{curated_links.strip()}\n"
            f"═══ END CLINIC LINKS ═══\n"
        )

    sections_list.append(
        "\n\n═══ WRITE THE ARTICLE ═══\n"
        "Fill the article template above. Replace every {{slot}} with real content. "
        "Output only the finished article — no commentary, no file paths, no explanation. "
        "Start with **Meta title:**. Mirror the exemplar's register and citation style. "
        "Do NOT include a Sources section — it will be appended automatically.\n\n"
        "LINK RULE: Each H3 section has a \"Lead URL:\" field. Link ONE sentence in each H3 "
        "to its Lead URL. Pick a short natural phrase (3-8 words) as the anchor. "
        "The anchor must NOT contain source-signaling language — the source signaling rule "
        "applies to both prose AND anchor text. Bad: [A 2025 study found that glutathione helps]. "
        "Good: [Glutathione may protect the liver]. Wrap like [short phrase](url).\n\n"
        "INTERNAL LINKS: The CLINIC INTERNAL LINKS block above lists clinic programs, services, "
        "and conditions with their URLs. Insert at least 5 internal links from this list. "
        "No maximum — add as many as are naturally helpful. "
        "Only link when the sentence genuinely references that topic. "
        "Like the exemplar articles do: [program name](url). "
        "Never force a link where it doesn't belong naturally.",
    )

    return "\n".join(sections_list)


# ── Shape template ───────────────────────────────────────────────────────

def get_shape_template(shape: str) -> str:
    """Fill-in-the-blank shape template. Model fills {{slots}}, not instructions."""
    if not shape or "pure" in shape.lower() or "prose" in shape.lower():
        return ""
    if "numbered" in shape.lower() or "step" in shape.lower():
        return (
            "\n=== NUMBERED STEPS — WRITE DIRECTLY INTO THIS STRUCTURE ===\n"
            "\n  INTRO: 1-2 sentences framing the process.\n"
            "  1. {{STEP_ONE}}\n"
            "  2. {{STEP_TWO}}\n"
            "  3. {{STEP_THREE}}\n"
            "  4. {{STEP_FOUR}}\n"
            "  5. {{STEP_FIVE}}\n"
            "  CLOSE: 1-2 sentences on what happens next.\n"
            "\n=== END NUMBERED STEPS ===\n"
        )
    if "comparison" in shape.lower() or "paired" in shape.lower():
        return (
            "\n=== COMPARISON — WRITE DIRECTLY INTO THIS STRUCTURE ===\n"
            "  * **{{OPTION_A}}:** Description.\n"
            "  * **{{OPTION_B}}:** Description.\n"
            "  CLOSE: 1-2 sentences on which to choose.\n"
            "\n=== END COMPARISON ===\n"
        )
    # Default: mixed section
    return (
        "\n=== MIXED SECTION — WRITE DIRECTLY INTO THIS STRUCTURE ===\n"
        "\n  [FRAMING PARAGRAPH: 2-4 sentences that land the point]:\n"
        "  {{FRAMING_PARAGRAPH}}\n"
        "\n  [BULLET LIST — 3-5 items. Each line MUST start with '* **']:\n"
        '  * **{{BOLDED_LABEL}}:** {{Explanatory sentence.}}\n'
        '  * **{{BOLDED_LABEL}}:** {{Explanatory sentence.}}\n'
        '  * **{{BOLDED_LABEL}}:** {{Explanatory sentence.}}\n'
        "\n  [CLOSE — 1-2 sentences. Forward pull, not summary]:\n"
        "  {{CLOSE}}\n"
        "\n=== END MIXED SECTION ===\n"
    )


def get_article_template(title: str = "Title", description: str = "Description") -> str:
    """Full article skeleton with {{slots}}. Title and description pre-filled from outline."""
    return (
        "=== ARTICLE TEMPLATE — FILL EVERY {{SLOT}} EXACTLY ===\n"
        "\n"
        f"**Meta title:** {title}\n"
        f"**Meta description:** {description}\n"
        "\n"
        f"# {title}\n"
        "\n"
        "{{CRISIS_SAFETY_BLOCK}}\n"
        "\n"
        "{{INTRO_PARAGRAPHS}}\n"
        "\n"
        "## Key Takeaways\n"
        "\n"
        "* {{KEY_TAKEAWAY_1}}\n"
        "* {{KEY_TAKEAWAY_2}}\n"
        "* {{KEY_TAKEAWAY_3}}\n"
        "* {{KEY_TAKEAWAY_4}}\n"
        "* {{KEY_TAKEAWAY_5}}\n"
        "\n"
        "{{ALL_H2_H3_SECTIONS}}\n"
        "\n"
        "{{BRIDGE_TO_CARE}}\n"
        "\n"
        "{{SOURCES}}\n"
        "\n"
        "<!-- HARD CONSTRAINTS (enforced by template structure) -->\n"
        "<!-- [ ] No em dashes — replace with commas or periods -->\n"
        "<!-- [ ] No source signaling in first 3 sentences of any H2 -->\n"
        "<!-- [ ] Paragraphs ≤ 420 chars, sentences ≤ 26 words -->\n"
        "<!-- [ ] All bullets use '* ' not '- ' -->\n"
        "<!-- [ ] MAX 2 research claims/citations per paragraph -->\n"
        "=== END ARTICLE TEMPLATE ===\n"
    )


# ── Outline brief extractor ──────────────────────────────────────────────

def extract_section_briefs(outline_md: str) -> str:
    sections = []
    h3_counter = 0
    current_h2 = ""
    current_h2_opener = ""
    current_h3 = ""
    current_type = ""
    current_shape = ""
    current_claims = []
    current_fail = ""
    current_pass = ""

    for line in outline_md.splitlines():
        # Track H2 headings
        h2 = re.match(r"^##\s+(.+)$", line) or re.match(r"^\*\*H2:\s*(.+?)\*\*$", line)
        if h2:
            if current_h3:
                sections.append(_brief_block(h3_counter, current_h3, current_type, current_shape, current_claims, current_fail, current_pass))
            current_h2 = h2.group(1).strip()
            # Emit H2 opener as standalone block BEFORE first H3
            if current_h2_opener:
                sections.append(f"H2 OPENER: {current_h2_opener}\n(Write 1-3 sentences introducing this H2 section. Then write the H3s.)")
                current_h2_opener = ""
            h3_counter = 0
            current_h3 = ""
            current_type = ""
            current_shape = ""
            current_claims = []
            current_fail = ""
            current_pass = ""
            continue

        # Track H2 openers
        h2_opener = re.match(r"\*\*Opener direction:\*\*\s*(.+)", line, re.I)
        if h2_opener:
            current_h2_opener = h2_opener.group(1).strip()
            continue

        h3 = re.match(r"^###\s+(.+)$", line) or re.match(r"^-\s+\*\*H3:\s*(.+?)\*\*$", line)
        if h3:
            if current_h3:
                sections.append(_brief_block(h3_counter, current_h3, current_type, current_shape, current_claims, current_fail, current_pass))
            h3_counter += 1
            current_h3 = h3.group(1).strip()
            current_type = ""
            current_shape = ""
            current_claims = []
            current_fail = ""
            current_pass = ""
            continue
        t = re.match(r"\*\*Type:\*\*\s*(.+)", line, re.I)
        if t: current_type = t.group(1).strip()
        s = re.match(r"\*\*Shape:\*\*\s*(.+)", line, re.I)
        if s: current_shape = s.group(1).strip()
        claim = re.match(r"^\-\s+(.+)", line)
        if claim and current_h3:
            current_claims.append(claim.group(1).strip())
        f = re.match(r"\*\*Fail:\*\*\s*(.+)", line, re.I)
        if f: current_fail = f.group(1).strip()
        p = re.match(r"\*\*Pass:\*\*\s*(.+)", line, re.I)
        if p: current_pass = p.group(1).strip()

    if current_h3:
        sections.append(_brief_block(h3_counter, current_h3, current_type, current_shape, current_claims, current_fail, current_pass))

    return "\n---\n".join(sections)


def _brief_block(idx: int, heading: str, type_: str, shape: str, claims: list, fail: str, pass_: str) -> str:
    lines = [f"<!-- SECTION:h3_{idx:02d}:START -->", f"### {heading}"]
    if type_: lines.append(f"Type: {type_}")
    if shape:
        lines.append(f"Shape: {shape} — {get_shape_template(shape)}")
    if claims:
        lines.append("Claims:")
        for c in claims[:5]:
            lines.append(f"  - {c}")
    if fail: lines.append(f"Do not: {fail}")
    if pass_: lines.append(f"Pass when: {pass_}")
    lines.append(f"<!-- SECTION:h3_{idx:02d}:END -- this section must be followed by the next H3 -->\n")
    return "\n".join(lines)


# ── Exemplar fragments (approved blocks, not full articles) ──────────────

def get_exemplar_fragments() -> str:
    """Return 5 approved writing fragments: intro, mixed section, bridge,
    key takeaways, crisis section. These are cacheable — same across articles."""
    fragments = """=== EXEMPLAR FRAGMENTS — Study these for register and craft ===

--- FRAGMENT 1: Introduction ---
A return to self-harm can happen after weeks, months, or even years of staying clean. When it does, shame often arrives before the physical pain. The thought that follows can feel automatic: those clean weeks did not count. You are back at zero.

The shame may be pushing you to hide instead of reaching out for support. Both reactions are common, but neither tells the truth about what happened. The question is not whether you failed. It is what the relapse tells you about where your plan reached its boundary, and what to do in the hours and days that follow.

--- FRAGMENT 2: Mixed Section (definition + scan bullets) ---
Not every return to self-harm means the same thing. A single incident after a long stretch of staying clean is different from sliding back into the ongoing pattern. Telling them apart changes what you do next.

* **A lapse is a one-time incident.** You felt the urge, acted on it, and stopped again. The clean time before it was weeks or months. Tend to the wound, tell one trusted person, and review your crisis plan. Your regular therapy can handle this.
* **A relapse is a return to the pattern.** You have done it more than once in a short window. You are starting to hide again. Do the same immediate steps, then talk to your therapist about whether your current treatment level is enough.

The distinction is not about how bad the act was. It is about what happens after.

--- FRAGMENT 3: Key Takeaways ---
* A single return to self-harm is a lapse, not the end of recovery. A lapse and a relapse call for different responses.
* The coping skills you built did not disappear. They hit a moment they were not enough for, and that gap tells you what to strengthen.
* Shame after a relapse can be more dangerous than the act itself because it drives isolation, which delays getting help.
* A crisis safety plan you can use when distressed beats one you can only follow when calm.
* Reaching out for professional support is not admitting defeat. It is responding to what the relapse tells you about whether your current level of care is enough.

--- FRAGMENT 4: Bridge to Care ---
If weekly therapy is not holding the week together, virtual PHP or IOP gives you more clinical hours without leaving home. Modern Recovery Services builds treatment around DBT, the approach with the strongest research support for self-harm reduction. Reach out for a free, confidential assessment to understand what level of support fits where you are right now.

--- FRAGMENT 5: Crisis Safety ---
If you are thinking about suicide or are in immediate danger, call or text 988 now or go to the nearest emergency room. Crisis response chain: 988 or 911 → emergency room → your therapist or doctor → a trusted parent, partner, or caregiver. If you cannot keep yourself safe, do not wait. Move up the chain until someone responds.

=== END EXEMPLAR FRAGMENTS ==="""
    return fragments


# ── Internal link DB (CSV-backed) ────────────────────────────────────────

INTERNAL_LINK_DB = Path("/Users/mac/Desktop/Golden writing framework/outputs/golden_sheet_template/Internal Link Database.csv")

# Map clinic names to CSV slugs
CLINIC_SLUG_MAP = {
    "Modern Recovery Services": "modern_recovery_services",
    "MRS": "modern_recovery_services",
    "Modern Recovery Arizona": "modern_recovery_arizona",
    "MRS Arizona": "modern_recovery_arizona",
    "Roots Renewal Ranch": "roots_renewal_ranch",
    "Avery's House": "averys_house",
}
 

def get_curated_links(topic: str, clinic_name: str = "") -> str:
    """Return topic-relevant internal links from CSV DB, filtered by clinic.

    Returns up to 15 links sorted by topic relevance.
    """
    slug = ""
    if clinic_name:
        for name, s in CLINIC_SLUG_MAP.items():
            if (name.lower() in clinic_name.lower()
                    or clinic_name.lower() in name.lower()):
                slug = s
                break

    # Load from CSV
    pages: dict[str, str] = {}
    if slug and INTERNAL_LINK_DB.exists():
        import csv
        with open(INTERNAL_LINK_DB, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("clinic_slug", "").strip() == slug
                        and row.get("status", "").strip().lower() == "approved"
                        and row.get("allowed_anchor_phrases", "").strip()):
                    label = row["allowed_anchor_phrases"].strip()
                    url = row.get("url", "").strip()
                    if label and url:
                        pages[label] = url

    if not pages:
        return ""

    # Sort by topic relevance
    topic_lower = topic.lower()
    topic_words = set(topic_lower.split())
    scored = []
    for label, url in pages.items():
        label_lower = label.lower()
        word_matches = sum(1 for w in topic_words if w in label_lower)
        scored.append((word_matches, label, url))
    scored.sort(key=lambda x: (-x[0], x[1]))

    lines = []
    for i, (_, label, url) in enumerate(scored, 1):
        lines.append(f"  {i:2d}. [[{label}]{{{url}}}]")
    return "\n".join(lines[:200])


# ── Link inserter (LLM-based) ─────────────────────────────────────────────

def insert_citations(article: str, dumb_down_brief: str, link_map: dict[str, str]) -> tuple[str, bool]:
    """Add both external citations and internal links via one LLM call.

    The model receives: exemplar article → clean article → per-section
    source URLs → internal link catalog. It adds links by wrapping existing
    text with [phrase](url). Zero prose changes.
    """
    hermes_bin = str(Path.home() / ".local" / "bin" / "hermes")
    research = _parse_research_by_section(dumb_down_brief)

    # Build per-section source block — every H3 gets its Lead URL
    h3_blocks = list(re.finditer(r'^### (.+?)\n(.*?)(?=^### |^## |\Z)', article, re.MULTILINE | re.DOTALL))
    sources_block = ""
    allowed_urls = set(link_map.values())
    for block in h3_blocks:
        heading = block.group(1).strip()
        brief = research.get(heading, {})
        lead = brief.get("lead_url", "")
        urls = brief.get("source_urls", [])
        # Use lead URL if available, otherwise first source URL
        target_url = lead or (urls[0] if urls else "")
        if target_url:
            sources_block += f"### {heading}\n  LINK: {target_url}\n"
            allowed_urls.add(target_url)
        else:
            sources_block += f"### {heading}\n  (no source for this section)\n"

    if not allowed_urls:
        print("  No approved URLs available — link stage skipped")
        return article, True

    # Build internal link catalog
    catalog_lines = []
    for label, url in sorted(link_map.items(), key=lambda x: -len(x[0])):
        catalog_lines.append(f"  {label} -> {url}")
    catalog_block = "\n".join(catalog_lines) if catalog_lines else "(none)"

    # Read exemplar article
    exemplar_path = Path.home() / "Downloads" / "Self Harm Relapse - Single Call.md"
    exemplar_block = ""
    if exemplar_path.exists():
        exemplar_block = exemplar_path.read_text(encoding="utf-8")[:6000]

    link_prompt = (
        f"═══ EXEMPLAR — STUDY HOW THIS ARTICLE HANDLES LINKS ═══\n"
        f"{exemplar_block[:3000]}\n\n"
        f"═══ ARTICLE TO ADD LINKS TO ═══\n"
        f"{article}\n\n"
        f"═══ EXTERNAL SOURCE URLs (per section) ═══\n"
        f"{sources_block}\n\n"
        f"═══ INTERNAL LINK CATALOG ═══\n"
        f"{catalog_block}\n\n"
        f"═══ RULES ═══\n"
        f"1. Do NOT change any words. Only wrap: [text](url)\n"
        f"2. No links in: intro, Key Takeaways, headings, crisis blocks, or Sources\n"
        f"3. The anchor must be AN EXACT SUBSTRING of the article text (copy-paste, do not paraphrase)\n"
        f"4. One link per URL max.\n"
        f"5. Every H3 section MUST have at least one link to its LINE: URL. "
        f"Find the best SENTENCE in that section, then pick a short natural phrase (3-8 words) "
        f"within it as the anchor. The anchor must read naturally as part of the sentence. "
        f"Do NOT include source-signaling words like 'study found,' 'research shows,' "
        f"'according to,' 'data suggests' in the anchor text.\n"
        f"  GOOD anchor: [milk thistle may support liver function]\n"
        f"  BAD anchor: [One study found that milk thistle may support liver function]\n"
        f"6. Additional links: also link any statistic to its supporting source. "
        f"Use the same URL across multiple sentences if needed.\n"
        f"7. For internal links: when a sentence naturally mentions a topic from the catalog, "
        f"add a link. Prioritize exact-phrase matches.\n\n"
        f"For EACH link, return ONE line:\n"
        f"LINK: [exact text from article] | URL: [url]\n\n"
        f"Example: LINK: Native Americans experience substance use at higher rates than the general population | URL: https://pmc.ncbi.nlm.nih.gov/...\n\n"
        f"Return ONLY the LINK lines. Nothing else."
    )

    r = subprocess.run(
        [hermes_bin, "--profile", "research-agent", "-z", link_prompt],
        capture_output=True, text=True, timeout=180,
    )
    if r.returncode == 0 and r.stdout and r.stdout.strip():
        links_added = 0
        for line in r.stdout.strip().splitlines():
            m = re.match(r'LINK:\s*(.+?)\s*\|\s*URL:\s*(.+)', line)
            if m:
                anchor = m.group(1).strip()
                url = m.group(2).strip()
                if anchor and url in allowed_urls and anchor in article:
                    # Check not already inside a link
                    pos = article.find(anchor)
                    pre = article[max(0, pos - 20):pos] if pos >= 0 else ""
                    prefix = article[:pos]
                    current_heading = ""
                    headings = list(re.finditer(r"^#{1,3}\s+(.+)$", prefix, re.MULTILINE))
                    if headings:
                        current_heading = headings[-1].group(1).lower()
                    line_start = article.rfind("\n", 0, pos) + 1
                    in_heading = article[line_start:pos].lstrip().startswith("#")
                    forbidden = (
                        not headings
                        or "key takeaway" in current_heading
                        or "source" in current_heading
                        or "crisis" in current_heading
                        or in_heading
                    )
                    if pos >= 0 and not forbidden and not ("[" in pre and "]" not in pre[pre.rfind("["):]):
                        replacement = f"[{anchor}]({url})"
                        article = article[:pos] + replacement + article[pos + len(anchor):]
                        links_added += 1
        print(f"  Links added: {links_added}")
        return article, True

    print(f"  ⚠️ Link call failed (code {r.returncode})")
    return article, False


# ── Deterministic cleanup (from batch_pipeline.py) ─────────────────────────

def deterministic_article_cleanup(text: str) -> str:
    """Apply formatting-only edits that cannot change sentence meaning."""
    text = re.sub(r"(?m)^(\s*)- ", r"\1* ", text)  # - bullet -> * bullet
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def compile_article(article: str, dumb_down_brief: str, link_map: dict[str, str]) -> str:
    """Compile final article: normalize meta, fix takeaways, strip markers, append Sources.

    0. Normalize meta format (detect **Meta Title:** or Meta title: → YAML frontmatter)
    1. Strip links from Key Takeaways section
    2. Strip <!-- SECTION: --> markers
    3. Strip placeholder headings like "### Bridge to Care"
    4. Copy dumb-down brief's ## Sources section verbatim
    """
    # 0. Normalize meta format — detect any format, convert to YAML frontmatter
    meta_title = ""
    meta_desc = ""
    mt = re.search(r'(?:\*\*)?[Mm]eta\s*[Tt]itle(?:\*\*)?:\s*(.+)', article)
    if mt:
        meta_title = mt.group(1).strip().strip('"').strip('*').strip()
        article = article[:mt.start()] + article[mt.end():]
    md = re.search(r'(?:\*\*)?[Mm]eta\s*[Dd]escription(?:\*\*)?:\s*(.+)', article)
    if md:
        meta_desc = md.group(1).strip().strip('"').strip('*').strip()
        article = article[:md.start()] + article[md.end():]
    # Remove any existing YAML frontmatter
    article = re.sub(r'^---\n.*?\n---\n?', '', article, flags=re.DOTALL)
    article = article.strip()
    # Build YAML frontmatter, but prepend only after body cleanup so the
    # separator cleanup below cannot strip its delimiters.
    frontmatter = ""
    if meta_title or meta_desc:
        frontmatter = "---\n"
        if meta_title:
            frontmatter += f'meta_title: {json.dumps(meta_title)}\n'
        if meta_desc:
            frontmatter += f'meta_description: {json.dumps(meta_desc)}\n'
        frontmatter += "---\n\n"

    # 1. Strip inline links from Key Takeaways section
    def _strip_takeaway_links(m: re.Match) -> str:
        section = m.group(0)
        # Remove all [text](url) — keep just the text
        section = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', section)
        return section
    article = re.sub(r'(?s)(## Key Takeaways.*?)(?=\n## |\Z)', _strip_takeaway_links, article)

    # 2. Strip section markers and separators
    article = re.sub(r'<!-- SECTION:h3_\d{2}:(?:START|END).*?-->\n?', '', article)
    # Strip any other HTML comments (template leakage)
    article = re.sub(r'<!--.*?-->\n?', '', article)
    article = re.sub(r'\n?---\n?', '\n', article)
    # Also handle [[anchor]{url}] format if model used it
    article = re.sub(r'\[\[(.+?)\]\{(.+?)\}\]', r'[\1](\2)', article)
    article = re.sub(r'\n{4,}', '\n\n\n', article)

    # 3. Strip placeholder bridge heading (any format)
    article = re.sub(r'^#{1,3}\s*Bridge to Care\s*$', '', article, flags=re.MULTILINE)
    article = re.sub(r'^#{1,3}\s*Crisis safety\s*$', '', article, flags=re.MULTILINE)
    article = re.sub(r'^\*{2}Bridge[^ ]*[Cc]are\*{2}\s*$', '', article, flags=re.MULTILINE)

    # Copy Sources block verbatim from dumb-down brief
    sources_match = re.search(r'^## Sources\n\n(.*?)(?:\n##|\Z)', dumb_down_brief, re.DOTALL | re.MULTILINE)
    if sources_match:
        sources_text = sources_match.group(1).strip()
        source_lines = []
        for line in sources_text.splitlines():
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('-') and not line.startswith('#'):
                source_lines.append(f'* {line}')
            elif line:
                source_lines.append(line)
        # Remove existing Sources section if model wrote one
        article = re.sub(r'\n## Sources\n.*?(\n##|\Z)', r'\n\1', article, flags=re.DOTALL)
        # Sort sources alphabetically A-Z by first letter after bullet prefix
        source_lines.sort(key=lambda x: re.sub(r'^[\*\-\s]+', '', x).lower())
        article = article.rstrip() + '\n\n\n## Sources\n\n' + '\n'.join(source_lines)

    body = deterministic_article_cleanup(article).strip()
    return frontmatter + body


# ── Repair phase (from batch_pipeline.py) ──────────────────────────────────

FIX_PAIRS: dict[str, str] = {
    "em dash": "EM DASHES & HARD BANS:\n  BEFORE: Your teen needs more support -- the right care structure can help.\n  AFTER:  Your teen needs more support. The right care structure can help.\n  Rule: never use em dashes. Use periods or commas instead.",
    "source signaling": "SOURCE SIGNALING — STRIP THE ATTRIBUTION PREFIX:\n  BEFORE: Research shows that DBT reduces self-harm in most people within 6 months.\n  AFTER:  DBT reduces self-harm in most people within 6 months.\n\n  BEFORE: One study found that NSAIDs did not show clear benefits for hangover headaches.\n  AFTER:  NSAIDs did not show clear benefits for hangover headaches.\n\n  BEFORE: A 2020 trial found that a supplement drink reduced some hangover symptoms.\n  AFTER:  A supplement drink reduced some hangover symptoms.\n\n  BEFORE: Evidence suggests that milk thistle may support liver function.\n  AFTER:  Milk thistle may support liver function.\n\n  BEFORE: According to research, Native Americans are three times as likely to develop a substance use disorder.\n  AFTER:  Native Americans are three times as likely to develop a substance use disorder.\n\n  BEFORE: Studies show that Native Americans experience substance use at higher rates.\n  AFTER:  Native Americans experience substance use at higher rates.\n\n  BEFORE: Is associated with improved recovery outcomes.\n  AFTER:  Improves recovery outcomes.\n\n  Rule: delete the entire attribution prefix. Never say 'Research shows,' 'One study found,' 'A recent study found,' 'Evidence suggests,' 'According to,' 'Studies show,' 'Is associated with.' State the claim directly. The URL is the hyperlink — never leave attributive scaffolding around a fact.",
    "signaling": "SOURCE SIGNALING — STRIP THE ATTRIBUTION PREFIX:\n  BEFORE: Research shows that DBT reduces self-harm in most people within 6 months.\n  AFTER:  DBT reduces self-harm in most people within 6 months.\n\n  BEFORE: One study found that NSAIDs did not show clear benefits for hangover headaches.\n  AFTER:  NSAIDs did not show clear benefits for hangover headaches.\n\n  BEFORE: A 2020 trial found that a supplement drink reduced some hangover symptoms.\n  AFTER:  A supplement drink reduced some hangover symptoms.\n\n  BEFORE: Evidence suggests that milk thistle may support liver function.\n  AFTER:  Milk thistle may support liver function.\n\n  BEFORE: According to research, Native Americans are three times as likely to develop a substance use disorder.\n  AFTER:  Native Americans are three times as likely to develop a substance use disorder.\n\n  BEFORE: Studies show that Native Americans experience substance use at higher rates.\n  AFTER:  Native Americans experience substance use at higher rates.\n\n  BEFORE: Is associated with improved recovery outcomes.\n  AFTER:  Improves recovery outcomes.\n\n  Rule: delete the entire attribution prefix. Never say 'Research shows,' 'One study found,' 'A recent study found,' 'Evidence suggests,' 'According to,' 'Studies show,' 'Is associated with.' State the claim directly. The URL is the hyperlink — never leave attributive scaffolding around a fact.",
    "reader assumption": "READER ASSUMPTIONS — NEVER assert what the reader feels, thinks, or experiences::\n  BEFORE: You sense that what you are doing is not the same as drug addiction.\n  AFTER:  Some people sense that what they are doing is not the same as drug addiction.\n\n  BEFORE: You reach for your magnesium gummies every night before bed. If you forget, you feel uneasy.\n  AFTER:  Many people who take magnesium gummies nightly feel uneasy when they miss a dose.\n\n  BEFORE: You take more than the label recommends because you want stronger effects.\n  AFTER:  Some people take more than the label recommends, looking for stronger effects.\n\n  BEFORE: You wonder if any of it is actually helping.\n  AFTER:  It is common to wonder whether any of it is actually helping.\n\n  BEFORE: The thought of stopping triggers a low-grade fear: what if you crash?\n  AFTER:  The thought of stopping can trigger a low-grade fear: what if things get worse?\n  Rule: never write 'you [feel/know/sense/realize/wonder/reach/take/want/notice/worry/think]'. State the observation from outside the reader's head. Use 'some people', 'many people', 'it is common to', or state the fact directly.",
    "shape": "MIXED SECTION ANATOMY:\n  1. FRAMING PARAGRAPH: 2-4 sentences. Ends with short transition.\n  2. BULLET LIST: 3-5 items. Each * **Label:** Summary.\n  3. CLOSING PARAGRAPH: 1-2 sentences. Forward pull, not summary.",
    "bullet": "BULLET QUALITY:\n  WRONG: Prose paragraph with bold labels but no '* ' prefix.\n  RIGHT: '* **Label:** 1-2 sentence summary. Each bullet starts with '* **'.\n  Rule: every bullet in a mixed section starts with '* **'.",
    "clinical": "CLINICAL -> PLAIN ENGLISH:\n  BEFORE: Nature-based interventions demonstrate moderate-to-strong effects on depressive symptomatology.\n  AFTER:  Time outside helps about as much as entry-level talk therapy for depression.\n  Rule: write like a parent at a coffee shop would understand it.",
    "bridge": "BRIDGE TO CARE:\n  1. Heading names destination: 'Professional support at [Clinic]' not 'When to seek help.'\n  2. Universal truth that earns the transition.\n  3. Name specific programs, not 'comprehensive care.'\n  4. Close with invitation, not a command.",
    "safety": "QUALIFIED SAFETY:\n  BEFORE: A safe space for healing.\n  AFTER:  An environment where you feel emotionally safe enough to do the work.\n  Rule: never use bare 'safety'. Qualify: 'emotional safety', 'physical safety'.",
    "cta": "CTA PROGRESSION:\n  BEFORE: Call us now for help.\n  AFTER:  Reach out for a confidential conversation about what level of support fits where you are.\n  Rule: invitation, not command. No urgency language.",
    "paragraph": "PARAGRAPH QUALITY:\n  BEFORE: Long 5+ sentence wall that buries the point.\n  AFTER:  2-3 sentences. One idea each.\n  Rule: split paragraphs longer than 4 sentences. Point-first.",
    "takeaway": "KEY TAKEAWAYS:\n  BEFORE: DBT is a therapy that teaches mindfulness and emotion regulation.\n  AFTER:  DBT teaches four concrete skills. Each targets a different part of the struggle.\n  Rule: one tight sentence. 25 words max. No URLs. No research summaries.",
    "hang": "CLOSE:\n  BEFORE: In conclusion, this approach works well for many people.\n  AFTER:  Hard days still come. The difference is they no longer mean losing everything.\n  Rule: forward pull, not summary. Let the last bullet be the close.",
}


def build_fix_pairs_block(violations_text: str) -> str:
    """Build Karpathy fix pairs for the specific QA violations found in this article."""
    vl = violations_text.lower()
    selected = []
    for keyword, pair in FIX_PAIRS.items():
        if keyword in vl:
            selected.append(pair)
    if not selected:
        selected.append("No specific pairs matched. Fix the listed violations using the article template below.")
    return "\n\n".join(selected)


def extract_repaired_article(output: str) -> str:
    """Extract the fixed article from between [FIXED_ARTICLE_START/END] markers."""
    marker_match = re.search(
        r"\[FIXED(?:_|\s+)ARTICLE(?:_|\s+)START\]\s*(.*?)\s*"
        r"\[FIXED(?:_|\s+)ARTICLE(?:_|\s+)END\]",
        output,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if marker_match:
        candidate = marker_match.group(1).strip()
    else:
        start = re.search(r"(?m)^(?:#\s+\S|\*\*Meta title:\*\*|Meta title:)", output)
        if not start:
            return ""
        prefix = output[:start.start()].strip()
        if prefix:
            return ""
        candidate = output[start.start():].strip()
    if not re.search(r"(?m)^#\s+\S", candidate):
        return ""
    if not re.search(r"(?im)^##\s+Key Takeaways\s*$", candidate):
        return ""
    return deterministic_article_cleanup(candidate).strip()


# ── Section shape validation ──────────────────────────────────────────

def validate_section_shapes(article_with_markers: str) -> list[str]:
    """Check each section's actual structure against its declared shape.
    Uses section markers and inline shape hints. Returns list of violations."""
    violations = []
    sections = re.findall(
        r'<!-- SECTION:h3_(\d{2}):START(.*?)-->\s*(.*?)'
        r'<!-- SECTION:h3_\1:END.*?-->',
        article_with_markers,
        re.DOTALL,
    )
    if not sections and re.search(r"(?m)^###\s+", article_with_markers):
        return ["section markers missing; shape validation could not run"]
    for idx, marker_meta, content in sections:
        shape_hint = re.search(r'Shape:\s*(.+?)(?:\||\n|$)', marker_meta + "\n" + content)
        shape = shape_hint.group(1).strip().lower() if shape_hint else ""
        has_bullets = bool(re.search(r'^\s*\*\s', content, re.M))
        has_numbers = bool(re.search(r'^\s*\d+\.\s', content, re.M))
        has_bold = bool(re.search(r'\*\*.+?\*\*', content))
        if 'mixed' in shape and not has_bullets:
            violations.append(f"h3_{idx}: expected mixed section (bullets), none found")
        if 'scan' in shape and not has_bold:
            violations.append(f"h3_{idx}: expected scan bullets (bold labels), none found")
        if 'number' in shape and not has_numbers:
            violations.append(f"h3_{idx}: expected numbered steps, none found")
        if 'pure' in shape and (has_bullets or has_numbers):
            violations.append(f"h3_{idx}: expected pure prose, found list")
        if 'comparison' in shape and not has_bold:
            violations.append(f"h3_{idx}: expected comparison (paired items), none found")
    return violations


# ── Prompt-level refine rules ─────────────────────────────────────────

def refine_may_can_rule(prompt: str) -> str:
    """Replace the broad 'may/can' rule with a precision rule."""
    old = ('Use qualified reader language (`may`, `can`, `might`) where the situation is uncertain.')
    new = ('Qualify reader circumstances, timelines, and uncertain outcomes. '
           'State well-supported general claims directly — do not over-qualify. '
           'The goal is earned caution, not weak prose.')
    return prompt.replace(old, new)


def refine_your_body_rule(prompt: str) -> str:
    """Replace the broad 'your [body] is' rule with a precision rule."""
    old = ('Hard rule: If a sentence starts with "Your" followed by a body part or emotion '
           '("your heart," "your mouth," "your first reaction") and asserts a feeling, '
           'add "may" or "can" before the verb. "Your heart is pounding" fails. '
           '"Your heart may pound" passes.')
    new = ('Hard rule: Do not assert an unestablished symptom or state as fact '
           '("your body is stuck in fight-or-flight," "your heart is pounding"). '
           'When applying a mechanism to the reader, describe it conditionally: '
           '"your body may enter fight-or-flight mode," "when panic hits, the heart may pound." '
           'Direct statements about the reader\'s current state (describing mechanisms neutrally) '
           'are fine — "Your body releases adrenaline when stressed" is earned, not assumptive.')
    return prompt.replace(old, new)


def add_signaling_exception_rule(prompt: str) -> str:
    """Add quotation exemption to source signaling rule."""
    old = ('PRINCIPLE 1: SOURCE SIGNALING')
    new = ('PRINCIPLE 1: SOURCE SIGNALING (with quotations exemption)\n'
           'Source signaling bans apply to article prose only. Direct quotations, '
           'APA source titles containing "evidence" or "research," and clinical terms '
           '("evidence-based") are exempt. If a phrase is inside quotation marks or is a '
           'source title, the rule does not apply.')
    return prompt.replace(old, new)


# ── Run ──────────────────────────────────────────────────────────────────

# Scanner paths (module-level for import by repair.py)
_SCANNER = Path("/Users/mac/Desktop/Golden writing framework/Active/Clinical_Factory/constraint_scanner.py")
_CONSTRAINTS = Path("/Users/mac/Desktop/Golden writing framework/Active/Clinical_Factory/prompts/constraints_v18.json")


def _run_scan(text: str) -> tuple[dict | None, str | None]:
    """Run constraint scanner on article text. Returns (data, error)."""
    import tempfile
    if not _SCANNER.exists() or not _CONSTRAINTS.exists():
        return None, "scanner not found"
    scan_input = Path(tempfile.mktemp(suffix=".md"))
    try:
        _atomic_write_text(scan_input, text)
        r = subprocess.run(
            [sys.executable, str(_SCANNER), "--draft", str(scan_input),
             "--constraints", str(_CONSTRAINTS),
             "--stage", "writer_output", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        d = json.loads(r.stdout)
        return (d, None) if isinstance(d, dict) and "violations" in d else (None, "incomplete JSON")
    except Exception as e:
        return None, f"scanner error: {e}"
    finally:
        if scan_input.exists():
            scan_input.unlink()


def main():
    parser = argparse.ArgumentParser(description="Golden Writer v2")
    parser.add_argument("--brief", required=True, help="Dumb-down research brief path")
    parser.add_argument("--outline", required=True, help="Outline markdown path")
    parser.add_argument("--topic", required=True, help="Article topic")
    parser.add_argument("--clinic", default="", help="Clinic name")
    parser.add_argument("--output", required=True, help="Output path for article")
    parser.add_argument("--skip-write", action="store_true", help="Assemble prompt only, no Hermes call")
    args = parser.parse_args()

    brief_path = Path(args.brief)
    outline_path = Path(args.outline)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not brief_path.exists():
        print(f"ERROR: Brief not found: {brief_path}", file=sys.stderr); return 1
    if not outline_path.exists():
        print(f"ERROR: Outline not found: {outline_path}", file=sys.stderr); return 1

    dumb_down = brief_path.read_text(encoding="utf-8")
    outline_md = outline_path.read_text(encoding="utf-8")

    # Phase 1: Select pairs
    print("=== PHASE 1: SELECT PAIRS ===")
    selector = Path(__file__).resolve().parent / "pair_selector.py"
    r = subprocess.run([sys.executable, str(selector), "--outline", str(outline_path), "--json"],
                       capture_output=True, text=True, timeout=60)
    data = json.loads(r.stdout) if r.stdout else {}
    pairs_block = data.get("pairs_block", "")
    arch = data.get("summary", {}).get("archetype", "heart")
    pairs_count = data.get("summary", {}).get("pair_count", 0)
    exemplar_label = data.get("summary", {}).get("exemplar", "none")
    print(f"  Archetype: {arch} | Pairs: {pairs_count} | Exemplar: {exemplar_label}")

    # Phase 2: Assemble prompt
    print("=== PHASE 2: ASSEMBLE PROMPT ===")
    section_briefs_block = extract_section_briefs(outline_md)
    exemplar_fragments = get_exemplar_fragments()
    sys.path.insert(0, str(Path(os.path.expanduser("~/.hermes/scripts"))))
    from draft_utils import build_link_list
    curated_links = build_link_list(args.clinic)

    prompt = build_write_prompt(
        dumb_down_brief=dumb_down,
        outline_md=outline_md,
        clinic_name=args.clinic,
        pairs_block=pairs_block,
        exemplar_fragments=exemplar_fragments,
        curated_links=curated_links,
        section_briefs_block=section_briefs_block,
    )
    # Apply prompt-level refine rules
    prompt = refine_may_can_rule(prompt)
    prompt = refine_your_body_rule(prompt)
    prompt = add_signaling_exception_rule(prompt)
    print(f"  Prompt: {len(prompt)} chars")

    if args.skip_write:
        prompt_path = output_path.with_suffix(".prompt.md")
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"\nSaved to {prompt_path} (--skip-write)")
        return 0

    # Phase 3: Write
    print("=== PHASE 3: WRITE (1 Hermes call) ===")
    hermes_bin = str(Path.home() / ".local" / "bin" / "hermes")
    t0 = time.time()
    r = subprocess.run(
        [hermes_bin, "--profile", "research-agent", "-m", "deepseek-v4-flash", "--provider", "deepseek", "-z", prompt],
        capture_output=True, text=True, timeout=600,
    )
    elapsed = time.time() - t0
    process_ok = r.returncode == 0
    print(f"  Hermes: {'OK' if process_ok else 'FAIL'} in {elapsed:.1f}s, {len(r.stdout.strip())} stdout chars")
    if not process_ok:
        print(f"  STDERR: {r.stderr[:300]}", file=sys.stderr)
        return 1

    article = r.stdout.strip()
    # The writer-agent may save to disk instead of stdout.
    # Only look for a file if stdout was empty.
    if not article:
        import glob
        output_dir = output_path.parent
        recent_md = sorted(
            (p for p in output_dir.glob("*.md") if p.stat().st_mtime >= t0 - 2),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for candidate in recent_md:
            if candidate.stat().st_size > 5000 and candidate.name != output_path.name:
                article = candidate.read_text(encoding="utf-8")
                print(f"  Found article file: {candidate.name} ({len(article)} chars)")
                break
    else:
        print(f"  Using stdout ({len(article)} chars)")
    # Check cwd too — model sometimes saves there instead of stdout
    if not article:
        import glob
        topic_slug = args.topic.lower().replace(" ", "-")[:50]
        cwd_candidates = sorted(
            (p for p in Path.cwd().glob(f"*{topic_slug}*.md") if p.stat().st_mtime >= t0 - 2),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for candidate in cwd_candidates:
            if candidate.stat().st_size > 5000:
                article = candidate.read_text(encoding="utf-8")
                print(f"  Found cwd file: {candidate.name} ({len(article)} chars)")
                break
    if len(article.strip()) <= 100:
        print("ERROR: Hermes returned no usable article text", file=sys.stderr)
        return 1
    artifact_stem = output_path.stem
    raw_path = output_path.with_name(f"{artifact_stem}.raw.md")
    cleaned_path = output_path.with_name(f"{artifact_stem}.cleaned.md")
    compiled_path = output_path.with_name(f"{artifact_stem}.compiled.md")
    qa_initial_path = output_path.with_name(f"{artifact_stem}.qa.initial.json")
    qa_final_path = output_path.with_name(f"{artifact_stem}.qa.final.json")

    raw_checkpoint = _write_checkpoint(raw_path, article)
    print(f"  Raw checkpoint: {raw_checkpoint}")

    # Phase 3b: QA scan — report only
    print("\n=== PHASE 3b: QA SCAN ===\n")
    review_required = False
    article = deterministic_article_cleanup(article)
    _write_checkpoint(cleaned_path, article)

    scan, err = _run_scan(article)
    if scan is None:
        review_required = True
        print(f"  ⚠️ {err}")
    else:
        _atomic_write_text(qa_initial_path, json.dumps(scan, indent=2))
        v = scan.get("violations", [])
        e = int(scan.get("error_count", 0) or 0)
        ed = len([x for x in v if _scan_classification(x) == "EDITORIAL"])
        sa = len([x for x in v if _scan_classification(x) == "SAFETY"])
        st = len([x for x in v if _scan_classification(x) == "STRUCTURAL"])
        print(f"  Scan: {e} total — {sa} safety, {st} structural, {ed} editorial")
        if sa > 0 or st > 0:
            review_required = True
    print("=== PHASE 4: COMPILE ARTICLE ===")
    # Run shape validation before compile (needs section markers still intact)
    shape_violations = validate_section_shapes(article)
    if shape_violations:
        review_required = True
        print(f"  ⚠️ {len(shape_violations)} shape violations:")
        for v in shape_violations[:5]:
            print(f"    - {v}")
        if len(shape_violations) > 5:
            print(f"    ... and {len(shape_violations) - 5} more")
    else:
        print(f"  ✅ All sections match their declared shapes")
    article = compile_article(article, dumb_down, {})
    _write_checkpoint(compiled_path, article)
    
    # ── Save final article ──
    output_path.write_text(article, encoding="utf-8")
    print(f"  Final article: {len(article)} chars")

    print(f"\n{'='*50}")
    print(f"DONE in {elapsed:.1f}s — {len(article)} chars")
    print(f"{'='*50}")
    if review_required:
        print("REVIEW_REQUIRED: usable article saved, but safety/structure checks need review")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
