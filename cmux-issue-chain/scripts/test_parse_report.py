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


def items_fixture(root: Path, kind="recommendation", pass_num=1) -> Path:
    path = root / f"triage-items-{pass_num}.md"
    followup = "yes" if pass_num == 1 else "no"
    path.write_text(f'Run: fixture\nIssue: ISSUE-001\nTriage pass: {pass_num}\nFollow-up pass allowed: {followup}\n'
                    'Scanned reports: ["review-1"]\nIssue diff files: ["src/a.py"]\n\n'
                    f'## R1\nSource: review-1 (reports/review-1.md)\nKind: {kind}\n\n- Keep exact item.\n')
    return path


def verdict(**overrides):
    fields = {"Source": "review-1", "Title": "A useful change", "Verdict": "accepted",
              "Follow-up eligible": "yes", "Files": "`src/a.py`", "Supersedes": "none", "Reason": "Measured duplication"}
    fields.update(overrides)
    return "- R1\n" + "".join(f"  - {key}: {value}\n" for key, value in fields.items() if value is not None)


DRAFT = "# A useful change\n\n## What to build\nMake the change.\n\n## Acceptance Criteria\n- [ ] Verify the result.\n"


class TriageVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.items = items_fixture(self.root)

    def test_verdict_section_without_items_cannot_advance(self):
        result = parse_report(report(Verdicts=verdict()))
        self.assertEqual(result["gate"], "hitl")
        self.assertIn("triage report requires --items-file", result["reasons"])

    def test_clean_verdict_advances_and_ungated_verdict_refuses(self):
        text = report(Verdicts=verdict())
        result = parse_report(text, self.items)
        self.assertEqual(result["gate"], "advance")
        self.assertEqual(result["followup_items"], ["R1"])
        self.assertFalse(result["verdicts_malformed"])
        unchecked = parse_report(text)
        self.assertEqual(unchecked["gate"], "hitl")
        self.assertIn("triage report requires --items-file", unchecked["reasons"])

    def test_pass_two_refuses_followup_and_accepts_ledger_verdict(self):
        self.items = items_fixture(self.root, pass_num=2)
        result = parse_report(report(Verdicts=verdict()), self.items)
        self.assertEqual(result["gate"], "hitl")
        self.assertTrue(result["verdicts_malformed"])
        self.assertIn("R1: follow-up is not allowed", result["verdict_errors"])
        result = parse_report(report(Verdicts=verdict(Verdict="recorded", **{"Follow-up eligible": "no"})), self.items)
        self.assertEqual(result["gate"], "advance")
        self.assertEqual(result["followup_items"], [])

    def test_malformed_verdicts(self):
        cases = [None, "", verdict().replace("- R1", "- R2"), verdict()+verdict(),
                 verdict(Source="test-1"), verdict(Verdict="resolved"), verdict(Title=None),
                 verdict(Reason=None), verdict(Title=""), verdict(Reason="", Evidence="observed"), verdict(**{"Follow-up eligible": "maybe"}),
                 verdict(Verdict="recorded"), verdict(Files="none"), verdict(Files="`other.py`"),
                 verdict(Supersedes=None), verdict(Files=None)]
        for body in cases:
            with self.subTest(body=body):
                result = parse_report(report(Verdicts=body), self.items)
                self.assertEqual(result["gate"], "hitl", result)
                self.assertTrue(result["verdicts_malformed"])
                self.assertTrue(result["reasons"][-1].startswith("malformed verdicts: "))
        duplicate = report(Verdicts=verdict()) + "\n## Verdicts\n" + verdict()
        self.assertEqual(parse_report(duplicate, self.items)["gate"], "hitl")
        result = parse_report(report(Verdicts="", Blockers="- BLOCKER unavailable"), self.items)
        self.assertEqual(result["gate"], "blocked")

    def test_counterproposal_requires_supersedes(self):
        items_fixture(self.root, "counter-proposal")
        self.assertEqual(parse_report(report(Verdicts=verdict()), self.items)["gate"], "hitl")
        self.assertEqual(parse_report(report(Verdicts=verdict(Supersedes="simplify-1 Not Applied 1")), self.items)["gate"], "advance")

    def test_issue_draft_validation_and_report_location_independence(self):
        body = report(Verdicts=verdict(**{"Follow-up eligible": "no", "Files": "none"}))
        self.assertEqual(parse_report(body, self.items)["gate"], "hitl")
        artifacts = self.root / "artifacts" / "triage-1"
        artifacts.mkdir(parents=True)
        draft = artifacts / "issue-draft-R1.md"
        for invalid in ["", "---\nid: ISSUE-002\n---\n"+DRAFT, DRAFT.replace("- [ ]", "- [x]"),
                        DRAFT.replace("## What to build", "## Other"), DRAFT+"\n# Second title\n",
                        DRAFT+"\n## Blocked by\n- Future issue\n"]:
            draft.write_text(invalid)
            self.assertEqual(parse_report(body, self.items)["gate"], "hitl")
        draft.write_text(DRAFT)
        result = parse_report(body, self.items)
        self.assertEqual(result["gate"], "advance")
        self.assertEqual(result["new_issue_items"], ["R1"])
        for location in [self.root / "reports" / "triage-1.md", artifacts / "report-draft.md"]:
            location.parent.mkdir(exist_ok=True)
            location.write_text(body)
            proc = subprocess.run([sys.executable, str(Path(__file__).with_name("parse_report.py")),
                                   "--items-file", str(self.items), str(location)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_ledger_only_verdicts(self):
        for word in ["recorded", "rejected", "deferred", "for-the-human"]:
            result = parse_report(report(Verdicts=verdict(Verdict=word, **{"Follow-up eligible": "no", "Files": "none"})), self.items)
            self.assertEqual(result["gate"], "advance")
            self.assertEqual(result["for_the_human"], ["R1"] if word == "for-the-human" else [])

    def test_draft_blocker_ids_must_be_canonical_at_cli_gate(self):
        artifacts = self.root / "artifacts" / "triage-1"
        artifacts.mkdir(parents=True)
        draft = artifacts / "issue-draft-R1.md"
        location = self.root / "report.md"
        body = report(Verdicts=verdict(**{"Follow-up eligible": "no", "Files": "none"}))
        location.write_text(body)
        cases = [("ISSUE-7", False), ("ISSUE-0007", False), ("ISSUE-\u0660\u0660\u0667", False),
                 ("ISSUE-007", True), ("ISSUE-1000", True)]
        for issue_id, canonical in cases:
            with self.subTest(issue_id=issue_id):
                draft.write_text(DRAFT + f"\n## Blocked by\n- {issue_id}\n")
                proc = subprocess.run([sys.executable, str(Path(__file__).with_name("parse_report.py")),
                                       "--items-file", str(self.items), str(location)], capture_output=True, text=True)
                if canonical:
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertEqual(parse_report(body, self.items)["verdicts"][0]["draft"]["blockers"], [issue_id])
                else:
                    self.assertEqual(proc.returncode, EXIT_CODES["hitl"], proc.stdout + proc.stderr)
                    self.assertIn("gate=hitl", proc.stdout)
                    self.assertIn("malformed verdicts", proc.stdout)
                    self.assertIn("invalid draft", proc.stdout)
                    self.assertIn("canonical", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
