"""4-stage research pipeline.

Stage 1: Python + NCBI E-utilities (PubMed search)
Stage 2: Python + SERPAPI (gov/edu/org web sources)
Stage 3: Hermes call (Clinical Research Brief)
Stage 4: Hermes call (Grade 8 Dumbed-down Brief)
Assembly: Combine both briefs deterministically

Reuses execute_stage from the outline pipeline.
"""

from __future__ import annotations

import concurrent.futures
from datetime import date
import hashlib
from html.parser import HTMLParser
import html
import json
import numpy as np
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

from outline_pipeline import (
    StageFailedError,
    _hermes_call,
    configure_pipeline,
    execute_stage,
)
from research_models import (
    AuthoritySource,
    ClinicalBriefResult,
    DumbedDownResult,
    PubMedArticle,
    PubMedEvidenceResult,
    SectionSearchResult,
    WebSourceResult,
)
from research_prompts import CLINICAL_BRIEF_PROMPT, DUMBED_DOWN_PROMPT
from research_exhaustive import (
    ExhaustiveLimits,
    JsonResearchCache,
    classify_evidence,
    fetch_trusted_page,
    paginate_pubmed,
)
from research_validators import (
    parse_json_response,
    validate_clinical_brief,
    validate_dumbed_down,
    validate_pubmed_evidence,
    validate_writer_semantics,
    validate_web_sources,
)


# ── NCBI E-utilities base URL ────────────────────────────────────────────

ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_NCBI_RATE_LOCK = threading.Lock()
_NCBI_NEXT_REQUEST_AT = 0.0


def _ncbi_rate_limit() -> None:
    """Respect NCBI's shared request rate across parallel H3 workers."""
    global _NCBI_NEXT_REQUEST_AT
    interval = 0.11 if os.environ.get("NCBI_API_KEY") else 0.34
    with _NCBI_RATE_LOCK:
        now = time.monotonic()
        wait_for = _NCBI_NEXT_REQUEST_AT - now
        if wait_for > 0:
            time.sleep(wait_for)
        _NCBI_NEXT_REQUEST_AT = time.monotonic() + interval


def _research_cache_get(namespace: str, key: str, ttl_days: int = 30) -> Any:
    """Read a non-secret research response cache entry."""
    if os.environ.get("RESEARCH_CACHE_DISABLE") == "1":
        return None
    root = Path(os.environ.get(
        "RESEARCH_CACHE_DIR", str(Path(__file__).resolve().parent / ".research_cache")
    ))
    path = root / namespace / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("created_at", 0)) > ttl_days * 86400:
            return None
        return payload.get("value")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _research_cache_set(namespace: str, key: str, value: Any) -> None:
    """Atomically cache public search results; API keys are never stored."""
    if os.environ.get("RESEARCH_CACHE_DISABLE") == "1":
        return
    root = Path(os.environ.get(
        "RESEARCH_CACHE_DIR", str(Path(__file__).resolve().parent / ".research_cache")
    ))
    path = root / namespace / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps({"created_at": time.time(), "value": value}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Cache failure must never corrupt or fail the research run.
        return

# ── Colloquial → medical term expansions ─────────────────────────────────

COLLOQUIAL_EXPANSIONS: dict[str, str] = {
    "anxious breakdown": "anxiety attack OR panic attack OR acute stress reaction OR emotional crisis OR nervous breakdown",
    "nervous breakdown": "acute stress reaction OR anxiety disorder OR emotional crisis OR decompensation",
    "mental breakdown": "acute stress reaction OR decompensation OR psychiatric crisis",
    "breakdown": "acute stress reaction OR decompensation OR emotional crisis",
    "meltdown": "emotional dysregulation OR temper outburst OR anger OR frustration",
    "snap": "acute stress reaction OR emotional crisis OR decompensation",
    "losing control": "emotional dysregulation OR impulse control OR behavioral dyscontrol",
    "freak out": "panic attack OR acute stress reaction OR emotional dysregulation",
    "spiral": "anxiety OR rumination OR depression OR escalation",
    "racing thoughts": "anxiety OR rumination OR flight of ideas OR thought pressure",
    "overwhelmed": "stress OR anxiety OR emotional distress OR burnout",
    "shut down": "emotional withdrawal OR dissociation OR freeze response",
    "numb": "emotional numbing OR dissociation OR anhedonia OR depression",
    "really anxious": "anxiety OR generalized anxiety OR panic OR worry",
    "really depressed": "depression OR major depressive disorder OR dysthymia",
    "feeling low": "depression OR low mood OR dysthymia",
    "can't sleep": "insomnia OR sleep disturbance OR sleep-onset insomnia",
    "racing heart": "palpitations OR tachycardia OR panic OR anxiety",
    "shortness of breath": "dyspnea OR hyperventilation OR panic OR respiratory distress",
    "butterflies": "anxiety OR nervousness OR anticipatory anxiety",
    "brain fog": "cognitive dysfunction OR concentration impairment OR mental fatigue",
    "can't focus": "inattention OR concentration impairment OR ADHD symptoms",
    "on edge": "hypervigilance OR hyperarousal OR anxiety OR irritability",
    "emotional": "emotional dysregulation OR lability OR reactivity",
    "people pleaser": "approval-seeking OR codependency OR social anxiety",
}

TOPIC_ALIASES: dict[str, str] = {
    "bpd": "borderline personality disorder",
    "bd": "bipolar disorder",
    "bipolar": "bipolar disorder",
    "add": "adhd",
    "adhd": "attention deficit hyperactivity disorder",
    "ocd": "obsessive compulsive disorder",
    "ptsd": "post traumatic stress disorder",
    "gad": "generalised anxiety disorder",
    "sad": "social anxiety disorder",
    "mdd": "major depressive disorder",
    "panic": "panic disorder",
    "ed": "eating disorder",
    "bn": "bulimia nervosa",
    "an": "anorexia nervosa",
    "bed": "binge eating disorder",
}

STOPWORDS = {
    "a", "about", "after", "all", "and", "are", "as", "at", "be", "before",
    "but", "by", "can", "comparison", "disorder", "do", "does", "each", "for",
    "from", "how", "if", "in", "into", "is", "it", "of", "on", "or", "really",
    "that", "the", "their", "this", "to", "what", "when", "where", "which", "who",
    "why", "with", "yet",
}

# ── Qualifier words to drop for broad-stroke queries ──────────────────────

QUALIFIER_WORDS = {
    "role", "impact", "effect", "importance", "benefit", "risk", "factor",
    "analysis", "study", "review", "overview", "understanding", "exploring",
    "examining", "assessing", "evaluating", "comparing", "investigating",
    "influence", "outcome", "finding", "result",
}

# ── Section-type term families  (from collect_pubmed_evidence.py) ─────────

SECTION_TYPE_TERMS: dict[str, list[str]] = {
    "communication": [
        "communication", "conversation", "discuss", "talk about",
        "ask about", "open up", "share feelings", "express emotion*",
        "active listening", "validate", "i statement*", "nonverbal",
        "dialogue", "connect", "tough conversation"
    ],
    "coping": [
        "coping", "cope", "manage", "handle", "stress management",
        "emotion regulation", "distress tolerance", "self soothe",
        "resilience", "acceptance", "mindfulness",
    ],
    "medication": [
        "medication", "antidepressant*", "SSRI", "SNRI",
        "stimulant*", "mood stabilizer*", "antipsychotic*",
        "anxiolytic*", "benzodiazepine*", "prescribe",
        "pharmacotherapy", "dosage", "side effect*", "adverse effect*",
        "medication adherence", "treatment resistant*",
    ],
    "therapy": [
        "therapy", "CBT", "cognitive behavior*", "DBT",
        "dialectical behavior*", "exposure therapy", "ERP",
        "ACT", "acceptance and commitment", "MBCT",
        "mindfulness based", "interpersonal therapy", "IPT",
        "psychotherapy", "counseling", "therapeutic",
        "group therapy", "family therapy", "EMDR",
        "psychodynamic", "supportive therapy",
    ],
    "trauma": [
        "trauma", "traumatic", "PTSD", "adverse childhood",
        "early adversity", "childhood abuse", "childhood neglect",
        "complex trauma", "developmental trauma", "intergenerational trauma",
        "historical trauma", "racial trauma", "acute stress",
        "trauma informed", "safety", "trigger*", "grounding",
        "dissociation", "hypervigilance", "reexperiencing",
        "intrusive memory*", "nightmare*", "flashback*",
    ],
    "stigma": [
        "stigma", "self stigma", "public stigma", "label",
        "stereotype", "discrimination", "prejudice",
        "shame", "embarrassment", "blame", "judgment",
        "mental health literacy", "normalize", "normalising",
        "attitude* toward*", "perception* of mental",
        "social rejection", "social distance",
    ],
    "digital": [
        "digital", "app", "smartphone", "mobile",
        "telehealth", "telemedicine", "online",
        "internet based", "computerized", "e health",
        "m health", "digital therapeutic*", "virtual",
        "wearable*", "social media", "screen time",
    ],
    "family": [
        "family", "parent*", "caregiver*",
        "sibling*", "household", "home environment",
        "family therapy", "family intervention",
        "parent training", "parenting skill*",
        "attachment", "family dynamic*",
        "marital", "couple*", "relationship quality",
    ],
    "development": [
        "development*", "lifespan", "life course",
        "adolescent*", "teen*", "youth",
        "young adult*", "pediatric*", "child*",
        "adverse childhood experience*", "ACE*",
        "developmental milestone*", "neurodevelopment*",
    ],
    "psychoeducation": [
        "psychoeducation", "education", "information",
        "knowledge", "awareness", "understanding",
        "learn about", "explain", "teach", "inform",
        "action plan*", "crisis plan*",
    ],
    "crisis": [
        "crisis", "emergency", "hospitali*",
        "inpatient", "admission", "crisis intervention",
        "crisis plan", "safety plan*",
        "suicide prevention", "self harm",
        "risk assessment", "triage",
    ],
    "prevention": [
        "prevention", "preventive", "screen*",
        "early detection", "early identification",
        "early intervention", "risk factor*",
        "protective factor*",
    ],
    "cultural": [
        "cultural", "culture", "ethnic*",
        "race", "racial", "indigenous",
        "immigrant*", "refugee*", "culturally adapted",
        "cultural competence", "cultural humility",
        "diversity", "equity", "inclusion",
        "spiritual", "religious",
    ],
    "recovery": [
        "recovery", "remission", "relapse prevention",
        "maintenance", "long term", "follow up",
        "wellness", "well being", "quality of life",
        "peer support", "recovery oriented",
    ],
    "social support": [
        "social support", "peer support", "family support",
        "friend*", "relationship*", "community",
        "connectedness", "belonging", "loneliness",
        "social isolation", "support group",
    ],
}

# ── Topic normalisation aliases  (from collect_pubmed_evidence.py) ──────

TOPIC_ALIASES: dict[str, str] = {
    "bpd": "borderline personality disorder",
    "bd": "bipolar disorder",
    "bipolar": "bipolar disorder",
    "add": "adhd",
    "adhd": "attention deficit hyperactivity disorder",
    "ocd": "obsessive compulsive disorder",
    "ptsd": "post traumatic stress disorder",
    "gad": "generalised anxiety disorder",
    "sad": "social anxiety disorder",
    "mdd": "major depressive disorder",
    "panic": "panic disorder",
    "ed": "eating disorder",
    "bn": "bulimia nervosa",
    "an": "anorexia nervosa",
    "bed": "binge eating disorder",
    "pmdd": "premenstrual dysphoric disorder",
    "pcos": "polycystic ovary syndrome",
    "ibs": "irritable bowel syndrome",
    "copd": "chronic obstructive pulmonary disease",
    "t2d": "type 2 diabetes",
    "cvd": "cardiovascular disease",
}

# ── Colloquial → medical term expansions  (from collect_pubmed_evidence.py) ──

COLLOQUIAL_EXPANSIONS: dict[str, str] = {
    "anxious breakdown": "anxiety attack OR panic attack OR acute stress reaction OR emotional crisis OR nervous breakdown",
    "nervous breakdown": "acute stress reaction OR anxiety disorder OR emotional crisis OR decompensation",
    "mental breakdown": "acute stress reaction OR decompensation OR psychiatric crisis",
    "breakdown": "acute stress reaction OR decompensation OR emotional crisis",
    "meltdown": "emotional dysregulation OR temper outburst OR anger OR frustration",
    "snap": "acute stress reaction OR emotional crisis OR decompensation",
    "losing control": "emotional dysregulation OR impulse control OR behavioral dyscontrol",
    "freak out": "panic attack OR acute stress reaction OR emotional dysregulation",
    "spiral": "anxiety OR rumination OR depression OR escalation",
    "racing thoughts": "anxiety OR rumination OR flight of ideas OR thought pressure",
    "overwhelmed": "stress OR anxiety OR emotional distress OR burnout",
    "shut down": "emotional withdrawal OR dissociation OR freeze response",
    "numb": "emotional numbing OR dissociation OR anhedonia OR depression",
    "brain fog": "cognitive dysfunction OR concentration impairment OR mental fatigue",
    "can't focus": "inattention OR concentration impairment OR ADHD symptoms",
    "on edge": "hypervigilance OR hyperarousal OR anxiety OR irritability",
    "emotional": "emotional dysregulation OR lability OR reactivity",
    "people pleaser": "approval-seeking OR codependency OR social anxiety",
}

# Restore the general clinical vocabulary that existed in the original
# section-mapped collector.  These are intentionally topic-agnostic: the
# approved H3, parent H2, and Claims decide which families are used.
SECTION_TYPE_TERMS.update({
    "exercise": [
        "exercise", "physical activity", "aerobic exercise",
        "resistance training", "sedentary behavior",
    ],
    "sleep": [
        "sleep", "insomnia", "circadian rhythm", "sleep quality",
        "sleep disturbance*", "fatigue", "daytime sleepiness",
    ],
    "nutrition": [
        "nutrition", "diet", "dietary", "nutrient*", "supplement*",
        "vitamin*", "mineral*", "hydration", "electrolyte*",
    ],
    "substance use": [
        "substance use", "substance use disorder", "alcohol",
        "cannabis", "opioid*", "addiction", "dependence", "withdrawal",
        "craving", "relapse", "harm reduction",
    ],
    "mindfulness": [
        "mindfulness", "meditation", "breathing exercise*",
        "relaxation response", "self compassion",
    ],
    "self care": [
        "self care", "rest", "routine", "hydration", "sleep",
        "symptom management",
    ],
    "work": [
        "workplace", "employment", "school", "academic",
        "functioning", "productivity", "accommodation*",
    ],
    "comorbidity": [
        "comorbid*", "co-occurring", "dual diagnosis",
        "multimorbidity", "chronic illness",
    ],
    "ethics": [
        "ethic*", "consent", "confidentiality", "autonomy",
        "rights", "policy", "involuntary treatment",
    ],
    "metabolism": [
        "metabolism", "metabolic", "alcohol metabolism", "acetaldehyde",
        "insulin resistance", "blood glucose", "energy balance",
    ],
    "gut": [
        "gastrointestinal", "digestive", "gastric", "stomach",
        "nausea", "vomiting", "microbiome", "gut brain axis",
    ],
    "pain": [
        "pain", "inflammation", "inflammatory", "headache*",
        "migraine*", "cytokine*", "C reactive protein",
    ],
    "heart": [
        "cardiovascular", "heart rate", "blood pressure",
        "palpitation*", "tachycardia", "heart rate variability",
    ],
    "hormones": [
        "hormone*", "endocrine", "cortisol", "thyroid",
        "estrogen", "progesterone", "testosterone", "melatonin",
    ],
    "genetics": [
        "genetic*", "epigenetic*", "heritability", "genome*",
        "gene expression", "family study*",
    ],
    "neurobiology": [
        "neurobiology", "neuroscience", "brain", "neural",
        "neurotransmitter*", "serotonin", "dopamine", "GABA",
        "neuroimaging",
    ],
    "grounding": [
        "grounding technique*", "distress tolerance",
        "breathing exercise*", "relaxation response",
        "emotion regulation", "crisis coping",
    ],
    "mechanisms": [
        "mechanism*", "pathophysiology", "physiology", "biological pathway*",
        "etiology", "causal pathway*",
    ],
    "symptoms": [
        "symptom*", "clinical presentation", "sign*", "phenotype",
        "severity", "functional impairment",
    ],
    "diagnosis": [
        "diagnosis", "diagnostic criteria", "assessment", "screening",
        "differential diagnosis", "clinical evaluation",
    ],
    "treatment": [
        "treatment", "intervention*", "management", "efficacy",
        "effectiveness", "clinical outcome*", "standard of care",
    ],
    "safety": [
        "safety", "adverse effect*", "contraindication*", "interaction*",
        "toxicity", "risk", "warning*", "precaution*",
    ],
    "complementary medicine": [
        "herbal medicine", "herb*", "botanical*", "dietary supplement*",
        "complementary medicine", "integrative medicine",
    ],
    "epidemiology": [
        "epidemiology", "prevalence", "incidence", "risk factor*",
        "population study*", "health disparity*",
    ],
    "prognosis": [
        "prognosis", "course", "trajectory", "long term outcome*",
        "recurrence", "remission", "mortality",
    ],
})

TOPIC_ALIASES.update({
    "pmad": "perinatal mood and anxiety disorder",
    "spd": "schizoid personality disorder",
    "avpd": "avoidant personality disorder",
    "dpd": "dependent personality disorder",
    "npd": "narcissistic personality disorder",
    "aspd": "antisocial personality disorder",
    "osfed": "other specified feeding or eating disorder",
    "arfid": "avoidant restrictive food intake disorder",
    "pdd": "persistent depressive disorder",
    "odd": "oppositional defiant disorder",
    "did": "dissociative identity disorder",
    "dpdr": "depersonalization derealization disorder",
    "t2dm": "type 2 diabetes mellitus",
    "cad": "coronary artery disease",
    "chd": "coronary heart disease",
    "ckd": "chronic kidney disease",
    "gerd": "gastroesophageal reflux disease",
    "ibd": "inflammatory bowel disease",
    "nafld": "nonalcoholic fatty liver disease",
    "masld": "metabolic dysfunction associated steatotic liver disease",
    "osa": "obstructive sleep apnea",
    "uti": "urinary tract infection",
})

COLLOQUIAL_EXPANSIONS.update({
    "out of control": "impulse control OR behavioral dyscontrol OR emotional dysregulation",
    "hitting a wall": "burnout OR exhaustion OR acute stress",
    "can't stop crying": "emotional dysregulation OR tearfulness OR depression OR anxiety",
    "zone out": "dissociation OR inattention OR daydreaming",
    "check out": "dissociation OR emotional withdrawal OR avoidance",
    "no motivation": "avolition OR apathy OR anhedonia OR depression",
    "knot in stomach": "anxiety OR abdominal tension OR visceral anxiety",
    "heavy chest": "chest tightness OR anxiety OR panic OR somatic symptom",
    "restless": "psychomotor agitation OR akathisia OR hyperactivity",
    "wired": "hyperarousal OR insomnia OR agitation OR mania",
    "tired but wired": "hyperarousal OR insomnia OR fatigue OR anxiety",
    "sensitive": "emotional sensitivity OR rejection sensitivity OR affective lability",
    "push people away": "interpersonal withdrawal OR avoidant behavior OR attachment avoidance",
})


# ── Outline type → concept group mapping ─────────────────────────────

TYPE_MAP: dict[str, list[str]] = {
    # Type is a writing-shape hint, never the primary clinical meaning.
    "action_checklist": ["safety"],
    "causes_mechanisms": ["mechanisms"],
    "safety_red_flags": ["safety", "crisis", "diagnosis"],
    "bridge_to_care": ["treatment", "recovery"],
    "definition": ["psychoeducation"],
    "distinction": ["diagnosis"],
    "differential": ["diagnosis"],
    "signs_scan": ["symptoms", "diagnosis"],
    "treatment_mechanism": ["treatment", "therapy", "medication"],
    "treatment_review": ["treatment", "safety"],
    "how_to_script": ["communication", "coping"],
    "depth_explainer": ["mechanisms"],
    "fast_orientation_intro": ["psychoeducation"],
    "mixed_section": ["treatment"],
    "prognosis_course": ["prognosis", "recovery"],
    "prevalence_context": ["epidemiology"],
}


def _extract_section_types(outline_markdown: str) -> dict[str, str]:
    """Extract **Type:** field for each H3 heading from the outline."""
    section_types: dict[str, str] = {}
    current_h3 = ""

    for line in outline_markdown.splitlines():
        stripped = line.strip().lstrip("> ").strip()
        # Detect H3 headings (both formats)
        h3_match = re.match(r"^(?:###\s+|-\s*\*\*H3:\*\*\s*)(.+)$", stripped)
        if h3_match:
            current_h3 = h3_match.group(1).strip().rstrip("*").strip()
        # Detect **Type:**
        field_line = re.sub(r"^(?:>\s*)?(?:-\s+)?", "", stripped).strip()
        type_match = re.match(r"\*\*Type:\*\*\s*(.+)$", field_line, re.I)
        if type_match and current_h3:
            section_types[current_h3] = type_match.group(1).strip()

    return section_types


def _keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    words = re.findall(r"[a-z][a-z-]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


CONCEPT_CUES: dict[str, tuple[str, ...]] = {
    "complementary medicine": ("herb", "herbal", "botanical", "supplement"),
    "substance use": ("alcohol", "drug use", "substance", "addiction", "withdrawal", "hangover"),
    "metabolism": ("metabolism", "metabolite", "acetaldehyde", "blood sugar"),
    "gut": ("nausea", "vomit", "stomach", "gastric", "digestive", "gastrointestinal"),
    "pain": ("pain", "headache", "inflammation", "inflammatory", "migraine"),
    "sleep": ("sleep", "insomnia", "fatigue", "tired"),
    "nutrition": ("diet", "food", "hydration", "electrolyte", "vitamin", "mineral"),
    "cultural": ("culture", "cultural", "indigenous", "native american", "american indian"),
    "genetics": ("genetic", "epigenetic", "hereditary", "heritability"),
    "neurobiology": ("brain", "neural", "neurobiology", "neurotransmitter"),
    "mechanisms": ("mechanism", "pathway", "physiology", "pathophysiology", "why the body"),
    "symptoms": ("symptom", "signs", "feels", "presentation", "impairment"),
    "diagnosis": ("diagnosis", "diagnostic", "differential", "screening", "assessment"),
    "treatment": ("treatment", "therapy", "intervention", "remedy", "efficacy", "effective"),
    "safety": ("safety", "safe", "risk", "warning", "interaction", "contraindication", "toxicity"),
    "epidemiology": ("prevalence", "incidence", "population", "disparity"),
    "prognosis": ("prognosis", "outlook", "course", "long-term", "recurrence"),
}

RESEARCH_QUERY_NOISE = STOPWORDS | QUALIFIER_WORDS | {
    "research", "whether", "evidence", "verify", "compare", "evaluate",
    "determine", "examine", "assess", "investigate", "identify", "reader",
    "section", "write", "explain", "established", "common", "target",
    "respect", "clinical", "clinically", "says", "said", "reduces",
    "reduce", "affect", "affects", "make", "makes", "happening",
}

QUERY_TERM_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "autonomic": ("sympathetic", "parasympathetic"),
    "arousal": ("sympathetic activation", "sympathetic tone"),
    "interaction": ("drug interaction", "herb drug interaction"),
    "interactions": ("drug interactions", "herb drug interactions"),
    "nausea": ("emesis", "antiemetic"),
    "withdrawal": ("abstinence syndrome",),
    "screening": ("case finding",),
    "criteria": ("diagnostic criteria",),
    "prevalence": ("epidemiology",),
}


def _matched_concept_keys(text: str) -> list[str]:
    """Infer clinical concept families from section meaning, not prose shape."""
    normalized = re.sub(r"[^a-z0-9-]+", " ", str(text or "").lower()).strip()
    keys: list[str] = []
    for key, cues in CONCEPT_CUES.items():
        candidates = (key, *cues)
        if any(re.search(rf"\b{re.escape(cue)}", normalized) for cue in candidates):
            keys.append(key)
    # Existing families whose names are themselves meaningful evidence cues.
    for key in SECTION_TYPE_TERMS:
        if key in keys or "|" in key:
            continue
        if re.search(rf"\b{re.escape(key)}\b", normalized):
            keys.append(key)
    return keys


def _preferred_phrases(
    heading: str,
    section_type: str = "",
    context: str = "",
) -> list[str]:
    """Return clinical phrases inferred from H3/H2/Claims plus type hints.

    Outline ``Type`` describes writing shape and is therefore secondary.  The
    actual section language and approved Claims determine the primary concepts.
    """
    semantic_text = " ".join(part for part in (heading, context) if part)
    concept_keys = _matched_concept_keys(semantic_text)
    for mapped_key in TYPE_MAP.get(section_type.strip(), []):
        if mapped_key not in concept_keys:
            concept_keys.append(mapped_key)

    terms: list[str] = []
    for key in concept_keys:
        terms.extend(SECTION_TYPE_TERMS.get(key, []))
    return list(dict.fromkeys(terms))


def _literal_section_terms(
    heading: str,
    parent_h2: str = "",
    claims: list[str] | None = None,
) -> list[str]:
    """Extract discriminative approved-outline terms for adaptive queries."""
    claim_text = " ".join(_research_question_subject(c) for c in (claims or []))
    # Claims are the factual contract, so their terms must survive bounded
    # query limits before editorial heading or parent-section vocabulary.
    source = " ".join((claim_text, heading, parent_h2))
    terms = [
        word for word in _keywords(source)
        if len(word) >= 4 and word not in RESEARCH_QUERY_NOISE
    ]
    return list(dict.fromkeys(terms))


def _fielded_pubmed_term(term: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 -]+", " ", term.rstrip("*")).strip()
    if not cleaned:
        return ""
    if term.endswith("*") and " " not in cleaned:
        return f"{cleaned}*[Title/Abstract]"
    return f'"{cleaned}"[Title/Abstract]'


def _pubmed_topic_expressions(topic: str) -> tuple[str, str]:
    """Build ATM-friendly and fielded topic expressions without title locking."""
    short_topic = topic.split(":")[0].split("|")[0].strip()
    clinical_topic = short_topic
    for short, expanded in sorted(TOPIC_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(short)}\b", clinical_topic, re.I):
            clinical_topic = re.sub(
                rf"\b{re.escape(short)}\b", expanded, clinical_topic,
                count=1, flags=re.I,
            )
            break

    groups = _scholarly_topic_groups(clinical_topic)
    if groups:
        untagged_groups = []
        fielded_groups = []
        for group in groups:
            phrases = list(dict.fromkeys(p for p in group if p))
            untagged_groups.append(
                "(" + " OR ".join(f'"{p}"' for p in phrases) + ")"
            )
            fielded_groups.append(
                "(" + " OR ".join(_fielded_pubmed_term(p) for p in phrases) + ")"
            )
        return " AND ".join(untagged_groups), " AND ".join(fielded_groups)

    words = [w for w in _keywords(clinical_topic) if len(w) >= 4]
    phrase_options = [clinical_topic] if clinical_topic else []
    phrase_options.extend(words[:6])
    phrase_options = list(dict.fromkeys(p for p in phrase_options if p))
    untagged = "(" + " OR ".join(f'"{p}"' for p in phrase_options) + ")"
    fielded = "(" + " OR ".join(
        _fielded_pubmed_term(p) for p in phrase_options
    ) + ")"
    return untagged, fielded


def _compact_topic_terms(topic: str) -> list[str]:
    """Choose one clinical anchor per recognized topic concept group."""
    groups = _scholarly_topic_groups(topic)
    if not groups:
        return []
    # The first item is the reader phrase; the first expansion is normally the
    # clinical/indexed phrase (anxious -> anxiety, shake -> tremor).
    return [group[1] if len(group) > 1 else group[0] for group in groups]


def _llm_generate_pubmed_queries(
    topic: str, heading: str, section_type: str = "",
    parent_h2: str = "", claims: list[str] | None = None,
) -> list[str]:
    """Generate PubMed queries for one H3 via LLM. Falls back to regex."""
    # This function is kept for backward compatibility.
    # Batched generation (all H3s in one call) is preferred in _call_pubmed_search.
    return _llm_generate_all_pubmed_queries(
        topic, [(heading, section_type, parent_h2, claims or [])]
    ).get(heading, _build_pubmed_queries_v3(topic, heading, section_type, parent_h2, claims))


def _llm_generate_all_pubmed_queries(
    topic: str,
    h3_list: list[tuple[str, str, str, list[str]]],
) -> dict[str, list[str]]:
    """Generate PubMed Boolean queries for ALL H3s in one LLM call.

    h3_list: list of (heading, section_type, parent_h2, claims) tuples.
    Returns dict mapping heading -> list of query strings.
    Falls back to regex per-H3 if LLM call fails.
    """
    sections_block = "\n".join(
        f"--- Section {i+1} ---\nH3: {h}\nH2: {p}\nType: {s}\nClaims: {'; '.join(c[:2])}\n"
        for i, (h, s, p, c) in enumerate(h3_list)
    )
    prompt = (
        f"You are a PhD-level clinical researcher conducting a systematic PubMed search.\n"
        f"\nArticle topic: {topic}\n\n"
        f"Below are {len(h3_list)} sections. For EACH section, construct 2 PubMed Boolean query strings "
        f"of increasing broadness. Map each H3 to its precise clinical/diagnostic term and MeSH. "
        f"Use [Title/Abstract] and [MeSH] field tags. "
        f"A PhD scholar uses exact clinical terminology, not lay wording.\n\n"
        f"{sections_block}\n\n"
        f"Return ONLY a JSON object with keys being H3 headings and values being lists of 2 query strings."
    )
    ok, stdout, stderr = _hermes_call("default", [], prompt, timeout=60)
    result: dict[str, list[str]] = {}
    if ok and stdout.strip():
        try:
            cleaned = stdout.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            parsed = json.loads(cleaned.strip())
            if isinstance(parsed, dict):
                for h, qs in parsed.items():
                    if isinstance(qs, list):
                        result[h] = [str(q) for q in qs[:3]]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    # Fallback for sections the LLM didn't handle
    for h, s, p, c in h3_list:
        if h not in result or not result[h]:
            result[h] = _build_pubmed_queries_v3(topic, h, s, p, c)
    return result


def _build_pubmed_queries_v3(
    topic: str,
    heading: str,
    section_type: str = "",
    parent_h2: str = "",
    claims: list[str] | None = None,
) -> list[str]:
    """Build a bounded adaptive PubMed query ladder for one approved H3.

    The first tier leaves terms untagged so PubMed Automatic Term Mapping can
    reach MeSH and synonyms. Later tiers add Title/Abstract precision, a
    component-evidence search, and evidence-synthesis escalation.
    """
    context = " ".join((parent_h2, " ".join(claims or [])))
    concept_terms = _preferred_phrases(heading, section_type, context)
    literal_terms = _literal_section_terms(heading, parent_h2, claims)
    topic_untagged, topic_fielded = _pubmed_topic_expressions(topic)

    curated = [
        term for term in concept_terms
        if term and " OR " not in term and len(term.rstrip("*")) >= 4
    ]
    curated = list(dict.fromkeys(curated))
    fielded_concepts = [
        value for value in (_fielded_pubmed_term(t) for t in curated[:8]) if value
    ]
    fielded_literals = [
        value for value in (_fielded_pubmed_term(t) for t in literal_terms[:10]) if value
    ]
    topic_vocabulary = set(_keywords(" ".join(_scholarly_topic_phrases(topic))))
    specific_literals = [
        term for term in literal_terms if term not in topic_vocabulary
    ]
    expanded_literals: list[str] = []
    for term in specific_literals[:6]:
        expanded_literals.append(term)
        expanded_literals.extend(QUERY_TERM_EXPANSIONS.get(term, ()))
    if not expanded_literals:
        expanded_literals = literal_terms[:6]
    curated_specific = [
        t.rstrip("*") for t in curated
        if t.rstrip("*").lower() not in topic_vocabulary
    ]
    untagged_needs = list(dict.fromkeys(
        expanded_literals + curated_specific[:4]
    ))

    queries: list[str] = []

    # Precision bridge: PubMed can rank a compact clinical intersection more
    # accurately than a large nested OR expression. Try at most two distinct
    # evidence-need terms before the broader recall tiers.
    compact_topic = _compact_topic_terms(topic)
    if compact_topic and expanded_literals:
        compact_base = " AND ".join(compact_topic)
        for need in expanded_literals[:2]:
            queries.append(f"{compact_base} AND {need}")

    # Tier 1: allow PubMed ATM/MeSH translation before adding field locks.
    if topic_untagged and untagged_needs:
        needs = " OR ".join(f'"{t}"' for t in untagged_needs)
        queries.append(f"({topic_untagged}) AND ({needs})")

    # Tier 2: topic plus curated clinical concept families.
    if topic_fielded and fielded_concepts:
        queries.append(
            f"({topic_fielded}) AND ({' OR '.join(fielded_concepts)})"
        )

    # Tier 3: topic plus literal H3/H2/Claims vocabulary.
    if topic_fielded and fielded_literals:
        queries.append(
            f"({topic_fielded}) AND ({' OR '.join(fielded_literals)})"
        )

    # Tier 4: higher-level evidence for the H3, still anchored to the article
    # topic. Topic-free component searches admitted clinically unrelated
    # sources into live packets.
    if len(fielded_literals) >= 2:
        queries.append(
            f"({topic_fielded}) AND ({' OR '.join(fielded_literals[:8])}) AND "
            "(systematic review[Publication Type] OR meta-analysis[Publication Type] "
            "OR randomized controlled trial[Publication Type] OR review[Publication Type])"
        )

    # Tier 5: broad synthesis for the topic; section relevance is still
    # required after retrieval.
    if topic_untagged:
        queries.append(
            f"({topic_untagged}) AND (systematic review[Publication Type] OR "
            "meta-analysis[Publication Type] OR practice guideline[Publication Type] "
            "OR review[Publication Type])"
        )

    # Tier 6: claim-based fallback — search claims directly without topic wrapper.
    # Catches cases where topic terms dilute queries for specific clinical tools
    # (e.g., CAGE, AUDIT) mentioned in the outline's Claims field.
    if claims:
        claim_terms_raw: set[str] = set()
        for claim in claims:
            # Remove research directives ("Research whether...")
            cleaned = re.sub(r"^(?:research|verify|compare|evaluate|determine)\s+(?:whether\s+)?", "", claim, flags=re.I)
            for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", cleaned):
                if word.lower() not in STOPWORDS and word.lower() not in RESEARCH_QUERY_NOISE:
                    # Keep short acronyms (CAGE, AUDIT, PHQ) and longer words
                    if len(word) >= 3:
                        claim_terms_raw.add(word)
        # Remove topic words that overlap — this is the fallback tier
        topic_words = set(_keywords(topic))
        filtered = [w for w in claim_terms_raw if w.lower() not in topic_words]
        if filtered:
            fielded_claims = [value for value in (_fielded_pubmed_term(t) for t in list(filtered)[:6]) if value]
            if fielded_claims and topic_fielded:
                queries.append(
                    f"({topic_fielded}) AND ({' OR '.join(fielded_claims)})"
                )

    return list(dict.fromkeys(q for q in queries if q))


def _relevance_score(
    record: dict,
    topic: str,
    heading: str,
    section_type: str = "",
    parent_h2: str = "",
    claims: list[str] | None = None,
) -> float:
    """Score a PubMed article's relevance to the section heading + topic."""
    context = " ".join((parent_h2, " ".join(claims or [])))
    target = set(
        w for w in _keywords(f"{topic} {heading} {context}") if len(w) >= 6
    )
    title = str(record.get("title", "")).lower()
    abstract = str(record.get("abstract", "")).lower()
    score = sum(4 for term in target if term in title) + sum(1 for term in target if term in abstract)

    # Boost for section-type concept match in title
    for phrase in _preferred_phrases(heading, section_type, context):
        clean_phrase = phrase.rstrip("*").lower()
        if clean_phrase in title:
            score += 12
        elif clean_phrase in abstract:
            score += 5

    # Publication type quality boost
    pub_types = " ".join(str(x).lower() for x in record.get("publication_types", []))
    if any(label in pub_types for label in ("meta-analysis", "systematic review", "guideline")):
        score += 5
    elif "review" in pub_types:
        score += 3
    if "randomized controlled trial" in pub_types:
        score += 4

    # Recency boost
    try:
        score += max(0, int(str(record.get("year", "0"))) - 2019) * 0.15
    except ValueError:
        pass

    return score


def _has_specific_match(
    record: dict,
    heading: str,
    section_type: str = "",
    parent_h2: str = "",
    claims: list[str] | None = None,
) -> bool:
    """Check if article has a specific match for this section's concept."""
    haystack = f"{record.get('title', '')} {record.get('abstract', '')}".lower()
    context = " ".join((parent_h2, " ".join(claims or [])))
    literal_terms = _literal_section_terms(heading, parent_h2, claims)
    expanded_literals: list[str] = []
    for term in literal_terms:
        expanded_literals.append(term)
        expanded_literals.extend(QUERY_TERM_EXPANSIONS.get(term, ()))
    phrases = expanded_literals + _preferred_phrases(
        heading=heading, section_type=section_type, context=context
    )
    # Strip wildcards from phrases for Python substring matching
    clean_phrases = [p.rstrip("*").lower() for p in phrases]
    if not clean_phrases:
        heading_words = _literal_section_terms(heading, parent_h2, claims)
        return any(kw in haystack for kw in heading_words) if heading_words else False
    return any(phrase in haystack for phrase in clean_phrases)


# ── Outline-type → intent class mapping ──────────────────────────────

INTENT_CLASS_MAP: dict[str, str] = {
    "action_checklist": "action_intervention",
    "causes_mechanisms": "causes_mechanisms",
    "safety_red_flags": "red_flags_diagnosis",
    "bridge_to_care": "bridge_to_care",
    "definition": "definition_differential",
    "signs_scan": "symptoms_phenotype",
    "treatment_mechanism": "treatment_intervention",
    "how_to_script": "action_intervention",
    "mixed_section": "treatment_intervention",
    "depth_explainer": "psychoeducation",
    "fast_orientation_intro": "psychoeducation",
}


def _extract_section_briefs(outline_markdown: str) -> dict[str, dict]:
    """Extract full section brief data for each H3 from the outline.

    Returns {heading: {type, depth, shape, claims, model, fail, pass, opener_direction}}
    """
    briefs: dict[str, dict] = {}
    current_h3 = ""
    current_h2 = ""
    current_h2_opener = ""  # opener direction at H2 level, assigned to first H3 under it
    current_data: dict = {}
    in_claims = False

    for line in outline_markdown.splitlines():
        stripped = line.strip()

        # Track H2s for opener direction
        h2_match = re.match(r"^(?:##\s+|\*\*H2:\*\*\s*)(.+)$", stripped)
        if h2_match:
            current_h2 = h2_match.group(1).strip().rstrip("*").strip()
            current_h2_opener = ""  # reset for new H2 section
            continue

        # Detect H3 headings
        h3_match = re.match(r"^(?:###\s+|-\s*\*\*H3:\*\*\s*)(.+)$", stripped)
        if h3_match:
            if current_h3 and current_data:
                briefs[current_h3] = current_data
            current_h3 = h3_match.group(1).strip().rstrip("*").strip()
            current_data = {"type": "", "depth": "", "shape": "", "claims": [],
                           "model": "", "fail": "", "pass": "", "opener_direction": current_h2_opener,
                           "parent_h2": current_h2}
            current_h2_opener = ""  # consumed — only assign to first H3 under each H2
            in_claims = False
            continue

        # Parse brief fields
        field_line = re.sub(r"^(?:>\s*)?(?:-\s+)?", "", stripped).strip()
        if re.match(r"\*\*Type:\*\*", field_line, re.I):
            current_data["type"] = re.sub(r"\*\*Type:\*\*\s*", "", field_line, flags=re.I).strip()
            in_claims = False
        elif re.match(r"\*\*Depth:\*\*", field_line, re.I):
            current_data["depth"] = re.sub(r"\*\*Depth:\*\*\s*", "", field_line, flags=re.I).strip()
            in_claims = False
        elif re.match(r"\*\*Shape:\*\*", field_line, re.I):
            current_data["shape"] = re.sub(r"\*\*Shape:\*\*\s*", "", field_line, flags=re.I).strip()
            in_claims = False
        elif re.match(r"\*\*Model:\*\*", field_line, re.I):
            current_data["model"] = re.sub(r"\*\*Model:\*\*\s*", "", field_line, flags=re.I).strip()
            in_claims = False
        elif re.match(r"\*\*Fail:\*\*", field_line, re.I):
            current_data["fail"] = re.sub(r"\*\*Fail:\*\*\s*", "", field_line, flags=re.I).strip()
            in_claims = False
        elif re.match(r"\*\*Pass:\*\*", field_line, re.I):
            current_data["pass"] = re.sub(r"\*\*Pass:\*\*\s*", "", field_line, flags=re.I).strip()
            in_claims = False
        elif re.match(r"\*\*Opener direction:\*\*", field_line, re.I):
            current_h2_opener = re.sub(r"\*\*Opener direction:\*\*\s*", "", field_line, flags=re.I).strip()
            # Only set on current H3 if it belongs to THIS H2 section
            if current_data.get("opener_direction") == "" and current_h3 and current_data.get("parent_h2") == current_h2:
                current_data["opener_direction"] = current_h2_opener
        elif re.match(r"\*\*Claims:\*\*", field_line, re.I):
            in_claims = True
        elif in_claims and current_h3:
            # Claims in production outlines are commonly blockquoted:
            # ``> 1. ...`` or ``> - ...``. Strip only the quote marker before
            # detecting the list marker so the factual contract is not lost.
            claim_line = re.sub(r"^(?:>\s*)?", "", stripped).strip()
            if not (
                re.match(r"^\d+\.\s+", claim_line)
                or re.match(r"^\-\s+", claim_line)
            ):
                continue
            claim_text = re.sub(r"^(?:\d+\.\s+|\-\s+)", "", claim_line)
            if claim_text:
                current_data.setdefault("claims", []).append(claim_text)

    # Flush last H3
    if current_h3 and current_data:
        briefs[current_h3] = current_data

    return briefs


_RESEARCH_DIRECTIVE_RE = re.compile(
    r"^(?:research|verify|compare|evaluate|determine|examine|assess|investigate|identify)\b",
    re.I,
)


def _is_research_directive(text: str) -> bool:
    """True when an outline item asks a question rather than states a fact."""
    cleaned = re.sub(r"^\d+\.\s*", "", str(text or "")).strip()
    return bool(_RESEARCH_DIRECTIVE_RE.match(cleaned))


def _research_question_subject(text: str) -> str:
    """Remove assignment scaffolding while preserving the proposition tested."""
    cleaned = re.sub(r"^\d+\.\s*", "", str(text or "")).strip()
    cleaned = re.sub(
        r"^(?:research|verify|evaluate|determine|examine|assess|investigate|identify)\s+whether\s+",
        "", cleaned, flags=re.I,
    )
    cleaned = re.sub(
        r"^(?:research|verify|evaluate|determine|examine|assess|investigate|identify)\s+",
        "", cleaned, flags=re.I,
    )
    cleaned = re.sub(r"^compare\s+(?:the\s+)?evidence\s+(?:for|on)\s+", "", cleaned, flags=re.I)
    return cleaned.rstrip(". ")


def _safe_cite(source: dict) -> str:
    """Format a citation. Raises ValueError if APA metadata is missing."""
    return _apa7_cite(source)


def _apa7_cite(source: dict) -> str:
    """Format a source in APA 7th edition style.

    Handles PubMed articles (with author/year) and government/clinical sources.
    Removes trailing punctuation from titles to prevent double punctuation.
    """
    url = source.get("url", "")
    title = _sentence_case_title(source.get("title", "Untitled").rstrip(". "))
    domain = source.get("domain", "")
    pmid = source.get("pmid", "")

    # NCBI Bookshelf pages are authored book entries, not journal articles.
    # Some pages expose ``citation_journal_title``-shaped metadata, so this
    # branch must run before the journal detector below.
    if source.get("source_type") == "book_entry" or re.search(
        r"ncbi\.nlm\.nih\.gov/books/NBK\d+", url, re.I
    ):
        authors = source.get("authors", [])
        year = str(source.get("year") or "").strip()
        book_title = _sentence_case_title(
            str(source.get("book_title") or "StatPearls").rstrip(". ")
        )
        publisher = str(
            source.get("publisher") or source.get("organization") or
            "StatPearls Publishing"
        ).strip()
        if not year or not title:
            raise ValueError(f"book source lacks APA metadata: {url or title}")
        if authors:
            normalized = [_apa_author_name(author) for author in authors]
            normalized = [author for author in normalized if author]
            if not normalized:
                raise ValueError(f"book source lacks APA metadata: {url or title}")
            if len(normalized) > 1:
                author_str = ", ".join(normalized[:-1]) + ", & " + normalized[-1]
            else:
                author_str = normalized[0]
        else:
            author_str = str(
                source.get("author") or source.get("organization") or publisher
            ).strip()
            if not author_str:
                raise ValueError(f"book source lacks APA metadata: {url or title}")
        publisher_part = (
            f" {publisher}."
            if publisher and publisher.casefold() != author_str.casefold()
            else ""
        )
        title_part = title if re.search(r"[.!?]$", title) else f"{title}."
        return f"{author_str} ({year}). {title_part} In *{book_title}*.{publisher_part} {url}"

    # Journal article with full metadata (PubMed, PMC, DOI, or OpenAlex).
    if pmid or source.get("journal") or "pubmed" in url or "pmc.ncbi" in url:
        authors = source.get("authors", [])
        year = source.get("year", "")
        journal = source.get("journal", "")
        doi = source.get("doi", "")
        if authors and year and journal:
            if len(authors) > 20:
                first_nineteen = [
                    _apa_author_name(author) for author in authors[:19]
                ]
                final_author = _apa_author_name(authors[-1])
                normalized = [author for author in first_nineteen if author]
                author_str = ", ".join(normalized) + ", … " + final_author
            else:
                normalized = [_apa_author_name(author) for author in authors]
                normalized = [author for author in normalized if author]
                author_str = ""
            if len(authors) <= 20 and len(normalized) > 1:
                author_str = ", ".join(normalized[:-1]) + ", & " + normalized[-1]
            elif len(authors) <= 20:
                author_str = normalized[0] if normalized else ""
            volume = str(source.get("volume") or "").strip()
            issue = str(source.get("issue") or "").strip()
            pages = str(source.get("pages") or source.get("article_number") or "").strip()
            pages = re.sub(r"(?<=\d)-(?=\d)", "–", pages)
            journal_part = f"*{_journal_title_case(journal)}*"
            if volume:
                journal_part += f", *{volume}*"
                if issue:
                    journal_part += f"({issue})"
            if pages:
                journal_part += f", {pages}"
            journal_part += "."
            if doi:
                doi = re.sub(r"^https?://doi\.org/", "", str(doi), flags=re.I)
                return f"{author_str} ({year}). {title}. {journal_part} https://doi.org/{doi}"
            return f"{author_str} ({year}). {title}. {journal_part} {url}"
        raise ValueError(f"journal source lacks APA metadata: {url or title}")

    # Derive organization name from domain
    org_map = {
        "cdc.gov": "U.S. Centers for Disease Control and Prevention",
        "nih.gov": "U.S. National Institutes of Health",
        "nlm.nih.gov": "U.S. National Library of Medicine",
        "samhsa.gov": "Substance Abuse and Mental Health Services Administration",
        "medlineplus.gov": "MedlinePlus",
        "nami.org": "National Alliance on Mental Illness",
        "apa.org": "American Psychological Association",
        "aap.org": "American Academy of Pediatrics",
        "healthychildren.org": "American Academy of Pediatrics",
        "who.int": "World Health Organization",
        "nimh.nih.gov": "National Institute of Mental Health",
        "mayoclinic.org": "Mayo Clinic",
        "clevelandclinic.org": "Cleveland Clinic",
        "ncbi.nlm.nih.gov": "National Center for Biotechnology Information",
        "pmc.ncbi.nlm.nih.gov": "NCBI PubMed Central",
        "schools.utah.gov": "Utah State Board of Education",
        "aspe.hhs.gov": "U.S. Department of Health and Human Services",
        "smart.ojp.gov": "U.S. Department of Justice",
        "congress.gov": "U.S. Congress",
        "akleg.gov": "Alaska State Legislature",
        "youth.gov": "U.S. Youth Programs",
        "fbi.gov": "Federal Bureau of Investigation",
        "ice.gov": "U.S. Immigration and Customs Enforcement",
        "dhs.gov": "U.S. Department of Homeland Security",
        "hhs.gov": "U.S. Department of Health and Human Services",
        "health.gov": "U.S. Department of Health and Human Services",
        "nccih.nih.gov": "National Center for Complementary and Integrative Health",
        "grants.nih.gov": "National Institutes of Health",
        "nida.nih.gov": "National Institute on Drug Abuse",
        "nigms.nih.gov": "National Institute of General Medical Sciences",
    }
    org = str(source.get("author") or source.get("organization") or "").strip()
    if not org:
        org = _organization_for_domain(domain or url)
    if org in {"U.S. Government resource", "University or academic resource"}:
        raise ValueError(f"web source has only a generic author label: {url}")
    for key, name in org_map.items():
        if _domain_matches(domain, key):
            org = name
            break

    # Extract year from title/content if possible
    published = str(source.get("date") or source.get("year") or "").strip()
    date_part = _apa_date(published)
    site_name = str(source.get("site_name") or "").strip()
    site_part = f" {site_name}." if site_name and site_name.casefold() != org.casefold() else ""
    return f"{org} ({date_part}). *{title}*.{site_part} {url}"


def _apa_author_name(value: str) -> str:
    """Normalize NCBI/OpenAlex author strings to APA surname-and-initials form."""
    name = re.sub(r"\s+", " ", str(value or "")).strip().strip(",")
    if not name:
        return ""
    if "," in name:
        surname, given = [part.strip() for part in name.split(",", 1)]
    else:
        parts = name.split()
        if len(parts) == 1:
            return parts[0]
        surname, given = parts[-1], " ".join(parts[:-1])
    initials = " ".join(
        token if re.fullmatch(r"[A-Z]\.", token) else f"{token[0].upper()}."
        for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+|[A-Z]\.", given)
        if token
    )
    return f"{surname}, {initials}".strip()


def _sentence_case_title(value: str) -> str:
    """Apply APA sentence case while preserving acronyms and mixed-case tokens."""
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    if not title:
        return title
    pieces = re.split(r"([:?!]\s+)", title)
    converted: list[str] = []
    start_of_segment = True
    for piece in pieces:
        if re.fullmatch(r"[:?!]\s+", piece):
            converted.append(piece)
            start_of_segment = True
            continue
        words = piece.split(" ")
        output_words: list[str] = []
        for word in words:
            letters = re.sub(r"[^A-Za-z]", "", word)
            preserve = (
                (letters.isupper() and len(letters) >= 2)
                or (letters and not (letters.islower() or letters.istitle()))
            )
            lowered = word if preserve else word.lower()
            if start_of_segment and letters:
                first_index = next(
                    (index for index, char in enumerate(lowered) if char.isalpha()),
                    0,
                )
                lowered = (
                    lowered[:first_index]
                    + lowered[first_index].upper()
                    + lowered[first_index + 1 :]
                )
                start_of_segment = False
            output_words.append(lowered)
        converted.append(" ".join(output_words))
    return "".join(converted)


def _journal_title_case(value: str) -> str:
    """Normalize PubMed's inconsistent full-journal casing for APA output."""
    minor = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to"}
    words = re.split(r"(\s+)", re.sub(r"\s+", " ", str(value or "")).strip())
    result: list[str] = []
    word_index = 0
    for token in words:
        if token.isspace():
            result.append(token)
            continue
        letters = re.sub(r"[^A-Za-z]", "", token)
        if letters.isupper() and len(letters) >= 2:
            rendered = token
        elif word_index > 0 and letters.casefold() in minor:
            rendered = token.lower()
        else:
            rendered = token[:1].upper() + token[1:].lower()
        result.append(rendered)
        word_index += 1
    return "".join(result)


def _apa_date(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return "n.d."
    match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value)
    if not match:
        return value
    year, month, day = match.groups()
    if not month:
        return year
    months = (
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    month_name = months[int(month)]
    return f"{year}, {month_name} {int(day)}" if day else f"{year}, {month_name}"


def _organization_for_domain(domain_or_url: str) -> str:
    host = _normalized_domain(domain_or_url)
    exact = {
        "cdc.gov": "Centers for Disease Control and Prevention",
        "dol.gov": "U.S. Department of Labor",
        "clinicaltrials.gov": "National Library of Medicine",
        "healthquality.va.gov": "U.S. Department of Veterans Affairs",
        "cde.ca.gov": "California Department of Education",
        "cdhs.colorado.gov": "Colorado Department of Human Services",
        "hca.wa.gov": "Washington State Health Care Authority",
        "health.ucdavis.edu": "UC Davis Health",
        "nam.edu": "National Academy of Medicine",
        "ccsu.edu": "Central Connecticut State University",
        "academic.gsu.edu": "Georgia State University",
    }
    for key, label in exact.items():
        if _domain_matches(host, key):
            return label
    label = _authority_label(host)
    if label not in {"U.S. Government resource", "University or academic resource"}:
        return label
    return ""


TRUSTED_CLINICAL_DOMAINS: dict[str, str] = {
    "who.int": "World Health Organization",
    "nhs.uk": "National Health Service",
    "england.nhs.uk": "NHS England",
    "nice.org.uk": "National Institute for Health and Care Excellence",
    "rcpsych.ac.uk": "Royal College of Psychiatrists",
    "psychiatry.org": "American Psychiatric Association",
    "nami.org": "National Alliance on Mental Illness",
    "apa.org": "American Psychological Association",
    "aap.org": "American Academy of Pediatrics",
    "healthychildren.org": "American Academy of Pediatrics",
    "cochrane.org": "Cochrane",
    "mayoclinic.org": "Mayo Clinic",
    "clevelandclinic.org": "Cleveland Clinic",
    # Authoritative mental health and therapy resources
    "psychologytoday.com": "Psychology Today",
    "goodtherapy.org": "GoodTherapy",
    "psychcentral.com": "Psych Central",
    "verywellmind.com": "Verywell Mind",
    "nationaleatingdisorders.org": "National Eating Disorders Association",
    "eatingdisorderhope.com": "Eating Disorder Hope",
    "thetrend.clinic": "The Trend Clinic",
    "equalhope.org": "Equal Hope",
    "anxietycanada.com": "Anxiety Canada",
    "brown.edu": "Brown University",
    "mcleanhospital.org": "McLean Hospital",
    "childmind.org": "Child Mind Institute",
    "reachout.com": "ReachOut Australia",
    "health.harvard.edu": "Harvard Health Publishing",
    "med.stanford.edu": "Stanford Medicine",
    "hopkinsmedicine.org": "Johns Hopkins Medicine",
}

SCHOLARLY_TOPIC_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "native american": ("American Indian", "Alaska Native", "Indigenous"),
    "substance abuse": ("substance use", "substance use disorder", "alcohol and drug use"),
    "hangover": (
        "alcohol hangover", "veisalgia", "post-intoxication symptoms",
    ),
    "herbs": ("herbal medicine", "botanical", "dietary supplement"),
    "depression": ("depressive disorder", "major depressive disorder", "depressive symptoms"),
    "anxious": ("anxiety", "anxiety disorder", "physiological arousal"),
    "shake": ("tremor", "physiological tremor", "enhanced physiological tremor"),
    "neurodivergent": (
        "neurodivergence",
        "neurodiversity",
        "neurodiverse",
    ),
}


def _scholarly_topic_phrases(topic: str) -> list[str]:
    """Expand plain-language topics into terms used by scholarly sources."""
    phrases = [topic.strip()]
    lower = topic.lower()
    for plain, expansions in SCHOLARLY_TOPIC_EXPANSIONS.items():
        if plain in lower:
            phrases.extend(expansions)
    return list(dict.fromkeys(p for p in phrases if p))


def _scholarly_topic_groups(topic: str) -> list[list[str]]:
    """Return concept groups; a relevant result must represent every group."""
    lower = topic.lower()
    groups: list[list[str]] = []
    for plain, expansions in SCHOLARLY_TOPIC_EXPANSIONS.items():
        if plain in lower:
            groups.append([plain, *expansions])
    return groups


def _topic_matches_text(topic: str, text: str) -> bool:
    haystack = text.lower()
    topic_groups = _scholarly_topic_groups(topic)
    if topic_groups:
        return all(
            any(phrase.lower() in haystack for phrase in group)
            for group in topic_groups
        )
    topic_phrases = _scholarly_topic_phrases(topic)
    exact_match = any(
        phrase.lower() in haystack for phrase in topic_phrases if len(phrase) >= 4
    )
    topic_terms = set(w for w in _keywords(topic) if len(w) >= 4)
    # Use a proportional threshold: at least half the topic terms.
    # A 2-term topic like "dysphoria vs dysmorphia" should match on either term
    # individually since .gov pages rarely discuss both conditions together.
    required = max(1, (len(topic_terms) + 1) // 2)
    return exact_match or sum(w in haystack for w in topic_terms) >= required


def _topic_has_title_anchor(topic: str, title: str) -> bool:
    """Require a direct paper to foreground at least one topic concept."""
    title_lower = title.lower()
    groups = _scholarly_topic_groups(topic)
    if groups:
        return any(
            any(phrase.lower() in title_lower for phrase in group)
            for group in groups
        )
    terms = [word for word in _keywords(topic) if len(word) >= 5]
    return not terms or any(word in title_lower for word in terms)


def _normalized_domain(domain_or_url: str) -> str:
    """Return a lower-case hostname, without credentials, port, or www."""
    value = (domain_or_url or "").strip().lower()
    if "://" not in value:
        value = "https://" + value
    host = urllib.parse.urlparse(value).hostname or ""
    return host.removeprefix("www.").rstrip(".")


def _domain_matches(domain_or_url: str, expected: str) -> bool:
    host = _normalized_domain(domain_or_url)
    expected = expected.lower().removeprefix("www.").rstrip(".")
    return host == expected or host.endswith("." + expected)


def _authority_label(domain_or_url: str) -> str:
    """Classify authority without substring spoofing or commercial inflation."""
    host = _normalized_domain(domain_or_url)
    if host.endswith(".gov") or host == "gov":
        return "U.S. Government resource"
    if host.endswith(".edu") or host == "edu":
        return "University or academic resource"
    for domain, label in TRUSTED_CLINICAL_DOMAINS.items():
        if _domain_matches(host, domain):
            return label
    return f"Web source ({host or 'unknown domain'})"


STUDENT_REPO_PATTERNS = re.compile(
    r"(honorstheses|bitstreams|scholarworks|stars\.library|mcnair|"
    r"jewlscholar|/theses/|/dissertations/|academia\.edu|"
    r"academia\.edu/Documents/in/|digital\.library|/ark:/)",
    re.I,
)


def _is_trusted_web_source(url: str) -> bool:
    host = _normalized_domain(url)
    if STUDENT_REPO_PATTERNS.search(url):
        return False
    if host.endswith(".gov") or host.endswith(".edu"):
        return True
    return any(_domain_matches(host, domain) for domain in TRUSTED_CLINICAL_DOMAINS)


def _http_get_bounded(url: str, timeout_seconds: int, max_bytes: int) -> dict[str, Any]:
    """Download a public evidence page with a strict response-size ceiling."""
    with requests.get(
        url,
        timeout=timeout_seconds,
        allow_redirects=True,
        stream=True,
        headers={"User-Agent": "GoldenResearchPipeline/1.0 evidence-retrieval"},
    ) as response:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        downloaded = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            downloaded += len(chunk)
            if downloaded > max_bytes:
                raise ValueError(f"response exceeds {max_bytes} bytes")
            chunks.append(chunk)
        return {
            "body": b"".join(chunks),
            "final_url": response.url,
            "content_type": response.headers.get("Content-Type", ""),
        }


class _CitationMetaParser(HTMLParser):
    """Collect standard Highwire, Dublin Core, OpenGraph, and article metadata."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        data = {str(key).casefold(): str(value or "").strip() for key, value in attrs}
        key = data.get("name") or data.get("property")
        value = html.unescape(data.get("content", "")).strip()
        if key and value:
            self.values.setdefault(key.casefold(), []).append(value)


def _first_meta(values: dict[str, list[str]], *keys: str) -> str:
    for key in keys:
        candidates = values.get(key.casefold(), [])
        if candidates and candidates[0].strip():
            return candidates[0].strip()
    return ""


def _fetch_citation_metadata(source: dict) -> dict:
    """Hydrate a selected trusted page before its public citation is formatted."""
    url = str(source.get("url") or "").strip()
    if not url:
        return source
    pubmed_match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url, re.I)
    if pubmed_match:
        articles = _efetch([pubmed_match.group(1)], raise_on_error=True)
        if articles:
            enriched = dict(source)
            enriched.update(articles[0])
            enriched["url"] = url
            return enriched
    pmc_match = re.search(r"/articles/(PMC\d+)", url, re.I)
    if pmc_match:
        journal_record = _pmc_journal_metadata(pmc_match.group(1).upper())
        if journal_record:
            enriched = dict(source)
            enriched.update(journal_record)
            # Keep the repository URL as an audit locator; APA formatting uses
            # the DOI when one exists and the canonical PubMed URL otherwise.
            enriched["repository_url"] = url
            return enriched
    cached = _research_cache_get("citation_metadata", url, ttl_days=30)
    if isinstance(cached, dict):
        enriched = dict(source)
        enriched.update(cached)
        return enriched
    try:
        response = _http_get_bounded(url, timeout_seconds=15, max_bytes=1_500_000)
        body = response["body"].decode("utf-8", errors="replace")
        parser = _CitationMetaParser()
        parser.feed(body)
        meta = parser.values
        authors = meta.get("citation_author", []) or meta.get("dc.creator", [])
        title = _first_meta(meta, "citation_title", "dc.title", "og:title")
        date_value = _first_meta(
            meta,
            "citation_publication_date",
            "citation_date",
            "article:published_time",
            "date",
            "dc.date",
        )
        metadata = {
            "url": response.get("final_url") or url,
            "title": re.sub(r"\s+", " ", title).strip() or source.get("title", ""),
            "authors": authors,
            "author": _first_meta(meta, "author", "article:author"),
            "organization": _first_meta(meta, "publisher", "dc.publisher"),
            "site_name": _first_meta(meta, "og:site_name"),
            "date": date_value,
            "year": date_value[:4] if re.match(r"^\d{4}", date_value) else source.get("year", ""),
            "journal": _first_meta(meta, "citation_journal_title"),
            "volume": _first_meta(meta, "citation_volume"),
            "issue": _first_meta(meta, "citation_issue"),
            "pages": _citation_pages(
                _first_meta(meta, "citation_firstpage"),
                _first_meta(meta, "citation_lastpage"),
            ),
            "doi": _first_meta(meta, "citation_doi"),
            "pmid": _first_meta(meta, "citation_pmid"),
        }
        if re.search(r"ncbi\.nlm\.nih\.gov/books/NBK\d+", url, re.I):
            book_title = _first_meta(
                meta, "citation_book_title", "citation_inbook_title"
            )
            publisher = _first_meta(
                meta, "citation_publisher", "publisher", "dc.publisher"
            )
            metadata.update({
                "source_type": "book_entry",
                "book_title": book_title or source.get("book_title", "")
                or "NCBI Bookshelf",
                "publisher": publisher or source.get("publisher", "")
                or source.get("organization", ""),
            })
        metadata = {key: value for key, value in metadata.items() if value}
        _research_cache_set("citation_metadata", url, metadata)
        enriched = dict(source)
        enriched.update(metadata)
        return enriched
    except Exception:
        return source


def _pmc_journal_metadata(pmcid: str) -> dict:
    """Resolve a PMC repository identifier to its original PubMed journal record."""
    cached = _research_cache_get("pmc_idconv", pmcid, ttl_days=365)
    if isinstance(cached, dict):
        return cached
    params = urllib.parse.urlencode(
        {
            "ids": pmcid,
            "format": "json",
            "tool": "golden-research-pipeline",
            "email": "research-metadata@localhost",
        }
    )
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?{params}"
    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "GoldenResearchPipeline/1.0 citation-metadata"},
        )
        response.raise_for_status()
        records = response.json().get("records", [])
        pmid = str(records[0].get("pmid") or "") if records else ""
        if not pmid:
            return {}
        articles = _efetch([pmid], raise_on_error=True)
        if not articles:
            return {}
        record = dict(articles[0])
        record["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        _research_cache_set("pmc_idconv", pmcid, record)
        return record
    except Exception:
        return {}


def _citation_pages(first: str, last: str) -> str:
    if first and last and first != last:
        return f"{first}–{last}"
    return first or last


def _web_result_relevant(
    topic: str,
    heading: str,
    title: str,
    snippet: str,
    concept_terms: list[str] | None = None,
) -> bool:
    """Require scholarly topic equivalence plus section-concept relevance."""
    haystack = f"{title} {snippet}".lower()
    topic_match = _topic_matches_text(topic, haystack)
    title_anchor = _topic_has_title_anchor(topic, title)
    topic_vocabulary = " ".join(_scholarly_topic_phrases(topic))
    literal_topic_terms = set(_keywords(topic_vocabulary))
    heading_terms = [
        w for w in _keywords(heading)
        if len(w) >= 5
        and w not in RESEARCH_QUERY_NOISE
        and w not in literal_topic_terms
    ]
    expanded_concepts = [
        term.rstrip("*").lower()
        for term in (concept_terms or [])
        if len(term.rstrip("*")) >= 4
        and term.rstrip("*").lower() not in literal_topic_terms
    ]
    section_terms = list(dict.fromkeys(heading_terms + expanded_concepts))
    section_hits = sum(term in haystack for term in section_terms)
    if not section_terms:
        return topic_match

    # Some H3s intentionally ask for component evidence rather than direct
    # whole-topic evidence (for example, ginger for nausea or AUD warning
    # signs inside a hangover article). Two distinct H3-concept matches may
    # therefore establish relevant indirect support even when "hangover" is
    # absent. The packet must still frame that evidence as indirect.
    # Require both topic match and section-concept hits — topic-free component
    # evidence admitted clinically unrelated sources into live packets.
    return topic_match and title_anchor and section_hits >= 1


def _pubmed_record_relevant(
    record: dict,
    topic: str,
    heading: str,
    section_type: str = "",
    parent_h2: str = "",
    claims: list[str] | None = None,
) -> bool:
    """Require both topic-population and H3-concept support in PubMed text."""
    title = str(record.get("title", ""))
    abstract = str(record.get("abstract", ""))
    literal_terms = _literal_section_terms(heading, parent_h2, claims)
    expanded_literals: list[str] = []
    for term in literal_terms:
        expanded_literals.append(term)
        expanded_literals.extend(QUERY_TERM_EXPANSIONS.get(term, ()))
    context = " ".join((parent_h2, " ".join(claims or [])))
    # Literal approved-outline terms are safer for component-evidence matching.
    # Curated families are used only when a heading is too generic to supply
    # meaningful terms of its own.
    concepts = expanded_literals or _preferred_phrases(
        heading, section_type, context
    )
    return _web_result_relevant(topic, heading, title, abstract, concepts)


def _evidence_status(section_articles: list[dict], section_web: list[dict]) -> str:
    """Determine evidence status for a section."""
    if not section_articles and not section_web:
        return "None"
    has_pubmed = any(a.get("source_layer", "") == "pubmed" for a in section_articles)
    has_web = len(section_web) > 0
    if has_pubmed:
        return "Direct clinical"
    if has_web and any(s.get("support_scope") != "component_only" for s in section_web):
        return "Guideline"
    if has_web:
        return "Indirect"
    return "Indirect"


def _semantic_claim_checker(
    all_sections: list[dict],
    section_briefs: dict[str, dict],
    section_results: list[dict],
    oa_results: list[dict],
    web_by_h3: dict[str, list[dict]],
) -> dict[str, dict]:
    """Match claims against source titles *and evidence text* using TF-IDF.

    Title-only matching produced false confidence: a paper can have a promising
    title while its abstract narrows or contradicts the claim.  PubMed
    abstracts and web snippets are therefore part of the comparison document.

    Returns dict mapping heading -> {
        "supported": list[str],
        "unsupported": list[str],
        "best_score": float,
        "source_scores": dict[str, float]  # title -> similarity score
    }
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    results: dict[str, dict] = {}

    for ps in section_results:
        heading = ps.get("heading", "")
        brief = section_briefs.get(heading, {})
        claims = brief.get("claims", [])
        cleaned_claims = [
            _research_question_subject(c) if _is_research_directive(c)
            else re.sub(r"^\d+\.\s*", "", c)
            for c in claims
        ]

        source_docs: list[tuple[str, str]] = []
        for a in ps.get("articles", []):
            t = a.get("title", "")
            if t:
                source_docs.append((t, f"{t}. {a.get('abstract', '')}".strip()))
        # Legacy alternate-index input remains accepted for compatibility, but
        # the active pipeline passes an empty list and never queries it.
        for oa_s in oa_results or []:
            if oa_s.get("heading") == heading:
                for oa_a in oa_s.get("articles", []):
                    t = oa_a.get("title", "")
                    if t and all(existing[0] != t for existing in source_docs):
                        source_docs.append((t, f"{t}. {oa_a.get('abstract', '')}".strip()))
        for src in web_by_h3.get(heading, []):
            t = src.get("title", "")
            if t:
                evidence_text = src.get("evidence_text") or src.get("relevance", "")
                source_docs.append((t, f"{t}. {evidence_text}".strip()))

        if not cleaned_claims or not source_docs:
            results[heading] = {"supported": [], "unsupported": claims, "best_score": 0.0, "source_scores": {}}
            continue

        titles = [item[0] for item in source_docs]
        evidence_texts = [item[1] for item in source_docs]

        # Use section heading + concept terms as the comparison text, not claims alone
        # This matches source titles like "Generalized Anxiety Disorder - NIMH" to
        # a heading like "The difference between normal anxiety and an anxiety disorder"
        st = ps.get("section_type", "")
        concept_terms = []
        if st in TYPE_MAP:
            for key in TYPE_MAP[st]:
                terms = SECTION_TYPE_TERMS.get(key, [])
                concept_terms.extend(terms[:5])  # top 5 terms per concept group

        comparison_texts = [heading] + concept_terms
        if cleaned_claims:
            comparison_texts.extend(cleaned_claims)

        # Vectorize comparison texts + the full available evidence text.
        all_texts = comparison_texts + evidence_texts
        vectorizer = TfidfVectorizer(stop_words="english", max_features=1000)
        tfidf = vectorizer.fit_transform(all_texts)

        cmp_vectors = tfidf[:len(comparison_texts)]
        evidence_vectors = tfidf[len(comparison_texts):]

        # Score each title against the best-matching comparison text (heading + concepts + claims)
        source_scores = {}
        for j, title in enumerate(titles):
            evidence_vector = evidence_vectors[j]
            similarities = cosine_similarity(evidence_vector, cmp_vectors)[0]
            source_scores[title] = float(np.max(similarities)) if similarities.size > 0 else 0.0

        # Score each claim against all titles (for supported/unsupported tracking)
        supported = []
        unsupported = []
        best_score = 0.0
        if cleaned_claims:
            claim_start = len(comparison_texts) - len(cleaned_claims)
            claim_vectors = cmp_vectors[claim_start:claim_start + len(cleaned_claims)]
            for i, claim in enumerate(cleaned_claims):
                similarities = cosine_similarity(claim_vectors[i], evidence_vectors)[0]
                max_sim = float(np.max(similarities)) if similarities.size > 0 else 0.0
                best_score = max(best_score, max_sim)
                if max_sim >= 0.25:
                    supported.append(claims[i])
                else:
                    unsupported.append(claims[i])

        results[heading] = {
            "supported": supported,
            "unsupported": unsupported,
            "best_score": best_score,
            "source_scores": source_scores,
        }

    return results


def _reuse_pubmed_sources(
    topic: str,
    section_results: list[dict],
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Reuse one relevant PubMed source across every H3 it can support.

    Search ownership is not evidence ownership.  If an article found for one
    H3 is also relevant to another H3, attach it there without another query.
    The final Sources registry still deduplicates the URL.
    """
    pool: dict[str, dict] = {}
    original_by_heading: dict[str, set[str]] = {}
    for section in section_results:
        heading = section.get("heading", "")
        original_by_heading[heading] = set()
        for article in section.get("articles", []):
            identity = str(
                article.get("pmid") or article.get("doi") or
                article.get("url") or article.get("title") or ""
            )
            if identity:
                pool[identity] = article
                original_by_heading[heading].add(identity)

    reused_by_source: dict[str, list[str]] = {}
    missing: list[str] = []
    weak: list[str] = []

    for section in section_results:
        heading = section.get("heading", "")
        section_type = section.get("section_type", "")
        parent_h2 = section.get("parent_h2", "")
        claims = section.get("claims", [])
        candidates: list[tuple[float, str, dict]] = []
        for identity, article in pool.items():
            if not _pubmed_record_relevant(
                article, topic, heading, section_type, parent_h2, claims
            ):
                continue
            candidates.append((
                _relevance_score(
                    article, topic, heading, section_type, parent_h2, claims
                ),
                identity,
                article,
            ))

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = [item[2] for item in candidates[:3]]
        section["articles"] = selected
        section["pmids"] = [a.get("pmid") for a in selected if a.get("pmid")]

        for _, identity, article in candidates[:3]:
            if identity not in original_by_heading.get(heading, set()):
                source_id = str(article.get("url") or article.get("pmid") or identity)
                reused_by_source.setdefault(source_id, []).append(heading)

        if not selected:
            missing.append(heading)
            continue
        top_score = _relevance_score(
            selected[0], topic, heading, section_type, parent_h2, claims
        )
        specific_expected = bool(
            _literal_section_terms(heading, parent_h2, claims)
            or _preferred_phrases(
                heading, section_type,
                " ".join((parent_h2, " ".join(claims))),
            )
        )
        has_specific = any(
            _has_specific_match(
                a, heading, section_type, parent_h2, claims
            )
            for a in selected
        )
        if (specific_expected and not has_specific) or (
            not specific_expected and top_score < 10
        ):
            weak.append(heading)

    return missing, weak, reused_by_source


def _llm_verify_sources(
    pubmed_sections: list[dict],
    topic: str,
) -> tuple[int, list[str]]:
    """Verify each source supports its section's claims.

    Returns (number_of_sources_filtered, list_of_headings_that_lost_sources)
    so the caller can re-search for those sections.
    """
    sections_for_llm: list[str] = []
    for section in pubmed_sections:
        heading = section.get("heading", "")
        claims = section.get("claims", [])
        articles = section.get("articles", [])
        web_sources = section.get("web_sources", [])
        if not claims or not (articles or web_sources):
            continue
        section_block = f"### {heading}\nClaims: {'; '.join(claims[:4])}\n"
        for art in articles:
            section_block += f"  [PubMed] {art.get('title','')[:120]}\n"
        for src in web_sources:
            section_block += f"  [Web] {src.get('title','')[:120]} — {src.get('relevance','')[:200]}\n"
        sections_for_llm.append(section_block)

    if not sections_for_llm:
        return 0, []

    prompt = (
        f"Article topic: {topic}\n"
        f"Below are research sections with their claims and candidate sources. "
        f"Some sources may be irrelevant to the claims (e.g. a biology paper about a "
        f"gene named after a psychological concept, or a source about a different condition).\n\n"
        + "\n".join(sections_for_llm) +
        f"\n\nFor each section, list which sources (by PMID for PubMed, by title for web) are "
        f"IRRELEVANT to the section's claims. A source is irrelevant if the claim is about "
        f"a psychological/clinical topic and the source is about a different clinical "
        f"construct, different population, different condition subtype, or different "
        f"diagnostic category than what the H3 and claims describe — even if both share "
        f"the same broad category (e.g., both are 'phobias' but one is about fear of "
        f"being alone and the source is about a different phobia type).\n\n"
        f"Return ONLY a JSON object with keys being section headings and values being lists of "
        f"source identifiers to remove. Example: {{\"What causes anxiety\": "
        f"[\"PMC1234567\"], \"Treatment options\": []}}\n"
        f"If no sources are irrelevant, return empty lists for all sections."
    )
    ok, stdout, stderr = _hermes_call("default", [], prompt, timeout=30)
    if not ok or not stdout.strip():
        return 0, []
    try:
        to_remove: dict[str, list[str]] = json.loads(stdout.strip())
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0, []

    removed = 0
    affected: list[str] = []
    for section in pubmed_sections:
        heading = section.get("heading", "")
        remove_ids = to_remove.get(heading, [])
        if not remove_ids:
            continue
        # Filter articles
        before_a = len(section.get("articles", []))
        section["articles"] = [
            a for a in section.get("articles", [])
            if a.get("pmid", "") not in remove_ids
            and a.get("url", "") not in remove_ids
            and a.get("title", "")[:80] not in remove_ids
        ]
        removed += before_a - len(section.get("articles", []))
        # Filter web sources
        before_w = len(section.get("web_sources", []))
        section["web_sources"] = [
            s for s in section.get("web_sources", [])
            if s.get("url", "") not in remove_ids
            and s.get("title", "")[:80] not in remove_ids
        ]
        removed += before_w - len(section.get("web_sources", []))
        # Track sections that lost all sources
        if not section.get("articles") and not section.get("web_sources"):
            affected.append(heading)
    return removed, affected


def _format_research_packet(
    topic: str,
    outline_markdown: str,
    pubmed_results: dict,
    web_results: dict,
    section_briefs: dict,
) -> str:
    """Build a GWF-format research packet.

    No LLM calls. Pure Python formatting.
    """
    # Merge all section results
    pubmed_sections = pubmed_results.get("section_results", [])
    web_sources = web_results.get("sources", [])
    research_mode = str(pubmed_results.get("research_mode") or "standard").casefold()

    # Group web sources by H3
    web_by_h3: dict[str, list[dict]] = {src.get("h3", ""): [] for src in web_results.get("sources", [])}
    for src in web_results.get("sources", []):
        h3 = src.get("h3", "")
        if h3 and h3 in web_by_h3:
            web_by_h3[h3].append(src)

    weak_sections = set(pubmed_results.get("weak_sections", []))
    missing_sections = set(pubmed_results.get("missing_sections", []))
    effective_sections = []
    for section in pubmed_sections:
        copy = dict(section)
        if copy.get("heading") in weak_sections or copy.get("heading") in missing_sections:
            copy["articles"] = []
        effective_sections.append(copy)

    # Batch semantic claim-evidence matching. In exhaustive mode, a search
    # snippet nominates a page but is not evidence when full-page extraction
    # failed.
    semantic_web_by_h3 = (
        {
            heading: [
                source for source in sources
                if source.get("extraction_status") == "extracted"
            ]
            for heading, sources in web_by_h3.items()
        }
        if research_mode == "exhaustive_v1"
        else web_by_h3
    )
    _checker_results = _semantic_claim_checker(
        all_sections=list(range(len(pubmed_sections))),
        section_briefs=section_briefs,
        section_results=effective_sections,
        oa_results=[],
        web_by_h3=semantic_web_by_h3,
    )

    # Build per-section research brief
    sections_out: list[str] = []
    source_registry: dict[str, str] = {}
    h2_map = _extract_h2_map(outline_markdown)
    current_h2 = ""
    today = date.today().isoformat()

    for ps in pubmed_sections:
        heading = ps.get("heading", "")
        section_type = ps.get("section_type", "")
        brief = section_briefs.get(heading, {})
        query_audits = ps.get("query_audits", [])
        search_failures = sum(bool(audit.get("errors")) for audit in query_audits)
        truncated_queries = sum(
            bool(audit.get("truncated_by_limit")) for audit in query_audits
        )
        search_status = (
            f"partial ({search_failures} query failure(s))"
            if search_failures
            else f"bounded complete ({truncated_queries} capped query/queries)"
            if truncated_queries
            else "complete"
            if research_mode == "exhaustive_v1"
            else "standard retrieval"
        )

        # Collect articles from PubMed
        # A weak PubMed hit is search telemetry, not direct evidence.
        articles = [] if heading in weak_sections or heading in missing_sections else ps.get("articles", [])

        web_candidates_for_section = web_by_h3.get(heading, [])
        web_for_section = (
            [
                source for source in web_candidates_for_section
                if source.get("extraction_status") == "extracted"
            ]
            if research_mode == "exhaustive_v1"
            else web_candidates_for_section
        )

        # Evidence status
        ev_status = _evidence_status(articles, web_for_section)

        # Intent class from section type
        intent = INTENT_CLASS_MAP.get(section_type, section_type)

        # Section goal from brief opener direction
        section_goal = brief.get("opener_direction", "")

        # Writer priority from Pass field
        writer_priority = brief.get("pass", brief.get("depth", ""))

        # Semantic claim-evidence matching (from batch checker, run once above loop)
        claims = brief.get("claims", [])
        checker_result = _checker_results.get(heading, {"supported": [], "unsupported": claims, "best_score": 0.0, "source_scores": {}})
        supported_claims = checker_result["supported"]
        unsupported_claims = checker_result["unsupported"]
        best_score = checker_result["best_score"]
        source_scores = checker_result.get("source_scores", {})

        research_questions = [c for c in claims if _is_research_directive(c)]
        factual_claims = [c for c in claims if not _is_research_directive(c)]
        supported_set = set(supported_claims)
        unsupported_set = set(unsupported_claims)
        supported_factual = [c for c in factual_claims if c in supported_set]
        unsupported_factual = [c for c in factual_claims if c in unsupported_set]
        evidence_sources: list[dict[str, Any]] = list(articles)
        evidence_sources.extend(
            web_candidates_for_section
            if research_mode == "exhaustive_v1"
            else web_for_section
        )
        question_cards = [
            classify_evidence(_research_question_subject(question), evidence_sources)
            for question in research_questions
        ]
        resolved_question_statuses = {
            "supported_match", "indirect_match", "explicit_negative",
            "explicitly_insufficient",
        }
        supported_questions = [
            question for question, card in zip(research_questions, question_cards)
            if card.disposition.value in {"supported_match", "indirect_match"}
        ]
        not_established_questions = [
            question for question, card in zip(research_questions, question_cards)
            if card.disposition.value not in {"supported_match", "indirect_match"}
        ]
        resolved_question_count = sum(
            card.disposition.value in resolved_question_statuses
            for card in question_cards
        )
        if research_mode != "exhaustive_v1" and (articles or web_for_section):
            # Preserve the established standard-mode contract: a credible
            # attached source dispositions the question even when automated
            # extraction cannot answer it. Exhaustive mode is intentionally
            # stricter and requires a resolved evidence card.
            resolved_question_count = len(research_questions)

        # Strongest safe claim: use best-supported claim, or first claim if none supported
        if supported_factual:
            strongest_claim = supported_factual[0]
        elif supported_questions:
            strongest_claim = (
                "Evidence relevant to this research question was located; state only the "
                "source-specific finding recorded below, not the question as fact."
            )
        elif research_questions and (articles or web_for_section):
            strongest_claim = (
                "The automated evidence extraction did not resolve the proposed relationship. "
                "Do not claim either that it is supported or that no research exists."
            )
        elif factual_claims:
            strongest_claim = re.sub(r"^\d+\.\s*", "", factual_claims[0]) + " (not supported by available evidence)"
        else:
            strongest_claim = "No specific claim available for this section."

        question_findings: list[str] = []
        for question, card in zip(research_questions, question_cards):
            subject = _research_question_subject(question)
            finding = card.finding
            if (
                research_mode != "exhaustive_v1"
                and card.disposition.value == "extraction_unresolved"
            ):
                finding = (
                    "Not resolved from the retrieved title, abstract, or snippet — "
                    "source review is required before claiming either support or "
                    "absence of research."
                )
            question_findings.append(
                f"- Question: {subject}\n"
                f"  Disposition: {card.disposition.value}\n"
                f"  Finding: {finding}\n"
                f"  Best lexical overlap: {card.best_overlap:.2f}"
            )

        # CAN CLAIM entries — all sources available (heading + claim-specific)
        can_claim: list[str] = []
        for art in articles:
            title = art.get("title", "")[:60]
            url = art.get("url", "")
            pmid = art.get("pmid", "")
            try:
                cite = _safe_cite(art)
            except ValueError:
                continue
            can_claim.append(f"- [{pmid or url[:30]}] {title} — {cite}")
            if url:
                source_registry[url] = cite

        for src in web_for_section:
            try:
                cite = _safe_cite(src)
            except ValueError:
                continue
            title = src.get("title", "")[:60]
            can_claim.append(f"- [WEB: {src.get('domain','')}] {title} — {cite}")
            url = src.get("url", "")
            if url:
                source_registry[url] = cite

        # Claim-specific sources (from independent claim search)
        claim_sources_list: list[dict] = []
        for art in ps.get("claim_articles", []):
            claim_sources_list.append({"type": "pubmed", "data": art})
        for src in ps.get("claim_web_sources", []):
            claim_sources_list.append({"type": "web", "data": src})
        claim_apa_cites: list[str] = []
        for cs in claim_sources_list:
            data = cs["data"]
            try:
                cite = _safe_cite(data)
            except ValueError:
                continue
            if cs["type"] == "pubmed":
                can_claim.append(f"- [CLAIM: {data.get('pmid','')[:30]}] {data.get('title','')[:60]} — {cite}")
            else:
                can_claim.append(f"- [CLAIM-WEB: {data.get('domain','')}] {data.get('title','')[:60]} — {cite}")
            claim_apa_cites.append(cite)
            url = data.get("url", "")
            if url:
                source_registry[url] = cite

        # All sources listed neutrally — LLM picks the lead during synthesis
        all_sources_flat: list[str] = []
        for art in articles:
            try:
                all_sources_flat.append(f"- {_safe_cite(art)}")
            except ValueError:
                continue
        for src in web_for_section:
            try:
                all_sources_flat.append(f"- {_safe_cite(src)}")
            except ValueError:
                continue
        for cite in claim_apa_cites:
            all_sources_flat.append(f"- {cite}  [claim-specific]")

        # Direct / Indirect / Guideline evidence
        direct_count = len(articles)
        web_count = len(web_for_section)
        direct_ev = f"{direct_count} PubMed {'studies' if direct_count != 1 else 'study'}" if direct_count else "None"
        indirect_ev = f"{web_count} trusted consensus/clinical source{'s' if web_count != 1 else ''}" if web_count else "None"

        # What not to claim: unsupported claims + outline fail field
        what_not_parts = []
        if unsupported_factual:
            what_not_parts.append("Unsupported factual claim: " + "; ".join(c[:80] for c in unsupported_factual[:3]))
        if not_established_questions:
            what_not_parts.append(
                "Automated extraction did not resolve; do not state as supported or unsupported: " + "; ".join(
                    _research_question_subject(c)[:80] for c in not_established_questions[:3]
                )
            )
        outline_fail = brief.get("fail", "")
        if outline_fail and outline_fail not in str(what_not_parts):
            what_not_parts.append(outline_fail)
        what_not = " | ".join(what_not_parts) if what_not_parts else "Do not overclaim beyond the evidence."

        # Writer framing based on evidence quality
        if research_questions and (articles or web_for_section):
            writer_framing = (
                f"{len(research_questions)} research question(s) were dispositioned. "
                "Preserve the recorded status. An unresolved extraction is not evidence that research is absent."
            )
        elif ev_status == "Direct clinical":
            writer_framing = f"Evidence directly supports {len(supported_claims)} of {len(claims)} claims. Write from study findings cited in CAN CLAIM."
        elif ev_status == "Guideline":
            writer_framing = f"Government/clinical guidelines are the primary evidence source ({len(web_for_section)} sources). Frame as guidance-level, not causal proof."
        elif ev_status == "Indirect":
            writer_framing = (
                "These sources support the named symptom, ingredient, warning sign, or care option only. "
                "Do not claim they prove that an herb prevents or cures a hangover."
            )
        elif best_score > 0 and best_score < 0.25:
            writer_framing = f"Claims have weak semantic match to evidence (best score: {best_score:.2f}). Use cautious framing — indirect support only."
        else:
            writer_framing = "EVIDENCE GAP — DO NOT DRAFT CLAIMS FOR THIS SECTION until a credible section-specific source is attached."

        # Writer action line
        writer_action = brief.get("pass", "")

        # Key citations (all sources including claim-specific)
        key_cites: list[str] = []
        for art in articles:
            try:
                key_cites.append(f"- {_safe_cite(art)}")
            except ValueError:
                continue
        for src in web_for_section:
            try:
                key_cites.append(f"- {_safe_cite(src)}")
            except ValueError:
                continue
        for cite in claim_apa_cites:
            key_cites.append(f"- {cite}  [claim-specific]")

        parent_h2 = h2_map.get(heading, "")
        section_lines: list[str] = []
        if parent_h2 and parent_h2 != current_h2:
            section_lines.extend([f"## {parent_h2}", ""])
            current_h2 = parent_h2
        section_lines.extend([
            f"### {heading}",
            f"Intent class: {intent}",
            f"Section goal: {section_goal or 'Describe ' + heading.lower()}",
            f"Writer priority: {writer_priority or 'Write this section clearly'}",
            f"Evidence status: {ev_status}",
            f"Search status: {search_status}",
            f"Claim strength: {'Strong' if ev_status == 'Direct clinical' else 'Moderate' if ev_status == 'Guideline' else 'Limited' if ev_status == 'Indirect' else 'None'}",
            f"Factual claim coverage: {len(supported_factual)}/{len(factual_claims)} supported",
            f"Research questions dispositioned: {resolved_question_count}/{len(research_questions)}",
            f"Strongest safe claim: {strongest_claim}",
        ])

        if all_sources_flat:
            section_lines.append("Available sources:")
            section_lines.extend(all_sources_flat[:8])

        if question_findings:
            section_lines.append("RESEARCH QUESTION FINDINGS:")
            section_lines.extend(question_findings)

        if can_claim:
            section_lines.append("CAN CLAIM:")
            section_lines.extend(can_claim[:8])

        section_lines.extend([
            f"Direct evidence: {direct_ev}",
            f"Indirect evidence: {indirect_ev}",
            f"Guideline support: {'Government/clinical sources available' if web_count else 'None'}",
            f"What not to claim: {what_not or 'Do not overclaim beyond the evidence.'}",
            f"Do not import beyond context: Stay within the scope of '{heading}'.",
            f"Writer framing: {writer_framing or 'Write from the evidence as presented.'}",
            f"Writer action line: {writer_action or 'Write this section to match the claims in the outline.'}",
        ])

        if key_cites:
            section_lines.append("Key citations:")
            section_lines.extend(key_cites[:8])

        has_section_sources = bool(articles or web_for_section)
        if research_mode == "exhaustive_v1" and search_failures:
            verification = (
                "UNVERIFIED — BLOCK DRAFTING: one or more bounded source "
                "queries failed after retries"
            )
        elif unsupported_factual:
            verification = "UNVERIFIED — BLOCK DRAFTING: one or more factual outline claims lack section evidence support"
        elif (
            research_mode == "exhaustive_v1"
            and research_questions
            and resolved_question_count < len(research_questions)
        ):
            verification = (
                "UNVERIFIED — BLOCK DRAFTING: one or more research questions "
                "remain search/extraction unresolved"
            )
        elif articles:
            verification = "Verified — section-specific PubMed evidence attached"
        elif ev_status == "Guideline":
            verification = "Consensus-supported — trusted section-specific source attached"
        elif web_for_section:
            verification = "Indirect component-supported — trusted section-specific source attached"
        else:
            verification = "UNVERIFIED — BLOCK DRAFTING"
        section_lines.append(f"Verification status: {verification}\n")

        sections_out.append("\n".join(section_lines))

    # Method and scope
    scope_lines = [
        f"# Clinical Research Brief: {topic}",
        "",
        "1. Search Scope and Method",
        f"- Exact search date: {today}.",
        "- Source types used: PubMed-indexed studies and government/clinical web sources.",
        "- Date filter: Last 7 years from search date.",
        f"- Retrieval mode: {research_mode}.",
        "- Retrieval protocol: PubMed section queries, then SERPAPI for every weak or missing H3; exhaustive_v1 paginates PubMed and extracts trusted source pages. Claim-based searches run independently for each section regardless of heading search results.",
        f"- Cross-section source reuse: {len(pubmed_results.get('reused_sources', {}))} source(s) reused where the title and abstract supported more than one H3.",
        f"- Total sources: {sum(len(ps.get('articles',[])) for ps in pubmed_sections if ps.get('heading') not in weak_sections)} PubMed + "
        f"{web_results.get('total_found', 0)} SERPAPI + "
        f"{sum(len(ps.get('claim_articles',[]))+len(ps.get('claim_web_sources',[])) for ps in pubmed_sections)} claim-specific.",
        "",
        "2. Executive Summary",
        f"- Safest editorial position: {topic} — write per the evidence for each section.",
        f"- Evidence strength profile: Most sections have {'direct clinical' if sum(len(ps.get('articles',[])) for ps in pubmed_sections) > 0 else 'indirect/guideline'} evidence.",
        "",
        "3. Core Editorial Position",
        f"Write each section according to its evidence status and outline brief. Government and clinical sources "
        f"carry guideline-level authority and should be cited alongside PubMed evidence.",
        "",
        "4. Evidence Language Guardrails",
        "Use these phrases:",
        "- can help reduce symptoms / may support",
        "- is associated with improved outcomes",
        "- is recommended as first-line in guidelines",
        "- government and clinical guidelines suggest",
        "Avoid: cures, guarantees, works for everyone, replaces professional treatment.",
        "",
        "5. Section-by-Section Research Brief",
        "",
        "\n".join(sections_out),
        "",
        "## Sources",
        *[f"- {citation}" for citation in sorted(source_registry.values())],
    ]

    return "\n".join(scope_lines)


def _extract_h2_map(outline_markdown: str) -> dict[str, str]:
    """Map each H3 heading to its parent H2 heading.

    Format-agnostic: handles any heading format by trying all known patterns:
      Standard: ## H2 / ### H3
      Pre-flight: **H2:** / - **H3:**
      Bare: H2: / H3:
    """
    h2_map: dict[str, str] = {}
    current_h2 = ""

    for line in outline_markdown.splitlines():
        stripped = line.strip()
        h2_match = re.match(r"^(?:##\s+|\*\*H2\s*:\*\*\s*|H2\s*[:.]\s*)(.+)$", stripped)
        if h2_match:
            current_h2 = h2_match.group(1).strip().rstrip("*").strip()
            continue
        h3_match = re.match(r"^(?:###\s+|-\s*\*\*H3\s*:\*\*\s*|H3\s*[:.]\s*)(.+)$", stripped)
        if h3_match and current_h2:
            h3 = h3_match.group(1).strip().rstrip("*").strip()
            h2_map[h3] = current_h2

    return h2_map


def _extract_h3s(outline_markdown: str) -> list[str]:
    """Extract all H3 headings using format-agnostic detection.

    Returns list of heading texts in order of appearance.
    """
    detected: list[str] = []

    def _clean(h: str) -> str:
        return h.strip().rstrip("*").strip()

    # Try all known patterns in order
    for pat in [
        r"^###\s+(.+)$",                                    # ### H3
        r"^\s*-+\s*\*\*H3\s*:?\*\*\s*(.+?)(?:\s*\*{0,2})$",  # - **H3:**
        r"^\s*\*\*H3\s*:?\*\*\s*(.+?)(?:\s*\*{0,2})$",      # **H3:**
        r"^\s*H3\s*[:.]\s*(.+?)$",                          # H3: or H3.
        r"^\s*\[H3\]\s*(.+?)$",                              # [H3] Title
        r"^\s*\(H3\)\s*(.+?)$",                              # (H3) Title
    ]:
        matches = re.findall(pat, outline_markdown, re.M)
        if matches:
            headings = [_clean(m) for m in matches if _clean(m)]
            if headings:
                detected = headings
                break

    # Generic fallback: any **bold** line not starting with H2
    if not detected:
        for line in outline_markdown.splitlines():
            stripped = line.strip()
            if re.match(r"^\*\*(?!H2\b)(.+?)\*\*\s*$", stripped):
                detected.append(_clean(stripped.strip("*")))

    return detected


def _clean_query(text: str, max_words: int = 8) -> str:
    """Clean text for query use: lowercase, strip punctuation, remove stopwords, keep top N words."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", text.lower())
    words = [w for w in cleaned.split() if w not in STOPWORDS and len(w) > 1]
    return " ".join(words[:max_words])


def _build_h3_queries(topic: str, h3: str, h2: str | None) -> list[str]:
    """Build up to 4 query tiers for a single H3 heading.

    No hardcoded expansions. Each tier tries a different framing:
      1. Verbatim H3 (cleaned)
      2. Topic + H3 core terms
      3. H2 parent context + H3 core terms
      4. Broad-stroke (drop qualifiers, keep domain nouns)

    Returns list of query strings to try in order. Stops at first PMID hit.
    """
    h3_base = _clean_query(h3)
    if not h3_base:
        return []

    topic_base = _clean_query(topic)

    queries = []

    # Tier 1: H3 verbatim — catches headings that already use PubMed language
    queries.append(h3_base)

    # Tier 2: Topic + H3 core — adds main topic framing
    if topic_base:
        h3_core = " ".join(h3_base.split()[:5])
        combined = f"{topic_base} {h3_core}"
        if combined != h3_base:
            queries.append(combined)

    # Tier 3: H2 context + H3 core — uses the section's parent heading for framing
    if h2:
        h2_base = _clean_query(h2, max_words=5)
        if h2_base:
            h3_core = " ".join(h3_base.split()[:5])
            combined = f"{h2_base} {h3_core}"
            if combined not in queries:
                queries.append(combined)

    # Tier 4: Broad-stroke — drop qualifier words, keep longest 3-4 domain nouns
    h3_words = h3_base.split()
    core_words = [w for w in h3_words if w not in QUALIFIER_WORDS]
    if not core_words:
        core_words = h3_words  # fallback if everything was a qualifier
    # Sort by length descending — longer words tend to be domain-specific nouns
    nouns = sorted(core_words, key=len, reverse=True)[:4]
    if len(nouns) >= 3:
        broad = " ".join(nouns)
        if broad not in queries and broad != h3_base:
            queries.append(broad)

    return queries


def expand_topic(topic: str) -> str:
    """Expand a colloquial topic string to PubMed-indexable medical terms."""
    lower = topic.lower()
    expansions = []
    for phrase, medical in COLLOQUIAL_EXPANSIONS.items():
        if phrase in lower:
            expansions.append(f"({medical})")
    # Also expand acronyms
    words = lower.split()
    for word in words:
        cleaned = word.strip(".,!?;:")
        if cleaned in TOPIC_ALIASES:
            expansions.append(TOPIC_ALIASES[cleaned])
    if expansions:
        return f"{topic} " + " ".join(expansions)
    return topic


def build_pubmed_queries(topic: str, outline_markdown: str) -> list[str]:
    """Build PubMed search queries from topic + outline H3 headings.

    Takes keyword fragments from the topic (first ~8 words stripped of
    stopwords) and combines with section heading terms.
    """
    # Extract keyword fragments from topic
    lower = topic.lower()
    # Remove common question stems
    for stem in ("why do i", "what is", "how does", "can you", "is it", "what are", "how to"):
        if lower.startswith(stem):
            lower = lower[len(stem):].strip()
            break
    # Remove stopwords and keep meaningful fragments
    fragments = [w.strip(".,?!:;") for w in lower.split() if w.lower() not in STOPWORDS and len(w) > 2]
    keyword_base = " ".join(fragments[:8])  # first 8 meaningful words

    queries = [keyword_base]

    # Also extract H3 headings for section-specific searches
    h3s = re.findall(r"^###\s+(.+)$", outline_markdown, re.M)
    for h3 in h3s[:6]:  # limit to 6 sections
        h3_clean = re.sub(r"[^a-z0-9\s]", "", h3.lower())
        h3_words = [w for w in h3_clean.split() if w not in STOPWORDS and len(w) > 2]
        if h3_words:
            section_query = f"{keyword_base} {' '.join(h3_words[:4])}"
            queries.append(section_query)

    return queries


def _esearch(query: str, retmax: int = 8, mindate: str | None = None) -> list[str]:
    """Search PubMed and return list of PMIDs."""
    query_params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(retmax),
        "sort": "relevance",
        "retmode": "json",
    }
    if os.environ.get("NCBI_API_KEY"):
        query_params["api_key"] = os.environ["NCBI_API_KEY"]
    params = urllib.parse.urlencode(query_params)
    # Add date filter if specified (default: last 7 years)
    if mindate:
        params += "&" + urllib.parse.urlencode({"mindate": mindate, "maxdate": "3000", "datetype": "pdat"})
    url = f"{ENTREZ_BASE}/esearch.fcgi?{params}"
    _ncbi_rate_limit()
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data.get("esearchresult", {}).get("idlist", [])


def _elink_related_pmids(pmid: str, max_results: int = 8) -> list[str]:
    """Return bounded PubMed-neighbor PMIDs for a promising seed article."""
    cache_key = f"{pmid}:{max_results}"
    cached = _research_cache_get("pubmed_related", cache_key)
    if isinstance(cached, list):
        return [str(value) for value in cached[:max_results]]

    query_params = {
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": pmid,
        "cmd": "neighbor_score",
        "retmode": "json",
    }
    if os.environ.get("NCBI_API_KEY"):
        query_params["api_key"] = os.environ["NCBI_API_KEY"]
    url = f"{ENTREZ_BASE}/elink.fcgi?{urllib.parse.urlencode(query_params)}"
    _ncbi_rate_limit()
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read().decode())

    related: list[str] = []
    for linkset in payload.get("linksets", []):
        for database in linkset.get("linksetdbs", []):
            if database.get("linkname") != "pubmed_pubmed":
                continue
            related.extend(str(value) for value in database.get("links", []))
    related = list(dict.fromkeys(value for value in related if value != str(pmid)))
    _research_cache_set("pubmed_related", cache_key, related[:max_results])
    return related[:max_results]


def _efetch(pmids: list[str], raise_on_error: bool = False) -> list[dict]:
    """Fetch article details for a list of PMIDs.

    Returns list of dicts with pmid, title, authors, journal, volume, issue,
    pages, year, doi, abstract.
    """
    if not pmids:
        return []
    query_params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    if os.environ.get("NCBI_API_KEY"):
        query_params["api_key"] = os.environ["NCBI_API_KEY"]
    params = urllib.parse.urlencode(query_params)
    url = f"{ENTREZ_BASE}/efetch.fcgi?{params}"
    try:
        _ncbi_rate_limit()
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml_data = resp.read().decode()
    except Exception:
        if raise_on_error:
            raise
        return []

    articles = []
    root = ET.fromstring(xml_data)
    for article_elem in root.findall(".//PubmedArticle"):
        try:
            pmid_el = article_elem.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else ""
            if not pmid:
                continue

            art = article_elem.find(".//Article")
            if art is None:
                continue

            title_el = art.find(".//ArticleTitle")
            title = "".join(title_el.itertext()) if title_el is not None else ""

            # Authors
            authors = []
            author_list = art.find(".//AuthorList")
            if author_list is not None:
                for author in author_list.findall("Author"):
                    last = author.find("LastName")
                    fore = author.find("ForeName")
                    if last is not None and fore is not None:
                        initials = " ".join(
                            f"{part[0].upper()}."
                            for part in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", fore.text or "")
                            if part
                        )
                        authors.append(f"{last.text}, {initials}".strip())
                    elif last is not None:
                        authors.append(last.text)

            # Journal
            journal_el = article_elem.find(".//Journal/Title")
            journal = journal_el.text if journal_el is not None else ""
            volume_el = article_elem.find(".//JournalIssue/Volume")
            issue_el = article_elem.find(".//JournalIssue/Issue")
            pagination_el = art.find(".//Pagination/MedlinePgn")
            volume = volume_el.text if volume_el is not None else ""
            issue = issue_el.text if issue_el is not None else ""
            pages = pagination_el.text if pagination_el is not None else ""

            # Year
            year_el = article_elem.find(".//PubDate/Year")
            if year_el is None:
                year_el = article_elem.find(".//PubDate/MedlineDate")
            year = (year_el.text or "")[:4] if year_el is not None else ""

            # DOI
            doi = ""
            for eid in article_elem.findall(".//ELocationID"):
                if eid.get("EIdType") == "doi":
                    doi = eid.text or ""
                    break

            # Abstract
            abstract_parts = []
            for abs_el in art.findall(".//AbstractText"):
                label = abs_el.get("Label", "")
                text = "".join(abs_el.itertext())
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = " ".join(abstract_parts)

            articles.append({
                "pmid": pmid,
                "title": title,
                "authors": authors,
                "journal": journal,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "year": year,
                "doi": doi,
                "abstract": abstract,
            })
        except Exception:
            continue

    return articles


def _esearch_page(
    query: str,
    retstart: int,
    retmax: int,
    mindate: str,
) -> dict[str, Any]:
    """Return one auditable PubMed result page for exhaustive mode."""
    query_params = {
        "db": "pubmed",
        "term": query,
        "retstart": str(max(0, retstart)),
        "retmax": str(max(1, retmax)),
        "sort": "relevance",
        "retmode": "json",
        "mindate": mindate,
        "maxdate": "3000",
        "datetype": "pdat",
    }
    if os.environ.get("NCBI_API_KEY"):
        query_params["api_key"] = os.environ["NCBI_API_KEY"]
    params = urllib.parse.urlencode(query_params)
    url = f"{ENTREZ_BASE}/esearch.fcgi?{params}"
    _ncbi_rate_limit()
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    result = data.get("esearchresult", {})
    return {
        "count": int(result.get("count", 0)),
        "ids": result.get("idlist", []),
    }


def _exhaustive_limits() -> ExhaustiveLimits:
    """Read bounded exhaustive-mode ceilings from environment variables."""
    return ExhaustiveLimits(
        pubmed_page_size=max(10, min(
            200, int(os.environ.get("RESEARCH_EXHAUSTIVE_PUBMED_PAGE_SIZE", "100"))
        )),
        pubmed_max_records_per_query=max(10, min(
            500, int(os.environ.get("RESEARCH_EXHAUSTIVE_PUBMED_MAX_PER_QUERY", "100"))
        )),
        pubmed_fetch_batch_size=max(10, min(
            200, int(os.environ.get("RESEARCH_EXHAUSTIVE_PUBMED_FETCH_BATCH", "100"))
        )),
        web_max_bytes=max(100_000, min(
            10_000_000, int(os.environ.get("RESEARCH_EXHAUSTIVE_WEB_MAX_BYTES", "2000000"))
        )),
        web_timeout_seconds=max(5, min(
            60, int(os.environ.get("RESEARCH_EXHAUSTIVE_WEB_TIMEOUT", "20"))
        )),
        retry_attempts=max(1, min(
            3, int(os.environ.get("RESEARCH_EXHAUSTIVE_RETRIES", "2"))
        )),
        cache_ttl_days=max(1, min(
            365, int(os.environ.get("RESEARCH_CACHE_TTL_DAYS", "30"))
        )),
    )


def _exhaustive_cache() -> JsonResearchCache:
    root = Path(os.environ.get(
        "RESEARCH_CACHE_DIR", str(Path(__file__).resolve().parent / ".research_cache")
    ))
    return JsonResearchCache(root, ttl_days=_exhaustive_limits().cache_ttl_days)


# ── OpenAlex search ──────────────────────────────────────────────────────


def _search_openalex(query: str, retmax: int = 5, topic_keywords: list[str] | None = None) -> list[dict]:
    """Search OpenAlex and return list of article dicts matching PubMed's shape.

    Free API, no key required. Returns title, authors, year, doi, abstract, id.
    When topic_keywords is provided, filters out articles whose title and
    abstract don't contain any of the keywords (prevents garbage results
    like diabetes guidelines for 'seek medical care' queries).
    """
    try:
        resp = requests.get(
            "https://api.openalex.org/works",
            params={"search": query, "per_page": retmax},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    papers = []
    for result in data.get("results", [])[:retmax]:
        try:
            # Authors
            authors = []
            for auth in result.get("authorships", []):
                name = auth.get("author", {}).get("display_name")
                if name:
                    authors.append(name)

            # Year
            year = str(result.get("publication_year") or "")

            # DOI
            doi_raw = result.get("doi") or ""
            doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

            # Abstract — OpenAlex uses inverted index, reconstruct
            abstract = ""
            inv_index = result.get("abstract_inverted_index")
            if inv_index:
                word_positions = []
                for word, positions in inv_index.items():
                    for pos in positions:
                        word_positions.append((pos, word))
                word_positions.sort()
                abstract = " ".join(w for _, w in word_positions)[:2000]

            url = result.get("id") or ""
            title = (result.get("title") or "").strip()
            if not title:
                continue

            # Relevance filter: article title MUST contain the topic phrase
            # e.g. "illness anxiety" must appear in the title for topic="illness anxiety"
            # If not, reject — prevents garbage diabetes papers from filling still_empty
            # and blocking SERPAPI from running for sections that need web sources
            if topic_keywords:
                title_lower = title.lower()
                if not any(kw.lower() in title_lower for kw in topic_keywords):
                    continue

            papers.append({
                "openalex_id": url.split("/")[-1] if url else "",
                "title": title,
                "authors": authors,
                "journal": (result.get("host_venue") or {}).get("display_name", "") if result.get("host_venue") else "",
                "year": year,
                "doi": doi,
                "abstract": abstract,
                "source": "openalex",
                "url": url,
            })
        except Exception:
            continue

    return papers


# ─── Stage Callers ────────────────────────────────────────────────────────


def _call_pubmed_search(input_data: dict, previous_errors: list[str] | None = None) -> str:
    """Stage 1a: search PubMed using SECTION_TYPE_TERMS-powered [Title/Abstract] queries.

    Uses the collect_pubmed_evidence.py approach:
    - Section types from outline → concept term families
    - Topic keywords + colloquial expansions → [Title/Abstract]-tagged topic terms
    - Queries built as (topic_terms) AND (concept_terms)
    - Results ranked by relevance_score() + has_specific_match()
    - Missing and weak sections tracked for trusted .gov/.edu fallback

    Python-only, deterministic. No Hermes call.
    """
    topic = input_data["topic"]
    outline_md = input_data["outline_markdown"]
    h2_map = input_data.get("h2_map", {})
    research_mode = str(input_data.get("research_mode") or "standard").casefold()
    exhaustive = research_mode == "exhaustive_v1"
    exhaustive_limits = _exhaustive_limits() if exhaustive else None
    exhaustive_cache = _exhaustive_cache() if exhaustive else None

    all_h3s = _extract_h3s(outline_md)
    section_types = _extract_section_types(outline_md)
    section_briefs = _extract_section_briefs(outline_md)

    if not all_h3s:
        return json.dumps({
            "topic": topic,
            "expanded_topic": topic,
            "section_results": [],
            "total_pmids": 0,
            "search_queries_used": [],
        })

    # Build queries per H3 using LLM (batched — one call for all H3s)
    h3_list: list[tuple[str, str, str, list[str]]] = []
    for h3 in all_h3s:
        h2 = h2_map.get(h3, "")
        st = section_types.get(h3, "")
        claims = list(section_briefs.get(h3, {}).get("claims", []))
        h3_list.append((h3, st, h2, claims))

    all_queries = _llm_generate_all_pubmed_queries(topic, h3_list)

    h3_data: list[tuple[str, list[str], str, str, list[str]]] = []
    for h3, st, h2, claims in h3_list:
        queries = all_queries.get(h3, [])
        if queries:
            h3_data.append((h3, queries, st, h2, claims))

    # Per-H3 results
    h3_results: dict[str, dict] = {}
    for h3, _, _, parent_h2, claims in h3_data:
        h3_results[h3] = {
            "articles": [],
            "pmids": [],
            "section_type": section_types.get(h3, ""),
            "parent_h2": parent_h2,
            "claims": claims,
            "queries_used": [],
            "all_articles": [],
            "tier_hit": None,
            "query_audits": [],
            "related_seed_pmids": [],
        }

    def search_one_h3(
        h3: str,
        queries: list[str],
        section_type: str,
        parent_h2: str,
        claims: list[str],
    ) -> dict:
        """Try every tier in order; stop only after a tier returns results."""
        today = date.today()
        mindate = f"{today.year - 7:04d}/{today.month:02d}/{today.day:02d}"
        all_articles: dict[str, dict] = {}
        queries_used: list[str] = []
        query_audits: list[dict[str, Any]] = []
        first_hit_tier = None
        for q_idx, query in enumerate(queries):
            if exhaustive:
                assert exhaustive_limits is not None
                articles, audit = paginate_pubmed(
                    query,
                    mindate,
                    _esearch_page,
                    lambda ids: _efetch(ids, raise_on_error=True),
                    cache=exhaustive_cache,
                    limits=exhaustive_limits,
                )
                query_audits.append(audit.to_dict())
            else:
                try:
                    pmids = _esearch(query, retmax=5, mindate=mindate)
                    articles = _efetch(pmids)
                except Exception:
                    articles = []
            articles = [
                article for article in articles
                if _pubmed_record_relevant(
                    article, topic, h3, section_type, parent_h2, claims
                )
            ]
            queries_used.append(query)
            if articles and first_hit_tier is None:
                first_hit_tier = q_idx + 1
            for article in articles:
                identity = article.get("pmid") or article.get("doi") or article.get("url") or article.get("title")
                if identity:
                    all_articles[str(identity)] = article
            # Standard mode is coverage-oriented, not exhaustive. Once three
            # section-relevant papers are found, later broad tiers add latency
            # and false-positive exposure without improving the brief.
            if not exhaustive and len(all_articles) >= 3:
                break
            if not exhaustive:
                time.sleep(0.35)

        # If ordinary queries locate a promising but thin evidence trail, use
        # PubMed's own citation-neighbor graph once. This is bounded, cached,
        # and still subject to the seven-year and section-relevance gates.
        related_seed_pmids: list[str] = []
        if (
            not exhaustive
            and len(queries) >= 3
            and 0 < len(all_articles) < 3
            and os.environ.get("RESEARCH_RELATED_EXPANSION", "1") != "0"
        ):
            seed = max(
                all_articles.values(),
                key=lambda article: _relevance_score(
                    article, topic, h3, section_type, parent_h2, claims
                ),
            )
            seed_pmid = str(seed.get("pmid") or "")
            if seed_pmid:
                related_seed_pmids.append(seed_pmid)
                try:
                    related_pmids = _elink_related_pmids(seed_pmid, max_results=8)
                    related_articles = _efetch(related_pmids)
                except Exception:
                    related_articles = []
                min_year = today.year - 7
                for article in related_articles:
                    try:
                        recent_enough = int(str(article.get("year", "0"))[:4]) >= min_year
                    except ValueError:
                        recent_enough = False
                    if not recent_enough or not _pubmed_record_relevant(
                        article, topic, h3, section_type, parent_h2, claims
                    ):
                        continue
                    identity = (
                        article.get("pmid") or article.get("doi") or
                        article.get("url") or article.get("title")
                    )
                    if identity:
                        all_articles[str(identity)] = article

        scored = sorted(
            all_articles.values(),
            key=lambda a: _relevance_score(
                a, topic, h3, section_type, parent_h2, claims
            ),
            reverse=True,
        )
        best = scored[:8 if exhaustive else 3]
        return {
            "articles": best,
            "pmids": [a["pmid"] for a in best if a.get("pmid")],
            "queries_used": queries_used,
            "all_articles": list(all_articles.values()),
            "tier_hit": first_hit_tier,
            "query_audits": query_audits,
            "related_seed_pmids": related_seed_pmids,
        }

    # Run H3s in parallel; query tiers within an H3 remain sequential.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_map = {
            executor.submit(search_one_h3, h3, queries, st, h2, claims): h3
            for h3, queries, st, h2, claims in h3_data if queries
        }
        for future in concurrent.futures.as_completed(future_map):
            h3 = future_map[future]
            try:
                h3_results[h3].update(future.result())
            except Exception:
                pass

    # Build section results with missing/weak tracking
    section_results = []
    missing_sections: list[str] = []
    weak_sections: list[str] = []

    for h3 in all_h3s:
        if h3 in h3_results:
            res = h3_results[h3]
            articles = res["articles"]
            st = res["section_type"]
            parent_h2 = res.get("parent_h2", "")
            claims = res.get("claims", [])
            tier = res["tier_hit"]

            if not articles:
                missing_sections.append(h3)
            elif articles:
                specific_expected = bool(
                    _literal_section_terms(h3, parent_h2, claims)
                    or _preferred_phrases(
                        h3, st,
                        " ".join((parent_h2, " ".join(claims))),
                    )
                )
                has_specific = any(
                    _has_specific_match(a, h3, st, parent_h2, claims)
                    for a in articles
                )
                top_score = _relevance_score(
                    articles[0], topic, h3, st, parent_h2, claims
                )
                if (specific_expected and not has_specific) or (
                    not specific_expected and top_score < 10
                ):
                    weak_sections.append(h3)

            section_results.append({
                "heading": h3,
                "search_term": res["queries_used"][0] if res["queries_used"] else "",
                "queries_used": res["queries_used"],
                "pmids": res["pmids"],
                "articles": articles,
                "tier_hit": tier,
                "section_type": st,
                "parent_h2": parent_h2,
                "claims": claims,
                "query_audits": res.get("query_audits", []),
                "related_seed_pmids": res.get("related_seed_pmids", []),
            })
        else:
            section_results.append({
                "heading": h3, "search_term": "", "pmids": [],
                "queries_used": [], "articles": [], "tier_hit": None, "section_type": "",
                "parent_h2": h2_map.get(h3, ""),
                "claims": section_briefs.get(h3, {}).get("claims", []),
                "query_audits": [], "related_seed_pmids": [],
            })

    all_queries = []
    for res in h3_results.values():
        all_queries.extend(res["queries_used"])

    return json.dumps({
        "topic": topic,
        "expanded_topic": topic,
        "section_results": section_results,
        "total_pmids": sum(len(r["pmids"]) for r in section_results),
        "search_queries_used": all_queries,
        "missing_sections": missing_sections,
        "weak_sections": weak_sections,
        "research_mode": research_mode,
        "query_audits": [
            audit
            for res in h3_results.values()
            for audit in res.get("query_audits", [])
        ],
    })


def _call_openalex_search(input_data: dict, previous_errors: list[str] | None = None) -> dict:
    """Stage 1b: search OpenAlex for H3s that PubMed returned 0 articles for.

    Only queries H3s listed in input_data['empty_h3s']. Two tiers per H3:
      1. Verbatim H3 heading
      2. Topic + H3 core terms

    Returns section_results matching the PubMed shape, merged into existing data.
    Python-only, deterministic. No key needed.
    """
    topic = input_data.get("topic", "")
    empty_h3s: list[dict] = input_data.get("empty_h3s", [])  # [{heading, h2, queries_tried}]
    h2_map = input_data.get("h2_map", {})

    if not empty_h3s:
        return {"section_results": [], "total_found": 0}

    results: dict[str, dict] = {}

    for entry in empty_h3s:
        h3 = entry["heading"]
        h2 = h2_map.get(h3, "")

        # Build relevance keywords: topic phrase + topic terms ONLY
        # (no H3 words — they're too generic like 'say', 'talk', 'boundaries')
        topic_clean = _clean_query(topic) if topic else ""
        topic_words = topic_clean.split()[:5] if topic_clean else []
        relevance_kw = [topic.lower().strip()] if topic else []
        relevance_kw.extend(w for w in topic_words if w not in relevance_kw)

        # Always query with topic + H3 combined — build bigrams for precision
        # (same approach as PubMed: no single-word topic terms like "exposure")
        topic_clean = _clean_query(topic) if topic else ""
        h3_clean = _clean_query(h3)
        if topic_clean and h3_clean:
            h3_core = " ".join(h3_clean.split()[:4])
            # Use quoted topic phrase for precision, not bare words
            quoted_topic = f'"{topic}"' if len(topic.split()) > 1 else topic
            combined_query = f"{quoted_topic} {h3_core}"
        else:
            combined_query = h3_clean or topic_clean

        # Tier 1: quoted topic phrase + H3 core (most targeted)
        if topic and h3_clean:
            h3_core = " ".join(h3_clean.split()[:4])
            quoted_query = f"\"{topic}\" {h3_core}" if len(topic.split()) > 1 else f"{topic} {h3_core}"
            articles = _search_openalex(quoted_query, retmax=5, topic_keywords=relevance_kw)
            if articles:
                results[h3] = {"articles": articles, "source": "openalex_tier1"}
                continue

        # Tier 2: unquoted topic + H3 combined (broader fallback)
        if combined_query:
            articles = _search_openalex(combined_query, retmax=5, topic_keywords=relevance_kw if topic else None)
            if articles:
                results[h3] = {"articles": articles, "source": "openalex_tier2"}

        # No results from OpenAlex either
        results[h3] = {"articles": [], "source": None}

    # Build section_results
    section_results = []
    for entry in empty_h3s:
        h3 = entry["heading"]
        r = results[h3]
        section_results.append({
            "heading": h3,
            "articles": r["articles"],
            "pmids": [],
            "openalex_ids": [
                a.get("openalex_id", "") for a in r["articles"] if a.get("openalex_id")
            ],
            "source": r["source"],
        })

    total_found = sum(len(r["articles"]) for r in section_results)
    return {"section_results": section_results, "total_found": total_found}


def _call_web_sources(input_data: dict, previous_errors: list[str] | None = None) -> str:
    """Find credible consensus/expert sources for every weak or missing H3.

    Each H3 is handled independently. A global query or result cap must never
    cause later sections to be skipped.
    """
    topic = input_data.get("topic", "")
    empty_h3s: list[dict] = input_data.get("empty_h3s", [])
    research_mode = str(input_data.get("research_mode") or "standard").casefold()
    exhaustive = research_mode == "exhaustive_v1"
    exhaustive_limits = _exhaustive_limits() if exhaustive else None
    exhaustive_cache = _exhaustive_cache() if exhaustive else None
    if not empty_h3s:
        # No fallback sections requested — skip SERPAPI entirely.
        return json.dumps({"topic": topic, "sources": [], "total_found": 0, "skipped": True})

    all_sources: list[dict] = []
    queries_run = 0
    coverage: dict[str, int] = {}
    paid_query_budget = max(1, int(os.environ.get("RESEARCH_MAX_SERP_QUERIES", "24")))
    paid_queries_claimed = 0
    paid_query_lock = threading.Lock()

    # Common English/medical stopwords to skip
    STOP_WORDS = {
        "about", "after", "also", "and", "are", "between", "can", "does",
        "down", "each", "effects", "for", "from", "having", "help", "how",
        "into", "long", "make", "more", "most", "much", "new", "not", "often",
        "ongoing", "other", "over", "same", "should", "side", "some", "such",
        "than", "that", "their", "them", "then", "there", "these", "they",
        "this", "through", "time", "under", "upon", "very", "ways", "what",
        "when", "where", "which", "while", "will", "with", "without", "year",
        "years", "your",
    }

    government_sites = (
        "site:nih.gov OR site:samhsa.gov OR site:cdc.gov OR site:fda.gov OR "
        "site:medlineplus.gov OR site:va.gov OR site:hhs.gov OR "
        "site:nccih.nih.gov OR site:nida.nih.gov OR site:ihs.gov"
    )

    def search_one_section(entry: dict) -> tuple[str, list[dict], int, int, list[str]]:
        nonlocal paid_queries_claimed
        h3 = entry.get("heading", "")
        parent_h2 = entry.get("h2", "")
        section_type = entry.get("section_type", "")
        claims = entry.get("claims", [])

        section_sources: list[dict] = []
        section_seen: set[str] = set()
        queries_attempted: list[str] = []

        # ── LLM query generation: one call returns 4 DDG + 2 PubMed queries ──
        llm_prompt = (
            f"You are a PhD-level clinical researcher conducting a systematic literature search.\n"
            f"\n"
            f"Article topic: {topic}\n"
            f"H3 heading: {h3}\n"
            f"H2 context: {parent_h2}\n"
            f"Section type: {section_type}\n"
            f"Approved claims: {'; '.join(claims[:4])}\n"
            f"\n"
            f"Construct a query ladder of INCREASING BROADNESS. Think step by step:\n"
            f"1. First, identify the PRECISE clinical/diagnostic term for this concept\n"
            f"2. Then identify its synonyms, narrower terms, and broader umbrella terms\n"
            f"3. Finally, identify adjacent constructs and related conditions\n"
            f"\n"
            f"A PhD scholar would never search for the lay wording of an H3 as-is. "
            f"They would use the exact clinical terminology that appears in the literature.\n"
            f"\n"
            f"Return ONLY a JSON object:\n"
            f'- "ddg": list of 4 DDG query strings, narrow to broad, using clinical terms\n'
            f'- "pubmed": list of 2 PubMed Boolean strings (narrow then broad) with MeSH, [Title/Abstract], year ranges\n'
            f'- "clinical_terms_used": list of precise clinical terms and synonyms used\n'
        )
        ok, stdout, stderr = _hermes_call("default", [], llm_prompt, timeout=30)
        if ok and stdout.strip():
            try:
                # Strip markdown code fences if present
                cleaned = stdout.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                llm_result = json.loads(cleaned.strip())
                # ── Run DDG queries in order (narrow → broad) ──
                for lq in llm_result.get("ddg", [])[:4]:
                    queries_attempted.append(f"[LLM] {lq}")
                    try:
                        from ddgs import DDGS
                        for r in DDGS().text(lq, max_results=5):
                            url = (r.get("href") or "").strip()
                            title = (r.get("title") or "").strip()
                            snippet = (r.get("body") or "").strip()
                            if url and title and url not in section_seen and _is_trusted_web_source(url):
                                section_seen.add(url)
                                section_sources.append({
                                    "url": url, "title": title,
                                    "domain": _normalized_domain(url),
                                    "authority": _authority_label(url),
                                    "relevance": snippet[:400], "h3": h3,
                                    "search_query": f"[LLM] {lq}",
                                    "support_scope": "llm_query",
                                })
                                if len(section_sources) >= 2:
                                    break
                        if len(section_sources) >= 2:
                            break
                    except Exception:
                        continue

                # ── If DDG found <2, try PubMed ──
                if len(section_sources) < 2:
                    for pq in llm_result.get("pubmed", [])[:2]:
                        queries_attempted.append(f"[LLM-PUBMED] {pq}")
                        try:
                            esearch_url = (
                                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                                f"?db=pubmed&term={urllib.parse.quote(pq)}"
                                "&retmax=5&retmode=json"
                            )
                            resp = requests.get(esearch_url, timeout=15)
                            if resp.status_code == 200:
                                for pmid in resp.json().get("esearchresult", {}).get("idlist", [])[:3]:
                                    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                                    if url not in section_seen:
                                        section_seen.add(url)
                                        section_sources.append({
                                            "url": url, "title": f"PubMed {pmid}",
                                            "domain": "pubmed.ncbi.nlm.nih.gov",
                                            "authority": "U.S. Government resource",
                                            "relevance": f"LLM query: {pq[:200]}",
                                            "h3": h3,
                                            "search_query": f"[LLM-PUBMED] {pq[:100]}",
                                            "support_scope": "llm_query",
                                        })
                                        if len(section_sources) >= 2:
                                            break
                        except Exception:
                            continue
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                pass

        selected_sources = section_sources[:3]
        local_queries = len(queries_attempted)
        local_cache_hits = 0
        if exhaustive:
            assert exhaustive_limits is not None
            extracted_sources: list[dict] = []
            for source in selected_sources:
                page = fetch_trusted_page(
                    source["url"],
                    _is_trusted_web_source,
                    _http_get_bounded,
                    cache=exhaustive_cache,
                    limits=exhaustive_limits,
                )
                enriched = dict(source)
                enriched["extraction_status"] = page.status
                enriched["final_url"] = page.final_url
                enriched["extraction_error"] = page.error
                enriched["page_cache_hit"] = page.cache_hit
                if page.text:
                    enriched["evidence_text"] = page.text[:50000]
                    if not _web_result_relevant(
                        topic,
                        h3,
                        enriched.get("title", ""),
                        page.text[:20000],
                        concept_terms,
                    ):
                        enriched["extraction_status"] = "extracted_but_not_section_relevant"
                        enriched["evidence_text"] = ""
                extracted_sources.append(enriched)
            selected_sources = extracted_sources

        return h3, selected_sources, local_queries, local_cache_hits, queries_attempted

    # Independent H3 web searches run concurrently. This changes elapsed time,
    # not the evidence standard or the number of permitted queries.
    section_sources_map: dict[str, list[dict]] = {}
    query_ledger: dict[str, list[str]] = {}
    cache_hits = 0
    workers = max(1, min(8, int(os.environ.get("RESEARCH_SERP_WORKERS", "4"))))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(search_one_section, entry) for entry in empty_h3s]
        for future in concurrent.futures.as_completed(futures):
            h3, sources, local_queries, local_cache_hits, attempted = future.result()
            section_sources_map[h3] = sources
            query_ledger[h3] = attempted
            queries_run += local_queries
            cache_hits += local_cache_hits

    # Reuse a trusted source for every other targeted H3 that its title and
    # snippet genuinely support. The same URL is cited in several sections but
    # appears only once in the final Sources registry.
    unique_pool: dict[str, dict] = {}
    for sources in section_sources_map.values():
        for source in sources:
            unique_pool.setdefault(source.get("url", ""), source)

    reused_sources: dict[str, list[str]] = {}
    for entry in empty_h3s:
        h3 = entry.get("heading", "")
        section_type = entry.get("section_type", "")
        parent_h2 = entry.get("h2", "")
        claims = entry.get("claims", [])
        section_context = " ".join((parent_h2, " ".join(claims)))
        concepts = [
            term.rstrip("*") for term in _preferred_phrases(
                h3, section_type, section_context
            )
            if len(term.rstrip("*")) >= 4
        ]
        existing = {s.get("url", "") for s in section_sources_map.get(h3, [])}
        for url, source in unique_pool.items():
            if not url or url in existing:
                continue
            if _web_result_relevant(
                topic, h3, source.get("title", ""),
                source.get("relevance", ""), concepts,
            ):
                reused = dict(source)
                reused["h3"] = h3
                reused["reused_from_h3"] = source.get("h3", "")
                section_sources_map.setdefault(h3, []).append(reused)
                existing.add(url)
                reused_sources.setdefault(url, []).append(h3)
            if len(section_sources_map.get(h3, [])) >= 3:
                break

    for entry in empty_h3s:
        h3 = entry.get("heading", "")
        sources = section_sources_map.get(h3, [])[:3]
        coverage[h3] = len(sources)
        all_sources.extend(sources)

    return json.dumps({
        "topic": topic,
        "sources": all_sources,
        "total_found": len(all_sources),
        "h3s_targeted": [e["heading"] for e in empty_h3s],
        "coverage": coverage,
        "queries_run": queries_run,
        "cache_hits": cache_hits,
        "query_budget": paid_query_budget,
        "budget_exhausted": paid_queries_claimed >= paid_query_budget,
        "query_ledger": query_ledger,
        "reused_sources": reused_sources,
        "research_mode": research_mode,
        "pages_extracted": sum(
            1 for source in all_sources
            if source.get("extraction_status") == "extracted"
        ),
        "page_extraction_failures": sum(
            1 for source in all_sources
            if exhaustive and source.get("extraction_status") != "extracted"
        ),
    })


def _call_clinical_brief(input_data: dict, previous_errors: list[str] | None = None) -> str:
    """Stage 3: Hermes call for Clinical Research Brief.

    Prompt now returns raw markdown (not JSON). Wraps as JSON for
    the execute_stage pipeline.

    Web sources are grouped by H3 heading so the LLM can easily
    associate sources with their sections.
    """
    pubmed_json = json.dumps(input_data.get("pubmed_evidence", {}), indent=2)[:4000]

    # Format web sources grouped by H3 heading with authority labels
    web_sources = input_data.get("web_sources", [])
    if web_sources:
        def authority_label(url: str, domain: str) -> str:
            """Classify a source by its domain authority."""
            if ".gov" in domain:
                if "cdc" in domain: return "CDC public health guidance"
                if "nih" in domain or "nlm" in domain: return "NIH research resource"
                if "samhsa" in domain: return "SAMHSA clinical guidance"
                if "medlineplus" in domain: return "MedlinePlus health resource"
                if "schools" in domain or "education" in domain: return "State education guidance"
                return "U.S. Government resource"
            if ".edu" in domain:
                return "University research / academic guidance"
            if "mayoclinic" in domain: return "Mayo Clinic clinical guidance"
            if "clevelandclinic" in domain: return "Cleveland Clinic clinical guidance"
            if "webmd" in domain: return "WebMD health resource"
            if "healthline" in domain: return "Healthline consumer health"
            if "ncbi" in domain or "pmc" in domain: return "NIH / National Library of Medicine"
            if "who" in domain: return "World Health Organization"
            if "nami" in domain: return "NAMI mental health guidance"
            if "aap" in domain or "healthychildren" in domain: return "American Academy of Pediatrics"
            if "apa" in domain: return "American Psychological Association"
            if "nimh" in domain: return "NIMH research guidance"
            return f"Professional resource ({domain})"

        by_h3: dict[str, list[dict]] = {}
        for src in web_sources:
            h3 = src.get("h3", "")
            if h3:
                by_h3.setdefault(h3, []).append(src)
        if by_h3:
            sections = []
            for h3, srcs in by_h3.items():
                urls = "\n".join(
                    f"    - [{authority_label(s['url'], s.get('domain',''))}] {s['title'][:80]} — {s['url']}"
                    for s in srcs[:5]
                )
                sections.append(f"  For section '{h3}':\n{urls}")
            sources_formatted = "GOVERNMENT AND CLINICAL SOURCES (grouped by section):\n" + "\n".join(sections)
        else:
            # Ungrouped fallback
            sources_formatted = json.dumps(web_sources, indent=2)[:2000]
    else:
        sources_formatted = "No web sources available."

    prompt = CLINICAL_BRIEF_PROMPT.format(
        outline=input_data["outline_markdown"],
        pubmed_evidence=pubmed_json,
        supplementary_sources=sources_formatted,
    )
    if previous_errors:
        prompt += "\n\nFix these issues:\n" + "\n".join(previous_errors)
    ok, out, err = _hermes_call("research-agent", ["research-agent"], prompt, timeout=180)
    if not ok:
        raise RuntimeError(f"Clinical brief synthesis failed: {err}")
    # Return raw markdown — parse function below handles wrapping
    return out.strip()


def _parse_clinical_brief(raw: str) -> dict:
    """Parse raw markdown into brief_markdown dict for execute_stage."""
    return {"brief_markdown": raw}


def _call_dumbed_down(input_data: dict, previous_errors: list[str] | None = None) -> str:
    """Stage 4: Hermes call for Grade 8 dumbed-down brief.

    Returns raw markdown (not JSON).
    """
    prompt = DUMBED_DOWN_PROMPT.format(
        research_brief=input_data["clinical_brief"],
    )
    if previous_errors:
        prompt += "\n\nFix:\n" + "\n".join(previous_errors)
    ok, out, err = _hermes_call("research-agent", ["research-agent", "brief-dumb-down"], prompt, timeout=300)
    if not ok:
        debug_path = "/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/avery-house-output/dumbed-down-failed.txt"
        with open(debug_path, "w") as f:
            f.write(f"STDOUT:\n{out}\n\nSTDERR:\n{err}")
        raise RuntimeError(f"Dumbed-down brief failed: {err[:200]}")
    return out.strip()


def _parse_dumbed_down(raw: str) -> dict:
    """Parse raw markdown into brief_markdown dict for execute_stage."""
    return {"brief_markdown": raw}


def _parse_dumbed_down_for_outline(raw: str, outline_h3s: list[str]) -> dict:
    """Restore exact approved H3 casing when the model changed casing only."""
    canonical = {heading.casefold(): heading for heading in outline_h3s}

    def replace_heading(match: re.Match) -> str:
        produced = match.group(1).strip()
        approved = canonical.get(produced.casefold(), produced)
        return f"### {approved}"

    normalized = re.sub(r"^###\s+(.+)$", replace_heading, raw, flags=re.M)
    return {"brief_markdown": normalized}


# ─── Deterministic Assembly ──────────────────────────────────────────────


def assemble_research(clinical: ClinicalBriefResult, dumbed: DumbedDownResult) -> tuple[str, str]:
    """Return clinical brief and dumbed-down brief as separate strings.

    Pure Python. No LLM involvement.
    """
    return clinical.brief_markdown.strip(), dumbed.brief_markdown.strip()


def _search_claims_for_section(
    heading: str,
    claims: list[str],
    topic: str,
) -> dict:
    """Independently search PubMed and SERPAPI for the section's claims.

    Runs regardless of heading-based search results. Finds evidence that
    heading+topic queries may miss (e.g., CAGE/AUDIT tools mentioned in claims
    of a 'herbs for hangover' article).

    Returns {'claim_articles': list[dict], 'claim_web_sources': list[dict]}
    """
    if not claims:
        return {"claim_articles": [], "claim_web_sources": []}

    # Extract search terms from claims (including acronyms)
    claim_terms: set[str] = set()
    for claim in claims:
        cleaned = re.sub(
            r"^(?:research|verify|compare|evaluate|determine|examine|assess|investigate)"
            r"\s+(?:whether\s+)?(?:the\s+)?(?:evidence\s+(?:for|on)\s+)?",
            "", claim, flags=re.I,
        )
        # Keep all-caps acronyms (CAGE, AUDIT, PHQ, etc.)
        for word in re.findall(r"[A-Z][A-Z0-9]{2,}", cleaned):
            if len(word) >= 3:
                claim_terms.add(word)
        # Keep longer regular words
        for word in re.findall(r"[a-zA-Z][a-zA-Z-]{4,}", cleaned):
            wl = word.lower()
            if wl not in STOPWORDS and wl not in RESEARCH_QUERY_NOISE:
                claim_terms.add(wl)

    # Remove topic words that would dilute the search
    topic_words = set(w.lower() for w in _keywords(topic))
    filtered = sorted(t for t in claim_terms if t.lower() not in topic_words)
    if not filtered:
        return {"claim_articles": [], "claim_web_sources": []}

    # ── PubMed claim search ──
    today = date.today()
    mindate = f"{today.year - 7:04d}/{today.month:02d}/{today.day:02d}"
    topic_untagged, topic_fielded = _pubmed_topic_expressions(topic)
    claim_expression = "(" + " OR ".join(
        _fielded_pubmed_term(t) for t in filtered[:6] if _fielded_pubmed_term(t)
    ) + ")"
    pubmed_query = (
        f"({topic_fielded or topic_untagged}) AND {claim_expression}"
        if (topic_fielded or topic_untagged) else claim_expression
    )
    claim_articles: list[dict] = []
    try:
        pmids = _esearch(pubmed_query, retmax=5, mindate=mindate)
        articles = _efetch(pmids)
        for a in articles:
            if _web_result_relevant(topic, heading, a.get("title", ""), a.get("abstract", "")[:500], filtered):
                claim_articles.append(a)
    except Exception:
        pass

    # ── SERPAPI claim search ──
    claim_web: list[dict] = []
    serp_query = (
        "(site:.gov OR site:.edu) "
        f'"{topic}" '
        "(" + " OR ".join(
            f'"{t}"' for t in sorted(filtered)[:6]
        ) + ")"
    )
    try:
        from ddgs import DDGS
        ddg = DDGS()
        ddg_results = list(ddg.text(serp_query, max_results=5))
        for r in ddg_results:
            url = (r.get("href") or "").strip()
            title = (r.get("title") or "").strip()
            snippet = (r.get("body") or "").strip()
            if url and title and _is_trusted_web_source(url) and \
               _web_result_relevant(topic, heading, title, snippet, filtered):
                claim_web.append({
                    "url": url,
                    "title": title,
                    "domain": _normalized_domain(url),
                    "authority": _authority_label(url),
                    "relevance": snippet[:400],
                    "h3": heading,
                    "source": "claim_search",
                })
    except Exception:
        pass

    return {
        "claim_articles": claim_articles[:3],
        "claim_web_sources": claim_web[:3],
    }


# ─── Orchestration ───────────────────────────────────────────────────────


def run_research_pipeline(
    topic: str,
    outline_markdown: str,
    db: Any,
    article_id: str,
    metrics: dict[str, Any] | None = None,
) -> str:
    """Run the full research pipeline with conditional 3-layer search.

    Flow:
      1. PubMed search on every H3
      2. SERPAPI fallback for every weak or missing H3
      3. Deterministic clinical brief assembly and validation
      4. Dumbed-down Brief (one Flash call, validated with retries)
      → Assembly

    Args:
        topic: Article topic / primary keyword
        outline_markdown: Approved outline markdown
        db: Open SQLite connection
        article_id: Article UUID

    Returns:
        Completed research package Markdown (clinical + dumbed-down briefs).

    Raises:
        StageFailedError if any stage exhausts retries.
    """
    run_id = str(uuid.uuid4())[:8]
    run_started = time.perf_counter()
    research_mode = os.environ.get("RESEARCH_MODE", "standard").strip().casefold()
    if research_mode not in {"standard", "exhaustive_v1"}:
        raise ValueError(
            f"Unsupported RESEARCH_MODE={research_mode!r}; "
            "expected 'standard' or 'exhaustive_v1'"
        )
    if metrics is not None:
        metrics.clear()
        metrics.update({"run_id": run_id, "topic": topic, "research_mode": research_mode})

    # Extract outline H3s for validation cross-check + H2 context map (dual format)
    outline_h3s = _extract_h3s(outline_markdown)
    h2_map = _extract_h2_map(outline_markdown)
    section_briefs = _extract_section_briefs(outline_markdown)

    # ──────────────────────────────────────────────────────────────────────
    # Stage 1a: PubMed search — parallel per-H3, tiered, for ALL H3s
    # ──────────────────────────────────────────────────────────────────────
    stage_started = time.perf_counter()
    pubmed_raw = execute_stage(
        stage_name="pubmed_search",
        input_data={
            "topic": topic,
            "outline_markdown": outline_markdown,
            "h2_map": h2_map,
            "research_mode": research_mode,
        },
        call_fn=_call_pubmed_search,
        parse_fn=parse_json_response,
        validate_fn=lambda d: validate_pubmed_evidence(d),
        article_id=article_id,
        max_attempts=1,
    )
    if metrics is not None:
        metrics["pubmed_seconds"] = round(time.perf_counter() - stage_started, 3)
        metrics["pubmed_queries"] = len(pubmed_raw.get("search_queries_used", []))
        query_audits = pubmed_raw.get("query_audits", [])
        metrics["pubmed_records_retrieved"] = sum(
            int(audit.get("records_fetched", 0)) for audit in query_audits
        )
        metrics["pubmed_query_failures"] = sum(
            bool(audit.get("errors")) for audit in query_audits
        )
        metrics["pubmed_queries_truncated"] = sum(
            bool(audit.get("truncated_by_limit")) for audit in query_audits
        )
        metrics["pubmed_cache_hits"] = sum(
            int(audit.get("cache_hits", 0)) for audit in query_audits
        )

    # Identify H3s with 0 articles from PubMed OR weak matches
    pubmed_sections = pubmed_raw.get("section_results", [])
    # Reuse evidence already found anywhere in the article before purchasing
    # fallback searches. One strong review or guideline may legitimately
    # support several H3 sections.
    missing_sections, weak_sections, reused_sources = _reuse_pubmed_sources(
        topic, pubmed_sections
    )
    pubmed_raw["missing_sections"] = missing_sections
    pubmed_raw["weak_sections"] = weak_sections
    pubmed_raw["reused_sources"] = reused_sources

    pubmed_raw["section_results"] = pubmed_sections

    # Run the authority/consensus lane only for H3s that remain missing or weak
    # after deterministic PubMed retrieval and valid cross-H3 reuse.
    targeted_h3s: list[dict] = []
    for section in pubmed_sections:
        heading = section.get("heading", "")
        if heading not in set(missing_sections) | set(weak_sections):
            continue
        if heading:
            targeted_h3s.append({
                "heading": heading,
                "h2": h2_map.get(heading, ""),
                "section_type": section.get("section_type", ""),
                "pubmed_queries_tried": section.get("queries_used", []),
                "claims": section_briefs.get(heading, {}).get("claims", []),
            })

    # ──────────────────────────────────────────────────────────────────────
    # Stage 2: SERPAPI — only for H3s still empty after both academic DBs
    # ──────────────────────────────────────────────────────────────────────
    web_raw = {"topic": topic, "sources": [], "total_found": 0, "h3s_targeted": []}
    if targeted_h3s:
        stage_started = time.perf_counter()
        web_raw = json.loads(_call_web_sources({
            "topic": topic,
            "empty_h3s": targeted_h3s,
            "research_mode": research_mode,
        }))
        web_validation = validate_web_sources(web_raw, strict=True)
        if not web_validation.valid:
            raise StageFailedError("web_sources", web_validation.errors)
        if metrics is not None:
            metrics["serpapi_seconds"] = round(time.perf_counter() - stage_started, 3)
            metrics["serpapi_queries"] = int(web_raw.get("queries_run", 0))
            metrics["serpapi_cache_hits"] = int(web_raw.get("cache_hits", 0))
            metrics["web_pages_extracted"] = int(web_raw.get("pages_extracted", 0))
            metrics["web_page_extraction_failures"] = int(
                web_raw.get("page_extraction_failures", 0)
            )

    pubmed_raw["section_results"] = pubmed_sections

    # ──────────────────────────────────────────────────────────────────────
    # Stage 2b: Claim-based search — independent search for each section's claims
    # Runs regardless of heading-based results. Finds evidence that heading+topic
    # queries miss (e.g., CAGE/AUDIT in a 'herbs for hangover' article).
    # ──────────────────────────────────────────────────────────────────────
    stage_started = time.perf_counter()
    for section in pubmed_sections:
        heading = section.get("heading", "")
        claims = section_briefs.get(heading, {}).get("claims", [])
        if not claims:
            continue
        claim_results = _search_claims_for_section(heading, claims, topic)
        section["claim_articles"] = claim_results.get("claim_articles", [])
        section["claim_web_sources"] = claim_results.get("claim_web_sources", [])

    # ──────────────────────────────────────────────────────────────────────
    # Stage 2c: LLM source verification + auto-correction
    #  1. Verify each source supports its section's claims
    #  2. For sections that lost all sources, generate replacement queries
    #     (DDG + PubMed) using what was learned about why previous results were wrong
    #  3. Run new queries and accept results from trusted domains
    # ──────────────────────────────────────────────────────────────────────
    stage_started = time.perf_counter()
    filtered, affected_headings = _llm_verify_sources(pubmed_sections, topic)

    # Re-search for sections that lost all sources — the LLM verifier knows what went wrong
    if affected_headings:
        for section in pubmed_sections:
            heading = section.get("heading", "")
            if heading not in affected_headings:
                continue
            claims = section_briefs.get(heading, {}).get("claims", [])
            parent_h2 = h2_map.get(heading, "")
            section_type = section_briefs.get(heading, {}).get("section_type", "")
            # Generate replacement queries informed by what was rejected
            repair_prompt = (
                f"Article topic: {topic}\n"
                f"H3 heading: {heading}\n"
                f"H2 context: {parent_h2}\n"
                f"Section type: {section_type}\n"
                f"Approved claims: {'; '.join(claims[:4])}\n"
                f"\n"
                f"All candidate sources for this section were rejected by a clinical relevance "
                f"check — they were about biology, genetics, animal studies, or unrelated "
                f"conditions instead of the actual topic. Generate 2 improved PubMed Boolean "
                f"queries and 3 DDG search queries that would find genuinely relevant sources "
                f"for this specific psychological/clinical topic. Use clinical synonyms, not "
                f"literal H3 wording.\n"
                f"\n"
                f"Return ONLY a JSON object with two keys:\n"
                f'- "pubmed": list of 2 PubMed query strings\n'
                f'- "ddg": list of 3 DDG query strings\n'
                f'Example: {{"pubmed": ["...", "..."], "ddg": ["...", "..."]}}\n'
            )
            ok, stdout, stderr = _hermes_call("default", [], repair_prompt, timeout=30)
            if not ok or not stdout.strip():
                continue
            try:
                new_queries = json.loads(stdout.strip())
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

            # Run new PubMed queries
            for pq in new_queries.get("pubmed", [])[:2]:
                try:
                    esearch_url = (
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                        f"?db=pubmed&term={urllib.parse.quote(pq)}&retmax=5&retmode=json"
                    )
                    resp = requests.get(esearch_url, timeout=15)
                    if resp.status_code == 200:
                        for pmid in resp.json().get("esearchresult", {}).get("idlist", [])[:3]:
                            article_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                            if not any(a.get("url") == article_url for a in section.get("articles", [])):
                                section.setdefault("articles", []).append({
                                    "pmid": pmid, "url": article_url,
                                    "title": f"PubMed {pmid}",
                                })
                except Exception:
                    continue

            # Run new DDG queries
            for lq in new_queries.get("ddg", [])[:3]:
                try:
                    from ddgs import DDGS
                    for r in DDGS().text(lq, max_results=5):
                        url = (r.get("href") or "").strip()
                        title = (r.get("title") or "").strip()
                        snippet = (r.get("body") or "").strip()
                        if url and title and _is_trusted_web_source(url):
                            if not any(s.get("url") == url for s in section.get("web_sources", [])):
                                section.setdefault("web_sources", []).append({
                                    "url": url, "title": title,
                                    "domain": _normalized_domain(url),
                                    "authority": _authority_label(url),
                                    "relevance": snippet[:400],
                                    "h3": heading,
                                    "support_scope": "llm_repair",
                                })
                except Exception:
                    continue

    if metrics is not None:
        metrics["claim_search_seconds"] = round(time.perf_counter() - stage_started, 3)

    # ──────────────────────────────────────────────────────────────────────
    # Stage 3: Assemble research packet (pure Python, no LLM)
    # ──────────────────────────────────────────────────────────────────────
    stage_started = time.perf_counter()
    research_packet = _format_research_packet(
        topic=topic,
        outline_markdown=outline_markdown,
        pubmed_results=pubmed_raw,
        web_results=web_raw,
        section_briefs=section_briefs,
    )
    clinical_validation = validate_clinical_brief(
        {"brief_markdown": research_packet}, outline_h3s=outline_h3s
    )
    if not clinical_validation.valid:
        raise StageFailedError("clinical_brief", clinical_validation.errors)
    if metrics is not None:
        metrics["assembly_validation_seconds"] = round(time.perf_counter() - stage_started, 3)
        metrics["pubmed_sources_reused"] = len(reused_sources)
        metrics["web_sources_reused"] = len(web_raw.get("reused_sources", {}))

    # ──────────────────────────────────────────────────────────────────────
    # Stage 4: Dumbed-down brief (1 Hermes call)
    # ──────────────────────────────────────────────────────────────────────
    stage_started = time.perf_counter()
    dumbed = execute_stage(
        stage_name="dumbed_down_brief",
        input_data={"clinical_brief": research_packet},
        call_fn=_call_dumbed_down,
        parse_fn=lambda raw: _parse_dumbed_down_for_outline(raw, outline_h3s),
        validate_fn=lambda d: validate_dumbed_down(d, outline_h3s=outline_h3s),
        article_id=article_id,
        max_attempts=max(1, min(2, int(os.environ.get("RESEARCH_MAX_FLASH_ATTEMPTS", "2")))),
    )
    dumbed_brief = dumbed["brief_markdown"].strip()

    # Save generated briefs before validation so runner can capture on failure
    _dbg_dir = Path(os.environ.get("RESEARCH_DEBUG_DIR", ""))
    if _dbg_dir.is_dir():
        (_dbg_dir / "research-brief.md").write_text(research_packet)
        (_dbg_dir / "dumbed-down-brief.md").write_text(dumbed_brief)

    # Retry dumbed-down with validation feedback (same pattern as execute_stage)
    semantic_errors = []
    for dumbed_attempt in range(max(1, min(2, int(os.environ.get("DUMBED_MAX_RETRIES", "3"))))):
        semantic_validation = validate_writer_semantics(
            dumbed_brief, research_packet, outline_h3s
        )
        if semantic_validation.valid:
            semantic_errors = []
            break
        semantic_errors = semantic_validation.errors
        if dumbed_attempt + 1 >= max(1, min(2, int(os.environ.get("DUMBED_MAX_RETRIES", "3")))):
            break
        # Retry dumbed-down with validation errors fed back
        error_context = "\n".join(f"- {e}" for e in semantic_errors)
        dumbed_retry = execute_stage(
            stage_name=f"dumbed_down_retry_{dumbed_attempt + 1}",
            input_data={
                "clinical_brief": research_packet,
                "previous_errors": error_context,
            },
            call_fn=_call_dumbed_down,
            parse_fn=lambda raw: _parse_dumbed_down_for_outline(raw, outline_h3s),
            validate_fn=lambda d: validate_dumbed_down(d, outline_h3s=outline_h3s),
            article_id=article_id,
            max_attempts=1,
        )
        dumbed_brief = dumbed_retry["brief_markdown"].strip()
        if _dbg_dir.is_dir():
            (_dbg_dir / "dumbed-down-brief.md").write_text(dumbed_brief)

    if semantic_errors:
        raise StageFailedError("writer_brief_semantics", semantic_errors)

    if metrics is not None:
        metrics["writer_brief_seconds"] = round(time.perf_counter() - stage_started, 3)
        metrics["total_seconds"] = round(time.perf_counter() - run_started, 3)
        metrics["status"] = "OK"

    return research_packet, dumbed_brief
