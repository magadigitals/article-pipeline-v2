"""Narrow prompts for each stage of the outline pipeline.

Each prompt is minimal and focused on ONE task. No mega-prompt.
"""

# ─── Stage 1: Source Discovery ─────────────────────────────────────────────────

SOURCE_DISCOVERY_PROMPT = """\
Search the web for this topic: {topic}

Find 5-10 competitor articles already ranking in organic search. NOT PubMed, NOT academic journals, NOT directories, NOT homepage-only pages. Focus on articles that directly address the topic for a general audience.

Return ONLY a valid JSON object with this exact structure:
{{
  "competitors": [
    {{
      "url": "https://example.com/article",
      "title": "Article title",
      "domain": "example.com",
      "relevance": "Why this source is relevant to the topic"
    }}
  ]
}}

Do not include markdown, code fences, or explanatory text. Return JSON only.
"""


# ─── Stage 2: Competitor Extraction ────────────────────────────────────────────

COMPETITOR_EXTRACTION_PROMPT = """\
Browse each URL below and extract the heading structure and key topics.

Topic: {topic}

Sources:
{urls}

For each accessible page, extract:
1. All H1, H2, H3, and H4 headings
2. Key topics the page covers (3-6 short phrases)
3. Notable points — anything unique, detailed, or surprising about this page's approach

If a page cannot be accessed, report it as a failure with the reason.

Return ONLY a valid JSON object with this exact structure:
{{
  "pages": [
    {{
      "url": "https://example.com/article",
      "headings": [
        {{"level": 2, "text": "What is topic?"}},
        {{"level": 3, "text": "Common signs"}}
      ],
      "key_topics": ["definition", "symptoms", "treatment"],
      "notable_points": ["Connects the pattern to childhood experiences"]
    }}
  ],
  "failures": [
    {{"url": "https://example.com/blocked", "reason": "Could not access"}}
  ]
}}

Do not include markdown, code fences, or explanatory text. Return JSON only.
"""


# ─── Stage 3: Outline Synthesis ────────────────────────────────────────────────

OUTLINE_SYNTHESIS_PROMPT = """\
You are the OUTLINE BUILDER V6.1. Analyze the competitor data below and build a skyscraper outline.

Topic: {topic}

Competitor analysis:
{competitors}

People Also Asked (from SERP):
{paa_questions}

Related searches (from SERP):
{related_searches}

Clinic: {clinic_name}
Brand: {clinic_brand}

SELECTED CLINIC PROFILE:
{clinic_context}

AUDIENCE AND EVIDENCE LOCK:
- Keep the whole outline inside the selected clinic profile's primary audience.
- Use only the profile-supported service model, positioning, offers, and bridge.
- Obey every banned-claim boundary in the selected clinic profile.
- If the profile says the audience varies by page, use the topic and search
  intent to choose one audience; do not mix teen and adult audiences casually.
- If no clinic profile is available, keep clinic references generic and do not
  invent an audience, program, service, location, insurance, or treatment claim.
- This is an outline, not an approved research brief. Do not invent or assert
  exact percentages, effect sizes, diagnostic accuracy, time-to-effect claims,
  FDA approval, physiological mechanisms, or treatment outcomes.
- Every item in Claims must be a provisional research target beginning with
  Research whether, Verify whether, Confirm whether, Determine whether, or
  Compare evidence for. The research stage will decide what can be stated.
- Never promise that a technique will stop a symptom, work within a fixed time,
  or change everything. Use bounded language such as may help or options to try.

Available model notes (benchmark article style references):
{model_notes}

Rules (apply strictly):

META TITLE (4-Stage Protocol):
- Stage 1: Identify the literal query AND the unspoken question driving the search
- Stage 2: Dual promise — informational (Symptoms, Guide, Causes) + practical (When to Get Help, How to Choose)
- Stage 3: Lead with mirrored query. Append dual promise. No brand/clinic names.
- Stage 4: Audit — Mirror test, Trust test, Clarity test, Length test (50-60 chars STRICT).

META DESCRIPTION: 140-160 chars. Count characters before returning JSON. Active voice. Never start with a question. No marketing words.

OUTLINE STRUCTURE:
- H1 identical to meta title in Title Case
- H2-H6: Sentence case (first word + proper nouns capitalized)
- Proper Noun Exception: Program names (CBT, MAT, DBT) capitalize correctly regardless
- The Stress Test: Every heading must be readable in under 2 seconds by a stressed reader at a middle school level
- Forbidden verbs in headings: define, explain, understand, show, list — describe the READER'S experience
- First character of every heading must be uppercase
- H2s: 4-6 total
- H3s: 8-12 total, max 3 per H2
- No single H3 under an H2 — if only one sub-topic, integrate into parent paragraph
- Bridge H2 (final section): understated, 4-6 words, no sub-H3s
- Set target_word_count between 2000 and 3000 and give a concrete scope_rationale.

NARRATIVE FLOW: What -> Why -> How -> Deeper -> Action -> Bridge

HEURISTICS (apply silently):
A) What's Next? — For every problem/action, what happens after? What are the follow-up steps?
B) Chronological Flow — Awareness -> Understanding -> Action -> Strategy -> Healing
C) Stakeholder — Address from the USER'S perspective, not "The bystander's role" but "How to talk to others"

ZERO-LOSS: Every topic and question from competitor data must be represented in the outline.

EVERY H3 must have all 7 fields below. H2s WITH subsections
only need heading, purpose, and subsections — no type/depth/shape/claims/model/fail/pass.
The final bridge H2 (no H3s) still needs all 7 fields.
- Type: treatment_review / definition / differential / safety_red_flags / action_checklist
- Depth: 2-3 sentences explaining what this section uniquely delivers vs competitors
- Shape: mixed section / action_checklist / numbered steps / pure prose
- Claims: at least 3 specific research targets. Each must begin with an approved
  research verb from the evidence lock; do not present an unverified claim as fact.
- Model: Benchmark site — specific craft move (e.g., "NAMI — Threshold stated without ambiguity")
- Fail: What NOT to do in this section
- Pass: What a neutral third party would observe the reader gains — use descriptive
  outcomes only. NEVER start with "The reader" followed by recognizes, realizes,
  accepts, admits, or similar assumption verbs. Bad: "The reader recognizes their
  experience in..." Good: "A clear, non-assumptive description of the topic's
  implications for anyone experiencing it."

Return ONLY a valid JSON object with this exact structure:
{{
  "search_intent": {{
    "primary": "informational",
    "reader_goal": "Understand the topic and what to do about it"
  }},
  "recommended_title": "Topic: Subtitle",
  "meta_title": "Topic: Subtitle",
  "meta_description": "140-160 char description without questions",
  "target_word_count": 2400,
  "scope_rationale": "Why this word count is enough to fulfill the search intent without padding",
  "outline": [
    {{
      "heading": "H2 heading in sentence case",
      "purpose": "2-4 sentence opener direction — what this section covers and why it matters",
      "subsections": [
        {{
          "heading": "H3 heading in sentence case",
          "type": "treatment_review",
          "depth": "What gap this section fills vs competitors",
          "shape": "mixed section",
          "claims": ["Research whether source-supported relationship 1 is accurate", "Verify whether source-supported distinction 2 is accurate", "Compare evidence for option 3 and its limits"],
          "model": "Benchmark site — Craft move description",
          "fail": "What pattern to avoid",
          "pass": "What the reader should feel after reading"
        }}
      ]
    }}
  ],
  "content_gaps": ["What competitors miss that this article will cover"],
  "differentiation": ["How this article will stand out from the competition"]
}}

Do not include markdown, code fences, or explanatory text. Return JSON only.
"""
