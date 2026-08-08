#!/usr/bin/env python3
"""Prune the Sources section to only include URLs cited inline in the article body.

Usage: python3 prune_sources.py <article.md>

The Sources section is part of the output article but the LLM writer sometimes
copies the entire research-brief source list into it, including sources never
cited in the article body. This script removes those dangling entries.

A "cited inline" URL is any URL that appears in the article body (before
## Sources) as an inline hyperlink like [text](url) or as a bare URL.
Internal modernrecoveryservices.com URLs are excluded from the check
(they're clinic links, not evidence citations).
"""

import re
import sys
from pathlib import Path


def extract_inline_urls(text: str) -> set[str]:
    """Extract all external URLs from article body text."""
    urls: set[str] = set()
    # Markdown inline links [text](url)
    for m in re.finditer(r'\]\(https?://([^\)]+)\)', text):
        urls.add(f"https://{m.group(1)}")
    # Bare URLs
    for m in re.finditer(r'(?<![\(\[])(https?://[^\s)"]+)', text):
        urls.add(m.group(1).rstrip(".,;:!?"))
    # DOI links
    for m in re.finditer(r'doi\.org/([^\s)"\']+)', text):
        urls.add(f"https://doi.org/{m.group(1)}")
    return urls


def prune_sources(article_path: Path) -> int:
    text = article_path.read_text(encoding="utf-8")

    # Split at ## Sources
    if "## Sources" not in text:
        return 0

    body, sources_section = text.split("## Sources", 1)

    # Extract inline URLs from body only
    inline_urls = extract_inline_urls(body)

    # Parse Sources section entries — each line starting with *
    source_lines = sources_section.split("\n")
    pruned: list[str] = []
    removed = 0

    for line in source_lines:
        stripped = line.strip()
        if not stripped.startswith("* "):
            pruned.append(line)
            continue
        # Extract URL from the entry
        url_match = re.search(r'(https?://[^\s)]+)', stripped)
        if not url_match:
            pruned.append(line)
            continue
        entry_url = url_match.group(1).rstrip(")")
        # Keep if cited inline OR if it's an internal MRS link
        if entry_url in inline_urls or "modernrecoveryservices.com" in entry_url:
            pruned.append(line)
        else:
            removed += 1

    if removed == 0:
        return 0

    new_text = text.split("## Sources")[0] + "## Sources" + "\n".join(pruned)
    Path(article_path).write_text(new_text, encoding="utf-8")
    return removed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 prune_sources.py <article.md>")
        sys.exit(1)
    article = Path(sys.argv[1])
    if not article.exists():
        print(f"File not found: {article}")
        sys.exit(1)
    removed = prune_sources(article)
    if removed:
        print(f"Pruned {removed} un-cited sources from {article.name}")
    else:
        print(f"No pruning needed for {article.name}")
