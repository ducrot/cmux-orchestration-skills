#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spec_contract import (
    ContractError,
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


def review_report(verdict: str, input_digest: str, result_digest: str, *, corrections: str = "- None", blockers: str = "- None") -> str:
    return f"""## Verdict
{verdict}

## Findings
- None

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
