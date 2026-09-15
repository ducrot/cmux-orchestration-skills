#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator_lib import sha256_file  # noqa: E402
from spec_contract import ContractError  # noqa: E402
from tracker_contract import (  # noqa: E402
    render_summary,
    stage_native_tracker,
    validate_native_tracker,
    validate_proposal,
    validate_summary,
    validate_ticket_author_report,
    validate_ticket_review_report,
)


SCRIPT_DIR = Path(__file__).resolve().parent
ISSUE_STATE = SCRIPT_DIR.parents[1] / "cmux-issue-chain" / "scripts" / "issue_state.py"


def ticket(
    issue_id: str,
    title: str,
    behavior: str,
    *,
    blocked_by: list[str] | None = None,
    slice_type: str = "vertical",
    phase: str | None = None,
) -> dict:
    wide = None
    if slice_type == "wide-refactor":
        wide = {
            "phase": phase,
            "sequence": "expand-migrate-contract",
            "integration_reason": (
                "Migration batches cannot be demonstrated green independently."
                if phase == "integration"
                else None
            ),
        }
    return {
        "id": issue_id,
        "title": title,
        "delivered_behavior": behavior,
        "acceptance_criteria": [
            f"A user can verify {behavior.lower()} through the public CLI.",
            "The complete baseline suite remains green.",
        ],
        "blocked_by": blocked_by or [],
        "merge_split_rationale": (
            "This is one outcome with one verification story and shared implementation context."
        ),
        "slice_type": slice_type,
        "technical_layers": ["CLI", "state", "tests"],
        "wide_refactor": wide,
    }


def proposal(spec: Path, tickets: list[dict] | None = None, *, slug: str = "planned-feature") -> dict:
    return {
        "schema_version": 1,
        "source_spec": {"path": str(spec.resolve()), "sha256": sha256_file(spec)},
        "tracker": {
            "slug": slug,
            "title": "Planned Feature",
            "working_branch": "main",
            "canonical_check_commands": ["python3 -m unittest discover -s tests"],
        },
        "tickets": tickets
        or [
            ticket("ISSUE-001", "Deliver the first behavior", "The first behavior works"),
            ticket(
                "ISSUE-002",
                "Build on the first behavior",
                "The dependent behavior works",
                blocked_by=["ISSUE-001"],
            ),
        ],
    }


class TrackerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.spec = self.root / "approved-spec.md"
        self.spec.write_text("# Approved\n", encoding="utf-8")
        self.spec_digest = sha256_file(self.spec)
        self.proposal_path = self.root / "proposal.json"
        self.summary_path = self.root / "summary.md"
        self.report_path = self.root / "report.md"

    def tearDown(self):
        self.temp.cleanup()

    def write_proposal(self, data: dict | None = None) -> dict:
        self.proposal_path.write_text(
            json.dumps(data or proposal(self.spec), indent=2) + "\n", encoding="utf-8"
        )
        return validate_proposal(
            self.proposal_path,
            expected_spec=self.spec,
            expected_spec_sha256=self.spec_digest,
        )

    def write_author_report(self, result: dict) -> None:
        self.report_path.write_text(
            f"""## Result
PASS

## Repository Sources / Methods
- `src/cli.py`: public entry point

## Source Spec Identity
sha256 {self.spec_digest}

## Ticket Count
{result['ticket_count']}

## Ready Frontier
{chr(10).join(f"- {item}" for item in result['ready_frontier'])}

## Blockers
- None

## Plan Drift
- None

## Proposal Paths
- `{self.proposal_path.resolve()}`
- `{self.summary_path.resolve()}`
""",
            encoding="utf-8",
        )

    def test_vertical_proposal_has_deterministic_human_summary_and_report_binding(self):
        result = self.write_proposal()
        self.assertEqual(result["ticket_count"], 2)
        self.assertEqual(result["ready_frontier"], ["ISSUE-001"])
        self.summary_path.write_text(render_summary(result), encoding="utf-8")
        self.write_author_report(result)

        validated = validate_ticket_author_report(
            self.report_path,
            self.proposal_path,
            self.summary_path,
            expected_spec=self.spec,
            expected_spec_sha256=self.spec_digest,
        )

        self.assertEqual(validated["gate"], "advance")
        summary = self.summary_path.read_text(encoding="utf-8")
        self.assertIn("1. ISSUE-001", summary)
        self.assertIn("Delivered behavior:", summary)
        self.assertIn("Merge/split rationale:", summary)

    def test_horizontal_decomposition_unknown_edges_cycles_and_quantitative_sizing_are_rejected(self):
        cases = []
        horizontal = proposal(self.spec)
        horizontal["tickets"][0]["slice_type"] = "frontend"
        cases.append((horizontal, "vertical or wide-refactor"))
        unknown = proposal(self.spec)
        unknown["tickets"][0]["blocked_by"] = ["ISSUE-999"]
        cases.append((unknown, "unknown blocker"))
        cycle = proposal(self.spec)
        cycle["tickets"][0]["blocked_by"] = ["ISSUE-002"]
        cases.append((cycle, "dependency cycle"))
        sized = proposal(self.spec)
        sized["tickets"][0]["merge_split_rationale"] = "This takes 1000 tokens."
        cases.append((sized, "qualitative"))
        duplicate = proposal(self.spec)
        duplicate["tickets"][1]["id"] = "ISSUE-001"
        cases.append((duplicate, "duplicate issue id"))

        for number, (data, message) in enumerate(cases):
            with self.subTest(message=message):
                path = self.root / f"invalid-{number}.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ContractError, message):
                    validate_proposal(path)

    def test_wide_refactor_requires_expand_bounded_migrate_and_contract_sequence(self):
        tickets = [
            ticket(
                "ISSUE-001",
                "Expand compatibility",
                "Both old and new forms work",
                slice_type="wide-refactor",
                phase="expand",
            ),
            ticket(
                "ISSUE-002",
                "Migrate one bounded area",
                "One bounded area uses the new form",
                blocked_by=["ISSUE-001"],
                slice_type="wide-refactor",
                phase="migrate",
            ),
            ticket(
                "ISSUE-003",
                "Contract compatibility",
                "Only the new form remains",
                blocked_by=["ISSUE-002"],
                slice_type="wide-refactor",
                phase="contract",
            ),
        ]
        valid = self.write_proposal(proposal(self.spec, tickets))
        self.assertEqual(set(valid["wide_refactor"]), {"expand", "migrate", "contract"})

        missing_contract = proposal(self.spec, tickets[:-1])
        self.proposal_path.write_text(json.dumps(missing_contract), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "expand, bounded migrate, and contract"):
            validate_proposal(self.proposal_path)

    def test_proposal_enforces_frozen_tracker_slug(self):
        self.write_proposal()
        for expected in (None, "planned-feature"):
            self.assertEqual(
                validate_proposal(self.proposal_path, expected_tracker_slug=expected)["tracker"]["slug"],
                "planned-feature",
            )
        with self.assertRaisesRegex(ContractError, "tracker.slug.*frozen"):
            validate_proposal(self.proposal_path, expected_tracker_slug="fixed-name")

    def test_proposal_cli_checks_frozen_slug(self):
        self.write_proposal()
        for expected in ("planned-feature", "different-slug"):
            result = subprocess.run([
                sys.executable, str(SCRIPT_DIR / "tracker_contract.py"), "proposal",
                str(self.proposal_path), "--spec", str(self.spec),
                "--spec-sha256", self.spec_digest, "--tracker-slug", expected,
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0 if expected == "planned-feature" else 1, result.stderr)
            if expected != "planned-feature":
                self.assertIn("tracker.slug must equal frozen", result.stderr)

    def test_all_review_verdicts_bind_digests_and_safe_fixes_need_no_second_review(self):
        original = self.write_proposal()
        digest = original["sha256"]
        review = self.root / "review.md"
        candidate = self.root / "candidate.json"

        def report(verdict: str, resulting: str, *, corrections: str = "- None", blockers: str = "- None") -> str:
            return f"""## Verdict
{verdict}

## Findings
- None

## Methods
- `src/cli.py`: independently inspected

## Input Identity
sha256 {digest}

## Resulting Candidate Identity
sha256 {resulting}

## Corrections
{corrections}

## Blockers
{blockers}

## Plan Drift
- None
"""

        review.write_text(report("pass", digest), encoding="utf-8")
        passed = validate_ticket_review_report(
            review,
            self.proposal_path,
            candidate,
            expected_input_sha256=digest,
            expected_spec=self.spec,
            expected_spec_sha256=self.spec_digest,
        )
        self.assertEqual(passed["candidate"], str(self.proposal_path.resolve()))

        corrected = proposal(self.spec)
        corrected["tickets"][0]["delivered_behavior"] = "The clarified first behavior works"
        candidate.write_text(json.dumps(corrected, indent=2) + "\n", encoding="utf-8")
        candidate_digest = validate_proposal(candidate)["sha256"]
        review.write_text(
            report(
                "pass_with_fixes",
                candidate_digest,
                corrections="- Clarified wording already established by the approved specification.",
            ),
            encoding="utf-8",
        )
        fixed = validate_ticket_review_report(
            review,
            self.proposal_path,
            candidate,
            expected_input_sha256=digest,
            expected_spec=self.spec,
            expected_spec_sha256=self.spec_digest,
        )
        self.assertEqual(fixed["gate"], "advance")
        for expected in ("planned-feature", "renamed-tracker"):
            command = [
                sys.executable, str(SCRIPT_DIR / "tracker_contract.py"), "review-report",
                str(review), "--input", str(self.proposal_path), "--candidate", str(candidate),
                "--input-sha256", digest, "--spec", str(self.spec),
                "--spec-sha256", self.spec_digest, "--tracker-slug", expected,
            ]
            checked = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0 if expected == "planned-feature" else 1, checked.stderr)
            if expected != "planned-feature":
                self.assertIn("tracker.slug must equal frozen", checked.stderr)
        corrected["tracker"]["slug"] = "renamed-tracker"
        candidate.write_text(json.dumps(corrected), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "tracker.slug.*frozen"):
            validate_ticket_review_report(
                review, self.proposal_path, candidate,
                expected_input_sha256=digest, expected_spec=self.spec,
                expected_spec_sha256=self.spec_digest, expected_tracker_slug="planned-feature",
            )
        candidate.unlink()

        review.write_text(
            report(
                "blocked",
                digest,
                blockers="- The approved specification leaves the rollout decision unresolved.",
            ),
            encoding="utf-8",
        )
        blocked = validate_ticket_review_report(
            review,
            self.proposal_path,
            candidate,
            expected_input_sha256=digest,
            expected_spec=self.spec,
            expected_spec_sha256=self.spec_digest,
        )
        self.assertEqual(blocked["gate"], "blocked")

    def test_staged_output_is_native_and_independently_accepted_by_issue_chain(self):
        result = self.write_proposal()
        tracker = self.root / "planned-feature"
        native = stage_native_tracker(tracker, result, approved_spec=self.spec)
        self.assertEqual(native["ready_frontier"], ["ISSUE-001"])
        validate_native_tracker(
            tracker,
            expected_spec_sha256=self.spec_digest,
            expected_ticket_ids=["ISSUE-001", "ISSUE-002"],
        )

        checked = subprocess.run(
            [sys.executable, str(ISSUE_STATE), "list", "--tracker", str(tracker), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        issues = json.loads(checked.stdout)
        self.assertEqual([item["id"] for item in issues], ["ISSUE-001", "ISSUE-002"])
        self.assertTrue(issues[0]["ready"])
        self.assertFalse(issues[1]["ready"])

    def test_native_validation_rejects_partial_issue_set_and_changed_spec(self):
        result = self.write_proposal()
        tracker = self.root / "planned-feature"
        stage_native_tracker(tracker, result, approved_spec=self.spec)
        next((tracker / "issues").glob("ISSUE-002-*.md")).unlink()
        with self.assertRaisesRegex(ContractError, "partial or mismatched"):
            validate_native_tracker(
                tracker,
                expected_spec_sha256=self.spec_digest,
                expected_ticket_ids=["ISSUE-001", "ISSUE-002"],
            )
        (tracker / "spec.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "approved specification"):
            validate_native_tracker(tracker, expected_spec_sha256=self.spec_digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
