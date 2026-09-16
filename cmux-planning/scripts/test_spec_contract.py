#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from spec_contract import (
    ContractError,
    SPEC_SECTIONS,
    validate_author_report,
    validate_review_report,
    validate_spec,
)


def spec(open_decisions: str = "- None", solution: str = "Implement the requested workflow.") -> str:
    return f"""# Specification

## Problem Statement

Users cannot plan safely.

## Solution

{solution}

## User Stories

- As a user, I can approve a reviewed specification.

## Implementation Decisions

- Keep state deterministic.

## Testing Decisions

- Existing seam: dependency-free CLI integration.
- Prior-art test: `scripts/test_run_state.py`.
- Verification: invoke the real CLI and inspect state.

## Assumptions

- Git is available.

## Open Decisions

{open_decisions}

## Out of Scope

- Ticket publication.

## Further Notes

- Literal copy “Speichern” stays German.
"""


def checked_evidence(references: Sequence[str]) -> str:
    return "\n".join(f"- `{reference}`: checked consistency with repository evidence: no discrepancy found" for reference in references)


def review_report(verdict: str, input_digest: str, result_digest: str, *, corrections: str = "- None", blockers: str = "- None", checked: str | None = None) -> str:
    evidence = checked_evidence(SPEC_SECTIONS) if checked is None else checked
    return f"""## Verdict
{verdict}

## Findings
- None

## Checked
{evidence}

## Methods
- `src/` and prior tests inspected independently

## Input Identity
sha256 {input_digest}

## Resulting Candidate Identity
sha256 {result_digest}

## Corrections
{corrections}

## Blockers
{blockers}

## Plan Drift
- None
"""


class SpecificationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.draft = self.root / "spec-1.md"
        self.report = self.root / "report.md"
        self.candidate = self.root / "reviewed.md"
        self.draft.write_text(spec(), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_spec_and_grounded_author_report_validate(self):
        self.report.write_text(
            f"""## Result
PASS

## Repository Sources / Methods
- `scripts/planning_state.py`: state seam inspected

## Proposed Test Seams
- CLI integration via temporary Git repository

## Blockers
- None

## Plan Drift
- None

## Draft Path
`{self.draft}`
""",
            encoding="utf-8",
        )
        result = validate_author_report(self.report, self.draft)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["draft_sha256"], validate_spec(self.draft)["sha256"])

    def test_malformed_or_ungrounded_author_handoff_stops(self):
        self.report.write_text(
            f"## Result\nPASS\n\n## Repository Sources / Methods\n- None\n\n## Proposed Test Seams\n- seam\n\n## Blockers\n- None\n\n## Plan Drift\n- None\n\n## Draft Path\n`{self.draft}`\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContractError, "ungrounded"):
            validate_author_report(self.report, self.draft)

    def test_blocked_author_report_validates_without_a_draft(self):
        self.draft.unlink()
        self.report.write_text(
            f"""## Result
BLOCKED

## Repository Sources / Methods
- `scripts/planning_state.py`: state seam inspected

## Proposed Test Seams
- None

## Blockers
- The task names an undefined subsystem; a human product decision is required.

## Plan Drift
- None

## Draft Path
`{self.draft}`
""",
            encoding="utf-8",
        )
        result = validate_author_report(self.report, self.draft)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIsNone(result["draft_sha256"])

    def test_all_review_verdicts_and_digest_binding(self):
        input_digest = validate_spec(self.draft)["sha256"]
        with self.subTest("pass"):
            self.report.write_text(review_report("pass", input_digest, input_digest), encoding="utf-8")
            result = validate_review_report(self.report, self.draft, self.candidate)
            self.assertEqual(result["candidate"], str(self.draft.resolve()))
        with self.subTest("pass_with_fixes"):
            self.candidate.write_text(spec(solution="Implement the clarified requested workflow."), encoding="utf-8")
            candidate_digest = validate_spec(self.candidate)["sha256"]
            self.report.write_text(
                review_report(
                    "pass_with_fixes",
                    input_digest,
                    candidate_digest,
                    corrections="- Clarified already-established workflow wording.",
                ),
                encoding="utf-8",
            )
            result = validate_review_report(self.report, self.draft, self.candidate)
            self.assertEqual(result["verdict"], "pass_with_fixes")
        with self.subTest("blocked"):
            self.candidate.unlink()
            self.report.write_text(
                review_report(
                    "blocked",
                    input_digest,
                    input_digest,
                    blockers="- Product must choose whether the new behavior is opt-in.",
                ),
                encoding="utf-8",
            )
            self.assertEqual(validate_review_report(self.report, self.draft, self.candidate)["gate"], "blocked")

    def test_checked_requires_complete_structured_evidence(self):
        digest = validate_spec(self.draft)["sha256"]
        complete = review_report("pass", digest, digest)
        evidence = checked_evidence(SPEC_SECTIONS)
        self.report.write_text(complete, encoding="utf-8")
        self.assertEqual(validate_review_report(self.report, self.draft, self.candidate)["gate"], "advance")
        invalid = {
            "missing": complete.replace("## Checked\n" + evidence + "\n\n", ""),
            "empty": review_report("pass", digest, digest, checked=""),
            "none": review_report("pass", digest, digest, checked="- None"),
            "prose_only": review_report("pass", digest, digest, checked=evidence.replace("- ", "")),
            "reference_only": review_report("pass", digest, digest, checked="\n".join(f"- `{name}`" for name in SPEC_SECTIONS)),
            "missing_section": review_report("pass", digest, digest, checked=checked_evidence(SPEC_SECTIONS[:-1])),
            "unquoted_bullet": review_report("pass", digest, digest, checked=evidence.replace("`", "")),
            "extra_unquoted_bullet": review_report("pass", digest, digest, checked=evidence + "\n- checked other concerns: clean"),
            "missing_check": review_report("pass", digest, digest, checked=evidence.replace("checked consistency with repository evidence", "")),
            "missing_outcome": review_report("pass", digest, digest, checked=evidence.replace("no discrepancy found", "")),
        }
        for name, report in invalid.items():
            with self.subTest(name=name):
                self.report.write_text(report, encoding="utf-8")
                with self.assertRaisesRegex(ContractError, "Checked"):
                    validate_review_report(self.report, self.draft, self.candidate)

    def test_checked_accepts_colon_bearing_and_multiple_quoted_references(self):
        digest = validate_spec(self.draft)["sha256"]
        evidence = checked_evidence(SPEC_SECTIONS)
        extra = "- `src/cli.py:42`, `tests/test_cli.py:7`: read handler and its test: match the draft"
        self.report.write_text(
            review_report("pass", digest, digest, checked=f"{evidence}\n{extra}"), encoding="utf-8"
        )
        self.assertEqual(validate_review_report(self.report, self.draft, self.candidate)["gate"], "advance")
        unterminated = "- `src/cli.py:42: read handler: matches the draft"
        self.report.write_text(
            review_report("pass", digest, digest, checked=f"{evidence}\n{unterminated}"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContractError, "Checked bullets must use"):
            validate_review_report(self.report, self.draft, self.candidate)

    def test_blocked_review_keeps_evidence_shape_without_full_coverage(self):
        digest = validate_spec(self.draft)["sha256"]
        partial = checked_evidence(SPEC_SECTIONS[:2])
        blocker = "- Product must choose whether the new behavior is opt-in."
        self.report.write_text(
            review_report("blocked", digest, digest, blockers=blocker, checked=partial),
            encoding="utf-8",
        )
        self.assertEqual(validate_review_report(self.report, self.draft, self.candidate)["gate"], "blocked")
        with self.subTest(name="passing_verdict_keeps_full_coverage"):
            self.report.write_text(
                review_report("pass", digest, digest, checked=partial), encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "Checked is missing references"):
                validate_review_report(self.report, self.draft, self.candidate)
        malformed = {
            "empty": "",
            "none": "- None",
            "prose_only": partial.replace("- ", ""),
            "unquoted": partial.replace("`", ""),
            "reference_only": "- `Problem Statement`",
        }
        for name, checked in malformed.items():
            with self.subTest(name=name):
                self.report.write_text(
                    review_report("blocked", digest, digest, blockers=blocker, checked=checked),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ContractError, "Checked"):
                    validate_review_report(self.report, self.draft, self.candidate)
        with self.subTest(name="substantive_blocker_still_required"):
            self.report.write_text(
                review_report("blocked", digest, digest, checked=partial), encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "blocked review must state"):
                validate_review_report(self.report, self.draft, self.candidate)
        with self.subTest(name="approval_candidate_still_refused"):
            self.candidate.write_text(spec(), encoding="utf-8")
            self.report.write_text(
                review_report("blocked", digest, digest, blockers=blocker, checked=partial),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "must not supply an approval candidate"):
                validate_review_report(self.report, self.draft, self.candidate)
            self.candidate.unlink()

    def test_open_decision_blocks_passing_review(self):
        self.draft.write_text(
            spec(open_decisions="- Question: Opt in? Context: Product choice. Options: A/B. Recommendation: A. Reason open: owner input."),
            encoding="utf-8",
        )
        digest = validate_spec(self.draft)["sha256"]
        self.report.write_text(review_report("pass", digest, digest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "Open Decision"):
            validate_review_report(self.report, self.draft, self.candidate)

    def test_digest_mismatch_stops_review(self):
        digest = validate_spec(self.draft)["sha256"]
        self.report.write_text(review_report("pass", "0" * 64, digest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "Input Identity"):
            validate_review_report(self.report, self.draft, self.candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
