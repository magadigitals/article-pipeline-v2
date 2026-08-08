import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_pipeline as rp
from research_exhaustive import (
    EvidenceDisposition,
    ExhaustiveLimits,
    JsonResearchCache,
    PubMedQueryAudit,
    classify_evidence,
    extract_html_text,
    fetch_trusted_page,
    paginate_pubmed,
)


class ExhaustiveResearchTests(unittest.TestCase):
    def test_exhaustive_mode_is_wired_without_changing_standard_contract(self):
        article = {
            "pmid": "123",
            "title": "Anxiety and hand tremor",
            "abstract": "Anxiety can be associated with physiological tremor.",
            "year": "2025",
        }
        audit = PubMedQueryAudit(
            query="planned query",
            total_available=1,
            ids_retrieved=1,
            records_fetched=1,
            pages_requested=1,
            complete_within_limit=True,
        )
        outline = "## Body\n### Why hands shake with anxiety\n"
        with patch.object(
            rp, "_build_pubmed_queries_v3", return_value=["planned query"]
        ), patch.object(
            rp, "paginate_pubmed", return_value=([article], audit)
        ) as paginator, patch.object(
            rp, "_pubmed_record_relevant", return_value=True
        ), patch.object(
            rp, "_has_specific_match", return_value=True
        ), patch.object(
            rp, "_relevance_score", return_value=20
        ):
            result = rp.parse_json_response(rp._call_pubmed_search({
                "topic": "my hands shake when anxious",
                "outline_markdown": outline,
                "h2_map": {"Why hands shake with anxiety": "Body"},
                "research_mode": "exhaustive_v1",
            }))

        self.assertTrue(paginator.called)
        self.assertEqual(result["research_mode"], "exhaustive_v1")
        self.assertEqual(result["query_audits"][0]["records_fetched"], 1)
        self.assertEqual(result["section_results"][0]["pmids"], ["123"])

    def test_pubmed_paginates_deduplicates_and_declares_cap(self):
        offsets = []

        def search_page(query, retstart, retmax, mindate):
            offsets.append(retstart)
            ids = [str(i) for i in range(retstart, min(retstart + retmax, 250))]
            return {"count": 250, "ids": ids}

        def fetch_records(ids):
            return [{"pmid": pmid, "title": f"Study {pmid}"} for pmid in ids]

        records, audit = paginate_pubmed(
            "test",
            "2019/01/01",
            search_page,
            fetch_records,
            limits=ExhaustiveLimits(
                pubmed_page_size=100,
                pubmed_max_records_per_query=220,
                pubmed_fetch_batch_size=50,
                retry_attempts=1,
            ),
            sleep_fn=lambda _: None,
        )

        self.assertEqual(offsets, [0, 100, 200])
        self.assertEqual(len(records), 220)
        self.assertEqual(audit.ids_retrieved, 220)
        self.assertTrue(audit.complete_within_limit)
        self.assertTrue(audit.truncated_by_limit)
        self.assertEqual(audit.errors, [])

    def test_pubmed_cache_prevents_second_network_pass(self):
        calls = {"search": 0, "fetch": 0}

        def search_page(query, retstart, retmax, mindate):
            calls["search"] += 1
            return {"count": 2, "ids": ["1", "2"]}

        def fetch_records(ids):
            calls["fetch"] += 1
            return [{"pmid": pmid, "title": pmid} for pmid in ids]

        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonResearchCache(Path(tmp))
            limits = ExhaustiveLimits(retry_attempts=1)
            first, _ = paginate_pubmed(
                "cached", "2019/01/01", search_page, fetch_records,
                cache=cache, limits=limits, sleep_fn=lambda _: None,
            )
            second, audit = paginate_pubmed(
                "cached", "2019/01/01", search_page, fetch_records,
                cache=cache, limits=limits, sleep_fn=lambda _: None,
            )

        self.assertEqual(first, second)
        self.assertEqual(calls, {"search": 1, "fetch": 1})
        self.assertGreaterEqual(audit.cache_hits, 3)

    def test_pubmed_retry_is_bounded_and_failure_is_audited(self):
        calls = 0

        def fail(*args):
            nonlocal calls
            calls += 1
            raise TimeoutError("temporary outage")

        records, audit = paginate_pubmed(
            "failure",
            "2019/01/01",
            fail,
            lambda ids: [],
            limits=ExhaustiveLimits(retry_attempts=2),
            sleep_fn=lambda _: None,
        )
        self.assertEqual(calls, 2)
        self.assertEqual(records, [])
        self.assertFalse(audit.complete_within_limit)
        self.assertIn("TimeoutError", audit.errors[0])

    def test_html_extraction_removes_non_evidence_scaffolding(self):
        raw = b"""
        <html><nav>Navigation words</nav><body>
        <h1>Clinical guidance</h1><p>Ginger may reduce nausea.</p>
        <script>fabricatedEvidence()</script></body></html>
        """
        text = extract_html_text(raw)
        self.assertIn("Clinical guidance", text)
        self.assertIn("Ginger may reduce nausea", text)
        self.assertNotIn("Navigation words", text)
        self.assertNotIn("fabricatedEvidence", text)

    def test_untrusted_redirect_is_rejected(self):
        page = fetch_trusted_page(
            "https://nih.gov/source",
            lambda url: url.endswith(".gov") or ".gov/" in url,
            lambda url, timeout, max_bytes: {
                "body": b"<p>Evidence</p>",
                "final_url": "https://example.com/landing",
                "content_type": "text/html",
            },
            limits=ExhaustiveLimits(retry_attempts=1),
            sleep_fn=lambda _: None,
        )
        self.assertEqual(page.status, "rejected_untrusted_redirect")
        self.assertEqual(page.text, "")

    def test_page_cache_prevents_second_download(self):
        calls = 0

        def get(url, timeout, max_bytes):
            nonlocal calls
            calls += 1
            return {
                "body": b"<main><p>Full clinical evidence text.</p></main>",
                "final_url": url,
                "content_type": "text/html",
            }

        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonResearchCache(Path(tmp))
            kwargs = {
                "cache": cache,
                "limits": ExhaustiveLimits(retry_attempts=1),
                "sleep_fn": lambda _: None,
            }
            first = fetch_trusted_page(
                "https://nih.gov/source", lambda _: True, get, **kwargs
            )
            second = fetch_trusted_page(
                "https://nih.gov/source", lambda _: True, get, **kwargs
            )

        self.assertEqual(calls, 1)
        self.assertEqual(first.status, "extracted")
        self.assertTrue(second.cache_hit)
        self.assertEqual(first.text, second.text)

    def test_negative_disposition_requires_explicit_relevant_text(self):
        card = classify_evidence(
            "electrolytes reduce hangover severity",
            [{
                "url": "https://nih.gov/study",
                "title": "Electrolytes and hangover severity",
                "abstract": (
                    "Electrolytes did not reduce hangover severity and there "
                    "was no significant benefit."
                ),
                "support_scope": "direct_topic",
            }],
        )
        self.assertEqual(card.disposition, EvidenceDisposition.EXPLICIT_NEGATIVE)

    def test_insufficient_evidence_is_not_mislabeled_as_absence(self):
        card = classify_evidence(
            "herbs improve hangover symptoms",
            [{
                "url": "https://nih.gov/review",
                "title": "Herbs for hangover symptoms",
                "abstract": "The evidence is insufficient and very low quality.",
                "support_scope": "direct_topic",
            }],
        )
        self.assertEqual(
            card.disposition, EvidenceDisposition.EXPLICITLY_INSUFFICIENT
        )
        self.assertNotIn("no research", card.finding.casefold())

    def test_failed_extraction_stays_unresolved(self):
        card = classify_evidence(
            "ginger reduces nausea",
            [{
                "url": "https://nih.gov/ginger",
                "title": "Ginger reduces nausea",
                "relevance": "Ginger reduces nausea",
                "extraction_status": "fetch_failed",
            }],
        )
        self.assertEqual(card.disposition, EvidenceDisposition.EXTRACTION_UNRESOLVED)

    def test_empty_search_is_gap_not_proof_of_absence(self):
        card = classify_evidence("ginger reduces nausea", [])
        self.assertEqual(card.disposition, EvidenceDisposition.SEARCH_GAP)
        self.assertIn("not proof", card.finding.casefold())

    def test_component_evidence_is_marked_indirect(self):
        card = classify_evidence(
            "ginger reduces nausea",
            [{
                "url": "https://nih.gov/ginger",
                "title": "Ginger reduces nausea",
                "abstract": "Ginger reduced nausea in pregnancy studies.",
                "support_scope": "component_only",
            }],
        )
        self.assertEqual(card.disposition, EvidenceDisposition.INDIRECT_MATCH)

    def test_hangover_question_uses_full_page_explicit_negative(self):
        heading = "Whether electrolytes reduce hangover severity"
        outline = (
            f"## Evidence\n### {heading}\n**Claims:**\n"
            "- Research whether electrolytes reduce hangover severity.\n"
        )
        pubmed = {
            "research_mode": "exhaustive_v1",
            "weak_sections": [heading],
            "missing_sections": [],
            "section_results": [{
                "heading": heading,
                "section_type": "",
                "articles": [],
                "query_audits": [{
                    "errors": [],
                    "truncated_by_limit": False,
                }],
            }],
        }
        web = {
            "sources": [{
                "h3": heading,
                "url": "https://niaaa.nih.gov/hangovers",
                "domain": "niaaa.nih.gov",
                "title": "Hangover mechanisms and remedies",
                "relevance": "Search-result snippet only",
                "evidence_text": (
                    "A randomized study found that electrolytes did not reduce "
                    "hangover severity and showed no significant benefit."
                ),
                "extraction_status": "extracted",
                "support_scope": "direct_topic",
            }],
        }
        packet = rp._format_research_packet(
            "herbs for hangover",
            outline,
            pubmed,
            web,
            rp._extract_section_briefs(outline),
        )
        self.assertIn("Disposition: explicit_negative", packet)
        self.assertIn("Research questions dispositioned: 1/1", packet)
        self.assertNotIn("UNVERIFIED — BLOCK DRAFTING", packet)

    def test_exhaustive_page_failure_blocks_instead_of_using_snippet(self):
        heading = "Whether ginger reduces hangover nausea"
        outline = (
            f"## Evidence\n### {heading}\n**Claims:**\n"
            "- Research whether ginger reduces hangover nausea.\n"
        )
        pubmed = {
            "research_mode": "exhaustive_v1",
            "weak_sections": [heading],
            "missing_sections": [],
            "section_results": [{
                "heading": heading,
                "section_type": "",
                "articles": [],
                "query_audits": [{"errors": [], "truncated_by_limit": False}],
            }],
        }
        web = {
            "sources": [{
                "h3": heading,
                "url": "https://nih.gov/ginger",
                "domain": "nih.gov",
                "title": "Ginger reduces hangover nausea",
                "relevance": "Ginger reduces hangover nausea",
                "extraction_status": "fetch_failed",
                "extraction_error": "timeout",
                "support_scope": "direct_topic",
            }],
        }
        packet = rp._format_research_packet(
            "herbs for hangover",
            outline,
            pubmed,
            web,
            rp._extract_section_briefs(outline),
        )
        self.assertIn("Disposition: extraction_unresolved", packet)
        self.assertIn("Research questions dispositioned: 0/1", packet)
        self.assertIn("UNVERIFIED — BLOCK DRAFTING", packet)


if __name__ == "__main__":
    unittest.main()
