#!/usr/bin/env python3
"""Gate regression tests. Run: python3 .agents/skills/cmux-grilling/scripts/test_parse_research_report.py"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parse_research_report import EXIT_CODES, classify_result, is_noneish, parse_report  # noqa: E402


CLEAN = """## Result
ANSWERED

## Answer
The frontend HTTP layer is `nuxtjs/services/ApiService.js`, wrapping axios.

## Sources
- nuxtjs/services/ApiService.js

## Method
- `grep -r axios nuxtjs/services`: located the HTTP layer

## Blockers
- None

## Plan Drift
- None
"""


def report(**overrides: str) -> str:
    """Build a report from the clean template with sections replaced or dropped (value None)."""
    sections = {
        "Result": "ANSWERED",
        "Answer": "The frontend HTTP layer is `nuxtjs/services/ApiService.js`, wrapping axios.",
        "Sources": "- nuxtjs/services/ApiService.js",
        "Method": "- `grep -r axios nuxtjs/services`: located the HTTP layer",
        "Blockers": "- None",
        "Plan Drift": "- None",
    }
    sections.update(overrides)
    return "\n".join(f"## {name}\n{body}\n" for name, body in sections.items() if body is not None)


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
        self.assertFalse(result["has_sources"])

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
        self.assertTrue(result["has_blockers"])

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
        result = parse_report(report(Result=None))
        self.assertEqual(result["gate"], "hitl")
        self.assertFalse(result["has_blockers"])
        self.assertIn("result", result["missing_sections"])

    def test_missing_sources_section_is_hitl_not_stop(self):
        """An absent section is malformed; only a present `- None` reads as an empty list."""
        result = parse_report(report(Sources=None))
        self.assertEqual(result["gate"], "hitl")
        self.assertIn("sources", result["missing_sections"])

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


class NotesDoNotBlock(unittest.TestCase):
    def test_notes_prose_does_not_affect_gate(self):
        text = report() + "\n## Notes\n- Caveat: version pin only checked in composer.json.\n"
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

    def run_cli(self, path: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, self.script, path], capture_output=True, text=True)

    def test_missing_report_is_pending_without_traceback(self):
        """SKILL.md: never parse a missing report path as a failure condition."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(str(Path(tmp) / "nope.md"))
        self.assertEqual(proc.returncode, EXIT_CODES["pending"])
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("gate=pending", proc.stdout)

    def test_exit_codes_are_distinct_and_avoid_argparse_2(self):
        self.assertNotIn(2, EXIT_CODES.values())
        self.assertEqual(len(set(EXIT_CODES.values())), len(EXIT_CODES))

    def test_clean_report_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.md"
            path.write_text(CLEAN, encoding="utf-8")
            self.assertEqual(self.run_cli(str(path)).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
