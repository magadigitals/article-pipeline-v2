"""3-stage outline pipeline runner.

Each stage is a narrow Hermes call with structured JSON output,
separate validation, and corrective retry logic.

Usage from worker.py:
    from outline_pipeline import run_outline_pipeline
    artifact = run_outline_pipeline(topic=..., db=db, article_id=...)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

import cloudscraper

import requests

from outline_models import (
    ExtractionResult,
    OutlineResult,
    SourceDiscoveryResult,
)
from outline_prompts import (
    COMPETITOR_EXTRACTION_PROMPT,
    OUTLINE_SYNTHESIS_PROMPT,
)
from outline_validators import (
    ValidationResult,
    parse_json_response,
    validate_extraction,
    validate_outline,
    validate_sources,
)

PIPELINE_VERSION = "outline-v1"

# Import these from worker.py at runtime
HERMES_BIN: Path | None = None
MODEL: str = "deepseek-v4-flash"
PROVIDER: str = "deepseek"
DB_PATH: Path | None = None
HERMES_SCRIPTS: Path | None = None

# ── Available benchmark model notes for section brief Model fields ──
MODEL_NOTES_DIR = Path.home() / "Desktop" / "Golden writing framework" / "Active" / "Evals" / "article_quality" / "external_benchmark" / "model_notes"
LOCAL_CLINIC_PROFILES_DIR = Path(__file__).resolve().parent / "clinic_profiles"
PROJECT_CLINIC_PROFILES_DIR = Path.home() / "Desktop" / "Golden writing framework" / "Active" / "Clinical_Factory" / "clinic_profiles"


def load_clinic_prompt_context(clinic_name: str) -> str:
    """Load the selected clinic profile without hardcoding one clinic in the prompt.

    Resolution order makes the outline worker portable: an environment override,
    profiles shipped beside the script, then the Golden project profiles.
    """
    configured = os.environ.get("GOLDEN_CLINIC_PROFILES_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend((LOCAL_CLINIC_PROFILES_DIR, PROJECT_CLINIC_PROFILES_DIR))

    wanted = clinic_name.casefold().strip()
    for directory in candidates:
        if not directory.is_dir():
            continue
        for profile_path in sorted(directory.glob("*.json")):
            try:
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            names = [profile.get("name", ""), *profile.get("aliases", [])]
            if wanted not in {str(name).casefold().strip() for name in names if name}:
                continue
            lines = [
                f"Name: {profile.get('name', clinic_name)}",
                f"Primary audience: {profile.get('primary_audience', 'Not specified')}",
                f"Service model: {profile.get('service_model', 'Not specified')}",
                f"Positioning: {profile.get('positioning', 'Not specified')}",
                f"Bridge to care: {profile.get('default_bridge_to_care_angle', 'Use a factual, low-pressure next step')}",
            ]
            offers = profile.get("core_offers", [])
            if offers:
                lines.append("Supported offers: " + "; ".join(str(item) for item in offers))
            allowed = profile.get("allowed_claims", [])
            if allowed:
                lines.append("Allowed claims: " + "; ".join(str(item) for item in allowed))
            banned = profile.get("banned_claims", [])
            if banned:
                lines.append("Banned claims: " + "; ".join(str(item) for item in banned))
            return "\n".join(lines)

    return (
        f"Name: {clinic_name}\n"
        "Profile status: No matching clinic profile found.\n"
        "Boundary: Keep clinic references generic. Do not invent audience, "
        "programs, locations, insurance, availability, outcomes, or treatment fit."
    )


def load_model_note_summaries() -> str:
    """Read model note files and return a compact summary of each.

    Each entry shows the filename, category, Use When, Craft Move,
    and What This Prevents — so the outline agent can reference
    actual benchmark content, not guess.
    """
    if not MODEL_NOTES_DIR.exists():
        return "No model notes available."

    summaries = []
    for f in sorted(MODEL_NOTES_DIR.iterdir()):
        if not f.suffix == ".md":
            continue
        text = f.read_text(encoding="utf-8")
        lines = text.split("\n")

        name = f.stem
        category = ""
        use_when = ""
        craft_move = ""
        prevents = ""

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- Category:"):
                category = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- Best used for:"):
                use_when = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- The benchmark move"):
                craft_move = stripped.lstrip("- ").strip()
            elif stripped.startswith("- The Golden move"):
                if craft_move:
                    craft_move += " | " + stripped.lstrip("- ").strip()
            elif stripped.startswith("- Prevents"):
                if not prevents:
                    prevents = stripped.lstrip("- ").strip()

        summaries.append(f"- **{name}** [{category}]: {craft_move}")
        if use_when:
            summaries.append(f"  Use: {use_when[:120]}")
        if prevents:
            summaries.append(f"  Prevents: {prevents[:120]}")

    return "\n".join(summaries) if summaries else "No model notes found."


def configure_pipeline(hermes_bin: Path, model: str, provider: str, db_path: Path, hermesscripts: Path) -> None:
    global HERMES_BIN, MODEL, PROVIDER, DB_PATH, HERMES_SCRIPTS
    HERMES_BIN = hermes_bin
    MODEL = model
    PROVIDER = provider
    DB_PATH = db_path
    HERMES_SCRIPTS = hermesscripts


# ─── Stage Callers ─────────────────────────────────────────────────────────────


def _hermes_call(
    profile: str,
    skills: list[str],
    prompt: str,
    timeout: int = 300,
) -> tuple[bool, str, str]:
    """Direct Hermes CLI call — mirrors worker.py's hermes_call()."""
    if not HERMES_BIN or not HERMES_BIN.exists():
        return False, "", f"Hermes executable not found at {HERMES_BIN}"

    skill_args = " ".join(f"-s {shlex.quote(s)}" for s in skills) if skills else ""
    profile_flag = f"--profile {shlex.quote(profile)}" if profile else ""
    model_flags = f" -m {shlex.quote(MODEL)} --provider {shlex.quote(PROVIDER)}"
    prompt_quoted = shlex.quote(prompt)

    cmd = (
        f"CONDA_NO_PLUGINS=true {shlex.quote(str(HERMES_BIN))} "
        f"{profile_flag} {skill_args} -z {prompt_quoted}{model_flags}"
    )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "")[:2000]
            return False, result.stdout.strip(), f"Hermes exited {result.returncode}: {error}"
        output = result.stdout.strip()
        if not output:
            return False, "", "Hermes returned empty output"
        return True, output, ""
    except subprocess.TimeoutExpired:
        return False, "", f"Hermes timed out after {timeout}s"
    except Exception as exc:
        return False, "", f"Hermes call failed: {exc}"


def _call_serpapi(input_data: dict, previous_errors: list[str] | None = None) -> str:
    """Stage 1: call SERPAPI directly for organic search results.

    Returns: filtered organic competitors, People Also Asked questions,
    and related searches. Filters out Wikipedia, Reddit, Quora, forums,
    research papers, and other non-article sources.
    """
    topic = input_data["topic"]
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_KEY environment variable is not set")

    query = topic
    if previous_errors:
        query = topic

    resp = requests.get(
        "https://serpapi.com/search",
        params={
            "q": query,
            "api_key": api_key,
            "engine": "google",
            "num": 10,
            "source": "web",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"SERPAPI returned error: {data['error']}")

    organic = data.get("organic_results", [])
    if not organic:
        raise RuntimeError(f"SERPAPI returned 0 organic results for query: {query}")

    # Domains/paths to filter out (non-article sources)
    exclude_domains = [
        "wikipedia.org", "reddit.com", "quora.com",
        "facebook.com", "twitter.com", "instagram.com",
        "youtube.com", "tiktok.com", "pinterest.com",
        "webmd.com",  # questionable authority
    ]
    exclude_paths = ["/forum", "/forums", "/discuss", "/questions/"]

    competitors = []
    filtered_count = 0
    for r in organic:
        url = (r.get("link") or "").strip()
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "")[:200]
        if not url or not title:
            continue

        domain = url.split("/")[2] if "//" in url else url

        # Filter unwanted sources
        skip = False
        for ex in exclude_domains:
            if ex in domain:
                skip = True
                break
        if not skip:
            for ex in exclude_paths:
                if ex in url.lower():
                    skip = True
                    break
        # Skip research papers (.gov research sites, PubMed links)
        if "pubmed.ncbi" in url or "ncbi.nlm" in url or "scholar.google" in url:
            skip = True

        if skip:
            filtered_count += 1
            continue

        competitors.append({
            "url": url,
            "title": title,
            "domain": domain,
            "relevance": snippet,
        })

    if not competitors:
        raise RuntimeError(
            f"SERPAPI returned {len(organic)} results but all were filtered "
            f"(Wikipedia, forums, research, etc.). Try a more specific topic."
        )

    # Extract People Also Asked questions
    paa_questions = []
    for item in data.get("people_also_ask", []):
        q = (item.get("question") or "").strip()
        if q:
            paa_questions.append(q)

    # Extract related searches
    related_searches = []
    for item in data.get("related_searches", []):
        q = (item.get("query") or "").strip()
        if q:
            related_searches.append(q)

    result = {
        "competitors": competitors,
        "paa_questions": paa_questions,
        "related_searches": related_searches,
        "filtered_count": filtered_count,
    }
    return json.dumps(result)


def _call_competitor_extraction(input_data: dict, previous_errors: list[str] | None = None) -> str:
    """Stage 2: fetch competitor pages with Python and extract headings.

    Uses requests + BeautifulSoup. No Hermes call — this is deterministic,
    fast (~2-3s per page), and more reliable than an agent browsing.
    """
    urls = input_data.get("competitors", [])
    if not urls:
        raise RuntimeError("No competitor URLs to extract")
    if previous_errors:
        # On retry, only retry failed URLs
        pass

    pages = []
    failures = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    session = requests.Session()
    session.headers.update(headers)
    # cloudscraper for sites that block standard requests (Cloudflare, etc.)
    scraper = cloudscraper.create_scraper()

    for url in urls:
        # Try twice per URL in case of transient failure
        extracted = None
        last_error = None
        for attempt in range(2):
            try:
                if attempt == 0:
                    resp = session.get(url, timeout=15)
                else:
                    # Second attempt: use cloudscraper for Cloudflare-blocked sites
                    resp = scraper.get(url, timeout=20)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                # Extract headings
                # Extract headings
                headings = []
                for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    for el in soup.find_all(tag):
                        text = el.get_text(strip=True)
                        if text:
                            headings.append({
                                "level": int(tag[1]),
                                "text": text,
                            })

                # Extract page title
                title_tag = soup.find("title")
                page_title = title_tag.get_text(strip=True) if title_tag else url

                # Extract meta description
                meta_desc = soup.find("meta", attrs={"name": "description"})
                description = meta_desc.get("content", "") if meta_desc else ""
                key_topics = []
                for h in headings[:6]:
                    if h["text"] not in key_topics and len(h["text"]) < 100:
                        key_topics.append(h["text"])

                extracted = {
                    "url": url,
                    "title": page_title,
                    "headings": headings[:30],
                    "key_topics": key_topics[:6],
                    "notable_points": [description[:200]] if description else [],
                }
                break  # success, exit retry loop
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue  # retry

        if extracted:
            pages.append(extracted)
        else:
            failures.append({
                "url": url,
                "reason": last_error or "Unknown error",
            })

    return json.dumps({"pages": pages, "failures": failures})


def _call_outline_synthesis(input_data: dict, previous_errors: list[str] | None = None) -> str:
    competitors_json = json.dumps(input_data.get("competitors", []), indent=2)
    paa = input_data.get("paa_questions", [])
    related = input_data.get("related_searches", [])
    clinic_name = input_data.get("clinic_name", "Modern Recovery Services")
    clinic_brand = input_data.get("clinic_brand", "MRS")
    clinic_context = input_data.get("clinic_context") or load_clinic_prompt_context(clinic_name)
    model_notes = input_data.get("model_notes", [])
    # load_model_note_summaries() returns one already-formatted string.  Treating
    # it as an iterable produced one bullet per character and badly degraded the
    # synthesis prompt.
    if isinstance(model_notes, str):
        model_notes_block = model_notes.strip() or "None"
    else:
        model_notes_block = "\n".join(f"- {n}" for n in model_notes) if model_notes else "None"
    paa_block = "\n".join(f"- {q}" for q in paa) if paa else "None"
    related_block = "\n".join(f"- {q}" for q in related) if related else "None"
    prompt = OUTLINE_SYNTHESIS_PROMPT.format(
        topic=input_data["topic"],
        competitors=competitors_json,
        paa_questions=paa_block,
        related_searches=related_block,
        clinic_name=clinic_name,
        clinic_brand=clinic_brand,
        clinic_context=clinic_context,
        model_notes=model_notes_block,
    )
    if previous_errors:
        prompt += "\n\nPrevious attempt failed. Fix these issues:\n" + "\n".join(previous_errors)
        prompt += "\n\nReturn valid JSON only."
    prompt += "\n\nPrint the JSON in stdout. Do not write it to a file and do not return a summary."
    call_started = time.time()
    ok, out, err = _hermes_call("outline-agent", [], prompt, timeout=300)
    if not ok:
        raise RuntimeError(f"Outline synthesis failed: {err}")
    # Hermes/Flash occasionally writes the requested JSON to a local file and
    # prints only a summary. Recover only a fresh JSON file explicitly named in
    # stdout and confined to the current working directory. This keeps a valid
    # result from consuming all retries without trusting an arbitrary path.
    if "{" not in out:
        path_matches = re.findall(r"`?((?:/[^`\n]+|[A-Za-z0-9_.-]+)\.json)`?", out)
        cwd = Path.cwd().resolve()
        for raw_path in path_matches:
            candidate = Path(raw_path.strip()).expanduser()
            if not candidate.is_absolute():
                candidate = cwd / candidate
            try:
                resolved = candidate.resolve()
                if not resolved.is_relative_to(cwd):
                    continue
                if not resolved.is_file() or resolved.stat().st_mtime < call_started - 2:
                    continue
                recovered = resolved.read_text(encoding="utf-8")
                parse_json_response(recovered)
                return recovered
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return out


# ─── Stage Runner ──────────────────────────────────────────────────────────────


class StageFailedError(Exception):
    def __init__(self, stage_name: str, errors: list[str]) -> None:
        self.stage_name = stage_name
        self.errors = errors
        super().__init__(f"Stage '{stage_name}' failed after retries: {'; '.join(errors)}")


def execute_stage(
    *,
    stage_name: str,
    input_data: dict,
    call_fn: Callable,
    parse_fn: Callable[[str], Any],
    validate_fn: Callable[[Any], ValidationResult],
    article_id: str,
    max_attempts: int = 3,
) -> Any:
    """Run one pipeline stage with retries and validation.

    Separates invocation failures (Hermes down), parse failures (bad JSON),
    and validation failures (wrong structure). Each retry feeds errors back
    to the call_fn.
    """
    previous_errors: list[str] = []
    run_id = uuid.uuid4().hex[:12]

    for attempt in range(1, max_attempts + 1):
        start = time.time()

        _save_checkpoint(article_id, stage_name, run_id, attempt, "started", input=input_data)

        # Invocation
        try:
            raw = call_fn(input_data=input_data, previous_errors=previous_errors)
        except Exception as exc:
            err_msg = f"Hermes call failed: {type(exc).__name__}: {exc}"
            previous_errors = [err_msg]
            _save_checkpoint(
                article_id, stage_name, run_id, attempt, "failed",
                input=input_data, errors=[err_msg], error_type="invocation",
            )
            continue

        # Parse
        try:
            parsed = parse_fn(raw)
        except Exception as exc:
            err_msg = f"JSON parse failed: {exc}"
            previous_errors = [err_msg]
            _save_checkpoint(
                article_id, stage_name, run_id, attempt, "failed",
                input=input_data, output_raw=raw, errors=[err_msg], error_type="parse",
            )
            continue

        # Validate
        validation = validate_fn(parsed)

        if validation.valid:
            elapsed = time.time() - start
            _save_checkpoint(
                article_id, stage_name, run_id, attempt, "success",
                input=input_data, output_raw=raw, output_parsed=parsed,
                duration_ms=int(elapsed * 1000),
            )
            return parsed

        previous_errors = validation.errors
        _save_checkpoint(
            article_id, stage_name, run_id, attempt, "failed",
            input=input_data, output_raw=raw, output_parsed=parsed,
            errors=validation.errors, error_type="validation",
        )

    raise StageFailedError(stage_name, previous_errors)


# ─── Checkpoint Persistence ────────────────────────────────────────────────────


def _get_db() -> Any:
    import sqlite3
    if not DB_PATH:
        raise RuntimeError("Pipeline not configured: DB_PATH is None")
    return sqlite3.connect(str(DB_PATH))


def _ensure_checkpoint_table(db: Any) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS stage_checkpoints (
            run_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            pipeline_name TEXT NOT NULL DEFAULT 'outline',
            stage_name TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            status TEXT NOT NULL,
            input_json TEXT,
            output_json TEXT,
            validation_errors TEXT,
            error_type TEXT,
            started_at TEXT,
            completed_at TEXT,
            duration_ms INTEGER,
            PRIMARY KEY (run_id, stage_name, attempt)
        )
    """)
    db.commit()


def _save_checkpoint(
    article_id: str,
    stage_name: str,
    run_id: str,
    attempt: int,
    status: str,
    input: dict | None = None,
    output_raw: str | None = None,
    output_parsed: Any = None,
    errors: list[str] | None = None,
    error_type: str | None = None,
    duration_ms: int | None = None,
) -> None:
    try:
        db = _get_db()
        _ensure_checkpoint_table(db)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        db.execute(
            """INSERT OR REPLACE INTO stage_checkpoints
               (run_id, article_id, pipeline_name, stage_name, attempt,
                status, input_json, output_json, validation_errors,
                error_type, started_at, completed_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                article_id,
                "outline",
                stage_name,
                attempt,
                status,
                json.dumps(input) if input else None,
                output_raw or (json.dumps(output_parsed) if output_parsed else None),
                json.dumps(errors) if errors else None,
                error_type,
                now if status == "started" else None,
                now if status != "started" else None,
                duration_ms,
            ),
        )
        db.commit()
        db.close()
    except Exception:
        pass  # checkpoint failures should not crash the pipeline


# ─── Deterministic Assembly ────────────────────────────────────────────────────


def assemble_outline(data: OutlineResult) -> str:
    """Assemble validated JSON into the final Markdown outline.

    Pure Python — no LLM involvement.
    Format:
    ---
    meta_title: "..."
    meta_description: "..."
    ---
    # H1

    ## H2
    [opener direction]

    ### H3
    - **Type:** type
    - **Depth:** depth
    - **Shape:** shape
    - **Model:** model
    - **Fail:** fail
    - **Pass:** pass

    **Claims:**
    - claim 1
    - claim 2
    """
    import json as _json

    lines: list[str] = []

    # YAML frontmatter
    lines.append("---")
    lines.append(f"meta_title: {_json.dumps(data.meta_title)}")
    lines.append(f"meta_description: {_json.dumps(data.meta_description)}")
    lines.append(f"topic: {_json.dumps(data.search_intent.get('topic', ''))}")
    lines.append(f"clinic_name: {_json.dumps(data.search_intent.get('clinic_name', ''))}")
    lines.append(f"target_word_count: {data.target_word_count}")
    lines.append(f"scope_rationale: {_json.dumps(data.scope_rationale)}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {data.recommended_title}")
    lines.append("")

    for section in data.outline:
        lines.append(f"## {section.heading}")
        lines.append("")
        if section.purpose:
            lines.append(f"**Opener direction:** {section.purpose}")
            lines.append("")
        if section.type_field:
            lines.append(f"- **Type:** {section.type_field}")
        if section.depth:
            lines.append(f"- **Depth:** {section.depth}")
        if section.shape:
            lines.append(f"- **Shape:** {section.shape}")
        if section.model:
            lines.append(f"- **Model:** {section.model}")
        if section.fail:
            lines.append(f"- **Fail:** {section.fail}")
        if section.pass_field:
            lines.append(f"- **Pass:** {section.pass_field}")
        if section.claims:
            lines.append("")
            lines.append("**Claims:**")
            for claim in section.claims:
                lines.append(f"- {claim}")
            lines.append("")

        for sub in section.subsections:
            lines.append(f"### {sub.heading}")
            lines.append("")
            # Section brief as bullet list
            if sub.type_field:
                lines.append(f"- **Type:** {sub.type_field}")
            if sub.depth:
                lines.append(f"- **Depth:** {sub.depth}")
            if sub.shape:
                lines.append(f"- **Shape:** {sub.shape}")
            if sub.model:
                lines.append(f"- **Model:** {sub.model}")
            if sub.fail:
                lines.append(f"- **Fail:** {sub.fail}")
            if sub.pass_field:
                lines.append(f"- **Pass:** {sub.pass_field}")
            # Claims as bold heading with bullet list
            if sub.claims:
                lines.append("")
                lines.append("**Claims:**")
                for claim in sub.claims:
                    lines.append(f"- {claim}")
            lines.append("")

    return "\n".join(lines)


# ─── Orchestration ─────────────────────────────────────────────────────────────


def run_outline_pipeline(
    topic: str,
    db: Any,
    article_id: str,
    clinic_name: str = "Modern Recovery Services",
    clinic_brand: str = "MRS",
) -> str:
    """Run the full 3-stage outline pipeline.

    Args:
        topic: Article topic / primary keyword
        db: Open SQLite connection
        article_id: Article UUID

    Returns:
        Completed outline Markdown artifact (string).

    Raises:
        StageFailedError if any stage exhausts retries.
    """
    # Stage 1: Source Discovery (direct SERPAPI — no Hermes call)
    source_raw = execute_stage(
        stage_name="source_discovery",
        input_data={"topic": topic},
        call_fn=_call_serpapi,
        parse_fn=parse_json_response,
        validate_fn=lambda d: validate_sources(SourceDiscoveryResult.from_dict(d)),
        article_id=article_id,
    )
    # Already validated — safe to wrap here
    source_result = SourceDiscoveryResult.from_dict(source_raw)

    # Stage 2: Competitor Extraction (Python fetches all pages fast — ~2-3s each)
    expected_urls = [c.url for c in source_result.competitors]
    extraction_pages = []
    try:
        extraction_raw = execute_stage(
            stage_name="competitor_extraction",
            input_data={"topic": topic, "competitors": expected_urls},
            call_fn=_call_competitor_extraction,
            parse_fn=parse_json_response,
            validate_fn=lambda d: validate_extraction(
                ExtractionResult.from_dict(d),
                expected_urls=expected_urls,
            ),
            article_id=article_id,
        )
        extraction_pages = ExtractionResult.from_dict(extraction_raw).pages
        # Convert dataclass objects to plain dicts for downstream use
        extraction_pages = [
            {
                "url": p.url,
                "title": p.title if hasattr(p, "title") else p.url,
                "headings": [{"level": h.level, "text": h.text} for h in p.headings],
                "key_topics": p.key_topics,
            }
            for p in extraction_pages
        ]
    except StageFailedError:
        # Fallback: use SERPAPI data (titles + snippets) instead of scraped headings
        extraction_pages = []
        for c in source_result.competitors:
            extraction_pages.append({
                "url": c.url,
                "title": c.title,
                "headings": [],
                "key_topics": [c.relevance[:80]] if c.relevance else [],
                "notable_points": [c.relevance] if c.relevance else [],
            })

    # Stage 3: Outline Synthesis
    # Combine SERPAPI data with extracted page headings
    competitors_summary = []
    for c in source_result.competitors:
        # Find matching extraction page, if any (ExtractedPage is a dataclass)
        match = next((p for p in extraction_pages if p["url"] == c.url), None)
        entry = {
            "url": c.url,
            "title": c.title,
            "domain": c.domain,
        }
        if match:
            entry["headings"] = match["headings"]
            entry["key_topics"] = match["key_topics"]
        competitors_summary.append(entry)
    # Also pass PAA questions, related searches, clinic name, and model notes
    paa = source_raw.get("paa_questions", [])
    related = source_raw.get("related_searches", [])
    outline_raw = execute_stage(
        stage_name="outline_synthesis",
        input_data={
            "topic": topic,
            "competitors": competitors_summary,
            "paa_questions": paa,
            "related_searches": related,
            "clinic_name": clinic_name,
            "clinic_brand": clinic_brand,
            "model_notes": load_model_note_summaries(),
        },
        call_fn=_call_outline_synthesis,
        parse_fn=parse_json_response,
        validate_fn=lambda d: validate_outline(
            OutlineResult.from_dict(d),
            topic=topic,
            clinic_name=clinic_name,
        ),
        article_id=article_id,
    )
    outline_result = OutlineResult.from_dict(outline_raw)

    # Persist identity in the artifact itself so downstream validators do not
    # need to infer topic or clinic from prose.
    outline_result.search_intent["topic"] = topic
    outline_result.search_intent["clinic_name"] = clinic_name

    # Deterministic assembly
    artifact = assemble_outline(outline_result)

    return artifact
