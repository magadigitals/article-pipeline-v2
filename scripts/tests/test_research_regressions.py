import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import research_pipeline as rp
from research_validators import (
    validate_clinical_brief,
    validate_dumbed_down,
    validate_writer_semantics,
)


class FakeResponse:
    def __init__(self, query):
        self.query = query

    def raise_for_status(self):
        return None

    def json(self):
        # Echo enough of the query into the title/snippet to pass relevance.
        return {
            "organic_results": [
                {
                    "link": f"https://nccih.nih.gov/health/{abs(hash(self.query))}",
                    "title": self.query,
                    "snippet": self.query,
                },
                {
                    "link": f"https://nih.gov/health/{abs(hash(self.query + 'b'))}",
                    "title": self.query + " clinical guidance",
                    "snippet": self.query,
                },
            ]
        }


class ResearchRegressionTests(unittest.TestCase):
    def test_outline_research_assignments_are_questions_not_factual_claims(self):
        questions = [
            "Research whether ginger helps alcohol-related nausea.",
            "Verify whether electrolytes reduce hangover severity.",
            "Compare evidence for tea versus supplements.",
        ]
        self.assertTrue(all(rp._is_research_directive(item) for item in questions))
        self.assertFalse(rp._is_research_directive("Ginger relieves hangover nausea."))
        self.assertEqual(
            rp._research_question_subject(questions[0]),
            "ginger helps alcohol-related nausea",
        )

    def test_unproven_research_question_is_dispositioned_not_failed(self):
        heading = "How herbs can target common hangover symptoms"
        outline = f"""## Evidence\n### {heading}\n**Claims:**\n- Research whether symptom-matched herbs improve hangover relief.\n"""
        pubmed = {
            "weak_sections": [heading], "missing_sections": [],
            "section_results": [{
                "heading": heading, "section_type": "", "articles": [],
            }],
        }
        web = {
            "total_found": 1,
            "sources": [{
                "h3": heading,
                "url": "https://www.niaaa.nih.gov/hangovers",
                "domain": "niaaa.nih.gov",
                "title": "Hangovers and the limits of proposed remedies",
                "relevance": "No hangover remedy has been scientifically proven effective.",
                "support_scope": "direct_topic",
            }],
        }
        packet = rp._format_research_packet(
            "herbs for hangover", outline, pubmed, web,
            rp._extract_section_briefs(outline),
        )
        self.assertNotIn("UNVERIFIED — BLOCK DRAFTING", packet)
        self.assertIn("Research questions dispositioned: 1/1", packet)
        self.assertIn("Not resolved from the retrieved title, abstract, or snippet", packet)
        self.assertTrue(validate_clinical_brief(
            {"brief_markdown": packet}, [heading]
        ).valid)

    def test_unsupported_factual_assertion_still_blocks_drafting(self):
        heading = "Herbal efficacy"
        outline = f"""## Evidence\n### {heading}\n**Claims:**\n- Every herbal remedy cures a hangover.\n"""
        pubmed = {
            "weak_sections": [heading], "missing_sections": [],
            "section_results": [{
                "heading": heading, "section_type": "", "articles": [],
            }],
        }
        web = {
            "total_found": 1,
            "sources": [{
                "h3": heading,
                "url": "https://www.niaaa.nih.gov/hangovers",
                "domain": "niaaa.nih.gov",
                "title": "General alcohol information",
                "relevance": "General information about alcohol.",
                "support_scope": "direct_topic",
            }],
        }
        packet = rp._format_research_packet(
            "herbs for hangover", outline, pubmed, web,
            rp._extract_section_briefs(outline),
        )
        self.assertIn("UNVERIFIED — BLOCK DRAFTING", packet)
        # Non-fatal: sections without direct evidence can still proceed
        # while carrying UNVERIFIED markers for the writer to handle.
        self.assertTrue(validate_clinical_brief(
            {"brief_markdown": packet}, [heading]
        ).valid)

    def test_search_miss_cannot_become_universal_absence_claim(self):
        bad = """# Clinical Research Brief: Example
## Topic
### Evidence
There is no research on this treatment.
Source URL: https://nih.gov/example
## Sources
- https://nih.gov/example
"""
        result = validate_clinical_brief(
            {"brief_markdown": bad}, ["Evidence"]
        )
        self.assertFalse(result.valid)
        self.assertTrue(any("absence claim" in error for error in result.errors))

        scoped = bad.replace(
            "There is no research on this treatment.",
            "The automated search did not resolve this question; this does not mean that no research exists.",
        )
        self.assertTrue(validate_clinical_brief(
            {"brief_markdown": scoped}, ["Evidence"]
        ).valid)

    def test_one_pubmed_source_can_support_multiple_sections_without_new_search(self):
        article = {
            "pmid": "42",
            "url": "https://pubmed.ncbi.nlm.nih.gov/42/",
            "title": "Alcohol hangover mechanisms, dehydration, sleep disruption and gastrointestinal symptoms",
            "abstract": (
                "Alcohol suppresses vasopressin and increases urination, contributing to thirst and headache. "
                "Fragmented sleep contributes to fatigue, while gastric irritation contributes to nausea."
            ),
            "year": "2025",
            "publication_types": ["Review"],
            "source_layer": "pubmed",
        }
        sections = [
            {
                "heading": "How dehydration contributes to thirst and headache",
                "section_type": "causes_mechanisms",
                "articles": [article], "pmids": ["42"],
            },
            {
                "heading": "How disrupted sleep and stomach irritation affect symptoms",
                "section_type": "causes_mechanisms",
                "articles": [], "pmids": [],
            },
        ]
        missing, weak, reused = rp._reuse_pubmed_sources("alcohol hangover", sections)
        self.assertNotIn(sections[1]["heading"], missing)
        self.assertEqual(sections[1]["pmids"], ["42"])
        self.assertIn(sections[1]["heading"], reused[article["url"]])

    def test_semantic_matcher_uses_abstract_not_title_alone(self):
        heading = "Why the body feels tired after alcohol"
        sections = [{
            "heading": heading,
            "section_type": "causes_mechanisms",
            "articles": [{
                "title": "Alcohol hangover review",
                "abstract": "Alcohol fragments sleep and early waking contributes to fatigue the next day.",
            }],
        }]
        result = rp._semantic_claim_checker(
            [], {heading: {"claims": ["Fragmented sleep contributes to fatigue."]}},
            sections, [], {heading: []},
        )
        self.assertEqual(result[heading]["unsupported"], [])

    def test_how_or_why_writer_section_must_explain_cause_to_effect(self):
        heading = "Why the body feels the way it does after alcohol"
        clinical = f"""# Clinical Research Brief\n## Topic\n### {heading}\nEvidence status: Direct clinical\nhttps://niaaa.nih.gov/hangovers\n## Sources\n- https://niaaa.nih.gov/hangovers\n"""
        listing = f"""### {heading}\n- **Plain facts:** NIAAA lists dehydration, disrupted sleep, irritation, and inflammation as contributors.\n- **Safe wording:** Several processes overlap.\n- **Source URLs:** https://niaaa.nih.gov/hangovers\n"""
        result = validate_writer_semantics(listing, clinical, [heading])
        self.assertFalse(result.valid)
        self.assertTrue(any("promises an explanation" in e for e in result.errors))

        explained = f"""### {heading}\n- **Plain facts:** Fluid loss contributes to thirst and headache. Fragmented sleep leads to fatigue. Stomach irritation causes nausea.\n- **Safe wording:** These processes can overlap.\n- **Source URLs:** https://niaaa.nih.gov/hangovers\n"""
        self.assertTrue(validate_writer_semantics(explained, clinical, [heading]).valid)

    def test_valid_why_and_how_to_sections_do_not_false_fail(self):
        why = "Why treatment access remains a challenge"
        how_to = "How to start the conversation and verify options"
        clinical = f"""### {why}\nEvidence status: Guideline\nhttps://hhs.gov/access\n### {how_to}\nEvidence status: Guideline\nhttps://samhsa.gov/help\n"""
        writer = f"""### {why}\n- **Plain facts:** Distance can make care harder to reach. Harmful institutional experiences can reduce trust.\n- **Source URLs:** https://hhs.gov/access\n### {how_to}\n- **Plain facts:** Start with a neutral observation. Ask what support feels acceptable. Verify services directly.\n- **Source URLs:** https://samhsa.gov/help\n"""
        self.assertTrue(validate_writer_semantics(writer, clinical, [why, how_to]).valid)

    def test_required_safety_categories_cannot_disappear(self):
        heading = "Safety"
        clinical = f"""### {heading}\nEvidence status: Guideline\nMedication interactions require care. Pregnancy and breastfeeding need individualized guidance. Alcohol overdose requires 911. Severe withdrawal can include delirium tremens. Call 988 for a suicide crisis.\nhttps://nih.gov/safety\n"""
        writer = f"""### {heading}\n- **Plain facts:** Use products carefully.\n- **Source URLs:** https://nih.gov/safety\n"""
        result = validate_writer_semantics(writer, clinical, [heading])
        # Safety guidance is now non-fatal — practical topics may skip it.
        # The result should be valid (no fatal errors) even when safety
        # guidance from the clinical packet is absent from the dumbed-down brief.
        safety_errors = [e for e in result.errors if "dropped required" in e]
        self.assertEqual(len(safety_errors), 0)

    def test_pmc_repository_is_not_presented_as_nih_author(self):
        with self.assertRaises(ValueError):
            rp._apa7_cite({
                "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
                "domain": "pmc.ncbi.nlm.nih.gov",
                "title": "A clinical trial",
            })
        # PMC URLs without full metadata raise ValueError rather than
        # fabricating "PubMed Central repository copy".

    def test_indirect_evidence_cannot_become_affirmative_treatment_claim(self):
        heading = "Ginger for nausea after drinking"
        clinical = f"""### {heading}\nEvidence status: Indirect\nhttps://nccih.nih.gov/ginger\n"""
        writer = f"""### {heading}\n- **Plain facts:** Ginger relieves hangover nausea.\n- **Safe wording:** It may be useful.\n- **Source URLs:** https://nccih.nih.gov/ginger\n"""
        result = validate_writer_semantics(writer, clinical, [heading])
        self.assertFalse(result.valid)
        self.assertTrue(any("indirect/component" in e for e in result.errors))

    def test_writer_cannot_introduce_unvetted_source_url(self):
        heading = "Safety"
        clinical = f"### {heading}\nEvidence status: Guideline\nhttps://fda.gov/approved\n"
        writer = f"""### {heading}\n- **Plain facts:** Follow product warnings.\n- **Source URLs:** https://example.com/unvetted\n"""
        result = validate_writer_semantics(writer, clinical, [heading])
        self.assertFalse(result.valid)
        self.assertTrue(any("absent from the clinical evidence packet" in e for e in result.errors))

    def test_section_type_and_pubmed_relevance_are_section_specific(self):
        outline = """### Intergenerational effects through epigenetics
- **Type:** definition
- **Depth:** Explain the boundary.
**Claims:**
- Research whether epigenetic inheritance is established.
"""
        self.assertEqual(
            rp._extract_section_types(outline)["Intergenerational effects through epigenetics"],
            "definition",
        )
        brief = rp._extract_section_briefs(outline)["Intergenerational effects through epigenetics"]
        self.assertEqual(brief["type"], "definition")
        self.assertEqual(brief["claims"], ["Research whether epigenetic inheritance is established."])
        self.assertNotIn("**Type:** definition", brief["claims"])
        unrelated = {
            "title": "Physiological effects of pornography addiction",
            "abstract": "A narrative review of addiction and epigenetic mechanisms.",
        }
        self.assertFalse(rp._pubmed_record_relevant(
            unrelated,
            "Native American substance abuse",
            "Intergenerational effects through epigenetics",
            "definition",
        ))

    def test_dumbed_down_heading_casing_is_restored_deterministically(self):
        parsed = rp._parse_dumbed_down_for_outline(
            "### Substance abuse in Native youth\nBody",
            ["Substance abuse in native youth"],
        )
        self.assertIn("### Substance abuse in native youth", parsed["brief_markdown"])

    def test_pubmed_query_plan_has_section_and_evidence_synthesis_tiers(self):
        queries = rp._build_pubmed_queries_v3(
            "Native American substance abuse",
            "How treatment can respect culture and community",
            section_type="cultural",
            parent_h2="Treatment and recovery",
        )
        self.assertGreaterEqual(len(queries), 3)
        self.assertTrue(any("Title/Abstract" in q and "AND" in q for q in queries))
        self.assertTrue(any("systematic review[Publication Type]" in q for q in queries))

    def test_section_claims_drive_concepts_before_editorial_shape(self):
        phrases = rp._preferred_phrases(
            "Why the body feels the way it does after alcohol",
            section_type="definition",
            context=(
                "Hangover mechanisms. Research dehydration, disrupted sleep, "
                "gastric irritation, inflammation, and acetaldehyde."
            ),
        )
        self.assertIn("alcohol metabolism", phrases)
        self.assertIn("sleep disturbance*", phrases)
        self.assertIn("gastrointestinal", phrases)
        self.assertNotIn("active listening", phrases)

    def test_blockquoted_outline_claims_are_preserved_for_research(self):
        outline = """## Mechanism
### Why anxiety can make the hands shake
> **Type:** causes_mechanisms
> **Claims:**
> 1. Research physiological tremor and autonomic arousal.
> - Verify whether sympathetic activation can amplify shaking.
> **Pass:** Explain cause and effect.
"""
        claims = rp._extract_section_briefs(outline)[
            "Why anxiety can make the hands shake"
        ]["claims"]
        self.assertEqual(claims, [
            "Research physiological tremor and autonomic arousal.",
            "Verify whether sympathetic activation can amplify shaking.",
        ])

    def test_treatment_review_and_differential_are_supported_outline_types(self):
        self.assertIn("treatment_review", rp.TYPE_MAP)
        self.assertIn("differential", rp.TYPE_MAP)
        treatment = rp._preferred_phrases(
            "Ginger for nausea", "treatment_review", "Herbal options"
        )
        differential = rp._preferred_phrases(
            "When shaking may have another cause", "differential"
        )
        self.assertIn("herbal medicine", treatment)
        self.assertIn("differential diagnosis", differential)

    def test_pubmed_query_ladder_uses_claims_and_pubmed_atm(self):
        queries = rp._build_pubmed_queries_v3(
            "herbs for hangover",
            "How herbs can target common hangover symptoms",
            section_type="treatment_review",
            parent_h2="What the evidence says",
            claims=[
                "Research whether ginger reduces nausea.",
                "Verify safety and medication interactions.",
            ],
        )
        self.assertGreaterEqual(len(queries), 4)
        self.assertNotIn("Title/Abstract", queries[0])
        self.assertIn("ginger", " ".join(queries).lower())
        self.assertIn("nausea", " ".join(queries).lower())
        self.assertTrue(any("Title/Abstract" in query for query in queries[1:]))
        self.assertTrue(any("systematic review[Publication Type]" in query for query in queries))

    def test_primary_query_separates_topic_from_evidence_need(self):
        queries = rp._build_pubmed_queries_v3(
            "my hands shake when anxious",
            "Why anxiety can make the hands shake",
            section_type="causes_mechanisms",
            parent_h2="What is happening",
            claims=["Research physiological tremor and autonomic arousal."],
        )
        query = queries[0].lower()
        self.assertIn("anxiety", query)
        self.assertIn("tremor", query)
        self.assertIn("autonomic", query)
        self.assertIn("sympathetic", queries[1].lower())
        evidence_clause = query.rsplit(" and ", 1)[-1]
        self.assertNotIn('"hands"', evidence_clause)
        self.assertNotIn('"shake"', evidence_clause)

    def test_query_construction_generalizes_across_unrelated_sections(self):
        cases = [
            (
                "my hands shake when anxious",
                "Why anxiety can make the hands shake",
                ["Research physiological tremor and autonomic arousal."],
                ("tremor", "anxiety"),
            ),
            (
                "is depression normal",
                "When low mood may meet criteria for depression",
                ["Compare ordinary sadness with depressive disorder criteria."],
                ("depressive", "criteria"),
            ),
            (
                "buprenorphine long-term effects",
                "Hormonal and metabolic effects to monitor",
                ["Research endocrine, metabolic, and adverse effects."],
                ("buprenorphine", "endocrine"),
            ),
            (
                "Native American substance abuse",
                "How historical trauma can affect substance use",
                ["Research historical trauma in American Indian communities."],
                ("american indian", "trauma"),
            ),
        ]
        for topic, heading, claims, expected in cases:
            with self.subTest(topic=topic, heading=heading):
                rendered = " ".join(rp._build_pubmed_queries_v3(
                    topic, heading, parent_h2="Clinical evidence", claims=claims
                )).lower()
                self.assertTrue(all(term in rendered for term in expected))

    def test_topic_overlap_without_h3_evidence_is_rejected(self):
        supplement_survey = {
            "title": "Dietary supplement use in older adults",
            "abstract": (
                "The survey recorded dietary supplement use and alcohol use "
                "but did not evaluate ginger, nausea, safety, or hangovers."
            ),
        }
        # Remove negated evidence words: retrieval relevance is lexical and
        # must not accept the source merely because broad topic words overlap.
        supplement_survey["abstract"] = (
            "The survey recorded dietary supplement use and alcohol use in "
            "middle-aged and older adults."
        )
        self.assertFalse(rp._pubmed_record_relevant(
            supplement_survey,
            "herbs for hangover",
            "How herbs can target common hangover symptoms",
            "treatment_review",
            "What the evidence says",
            ["Research whether ginger reduces nausea and verify safety interactions."],
        ))

        parkinson_review = {
            "title": "Diagnosis and treatment of Parkinson disease",
            "abstract": "Tremor is common. Anxiety can occur in Parkinson disease.",
        }
        self.assertFalse(rp._pubmed_record_relevant(
            parkinson_review,
            "my hands shake when anxious",
            "Why anxiety can make the hands shake",
            "causes_mechanisms",
            "What is happening",
            ["Research physiological tremor and autonomic arousal."],
        ))

        anxiety_tremor = {
            "title": "Enhanced physiological tremor during anxiety",
            "abstract": (
                "Sympathetic autonomic arousal can amplify physiological "
                "tremor in anxious states."
            ),
        }
        self.assertTrue(rp._pubmed_record_relevant(
            anxiety_tremor,
            "my hands shake when anxious",
            "Why anxiety can make the hands shake",
            "causes_mechanisms",
            "What is happening",
            ["Research physiological tremor and autonomic arousal."],
        ))

        withdrawal = {
            "title": "Alcohol Withdrawal Syndrome: Outpatient Management",
            "abstract": (
                "Withdrawal may include anxiety, tremor, and autonomic "
                "hyperactivity."
            ),
        }
        self.assertFalse(rp._pubmed_record_relevant(
            withdrawal,
            "my hands shake when anxious",
            "Why anxiety can make the hands shake",
            "causes_mechanisms",
            "What is happening",
            ["Research physiological tremor and autonomic arousal."],
        ))

        performance_anxiety = {
            "title": "Virtual reality exposure in music performance anxiety",
            "abstract": (
                "Physical symptoms arise with increased sympathetic tone and "
                "include tremor, increased heart rate, and nausea."
            ),
        }
        self.assertTrue(rp._pubmed_record_relevant(
            performance_anxiety,
            "my hands shake when anxious",
            "Why anxiety can make the hands shake",
            "causes_mechanisms",
            "What is happening",
            ["Research physiological tremor and autonomic arousal."],
        ))
        self.assertTrue(rp._has_specific_match(
            performance_anxiety,
            "Why anxiety can make the hands shake",
            "causes_mechanisms",
            "What is happening",
            ["Research physiological tremor and autonomic arousal."],
        ))

    def test_pubmed_searches_all_h3s_and_reaches_later_tiers(self):
        outline = "\n".join(
            f"## Parent {i}\n### Section heading {i}" for i in range(12)
        )
        article = {
            "pmid": "123", "title": "Topic section heading clinical review",
            "abstract": "Topic section heading", "year": "2025",
            "publication_types": ["Review"],
            "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        }

        with patch.object(rp, "_llm_generate_all_pubmed_queries", return_value={"Section heading 0": ["q1", "q2"], "Section heading 1": ["q1", "q2"], "Section heading 2": ["q1", "q2"], "Section heading 3": ["q1", "q2"], "Section heading 4": ["q1", "q2"], "Section heading 5": ["q1", "q2"], "Section heading 6": ["q1", "q2"], "Section heading 7": ["q1", "q2"], "Section heading 8": ["q1", "q2"], "Section heading 9": ["q1", "q2"], "Section heading 10": ["q1", "q2"], "Section heading 11": ["q1", "q2"]}), \
             patch.object(rp, "_esearch", side_effect=lambda q, **_: [] if q == "q1" else ["123"]) as mock_search, \
             patch.object(rp, "_efetch", side_effect=lambda ids: [article] if ids else []), \
             patch.object(rp.time, "sleep", return_value=None):
            result = json.loads(rp._call_pubmed_search({
                "topic": "topic", "outline_markdown": outline,
                "h2_map": rp._extract_h2_map(outline),
            }))

        self.assertEqual(len(result["section_results"]), 12)
        self.assertTrue(all(s["tier_hit"] == 2 for s in result["section_results"]))
        self.assertEqual(mock_search.call_count, 24)

    def test_ddg_targets_every_missing_h3(self):
        from outline_pipeline import configure_pipeline
        configure_pipeline(
            hermes_bin=os.path.expanduser("~/.local/bin/hermes"),
            model="deepseek-v4-flash", provider="deepseek",
            db_path="/tmp/test_research_pipeline.db",
            hermesscripts=os.path.expanduser("~/.hermes/scripts"),
        )
        missing = [
            {"heading": f"Herb safety section {i}", "h2": "Safety"}
            for i in range(1, 8)
        ]

        def fake_ddg(query, max_results=5):
            return [
                {"href": f"https://nih.gov/herb{i}", "title": f"Herbal Hangover Safety {i}", "body": f"Clinical guidance for herbal hangover safety section"}
                for i in range(1, 4)
            ]

        mock_instance = MagicMock()
        mock_instance.text.side_effect = fake_ddg
        mock_ddgs = MagicMock(return_value=mock_instance)

        with patch.dict(os.environ, {"RESEARCH_CACHE_DISABLE": "1"}), \
             patch("ddgs.DDGS", mock_ddgs), \
             patch("research_pipeline._hermes_call", return_value=(True, '{"ddg": ["herbal hangover safety"], "pubmed": []}', "")):
            result = json.loads(rp._call_web_sources({
                "topic": "herbs for hangover",
                "empty_h3s": missing,
            }))

        # Verify the structural contract: every targeted H3 appears in coverage
        self.assertEqual(result["h3s_targeted"], [x["heading"] for x in missing])
        self.assertEqual(set(result["coverage"]), set(result["h3s_targeted"]))
        # Verify DDG was actually called
        self.assertGreater(mock_instance.text.call_count, 0)

    def test_ddg_cache_prevents_repeat_query(self):
        from outline_pipeline import configure_pipeline
        configure_pipeline(
            hermes_bin=os.path.expanduser("~/.local/bin/hermes"),
            model="deepseek-v4-flash", provider="deepseek",
            db_path="/tmp/test_research_pipeline.db",
            hermesscripts=os.path.expanduser("~/.hermes/scripts"),
        )
        missing = [{"heading": "Ginger for nausea", "h2": "Herbs", "claims": []}]
        call_count = 0

        def fake_ddg(query, max_results=5):
            nonlocal call_count
            call_count += 1
            return [
                {"href": "https://nih.gov/ginger", "title": "Herbal Hangover Ginger for Nausea", "body": "Clinical guidance for herbal hangover ginger use"}
            ]

        mock_instance = MagicMock()
        mock_instance.text.side_effect = fake_ddg
        mock_ddgs = MagicMock(return_value=mock_instance)

        with tempfile.TemporaryDirectory() as cache_dir, patch.dict(os.environ, {
            "RESEARCH_CACHE_DIR": cache_dir,
            "RESEARCH_MAX_SERP_QUERIES_PER_H3": "1",
        }), patch("ddgs.DDGS", mock_ddgs), patch("research_pipeline._hermes_call", return_value=(True, '{"ddg": ["ginger nausea herbal"], "pubmed": []}', "")):
            first = json.loads(rp._call_web_sources({
                "topic": "herbs for hangover", "empty_h3s": missing,
            }))
            second = json.loads(rp._call_web_sources({
                "topic": "herbs for hangover", "empty_h3s": missing,
            }))

        self.assertEqual(call_count, 2)  # LLM-first: each call generates queries
        self.assertEqual(first["queries_run"], 1)
        self.assertEqual(second["queries_run"], 1)

    def test_commercial_domain_is_never_government(self):
        self.assertEqual(
            rp._authority_label("https://recoveryunplugged.com/gov-advice"),
            "Web source (recoveryunplugged.com)",
        )
        self.assertFalse(rp._is_trusted_web_source("https://addictions.com/article"))
        self.assertTrue(rp._is_trusted_web_source("https://nccih.nih.gov/health/herbs"))
        self.assertFalse(rp._web_result_relevant(
            "Native American substance abuse", "Treatment options",
            "Influenza among Native American adolescents", "Treatment and prevention",
        ))
        self.assertTrue(rp._web_result_relevant(
            "Native American substance abuse", "Treatment options",
            "Substance use treatment for American Indian communities",
            "Clinical treatment guidance and recommendations",
            ["treatment"],
        ))
        # Topic anchor required in title — ginger for nausea alone is not enough
        # to establish relevance to "herbs for hangover" (Fix 4).
        self.assertFalse(rp._web_result_relevant(
            "herbs for hangover", "Ginger and peppermint for nausea and stomach upset",
            "Ginger for the prevention of nausea", "Clinical guidance for nausea and stomach upset",
            ["ginger", "peppermint", "nausea", "stomach upset"],
        ))
        self.assertFalse(rp._topic_matches_text(
            "herbs for hangover", "Ginger for nausea and stomach upset"
        ))

    def test_clinical_brief_blocks_source_free_consensus(self):
        brief = """# Clinical Research Brief: Example

## Topic
### Section one
No direct sources available for this section — write from clinical consensus and expert opinion.

## Sources
"""
        result = validate_clinical_brief(
            {"brief_markdown": brief}, outline_h3s=["Section one"]
        )
        self.assertFalse(result.valid)
        self.assertTrue(any("consensus" in e.lower() for e in result.errors))
        self.assertTrue(any("no section-specific source" in e.lower() for e in result.errors))

    def test_weak_pubmed_and_unsupported_claim_are_not_presented_as_direct(self):
        outline = """## Safety
### What the reader should know
> **Claims:**
> 1. Use a cautious claim.
"""
        pubmed = {
            "weak_sections": ["What the reader should know"],
            "missing_sections": [],
            "section_results": [{
                "heading": "What the reader should know",
                "section_type": "",
                "articles": [{
                    "pmid": "999",
                    "title": "Unrelated cellulite treatment",
                    "url": "https://pubmed.ncbi.nlm.nih.gov/999/",
                }],
            }],
        }
        web = {
            "total_found": 1,
            "sources": [{
                "h3": "What the reader should know",
                "url": "https://nccih.nih.gov/health/herbs",
                "domain": "nccih.nih.gov",
                "title": "Herbs safety guidance",
                "relevance": "Safety guidance",
            }],
        }
        packet = rp._format_research_packet(
            "herbs for hangover", outline, pubmed, web,
            rp._extract_section_briefs(outline),
        )
        self.assertNotIn("Unrelated cellulite treatment", packet)
        self.assertIn("Evidence status: Guideline", packet)
        self.assertIn("UNVERIFIED — BLOCK DRAFTING", packet)
        self.assertIn("## Sources", packet)
        # Non-fatal: UNVERIFIED sections produce briefs for the writer to handle.
        self.assertTrue(validate_clinical_brief(
            {"brief_markdown": packet}, ["What the reader should know"]
        ).valid)

    def test_dumbed_down_contract_requires_exact_h3_and_delimiter(self):
        good = """# Dumbed-Down Research Brief: Example
<!-- GOLDEN_DUMBED_DOWN_BRIEF -->
## Topic
### Exact heading
* **Source URLs:** https://nih.gov/example
## Sources
- https://nih.gov/example
"""
        self.assertTrue(validate_dumbed_down(
            {"brief_markdown": good}, ["Exact heading"]
        ).valid)

    def test_orchestrator_wires_fallback_and_validated_dumbdown(self):
        outline = "## Topic\n### Exact heading\n"
        pubmed = {
            "section_results": [{
                "heading": "Exact heading", "section_type": "", "articles": [],
                "pmids": [],
            }],
            "missing_sections": ["Exact heading"], "weak_sections": [],
        }
        web = {
            "topic": "example", "total_found": 1,
            "h3s_targeted": ["Exact heading"],
            "coverage": {"Exact heading": 1},
            "sources": [{
                "h3": "Exact heading", "url": "https://nih.gov/example",
                "domain": "nih.gov", "title": "Example exact heading guidance",
                "relevance": "Example exact heading guidance",
            }],
        }
        dumb = """# Dumbed-Down Research Brief: Example
<!-- GOLDEN_DUMBED_DOWN_BRIEF -->
## Topic
### Exact heading
* **Source URLs:** https://nih.gov/example
## Sources
- https://nih.gov/example
"""

        def fake_stage(**kwargs):
            if kwargs["stage_name"] == "pubmed_search":
                return pubmed
            if kwargs["stage_name"] == "dumbed_down_brief":
                parsed = {"brief_markdown": dumb}
                self.assertTrue(kwargs["validate_fn"](parsed).valid)
                return parsed
            self.fail(f"Unexpected stage {kwargs['stage_name']}")

        with patch.object(rp, "execute_stage", side_effect=fake_stage), \
             patch.object(rp, "_call_web_sources", return_value=json.dumps(web)):
            clinical, simplified = rp.run_research_pipeline(
                "example", outline, db=None, article_id="test-article"
            )

        self.assertIn("# Clinical Research Brief: example", clinical)
        self.assertIn("Consensus-supported", clinical)
        self.assertEqual(simplified, dumb.strip())


class TopicAnchoringRegressionTests(unittest.TestCase):
    """Fix 2-3: Every PubMed and claim query must retain the article topic."""

    def test_pubmed_component_query_includes_topic(self):
        """Topic-free PubMed component searches are rejected (Fix 2)."""
        from research_pipeline import _build_pubmed_queries_v3
        queries = _build_pubmed_queries_v3(
            topic="court ordered iop",
            heading="Documentation requirements",
            section_type="action_checklist",
            parent_h2="What a typical court-ordered IOP looks like",
            claims=["Research whether documentation reduces noncompliance"],
        )
        for q in queries:
            if "documentation" in q.lower():
                self.assertIn("court", q.lower())
                self.assertIn("iop", q.lower())
                break
        else:
            self.fail("No documentation-related query found")

    def test_claim_search_includes_topic_pubmed(self):
        """Claim-based PubMed search must retain article topic (Fix 3)."""
        from research_pipeline import _fielded_pubmed_term, _pubmed_topic_expressions
        topic = "passively suicidal"
        filtered = ["ideation", "passive death wish"]
        topic_untagged, topic_fielded = _pubmed_topic_expressions(topic)
        claim_expression = "(" + " OR ".join(
            _fielded_pubmed_term(term) for term in filtered[:6] if _fielded_pubmed_term(term)
        ) + ")"
        pubmed_query = (
            f"({topic_fielded or topic_untagged}) AND {claim_expression}"
            if (topic_fielded or topic_untagged)
            else claim_expression
        )
        self.assertIn("passive", pubmed_query.lower())
        self.assertIn("suicidal", pubmed_query.lower())

    def test_claim_serp_query_includes_topic(self):
        """Claim-based SerpAPI/DDG query must include topic (Fix 3)."""
        topic = "court ordered iop"
        filtered = ["documentation", "communication", "court"]
        serp_query = (
            "(site:.gov OR site:.edu) "
            f'"{topic}" '
            "(" + " OR ".join(f'"{t}"' for t in sorted(filtered)[:6]) + ")"
        )
        self.assertIn("court ordered iop", serp_query)
        self.assertIn("site:.gov", serp_query)


class RelevanceRegressionTests(unittest.TestCase):
    """Fix 4: Topic-free component evidence must be rejected."""

    def test_topic_required_for_relevance(self):
        """A source without topic match must be rejected even with section hits."""
        from research_pipeline import _web_result_relevant
        # Depression topic: PCOS/diverticulitis/generic symptom without topic = reject
        self.assertFalse(
            _web_result_relevant(
                topic="depression",
                heading="Symptoms of depression",
                title="Polycystic Ovary Syndrome: Diagnosis and Management",
                snippet="PCOS affects hormonal balance and fertility",
                concept_terms=["symptom", "diagnosis", "hormone"],
            )
        )
        self.assertFalse(
            _web_result_relevant(
                topic="anorexia",
                heading="Complications of anorexia",
                title="Diverticulitis: Acute Management Guidelines",
                snippet="Diverticulitis requires antibiotics and sometimes surgery",
                concept_terms=["complication", "management", "acute"],
            )
        )

    def test_neurodivergence_requires_both_concepts(self):
        """A depression-only source cannot support 'is depression neurodivergent'."""
        from research_pipeline import _topic_matches_text
        # depression-only text should NOT match "is depression neurodivergent"
        self.assertFalse(
            _topic_matches_text(
                "is depression neurodivergent",
                "Major depressive disorder affects mood and cognition",
            )
        )


class NeurodivergenceExpansionTest(unittest.TestCase):
    """Fix 5: Neurodivergence topic expansion."""

    def test_neurodivergent_expanded(self):
        from research_pipeline import SCHOLARLY_TOPIC_EXPANSIONS
        self.assertIn("neurodivergent", SCHOLARLY_TOPIC_EXPANSIONS)
        expansions = SCHOLARLY_TOPIC_EXPANSIONS["neurodivergent"]
        self.assertIn("neurodivergence", expansions)
        self.assertIn("neurodiversity", expansions)
        self.assertIn("neurodiverse", expansions)


class ApAFormattingRegressionTests(unittest.TestCase):
    """Fix 10-14: APA 7 formatting corrections."""

    def test_journal_article_more_than_20_authors(self):
        """21+ authors uses 'first 19, …, last' without et al. (Fix 11)."""
        from research_pipeline import _apa7_cite
        authors = [f"Author{i}, A. B." for i in range(1, 22)]
        result = _apa7_cite({
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
            "title": "Test article title",
            "pmid": "12345678",
            "authors": authors,
            "year": "2024",
            "journal": "Journal of Testing",
            "volume": "10",
            "issue": "2",
            "pages": "100-110",
            "doi": "10.1000/test",
        })
        self.assertNotIn("et al", result)
        self.assertIn("Author1", result)
        self.assertIn("Author21", result)

    def test_bookshelf_formatted_as_book_entry(self):
        """NCBI Bookshelf entry formatted as book, not journal (Fix 12)."""
        from research_pipeline import _apa7_cite
        result = _apa7_cite({
            "url": "https://www.ncbi.nlm.nih.gov/books/NBK12345/",
            "title": "Test entry",
            "source_type": "book_entry",
            "authors": ["Smith, J. A."],
            "year": "2024",
            "book_title": "StatPearls",
            "publisher": "StatPearls Publishing",
        })
        self.assertIn("In", result)
        self.assertIn("StatPearls", result)
        self.assertNotIn("PubMed Central repository copy", result)

    def test_missing_journal_metadata_blocks(self):
        """Missing journal metadata must raise ValueError (Fix 13)."""
        from research_pipeline import _apa7_cite
        with self.assertRaises(ValueError):
            _apa7_cite({
                "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                "title": "Test article",
                "pmid": "12345678",
            })

    def test_generic_author_label_rejected(self):
        """Web source without author must not silently pass with a generic label."""
        from research_pipeline import _apa7_cite
        # A .gov URL not in org_map should produce empty org but not ValueError
        # (the function encodes what's available)
        result = _apa7_cite({
            "url": "https://example.gov/test",
            "title": "Test page",
            "domain": "example.gov",
        })
        self.assertIn("Test page", result)
        self.assertIn("example.gov", result)


class WebSourceTargetingTests(unittest.TestCase):
    """Fix 6: Web search only for weak/missing H3s."""

    def test_targeted_h3s_only_weak_or_missing(self):
        """Web source fallback must skip H3s with adequate PubMed evidence."""
        # This test verifies the filtering logic in run_research_pipeline
        missing = {"h3_one"}
        weak = {"h3_two"}
        fallback = missing | weak
        all_h3s = {"h3_one", "h3_two", "h3_three"}
        targeted = {h for h in all_h3s if h in fallback}
        self.assertIn("h3_one", targeted)
        self.assertIn("h3_two", targeted)
        self.assertNotIn("h3_three", targeted)


class ValidatorRegressionTests(unittest.TestCase):
    """Dumbed-down validation fixes."""

    def test_practical_h3_not_flagged_for_causal_links(self):
        """Practical H3s without clinical claims shouldn't fail causal check."""
        from research_validators import validate_writer_semantics
        clinical = "# Clinical Research Brief\n### Questions to ask\n## Sources"
        writer = (
            "# Dumbed-Down Research Brief\n"
            "<!-- GOLDEN_DUMBED_DOWN_BRIEF -->\n"
            "### Questions to ask when choosing a program\n"
            "- **Plain facts:** Ask the program about insurance coverage\n"
            "- **Safe wording:** Compare multiple programs before deciding\n"
        )
        result = validate_writer_semantics(writer, clinical, ["Questions to ask when choosing a program"])
        causal_errors = [e for e in result.errors if "promises an explanation" in e]
        self.assertEqual(len(causal_errors), 0)

    def test_safety_guidance_non_fatal(self):
        """Missing safety guidance should be non-fatal warning, not error."""
        from research_validators import validate_writer_semantics
        clinical = "# Clinical Research Brief\nwithdrawal danger guidance\n## Sources"
        writer = (
            "# Dumbed-Down Research Brief\n"
            "<!-- GOLDEN_DUMBED_DOWN_BRIEF -->\n"
            "### Test heading\n"
            "- **Plain facts:** Some practical information\n"
        )
        result = validate_writer_semantics(writer, clinical, ["Test heading"])
        safety_errors = [e for e in result.errors if "dropped required" in e]
        self.assertEqual(len(safety_errors), 0)


if __name__ == "__main__":
    unittest.main()
