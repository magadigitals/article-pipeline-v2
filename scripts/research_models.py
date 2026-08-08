"""Dataclass models for the 4-stage research pipeline.

Each model has a strict from_dict constructor that validates required
fields and types. No Pydantic dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PubMedArticle:
    """A single PubMed article with key metadata."""

    pmid: str
    title: str
    authors: list[str]
    journal: str
    year: str
    doi: str
    abstract: str
    publication_type: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> PubMedArticle:
        pmid = str(data.get("pmid") or "").strip()
        if not pmid:
            raise ValueError("PubMedArticle.pmid is required")
        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("PubMedArticle.title is required")
        authors = data.get("authors", [])
        if not isinstance(authors, list):
            authors = [str(authors)]
        authors = [str(a).strip() for a in authors if a]
        return cls(
            pmid=pmid,
            title=title,
            authors=authors,
            journal=str(data.get("journal") or "").strip(),
            year=str(data.get("year") or "").strip(),
            doi=str(data.get("doi") or "").strip(),
            abstract=str(data.get("abstract") or "").strip(),
            publication_type=list(data.get("publication_type", [])),
        )


@dataclass
class SectionSearchResult:
    """PubMed results for one outline H3 section."""

    heading: str
    search_term: str
    pmids: list[str]
    articles: list[PubMedArticle] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> SectionSearchResult:
        heading = str(data.get("heading") or "").strip()
        if not heading:
            raise ValueError("SectionSearchResult.heading is required")
        pmids = list(data.get("pmids", []))
        articles_raw = data.get("articles", [])
        articles = [PubMedArticle.from_dict(a) for a in articles_raw] if articles_raw else []
        return cls(
            heading=heading,
            search_term=str(data.get("search_term") or "").strip(),
            pmids=pmids,
            articles=articles,
        )


@dataclass
class PubMedEvidenceResult:
    """Complete PubMed evidence packet for an article."""

    topic: str
    expanded_topic: str
    section_results: list[SectionSearchResult]
    total_pmids: int
    search_queries_used: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> PubMedEvidenceResult:
        topic = str(data.get("topic") or "").strip()
        if not topic:
            raise ValueError("PubMedEvidenceResult.topic is required")
        sections_raw = data.get("section_results", [])
        sections = [SectionSearchResult.from_dict(s) for s in sections_raw] if sections_raw else []
        total = int(data.get("total_pmids", 0))
        return cls(
            topic=topic,
            expanded_topic=str(data.get("expanded_topic") or ""),
            section_results=sections,
            total_pmids=total,
            search_queries_used=list(data.get("search_queries_used", [])),
        )


@dataclass
class AuthoritySource:
    """A single high-authority web source (gov/edu/org)."""

    url: str
    title: str
    domain: str
    relevance: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> AuthoritySource:
        url = str(data.get("url") or "").strip()
        if not url:
            raise ValueError("AuthoritySource.url is required")
        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("AuthoritySource.title is required")
        domain = str(data.get("domain") or url.split("/")[2] if "//" in url else url).strip()
        return cls(
            url=url,
            title=title,
            domain=domain,
            relevance=str(data.get("relevance") or "").strip()[:200],
        )


@dataclass
class WebSourceResult:
    """Results from high-authority web source search."""

    topic: str
    sources: list[AuthoritySource]
    total_found: int

    @classmethod
    def from_dict(cls, data: dict) -> WebSourceResult:
        topic = str(data.get("topic") or "").strip()
        if not topic:
            raise ValueError("WebSourceResult.topic is required")
        sources_raw = data.get("sources", [])
        sources = [AuthoritySource.from_dict(s) for s in sources_raw] if sources_raw else []
        return cls(
            topic=topic,
            sources=sources,
            total_found=int(data.get("total_found", len(sources))),
        )


@dataclass
class ClinicalBriefResult:
    """The clinical research brief produced by Stage 3."""

    topic: str
    brief_markdown: str

    @classmethod
    def from_dict(cls, data: dict) -> ClinicalBriefResult:
        topic = str(data.get("topic") or "").strip()
        brief = str(data.get("brief_markdown") or data.get("brief", "")).strip()
        if not brief:
            raise ValueError("ClinicalBriefResult: brief_markdown is required")
        if not topic:
            topic = "clinical research brief"
        return cls(topic=topic, brief_markdown=brief)


@dataclass
class DumbedDownResult:
    """The dumbed-down (Grade 8) brief produced by Stage 4."""

    topic: str
    brief_markdown: str

    @classmethod
    def from_dict(cls, data: dict) -> DumbedDownResult:
        topic = str(data.get("topic") or "").strip()
        brief = str(data.get("brief_markdown") or data.get("brief", "")).strip()
        if not brief:
            raise ValueError("DumbedDownResult: brief_markdown is required")
        if not topic:
            topic = "dumbed down brief"
        return cls(topic=topic, brief_markdown=brief)
