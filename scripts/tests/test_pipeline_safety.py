from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


PATCH_DIR = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PATCH_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


golden_writer = load_module("golden_writer_under_test", "golden_writer.py")
pipeline = load_module("pipeline_under_test", "pipeline.py")


class GoldenWriterSafetyTests(unittest.TestCase):
    def test_cleanup_does_not_make_unsafe_em_dash_rewrite(self):
        original = "One clause — another clause.\n- Item\n"
        cleaned = golden_writer.deterministic_article_cleanup(original)
        self.assertIn("—", cleaned)
        self.assertIn("* Item", cleaned)

    def test_compile_preserves_yaml_delimiters(self):
        article = "Meta Title: Test title\nMeta Description: Test description\n\n# Heading\n\nBody."
        compiled = golden_writer.compile_article(article, "", {})
        self.assertTrue(compiled.startswith("---\nmeta_title:"))
        self.assertIn("\n---\n\n# Heading", compiled)

    def test_integrity_rejects_missing_heading_and_truncation(self):
        before = "# Title\n\n## One\n\n" + ("Body. " * 100) + "\n\n## Two\n\nEnding."
        after = "# Title\n\n## One\n\nShort."
        problems = golden_writer._repair_integrity_errors(before, after)
        self.assertTrue(any("missing headings" in item for item in problems))
        self.assertTrue(any("shrank" in item for item in problems))

    def test_checkpoint_versions_different_content(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "article.raw.md"
            first = golden_writer._write_checkpoint(path, "first")
            second = golden_writer._write_checkpoint(path, "second")
            self.assertEqual(first, path)
            self.assertNotEqual(second, path)
            self.assertEqual(path.read_text(), "first")
            self.assertEqual(second.read_text(), "second")

    def test_shape_validator_fails_when_markers_are_missing(self):
        violations = golden_writer.validate_section_shapes("# Title\n\n### Section\n\nText")
        self.assertIn("section markers missing", violations[0])

    def test_scanner_warning_never_triggers_automatic_repair(self):
        finding = {"category": "headings", "severity": "warning"}
        self.assertEqual(golden_writer._scan_classification(finding), "WARNING")

    def test_only_explicit_safety_error_is_safety_repairable(self):
        finding = {"category": "safety_enforcement", "severity": "error"}
        self.assertEqual(golden_writer._scan_classification(finding), "SAFETY")

    def test_writer_main_preserves_all_checkpoints(self):
        article = (
            "Meta Title: Test article\n"
            "Meta Description: A safe test description.\n\n"
            "# Test article\n\nIntro text for the reader.\n\n"
            "## Main section\n\n### Useful detail\n\n"
            "<!-- SECTION:h3_01:START | Shape: pure prose -->\n"
            + ("This is a complete explanatory sentence. " * 20)
            + "\n<!-- SECTION:h3_01:END -->\n\n"
            "## Key Takeaways\n\n* A useful takeaway.\n* Another useful takeaway.\n"
        )
        pair_result = {"pairs_block": "", "summary": {"archetype": "heart", "pair_count": 0, "exemplar": "none"}}
        clean_scan = {"ok": True, "error_count": 0, "warning_count": 0, "violations": []}

        def fake_subprocess(command, **kwargs):
            joined = " ".join(str(item) for item in command)
            if "pair_selector.py" in joined:
                return types.SimpleNamespace(returncode=0, stdout=json.dumps(pair_result), stderr="")
            if "constraint_scanner.py" in joined:
                return types.SimpleNamespace(returncode=0, stdout=json.dumps(clean_scan), stderr="")
            if " -m deepseek-v4-flash " in f" {joined} ":
                return types.SimpleNamespace(returncode=0, stdout=article, stderr="")
            return types.SimpleNamespace(returncode=1, stdout="", stderr="link service unavailable")

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            outline = temp_path / "outline.md"
            brief = temp_path / "brief.md"
            output = temp_path / "article.md"
            outline.write_text("# Outline\n\n## Main section\n\n### Useful detail\n")
            brief.write_text("### Useful detail\n\nPlain facts.\n\n## Sources\n\nhttps://example.com/source")
            argv = [
                "golden_writer.py", "--topic", "test article", "--outline", str(outline),
                "--brief", str(brief), "--output", str(output), "--clinic", "Clinic",
            ]
            with mock.patch.object(golden_writer.subprocess, "run", side_effect=fake_subprocess), \
                 mock.patch.object(golden_writer, "get_exemplar_fragments", return_value=""), \
                 mock.patch.object(golden_writer, "get_curated_links", return_value=""), \
                 mock.patch.object(sys, "argv", argv):
                exit_code = golden_writer.main()

            self.assertEqual(exit_code, 0)
            for suffix in ("raw.md", "cleaned.md", "repaired.md", "compiled.md", "linked.md"):
                self.assertTrue((temp_path / f"article.{suffix}").exists(), suffix)
            self.assertTrue((temp_path / "article.qa.initial.json").exists())
            self.assertTrue((temp_path / "article.qa.final.json").exists())
            self.assertTrue(output.read_text().startswith("---\nmeta_title:"))

    def test_link_service_failure_is_reported(self):
        failed = types.SimpleNamespace(returncode=1, stdout="", stderr="unavailable")
        article = "# Title\n\n## Section\n\nA natural treatment anchor appears here."
        with mock.patch.object(golden_writer.subprocess, "run", return_value=failed):
            linked, ok = golden_writer.insert_citations(
                article, "", {"treatment anchor": "https://example.com/internal"}
            )
        self.assertFalse(ok)
        self.assertEqual(linked, article)


class PipelineSafetyTests(unittest.TestCase):
    def topic(self):
        article_id, safe_slug = pipeline._topic_identity("Same Title", "keyword", "Space", "Clinic")
        return {
            "article_id": article_id,
            "state_key": f"Same Title::{article_id}",
            "safe_slug": safe_slug,
            "title": "Same Title",
            "keyword": "keyword",
            "space": "Space",
            "clinic": "Clinic",
        }

    def test_topic_identity_prevents_slug_collision(self):
        first = pipeline._topic_identity("Same Title", "first", "Space", "Clinic")
        second = pipeline._topic_identity("Same Title", "second", "Space", "Clinic")
        self.assertNotEqual(first, second)

    def test_atomic_state_is_valid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "pipeline_state.json"
            with mock.patch.object(pipeline, "STATE_PATH", state_path):
                pipeline._atomic_save_state({"value": {"status": "OK"}})
            self.assertEqual(json.loads(state_path.read_text())["value"]["status"], "OK")

    def test_research_tuple_is_saved_as_two_artifacts(self):
        topic = self.topic()
        fake_research = types.ModuleType("research_pipeline")
        plain_brief = "### Evidence section\n\n" + ("Plain evidence. " * 100)
        fake_research.run_research_pipeline = lambda **kwargs: ("clinical packet", plain_brief)
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            (out_dir / "outline.md").write_text("# Outline")
            with mock.patch.dict(sys.modules, {"research_pipeline": fake_research}), \
                 mock.patch.object(pipeline, "_out_dir", return_value=out_dir), \
                 mock.patch.object(pipeline, "_valid_research_briefs", return_value=True), \
                 mock.patch.object(pipeline, "_to_gdoc", return_value=("url", "doc-id")):
                result = pipeline.phase_research(topic, {})
            self.assertEqual(result["status"], "OK")
            self.assertEqual((out_dir / "research-brief.md").read_text(), "clinical packet")
            self.assertEqual((out_dir / "dumbed-down-brief.md").read_text(), plain_brief)

    def test_draft_failure_does_not_write_placeholder(self):
        topic = self.topic()
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            (out_dir / "outline.md").write_text("# Outline")
            (out_dir / "dumbed-down-brief.md").write_text("# Brief")
            writer_dir = out_dir / "writer"
            writer_dir.mkdir()
            (writer_dir / "golden_writer.py").write_text("# test")
            failed = types.SimpleNamespace(returncode=1, stdout="", stderr="writer failed")
            with mock.patch.object(pipeline, "_out_dir", return_value=out_dir), \
                 mock.patch.object(pipeline, "GW", writer_dir), \
                 mock.patch.object(pipeline.subprocess, "run", return_value=failed):
                result = pipeline.phase_draft(topic, {})
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse((out_dir / "article.md").exists())
            self.assertTrue((out_dir / "draft.error.txt").exists())

    def test_existing_doc_id_is_passed_to_updater(self):
        completed = types.SimpleNamespace(
            stdout=json.dumps({"doc_link": "https://docs.google.com/document/d/abc/edit", "doc_id": "abc"}),
            stderr="",
            returncode=0,
        )
        with tempfile.TemporaryDirectory() as temp:
            md_path = Path(temp) / "article.md"
            md_path.write_text("# Article")
            with mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run:
                url, doc_id = pipeline._to_gdoc(md_path, "Article", "abc")
            command = run.call_args.args[0]
            self.assertIn("--doc-id", command)
            self.assertEqual(doc_id, "abc")
            self.assertIn("docs.google.com", url)

    def test_pipeline_stops_for_outline_approval(self):
        fake_outline = types.ModuleType("outline_pipeline")
        fake_outline.configure_pipeline = lambda **kwargs: None
        fake_research = types.ModuleType("research_pipeline")
        fake_research.configure_pipeline = lambda **kwargs: None

        def fake_run_phase(phase, topics, state, worker, workers):
            results = {pipeline._topic_key(topic): {"status": "OK", "delivery_status": "OK"} for topic in topics}
            state.setdefault("_phases", {})[phase] = results
            return results

        with tempfile.TemporaryDirectory() as temp:
            topics_file = Path(temp) / "topics.txt"
            topics_file.write_text("Test Article | test keyword | Space | Clinic")
            state_path = Path(temp) / "state.json"
            argv = ["pipeline.py", str(topics_file)]
            with mock.patch.dict(sys.modules, {"outline_pipeline": fake_outline, "research_pipeline": fake_research}), \
                 mock.patch.object(pipeline, "STATE_PATH", state_path), \
                 mock.patch.object(pipeline, "run_phase", side_effect=fake_run_phase), \
                 mock.patch.object(sys, "argv", argv):
                exit_code = pipeline.main()
            state = json.loads(state_path.read_text())
            self.assertEqual(exit_code, 2)
            waiting = list(state["_phases"]["research"].values())[0]
            self.assertEqual(waiting["status"], "WAITING_APPROVAL")

    def test_pipeline_returns_zero_when_all_approved_stages_succeed(self):
        fake_outline = types.ModuleType("outline_pipeline")
        fake_outline.configure_pipeline = lambda **kwargs: None
        fake_research = types.ModuleType("research_pipeline")
        fake_research.configure_pipeline = lambda **kwargs: None

        def fake_run_phase(phase, topics, state, worker, workers):
            results = {pipeline._topic_key(topic): {"status": "OK", "delivery_status": "OK"} for topic in topics}
            state.setdefault("_phases", {})[phase] = results
            return results

        with tempfile.TemporaryDirectory() as temp:
            topics_file = Path(temp) / "topics.txt"
            topics_file.write_text("Test Article | test keyword | Space | Clinic")
            state_path = Path(temp) / "state.json"
            argv = ["pipeline.py", str(topics_file), "--approve-outlines", "--approve-research"]
            with mock.patch.dict(sys.modules, {"outline_pipeline": fake_outline, "research_pipeline": fake_research}), \
                 mock.patch.object(pipeline, "STATE_PATH", state_path), \
                 mock.patch.object(pipeline, "run_phase", side_effect=fake_run_phase), \
                 mock.patch.object(sys, "argv", argv):
                exit_code = pipeline.main()
            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
