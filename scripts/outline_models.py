"""Strict dataclass models for the 3-stage outline pipeline.

Each model has a from_dict classmethod that validates required fields
and types on construction — no Pydantic dependency needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─── Stage 1: Source Discovery ────────────────────────────────────────────────


@dataclass
class Competitor:
    url: str
    title: str
    domain: str
    relevance: str

    @classmethod
    def from_dict(cls, data: dict) -> Competitor:
        for field_name in ("url", "title", "domain", "relevance"):
            val = data.get(field_name)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"Competitor.{field_name} must be a non-empty string, got {val!r}")
        return cls(
            url=data["url"].strip(),
            title=data["title"].strip(),
            domain=data["domain"].strip(),
            relevance=data["relevance"].strip(),
        )


@dataclass
class SourceDiscoveryResult:
    competitors: list[Competitor] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> SourceDiscoveryResult:
        raw = data.get("competitors")
        if not isinstance(raw, list) or not raw:
            raise ValueError("SourceDiscoveryResult.competitors must be a non-empty list")
        return cls(competitors=[Competitor.from_dict(c) for c in raw])


# ─── Stage 2: Competitor Extraction ────────────────────────────────────────────


@dataclass
class ExtractedHeading:
    level: int
    text: str

    @classmethod
    def from_dict(cls, data: dict) -> ExtractedHeading:
        level = data.get("level")
        text = data.get("text")
        if not isinstance(level, int) or level not in (1, 2, 3, 4, 5, 6):
            raise ValueError(f"ExtractedHeading.level must be 1-6, got {level!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"ExtractedHeading.text must be a non-empty string, got {text!r}")
        return cls(level=level, text=text.strip())


@dataclass
class ExtractedPage:
    url: str
    headings: list[ExtractedHeading] = field(default_factory=list)
    key_topics: list[str] = field(default_factory=list)
    notable_points: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> ExtractedPage:
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"ExtractedPage.url must be a non-empty string, got {url!r}")
        raw_headings = data.get("headings", [])
        if not isinstance(raw_headings, list):
            raise ValueError("ExtractedPage.headings must be a list")
        return cls(
            url=url.strip(),
            headings=[ExtractedHeading.from_dict(h) for h in raw_headings],
            key_topics=[str(t) for t in data.get("key_topics", []) if t],
            notable_points=[str(p) for p in data.get("notable_points", []) if p],
        )


@dataclass
class ExtractionFailure:
    url: str
    reason: str

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionFailure:
        url = data.get("url", "")
        reason = data.get("reason", "")
        return cls(url=str(url).strip(), reason=str(reason).strip())


@dataclass
class ExtractionResult:
    pages: list[ExtractedPage] = field(default_factory=list)
    failures: list[ExtractionFailure] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionResult:
        raw_pages = data.get("pages", [])
        raw_failures = data.get("failures", [])
        if not isinstance(raw_pages, list):
            raise ValueError("ExtractionResult.pages must be a list")
        return cls(
            pages=[ExtractedPage.from_dict(p) for p in raw_pages],
            failures=[ExtractionFailure.from_dict(f) for f in raw_failures] if isinstance(raw_failures, list) else [],
        )


# ─── Stage 3: Outline Synthesis ────────────────────────────────────────────────


@dataclass
class Subsection:
    heading: str
    type_field: str = ""
    depth: str = ""
    shape: str = ""
    claims: list[str] = field(default_factory=list)
    model: str = ""
    fail: str = ""
    pass_field: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Subsection:
        heading = data.get("heading")
        if not isinstance(heading, str) or not heading.strip():
            raise ValueError(f"Subsection.heading must be a non-empty string, got {heading!r}")
        claims = data.get("claims", [])
        if not isinstance(claims, list):
            claims = []
        return cls(
            heading=heading.strip(),
            type_field=str(data.get("type") or data.get("type_field") or ""),
            depth=str(data.get("depth") or ""),
            shape=str(data.get("shape") or ""),
            claims=[str(c) for c in claims if c],
            model=str(data.get("model") or ""),
            fail=str(data.get("fail") or ""),
            pass_field=str(data.get("pass") or data.get("pass_field") or ""),
        )


@dataclass
class OutlineSection:
    heading: str
    purpose: str = ""
    type_field: str = ""
    depth: str = ""
    shape: str = ""
    claims: list[str] = field(default_factory=list)
    model: str = ""
    fail: str = ""
    pass_field: str = ""
    subsections: list[Subsection] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> OutlineSection:
        heading = data.get("heading")
        if not isinstance(heading, str) or not heading.strip():
            raise ValueError(f"OutlineSection.heading must be a non-empty string, got {heading!r}")
        raw_subs = data.get("subsections", [])
        claims = data.get("claims", [])
        if not isinstance(claims, list):
            claims = []
        return cls(
            heading=heading.strip(),
            purpose=str(data.get("purpose") or data.get("opener_direction") or ""),
            type_field=str(data.get("type") or data.get("type_field") or ""),
            depth=str(data.get("depth") or ""),
            shape=str(data.get("shape") or ""),
            claims=[str(c) for c in claims if c],
            model=str(data.get("model") or ""),
            fail=str(data.get("fail") or ""),
            pass_field=str(data.get("pass") or data.get("pass_field") or ""),
            subsections=[Subsection.from_dict(s) for s in raw_subs] if isinstance(raw_subs, list) else [],
        )


@dataclass
class OutlineResult:
    search_intent: dict = field(default_factory=dict)
    recommended_title: str = ""
    meta_title: str = ""
    meta_description: str = ""
    outline: list[OutlineSection] = field(default_factory=list)
    content_gaps: list[str] = field(default_factory=list)
    differentiation: list[str] = field(default_factory=list)
    target_word_count: int = 0
    scope_rationale: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> OutlineResult:
        raw_outline = data.get("outline", [])
        if not isinstance(raw_outline, list) or not raw_outline:
            raise ValueError("OutlineResult.outline must be a non-empty list")
        meta_description = str(data.get("meta_description") or "").strip()
        if len(meta_description) > 160:
            # Length is deterministic formatting, not editorial judgment. Trim
            # at a word boundary so a model that returns 168 chars does not cost
            # another full synthesis call.
            shortened = meta_description[:160].rsplit(" ", 1)[0].rstrip(" ,;:-")
            if len(shortened) >= 139:
                meta_description = shortened.rstrip(".") + "."
        return cls(
            search_intent=dict(data.get("search_intent", {})),
            recommended_title=str(data.get("recommended_title") or data.get("meta_title") or ""),
            meta_title=str(data.get("meta_title") or ""),
            meta_description=meta_description,
            outline=[OutlineSection.from_dict(s) for s in raw_outline],
            content_gaps=[str(g) for g in data.get("content_gaps", []) if g],
            differentiation=[str(d) for d in data.get("differentiation", []) if d],
            target_word_count=int(data.get("target_word_count") or 0),
            scope_rationale=str(data.get("scope_rationale") or "").strip(),
        )
