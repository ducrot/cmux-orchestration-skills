#!/usr/bin/env python3
"""Gate regression tests. Run: python3 scripts/test_parse_report.py"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parse_report import EXIT_CODES, QUALITY_ONLY_REASON, classify_result, is_noneish, parse_report  # noqa: E402


CLEAN = """## Result
NO FINDINGS

## Tests / Checks
- `make test`: pass

## Findings
- None

## Blockers
- None

## Plan Drift
- None
"""


def report(**overrides: str) -> str:
    """Build a report from the clean template with sections replaced or dropped (value None)."""
    sections = {
        "Result": "NO FINDINGS",
        "Tests / Checks": "- `make test`: pass",
        "Findings": "- None",
        "Blockers": "- None",
        "Plan Drift": "- None",
    }
    sections.update(overrides)
    return "\n".join(f"## {name}\n{body}\n" for name, body in sections.items() if body is not None)


class GateSeverity(unittest.TestCase):
    def test_clean_report_advances(self):
        self.assertEqual(parse_report(CLEAN)["gate"], "advance")

    def test_blocker_outranks_plan_drift(self):
        """Regression: last-write-wins let plan drift downgrade a BLOCKER to 'review-plan'."""
        result = parse_report(report(Result="BLOCKER", Blockers="- Needs prod credentials", **{"Plan Drift": "- Command renamed"}))
        self.assertEqual(result["gate"], "blocked")
        self.assertTrue(result["has_blockers"])

    def test_blocker_outranks_findings_and_missing_tests(self):
        result = parse_report(report(Result="BLOCKER", Blockers="- Hard stop", Findings="- Broken", **{"Tests / Checks": "- None"}))
        self.assertEqual(result["gate"], "blocked")

    def test_plan_drift_alone_is_hitl(self):
        result = parse_report(report(**{"Plan Drift": "- Script moved to bin/"}))
        self.assertEqual(result["gate"], "hitl")
        self.assertEqual(result["result"], "NO FINDINGS")  # drift alone never downgrades Result

    def test_findings_stop(self):
        self.assertEqual(parse_report(report(Result="FINDINGS", Findings="- Null deref at x.py:12"))["gate"], "stop")

    def test_missing_tests_stop_even_with_no_findings(self):
        self.assertEqual(parse_report(report(**{"Tests / Checks": "- None"}))["gate"], "stop")


class MalformedReports(unittest.TestCase):
    def test_missing_result_section_is_hitl_not_phantom_blocker(self):
        """Regression: the fallback scanned the whole doc, and '## Blockers' spells 'BLOCKER'."""
        result = parse_report(report(Result=None))
        self.assertEqual(result["gate"], "hitl")
        self.assertFalse(result["has_blockers"])
        self.assertIn("result", result["missing_sections"])

    def test_missing_blockers_section_is_hitl_not_advance(self):
        """Regression: an absent section was indistinguishable from one saying 'None'."""
        result = parse_report(report(Blockers=None))
        self.assertEqual(result["gate"], "hitl")
        self.assertIn("blockers", result["missing_sections"])

    def test_missing_plan_drift_section_is_hitl(self):
        self.assertEqual(parse_report(report(**{"Plan Drift": None}))["gate"], "hitl")

    def test_empty_required_section_is_malformed(self):
        self.assertTrue(parse_report(report(Blockers=""))["malformed"])

    def test_review_shaped_report_without_blockers_does_not_advance(self):
        """The review template omitted Blockers/Plan Drift; that shape must not sail through."""
        text = (
            "## Result\nNO FINDINGS\n\n"
            "## Tests / Checks\n- `/code-review medium --fix`: done\n\n"
            "## Change Summary\n- Fixed null deref\n\n"
            "## Findings\n- None\n\n"
            "## Recommendations\n- Consider extracting a helper\n"
        )
        self.assertEqual(parse_report(text)["gate"], "hitl")

    def test_unfilled_template_result_is_unknown(self):
        self.assertEqual(classify_result("NO FINDINGS | FINDINGS | BLOCKER"), "UNKNOWN")
        self.assertEqual(parse_report(report(Result="NO FINDINGS | FINDINGS | BLOCKER"))["gate"], "stop")

    def test_blockers_heading_does_not_leak_into_result(self):
        self.assertEqual(classify_result("NO FINDINGS"), "NO FINDINGS")
        self.assertEqual(classify_result(""), "UNKNOWN")


class RecommendationsDoNotBlock(unittest.TestCase):
    def test_non_blocking_recommendations_advance(self):
        """SKILL.md: review reports advance when Findings is None, whatever Recommendations says."""
        text = report(Findings="- None") + "\n## Recommendations\n- Nice-to-have: extract helper\n"
        self.assertEqual(parse_report(text)["gate"], "advance")


def finding(recommendation: str, scope: str, title: str = "Memoization re-applied") -> str:
    return (
        f"- {title}\n  - Severity: low\n  - Recommendation: {recommendation}\n"
        f"  - Scope: {scope}\n  - Evidence: `a.tsx:19`\n  - Suggested fix: the human decides"
    )


class QualityOnlyFindings(unittest.TestCase):
    """A quality-only ask-user finding still stops, but carries its own re-emission reason."""

    def parse(self, findings: str) -> dict:
        return parse_report(report(Result="FINDINGS", Findings=findings))

    def test_ask_user_with_scope_other_is_flagged_and_still_stops(self):
        result = self.parse(finding("ask-user", "other"))
        self.assertEqual(result["gate"], "stop")
        self.assertTrue(result["quality_only_findings"])
        self.assertIn(QUALITY_ONLY_REASON, result["reasons"])

    def test_unindented_fields_are_recognized(self):
        text = "- Severity: low\n  Recommendation: ask-user\n  Scope: other\n  Evidence: `a.ts:1`"
        self.assertTrue(self.parse(text)["quality_only_findings"])

    def test_mixed_findings_are_a_plain_stop(self):
        result = self.parse(finding("ask-user", "other") + "\n" + finding("ask-user", "acceptance", "AC gap"))
        self.assertEqual(result["gate"], "stop")
        self.assertFalse(result["quality_only_findings"])
        self.assertNotIn(QUALITY_ONLY_REASON, result["reasons"])

    def test_must_fix_with_scope_other_is_a_plain_stop(self):
        self.assertFalse(self.parse(finding("must-fix", "other"))["quality_only_findings"])

    def test_unclassified_finding_is_a_plain_stop(self):
        self.assertFalse(self.parse("- Null deref at x.py:12")["quality_only_findings"])
        self.assertFalse(self.parse("Prose first.\n" + finding("ask-user", "other"))["quality_only_findings"])

    def test_clean_report_is_not_flagged(self):
        self.assertFalse(parse_report(CLEAN)["quality_only_findings"])


class NoneDetection(unittest.TestCase):
    def test_multiline_none_bullets(self):
        self.assertTrue(is_noneish("- None\n- None"))

    def test_prose_after_none_is_not_none(self):
        self.assertFalse(is_noneish("- None\n\nActually, one thing:"))

    def test_unfilled_findings_template_is_not_none(self):
        self.assertFalse(is_noneish("- None, or remaining must-fix findings after `--fix`:"))


class Cli(unittest.TestCase):
    script = str(Path(__file__).parent / "parse_report.py")

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
