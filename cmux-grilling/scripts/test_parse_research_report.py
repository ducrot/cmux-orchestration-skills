#!/usr/bin/env python3
"""Gate regression tests. Run: python3 .agents/skills/cmux-grilling/scripts/test_parse_research_report.py"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parse_research_report import EXIT_CODES, classify_result, is_noneish  # noqa: E402
from parse_research_report import parse_report as parse_expecting  # noqa: E402


def parse_report(text: str, expected: int = 1) -> dict:
    return parse_expecting(text, expected)


def block(question_id: str = "Q1", **overrides: str) -> str:
    """One question block from the clean template with sections replaced or dropped (value None)."""
    sections = {
        "Result": "ANSWERED",
        "Answer": "The frontend HTTP layer is `nuxtjs/services/ApiService.js`, wrapping axios.",
        "Sources": "- nuxtjs/services/ApiService.js",
        "Method": "- `grep -r axios nuxtjs/services`: located the HTTP layer",
        "Blockers": "- None",
        "Plan Drift": "- None",
    }
    sections.update(overrides)
    body = "\n".join(f"### {name}\n{body}\n" for name, body in sections.items() if body is not None)
    return f"## {question_id}\n{body}"


def report(**overrides: str) -> str:
    return block("Q1", **overrides)


def first(text: str, expected: int = 1) -> dict:
    return parse_report(text, expected)["questions"][0]


CLEAN = report()


class GateSeverity(unittest.TestCase):
    def test_clean_answered_report_advances(self):
        self.assertEqual(parse_report(CLEAN)["gate"], "advance")

    def test_no_answer_with_explanation_advances(self):
        """A well-formed empty finding is a content signal for the synthesizer, not a gate failure."""
        result = parse_report(
            report(
                Result="NO ANSWER",
                Answer="This question concerns project-internal state and is not answerable from the web.",
                Sources="- None",
            )
        )
        self.assertEqual(result["gate"], "advance")
        self.assertFalse(result["questions"][0]["has_sources"])

    def test_no_answer_without_explanation_stops(self):
        self.assertEqual(parse_report(report(Result="NO ANSWER", Answer="- None", Sources="- None"))["gate"], "stop")

    def test_answered_without_sources_stops(self):
        """An ANSWERED finding without sources is ungrounded and must not reach the synthesizer."""
        self.assertEqual(parse_report(report(Sources="- None"))["gate"], "stop")

    def test_missing_method_stops(self):
        self.assertEqual(parse_report(report(Method="- None"))["gate"], "stop")

    def test_blocker_outranks_plan_drift(self):
        result = parse_report(
            report(Result="BLOCKER", Blockers="- Repo unreadable", **{"Plan Drift": "- Task premise stale"})
        )
        self.assertEqual(result["gate"], "blocked")
        self.assertTrue(result["questions"][0]["has_blockers"])

    def test_blocker_outranks_missing_method(self):
        result = parse_report(report(Result="BLOCKER", Blockers="- Hard stop", Method="- None"))
        self.assertEqual(result["gate"], "blocked")

    def test_blocker_result_without_answer_is_blocked_not_stop(self):
        result = parse_report(report(Result="BLOCKER", Answer="- None", Blockers="- Environment broken"))
        self.assertEqual(result["gate"], "blocked")

    def test_plan_drift_alone_is_hitl(self):
        self.assertEqual(parse_report(report(**{"Plan Drift": "- The named service no longer exists"}))["gate"], "hitl")


class MalformedReports(unittest.TestCase):
    def test_missing_result_section_is_hitl_not_phantom_blocker(self):
        question = first(report(Result=None))
        self.assertEqual(question["gate"], "hitl")
        self.assertFalse(question["has_blockers"])
        self.assertIn("result", question["missing_sections"])

    def test_missing_sources_section_is_hitl_not_stop(self):
        """An absent section is malformed; only a present `- None` reads as an empty list."""
        question = first(report(Sources=None))
        self.assertEqual(question["gate"], "hitl")
        self.assertIn("sources", question["missing_sections"])

    def test_missing_plan_drift_section_is_hitl(self):
        self.assertEqual(parse_report(report(**{"Plan Drift": None}))["gate"], "hitl")

    def test_empty_required_section_is_malformed(self):
        self.assertTrue(parse_report(report(Blockers=""))["malformed"])

    def test_unfilled_template_result_is_unknown(self):
        self.assertEqual(classify_result("ANSWERED | NO ANSWER | BLOCKER"), "UNKNOWN")
        self.assertEqual(parse_report(report(Result="ANSWERED | NO ANSWER | BLOCKER"))["gate"], "stop")

    def test_result_classification_by_first_line_only(self):
        self.assertEqual(classify_result("ANSWERED"), "ANSWERED")
        self.assertEqual(classify_result("NO ANSWER"), "NO ANSWER")
        self.assertEqual(classify_result(""), "UNKNOWN")

    def test_flat_report_without_question_blocks_is_hitl(self):
        flat = "## Result\nANSWERED\n\n## Answer\nx\n\n## Sources\n- a\n\n## Method\n- b\n"
        result = parse_report(flat)
        self.assertEqual(result["gate"], "hitl")
        self.assertEqual(result["questions"][0]["result"], "MISSING")
        self.assertTrue(result["malformed"])

    def test_top_level_section_headings_do_not_count_as_sections(self):
        """Question sections are `###`; a flat `##` section inside a block stays missing."""
        text = "## Q1\n## Result\nANSWERED\n"
        self.assertEqual(first(text)["gate"], "hitl")


class PerQuestionGates(unittest.TestCase):
    def three(self, q2: str, q3: str | None = None) -> str:
        return block("Q1") + "\n" + q2 + "\n" + (q3 if q3 is not None else block("Q3"))

    def test_gates_are_reported_per_question(self):
        result = parse_report(self.three(block("Q2", Sources="- None")), 3)
        self.assertEqual([q["gate"] for q in result["questions"]], ["advance", "stop", "advance"])
        self.assertEqual(result["gate"], "stop")
        self.assertIn("Q2: ANSWERED without sources", result["reasons"])

    def test_report_gate_is_most_severe_question_gate(self):
        result = parse_report(
            self.three(block("Q2", Sources="- None"), block("Q3", Result="BLOCKER", Blockers="- broken")), 3
        )
        self.assertEqual(result["gate"], "blocked")

    def test_all_clean_questions_advance(self):
        result = parse_report(self.three(block("Q2")), 3)
        self.assertEqual(result["gate"], "advance")
        self.assertEqual([q["id"] for q in result["questions"]], ["Q1", "Q2", "Q3"])

    def test_missing_expected_block_is_hitl_for_that_question_only(self):
        result = parse_report(block("Q1") + "\n" + block("Q3"), 3)
        self.assertEqual([q["gate"] for q in result["questions"]], ["advance", "hitl", "advance"])
        self.assertEqual(result["questions"][1]["result"], "MISSING")
        self.assertEqual(result["gate"], "hitl")

    def test_unexpected_block_is_hitl(self):
        result = parse_report(block("Q1") + "\n" + block("Q2"), 1)
        self.assertEqual(result["gate"], "hitl")
        self.assertTrue(any("unexpected question blocks: Q2" in reason for reason in result["reasons"]))

    def test_duplicate_block_is_hitl(self):
        result = parse_report(block("Q1") + "\n" + block("Q1"), 1)
        self.assertEqual(result["gate"], "hitl")
        self.assertTrue(any("duplicate question blocks: Q1" in reason for reason in result["reasons"]))

    def test_report_answering_only_the_first_of_three_questions_is_not_clean(self):
        result = parse_report(block("Q1"), 3)
        self.assertEqual([q["gate"] for q in result["questions"]], ["advance", "hitl", "hitl"])
        self.assertEqual(result["gate"], "hitl")

    def test_blocks_are_gated_in_question_order_whatever_their_order_in_the_report(self):
        result = parse_report(block("Q3") + "\n" + block("Q1") + "\n" + block("Q2"), 3)
        self.assertEqual([q["id"] for q in result["questions"]], ["Q1", "Q2", "Q3"])
        self.assertEqual(result["gate"], "advance")

    def test_expected_count_must_be_positive(self):
        with self.assertRaises(ValueError):
            parse_expecting(CLEAN, 0)

    def test_plan_drift_is_attributed_to_its_question(self):
        result = parse_report(
            self.three(block("Q2", **{"Plan Drift": "- premise stale"})), 3
        )
        self.assertEqual([q["has_plan_drift"] for q in result["questions"]], [False, True, False])
        self.assertEqual(result["gate"], "hitl")

    def test_question_block_with_title_is_recognized(self):
        text = block("Q1").replace("## Q1", "## Q1 — Which HTTP layer?", 1)
        self.assertEqual(parse_report(text, 1)["gate"], "advance")

    def test_question_id_prefix_is_not_a_block(self):
        """`## Q1x` or `## Question` headings must not open a block."""
        self.assertEqual(parse_report("## Question\n### Result\nANSWERED\n", 1)["questions"][0]["result"], "MISSING")


class NotesDoNotBlock(unittest.TestCase):
    def test_notes_prose_does_not_affect_gate(self):
        text = report() + "\n### Notes\n- Caveat: version pin only checked in composer.json.\n"
        self.assertEqual(parse_report(text)["gate"], "advance")

    def test_trailing_top_level_notes_do_not_affect_gate(self):
        text = report() + "\n## Notes\n- Caveat.\n"
        self.assertEqual(parse_report(text)["gate"], "advance")


class NoneDetection(unittest.TestCase):
    def test_multiline_none_bullets(self):
        self.assertTrue(is_noneish("- None\n- None"))

    def test_prose_after_none_is_not_none(self):
        self.assertFalse(is_noneish("- None\n\nActually, one thing:"))

    def test_unfilled_sources_template_is_not_none(self):
        self.assertFalse(is_noneish("- None, or list of paths/URLs:"))


class Cli(unittest.TestCase):
    script = str(Path(__file__).parent / "parse_research_report.py")

    def run_cli(self, path: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, self.script, path, *args], capture_output=True, text=True)

    def write(self, tmp: str, text: str) -> str:
        path = Path(tmp) / "r.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_missing_report_is_pending_without_traceback(self):
        """SKILL.md: never parse a missing report path as a failure condition."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(str(Path(tmp) / "nope.md"), "--questions", "1")
        self.assertEqual(proc.returncode, EXIT_CODES["pending"])
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("gate=pending", proc.stdout)

    def test_exit_codes_are_distinct_and_avoid_argparse_2(self):
        self.assertNotIn(2, EXIT_CODES.values())
        self.assertEqual(len(set(EXIT_CODES.values())), len(EXIT_CODES))

    def test_clean_report_exits_zero_and_prints_gate_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(self.write(tmp, CLEAN), "--questions", "1")
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("gate=advance"))
        self.assertIn("Q1 gate=advance", proc.stdout)

    def test_cli_lists_each_question_and_exits_with_worst_gate(self):
        text = block("Q1") + "\n" + block("Q2", Sources="- None")
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(self.write(tmp, text), "--questions", "2")
        self.assertEqual(proc.returncode, EXIT_CODES["stop"])
        self.assertIn("Q1 gate=advance", proc.stdout)
        self.assertIn("Q2 gate=stop", proc.stdout)

    def test_json_output_carries_per_question_gates(self):
        text = block("Q1") + "\n" + block("Q2", Sources="- None")
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(self.write(tmp, text), "--questions", "2", "--json")
        payload = json.loads(proc.stdout)
        self.assertEqual([q["gate"] for q in payload["questions"]], ["advance", "stop"])

    def test_questions_flag_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(self.write(tmp, CLEAN))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--questions", proc.stderr)

    def test_questions_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(self.write(tmp, CLEAN), "--questions", "0")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(">= 1", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
