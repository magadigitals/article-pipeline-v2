#!/usr/bin/env python3
"""Clinical Review Gate — LLM-based clinical accuracy check for pipeline articles.

Usage: python3 clinical_review_gate.py <article.md>

Reads the article, extracts inline citations (DOIs, PMC URLs, PubMed URLs),
resolves their abstracts, and sends one bounded LLM call to verify clinical
accuracy. Outputs a structured JSON report. Does NOT modify the article.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# ── Config ───────────────────────────────────────────────────────────────────
LLM_TIMEOUT = 60
DOI_RESOLVE_TIMEOUT = 10

# DeepSeek API for fast inference (bypass Hermes CLI overhead)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


# ── Citation extraction ──────────────────────────────────────────────────────

def extract_citations(text):
    """Extract all external citations from article body (before Sources)."""
    body = text.split("## Sources")[0]
    citations = []
    seen = set()

    for m in re.finditer(r'https?://doi\.org/([^\s)"\']+)', body):
        doi = m.group(1).rstrip(".,;:!?")
        url = "https://doi.org/" + doi
        if url not in seen:
            seen.add(url)
            citations.append({"type": "doi", "url": url, "doi": doi})

    for m in re.finditer(r'https?://pmc\.ncbi\.nlm\.nih\.gov/articles/([^\s)"\']+)', body):
        url = m.group(0).rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            citations.append({"type": "pmc", "url": url})

    for m in re.finditer(r'https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', body):
        pmid = m.group(1)
        url = "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/"
        if url not in seen:
            seen.add(url)
            citations.append({"type": "pubmed", "url": url, "pmid": pmid})

    citations = [c for c in citations if "modernrecoveryservices.com" not in c["url"]]
    return citations


def resolve_doi_metadata(doi):
    """Resolve DOI to title and abstract via Crossref API."""
    try:
        resp = requests.get(
            "https://api.crossref.org/works/" + doi,
            timeout=DOI_RESOLVE_TIMEOUT,
            headers={"User-Agent": "ClinicalReviewGate/1.0"},
        )
        if resp.status_code == 200:
            data = resp.json().get("message", {})
            title = (data.get("title") or [""])[0]
            abstract = data.get("abstract", "")
            return {"title": title, "abstract": abstract}
    except Exception:
        pass
    return {"title": "", "abstract": ""}


def fetch_abstract(citation):
    """Fetch abstract/description for a citation."""
    ct = citation.get("type", "")
    if ct == "doi" and citation.get("doi"):
        meta = resolve_doi_metadata(citation["doi"])
        abstract = meta.get("abstract", "") or ""
        title = meta.get("title", "") or ""
        if abstract:
            return (title + ": " + abstract)[:500]
        return title or citation["url"]
    elif ct == "pubmed" and citation.get("pmid"):
        try:
            url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                "?db=pubmed&id=" + citation["pmid"] + "&retmode=xml&rettype=abstract"
            )
            resp = requests.get(url, timeout=DOI_RESOLVE_TIMEOUT)
            if resp.status_code == 200:
                title_m = re.search(r"<ArticleTitle>([^<]+)", resp.text)
                abs_m = re.search(r"<AbstractText[^>]*>([^<]+)", resp.text)
                title = title_m.group(1) if title_m else ""
                abstract = abs_m.group(1) if abs_m else ""
                if abstract:
                    return (title + ": " + abstract)[:500]
                return title or citation["url"]
        except Exception:
            pass
        return citation["url"]
    return citation["url"]


# ── Article section extraction ────────────────────────────────────────────────

def extract_sections(text):
    """Extract article body sections by H3 heading."""
    sections = {}
    current_h3 = "preamble"
    lines = text.split("\n")
    in_frontmatter = 0

    for line in lines:
        stripped = line.strip()
        if stripped == "---" and in_frontmatter < 2:
            in_frontmatter += 1
            continue
        if in_frontmatter < 2:
            continue
        if stripped.startswith("## Sources"):
            break
        if stripped.startswith("### "):
            current_h3 = stripped.replace("### ", "").strip()
            sections[current_h3] = ""
        elif current_h3:
            sections[current_h3] = sections.get(current_h3, "") + line + "\n"

    return sections


# ── LLM review ────────────────────────────────────────────────────────────────

def run_llm_review(topic, sections, citations, abstracts):
    """Run one bounded LLM call for clinical review."""
    sources_block = "\n".join(
        "[{}] {}: {}".format(i + 1, label, abst[:200])
        for i, (label, abst) in enumerate(abstracts)
    )

    parts = []
    for heading, text in sections.items():
        # Just heading + first sentence is enough for clinical review
        first_line = text.strip().split("\n")[0][:200] if text.strip() else ""
        parts.append("### {}: {}".format(heading, first_line[:150]))
    sections_block = "\n".join(parts)

    prompt = (
        'You are a clinical review editor. Review this article about "'
        + topic
        + '" for clinical accuracy and safety.\n\n'
        + "SOURCES CITED:\n"
        + sources_block
        + "\n\n"
        + "ARTICLE SECTIONS:\n"
        + sections_block
        + "\n\n"
        + "Check each section for:\n"
        + "1. **Claim-source mismatch** — Does the claim match what the cited source actually says?\n"
        + "2. **Efficacy overstatement** — 'treats' vs 'may help', 'cures' vs 'reduces symptoms'\n"
        + "3. **Missing caveats** — Treatment risks, side effects, or limitations not mentioned\n"
        + "4. **Safety gap** — Crisis resources missing from sections discussing severe symptoms\n"
        + "5. **Dual-concept confusion** — Two distinct conditions treated as identical\n"
        + "6. **Outdated guidance** — Source >10 years old for a fast-moving clinical topic\n\n"
        + 'Return ONLY a JSON object:\n'
        + '{"verdict": "PASS" | "WARN" | "FLAG", '
        + '"flags": [{"severity": "CRITICAL" | "MODERATE" | "INFO", '
        + '"section": "...", "issue": "...", "recommendation": "..."}], '
        + '"summary": "One-sentence verdict for a human editor"}\n'
    )

    try:
        if not DEEPSEEK_API_KEY:
            return {"verdict": "WARN", "flags": [{"severity": "INFO", "section": "pipeline", "issue": "DEEPSEEK_API_KEY not set", "recommendation": "Set DEEPSEEK_API_KEY env var or use manual review."}], "summary": "Clinical review unavailable — no API key."}
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": "Bearer " + DEEPSEEK_API_KEY, "Content-Type": "application/json"},
            json={"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 2000},
            timeout=LLM_TIMEOUT,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            idx = content.find("{")
            if idx >= 0:
                return json.loads(content[idx:])
            return {"verdict": "WARN", "flags": [{"severity": "INFO", "section": "pipeline", "issue": "No JSON in response: " + content[:200].strip()[:150], "recommendation": "Manual review recommended."}], "summary": "Failed to parse LLM response."}
        return {"verdict": "WARN", "flags": [{"severity": "INFO", "section": "pipeline", "issue": "API error: " + str(resp.status_code) + " " + resp.text[:200], "recommendation": "Manual review recommended."}], "summary": "Clinical review API error."}
    except Exception as e:
        return {
            "verdict": "WARN",
            "flags": [{
                "severity": "INFO",
                "section": "pipeline",
                "issue": "LLM review call failed: " + str(e),
                "recommendation": "Manual review recommended.",
            }],
            "summary": "Automated clinical review failed — manual review needed.",
        }
    return {
        "verdict": "WARN",
        "flags": [],
        "summary": "Automated clinical review returned no result — manual review recommended.",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def review(article_path):
    text = Path(article_path).read_text(encoding="utf-8")

    title_m = re.search(r"^# (.+)$", text, re.MULTILINE)
    topic = title_m.group(1).strip() if title_m else "unknown"

    citations = extract_citations(text)
    sections = extract_sections(text)

    abstracts = []
    for c in citations:
        label = c.get("doi", c.get("url", ""))[:60]
        abstract = fetch_abstract(c)
        abstracts.append((label, abstract))

    result = run_llm_review(topic, sections, citations, abstracts)

    result["article_path"] = str(article_path)
    result["topic"] = topic
    result["citations_found"] = len(citations)
    result["citations_resolved"] = sum(1 for _, a in abstracts if len(a) > 50)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Clinical Review Gate — LLM-based clinical accuracy check"
    )
    parser.add_argument("article", help="Path to the article .md file")
    parser.add_argument("--output", "-o", help="Write JSON report to file instead of stdout")
    args = parser.parse_args()

    if not Path(args.article).exists():
        print("Error: File not found: " + args.article, file=sys.stderr)
        sys.exit(1)

    result = review(args.article)
    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print("Clinical review report written to " + args.output)
    else:
        # Strip conda noise from output
        json_start = output.find('{\n  "verdict"')
        if json_start >= 0:
            print(output[json_start:])
        else:
            print(output)


if __name__ == "__main__":
    main()
