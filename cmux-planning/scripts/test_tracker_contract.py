#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator_lib import sha256_file  # noqa: E402
from spec_contract import ContractError  # noqa: E402
from test_spec_contract import checked_evidence, review_report  # noqa: E402
from tracker_contract import (  # noqa: E402
    issue_slug,
    render_issue,
    render_readme,
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


def with_execution_modes(data: dict, modes) -> dict:
    data["schema_version"] = 2
    for item, mode in zip(data["tickets"], modes, strict=True):
        item["execution_mode"] = mode
    return data


def wide_proposal(spec: Path) -> dict:
    return proposal(spec, [
        ticket(
            f"ISSUE-{index:03}", f"Deliver {phase} phase", f"The {phase} phase works",
            blocked_by=[f"ISSUE-{index - 1:03}"] if index > 1 else [],
            slice_type="wide-refactor", phase=phase,
        )
        for index, phase in enumerate(("expand", "migrate", "contract"), start=1)
    ])


def with_slice_types(data: dict, slice_types) -> dict:
    for item, slice_type in zip(data["tickets"], slice_types, strict=True):
        item["slice_type"] = slice_type
    return data


def summary_headings(summary: str) -> list[str]:
    return [line for line in summary.splitlines() if line.startswith("### ")]


def mixed_proposal(spec: Path) -> dict:
    data = with_execution_modes(proposal(spec), ("AFK", "HITL"))
    for item in data["tickets"]:
        item["blocked_by"] = []
    return data


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
        baseline = (SCRIPT_DIR / "fixtures" / "vertical-summary.md").read_bytes()
        self.assertEqual(
            summary.encode("utf-8"),
            baseline.replace(b"<spec-sha256>", self.spec_digest.encode("ascii")),
        )

    def test_horizontal_decomposition_unknown_edges_cycles_and_quantitative_sizing_are_rejected(self):
        cases = []
        horizontal = proposal(self.spec)
        horizontal["tickets"][0]["slice_type"] = "frontend"
        cases.append((horizontal, "slice_type must be"))
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

    def test_summary_marks_prefactor_and_preserves_hitl_and_vertical_titles(self):
        data = with_slice_types(
            with_execution_modes(proposal(self.spec), ("HITL", "AFK")), ("prefactor", "vertical"),
        )
        self.assertEqual(
            summary_headings(render_summary(self.write_proposal(data))),
            ["### 1. ISSUE-001 — Deliver the first behavior [HITL] [prefactor]",
             "### 2. ISSUE-002 — Build on the first behavior"],
        )

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
        summary = render_summary(valid)
        self.assertEqual(
            summary_headings(summary),
            ["### 1. ISSUE-001 — Expand compatibility [wide-refactor: expand]",
             "### 2. ISSUE-002 — Migrate one bounded area [wide-refactor: migrate]",
             "### 3. ISSUE-003 — Contract compatibility [wide-refactor: contract]"],
        )
        tracker = self.root / "wide-tracker"
        stage_native_tracker(tracker, valid, approved_spec=self.spec)
        self.assertEqual((tracker / "map.md").read_text(), summary)
        for issue in (tracker / "issues").glob("*.md"):
            text = issue.read_text()
            item = next(item for item in valid["tickets"] if item["id"] in issue.name)
            self.assertIn("slice_type: wide-refactor\n", text)
            self.assertIn(f"wide_refactor_phase: {item['wide_refactor']['phase']}\n", text)
            self.assertIn(
                "## Wide Refactor Sequence\n\n- Sequence: `expand-migrate-contract`\n"
                f"- Phase: `{item['wide_refactor']['phase']}`", text,
            )
            self.assertNotIn("## Merge / Split Rationale", text)

        missing_contract = proposal(self.spec, tickets[:-1])
        self.proposal_path.write_text(json.dumps(missing_contract), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "expand, bounded migrate, and contract"):
            validate_proposal(self.proposal_path)

    def test_prefactor_accepts_null_wide_refactor_and_rejects_details(self):
        data = proposal(self.spec)
        data["tickets"][0]["slice_type"] = "prefactor"
        result = self.write_proposal(data)
        self.assertEqual(result["tickets"][0]["slice_type"], "prefactor")
        self.assertIsNone(result["tickets"][0]["wide_refactor"])
        self.assertEqual(result["ready_frontier"], ["ISSUE-001"])
        for kind in ("vertical", "prefactor"):
            with self.subTest(kind=kind):
                data["tickets"][0]["slice_type"] = kind
                data["tickets"][0]["wide_refactor"] = {"phase": "expand"}
                with self.assertRaisesRegex(ContractError, "wide_refactor to null"):
                    self.write_proposal(data)

    def test_prefactor_without_a_later_dependent_is_rejected_by_module_and_cli(self):
        for schema in (1, 2):
            for orphan in ("ISSUE-001", "ISSUE-002"):
                with self.subTest(schema=schema, orphan=orphan):
                    data = proposal(self.spec)
                    data["tickets"][0]["slice_type"] = "prefactor"
                    if orphan == "ISSUE-001":
                        data["tickets"][1]["blocked_by"] = []
                    else:
                        data["tickets"][1]["slice_type"] = "prefactor"
                    if schema == 2:
                        with_execution_modes(data, ("AFK", "HITL"))
                    message = rf"{orphan}.*prefactor.*blocked_by.*later ticket"
                    with self.assertRaisesRegex(ContractError, message):
                        self.write_proposal(data)
                    checked = self.proposal_cli()
                    self.assertNotEqual(checked.returncode, 0)
                    self.assertRegex(checked.stderr, message)

    def test_prefactor_with_a_later_dependent_accepts_either_proposal_order(self):
        for schema in (1, 2):
            for reverse in (False, True):
                with self.subTest(schema=schema, reverse=reverse):
                    data = proposal(self.spec)
                    data["tickets"][0]["slice_type"] = "prefactor"
                    if schema == 2:
                        with_execution_modes(data, ("AFK", "HITL"))
                    if reverse:
                        data["tickets"].reverse()
                    result = self.write_proposal(data)
                    self.assertEqual(result["ready_frontier"], ["ISSUE-001"])
                    self.assertEqual(result["tickets"], [
                        {**item, "execution_mode": item.get("execution_mode", "AFK")}
                        for item in data["tickets"]
                    ])
                    checked = self.proposal_cli()
                    self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_blockers_must_have_lower_numbers_regardless_of_proposal_order(self):
        data = proposal(self.spec)
        data["tickets"].reverse()
        self.assertEqual(self.write_proposal(data)["ready_frontier"], ["ISSUE-001"])
        for blocker in ("ISSUE-001", "ISSUE-002"):
            with self.subTest(blocker=blocker):
                data = proposal(self.spec)
                data["tickets"][1]["blocked_by"] = []
                data["tickets"][0]["blocked_by"] = [blocker]
                expected = "lists itself" if blocker == "ISSUE-001" else "must have a lower number"
                with self.assertRaisesRegex(ContractError, expected):
                    self.write_proposal(data)

    def test_product_token_vocabulary_passes_but_number_plus_token_sizing_fails(self):
        for text in ("Auth-Token erneuern", "Tokens bleiben gültig", "Token 123", "Tokenizer"):
            with self.subTest(text=text):
                data = proposal(self.spec)
                data["tickets"][0]["title"] = text
                self.write_proposal(data)
        for field in ("title", "delivered_behavior", "acceptance_criteria",
                      "merge_split_rationale", "technical_layers"):
            for text in ("1000 tokens", "1 Token", "2 TOKENS", "100\tTokens", "10k tokens",
                         "500-token budget", "1,500 Tokens", "5000tokens"):
                with self.subTest(field=field, text=text):
                    data = proposal(self.spec)
                    data["tickets"][0][field] = [text] if field in (
                        "acceptance_criteria", "technical_layers"
                    ) else text
                    with self.assertRaisesRegex(ContractError, "qualitative"):
                        self.write_proposal(data)

    def test_issue_slugs_transliterate_german_and_normalize_other_latin_titles(self):
        for title, expected in (
            ("ÄÖÜ äöü ß ẞ", "aeoeue-aeoeue-ss-ss"),
            ("Größe ändern", "groesse-aendern"),
            ("Gro\u0308\u00dfe a\u0308ndern", "groesse-aendern"),
            ("Crème brûlée", "creme-brulee"),
            ("東京", "work"),
            ("!!!", "work"),
            ("a" * 71 + " b", "a" * 71),
        ):
            with self.subTest(title=title):
                self.assertEqual(issue_slug(title), expected)

    def test_new_issues_omit_rationale_and_legacy_issues_still_validate(self):
        data = proposal(self.spec)
        data["tickets"][0]["slice_type"] = "prefactor"
        data["tickets"][0]["title"] = "Größe ändern: Auth-Token"
        result = self.write_proposal(data)
        tracker = self.root / "planned-feature"
        stage_native_tracker(tracker, result, approved_spec=self.spec)
        issue = tracker / "issues" / "ISSUE-001-groesse-aendern-auth-token.md"
        self.assertTrue(issue.is_file())
        text = issue.read_text()
        self.assertIn("slice_type: prefactor\n", text)
        self.assertNotIn("wide_refactor_phase:", text)
        self.assertNotIn("## Merge / Split Rationale", text)
        rationale = data["tickets"][0]["merge_split_rationale"]
        self.assertEqual(rationale, result["tickets"][0]["merge_split_rationale"])
        self.assertIn(rationale, render_summary(result))
        for name in ("map.md", "decisions.md"):
            self.assertIn(rationale, (tracker / name).read_text())
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    issue.write_text(issue.read_text().replace(
                        "## Blocked by", f"## Merge / Split Rationale\n\n{rationale}\n\n## Blocked by"
                    ))
                checked = self.contract_cli("native-tracker", str(tracker),
                                            "--spec-sha256", self.spec_digest)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                chain = subprocess.run(
                    [sys.executable, str(ISSUE_STATE), "list", "--tracker", str(tracker), "--json"],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(chain.returncode, 0, chain.stderr)
                self.assertEqual([item["id"] for item in json.loads(chain.stdout)],
                                 ["ISSUE-001", "ISSUE-002"])

    def test_proposal_enforces_frozen_tracker_slug(self):
        self.write_proposal()
        for case, expected in (("optional", None), ("equal", "planned-feature")):
            with self.subTest(case=case):
                self.assertEqual(
                    validate_proposal(self.proposal_path, expected_tracker_slug=expected)["tracker"]["slug"],
                    "planned-feature",
                )
        with self.assertRaisesRegex(ContractError, "tracker.slug.*frozen"):
            validate_proposal(self.proposal_path, expected_tracker_slug="fixed-name")

    def test_proposal_cli_checks_frozen_slug(self):
        self.write_proposal()
        for case, expected, returncode in (
            ("optional", None, 0), ("equal", "planned-feature", 0), ("different", "different-slug", 1),
        ):
            with self.subTest(case=case):
                result = self.proposal_cli(*(("--tracker-slug", expected) if expected else ()))
                self.assertEqual(result.returncode, returncode, result.stderr)
                if returncode:
                    self.assertIn("tracker.slug must equal frozen", result.stderr)

    def contract_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "tracker_contract.py"), *args],
            capture_output=True, text=True, timeout=30,
        )

    def proposal_cli(self, *args: str) -> subprocess.CompletedProcess:
        return self.contract_cli(
            "proposal", str(self.proposal_path), "--spec", str(self.spec),
            "--spec-sha256", self.spec_digest, *args,
        )

    def test_review_report_cli_checks_frozen_slug_and_rejects_renamed_candidate(self):
        digest = self.write_proposal()["sha256"]
        review = self.root / "review.md"
        candidate = self.root / "candidate.json"
        corrected = proposal(self.spec)
        corrected["tickets"][0]["delivered_behavior"] = "The clarified first behavior works"
        candidate.write_text(json.dumps(corrected), encoding="utf-8")
        review.write_text(
            review_report(
                "pass_with_fixes", digest, validate_proposal(candidate)["sha256"],
                corrections="- Clarified wording already established by the approved specification.",
                checked=checked_evidence(["ISSUE-001", "ISSUE-002"]),
            ), encoding="utf-8",
        )
        for case, expected, returncode in (
            ("optional", None, 0), ("equal", "planned-feature", 0), ("different", "renamed-tracker", 1),
        ):
            with self.subTest(case=case):
                result = self.contract_cli(
                    "review-report", str(review), "--input", str(self.proposal_path),
                    "--candidate", str(candidate), "--input-sha256", digest,
                    "--spec", str(self.spec), "--spec-sha256", self.spec_digest,
                    *(("--tracker-slug", expected) if expected else ()),
                )
                self.assertEqual(result.returncode, returncode, result.stderr)
                if returncode:
                    self.assertIn("tracker.slug must equal frozen", result.stderr)
        corrected["tracker"]["slug"] = "renamed-tracker"
        candidate.write_text(json.dumps(corrected), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "tracker.slug.*frozen"):
            validate_ticket_review_report(
                review, self.proposal_path, candidate,
                expected_input_sha256=digest, expected_spec=self.spec,
                expected_spec_sha256=self.spec_digest, expected_tracker_slug="planned-feature",
            )

    def test_pass_report_rejects_explanatory_empty_sections_until_moved_to_methods(self):
        digest = self.write_proposal()["sha256"]
        review = self.root / "review.md"
        candidate = self.root / "candidate.json"
        clean = review_report(
            "pass", digest, digest,
            checked=checked_evidence(["ISSUE-001", "ISSUE-002"]),
        )
        explanation = "The proposal and approved specification remain unchanged."
        for section in ("Findings", "Corrections", "Blockers", "Plan Drift"):
            for suffix in (". " + explanation, "\n\n" + explanation):
                with self.subTest(section=section, suffix=suffix):
                    review.write_text(clean.replace(
                        f"## {section}\n- None", f"## {section}\n- None{suffix}"
                    ), encoding="utf-8")
                    result = self.contract_cli(
                        "review-report", str(review), "--input", str(self.proposal_path),
                        "--candidate", str(candidate), "--input-sha256", digest,
                        "--spec", str(self.spec), "--spec-sha256", self.spec_digest,
                    )
                    self.assertNotEqual(result.returncode, 0)
        review.write_text(clean.replace(
            "## Methods\n", f"## Methods\n- {explanation}\n"
        ), encoding="utf-8")
        result = self.contract_cli(
            "review-report", str(review), "--input", str(self.proposal_path),
            "--candidate", str(candidate), "--input-sha256", digest,
            "--spec", str(self.spec), "--spec-sha256", self.spec_digest,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

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

## Checked
{checked_evidence(["ISSUE-001", "ISSUE-002"])}

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

    def test_checked_covers_every_input_ticket(self):
        original = self.write_proposal()
        digest = original["sha256"]
        review = self.root / "review.md"
        candidate = self.root / "candidate.json"
        complete = review_report(
            "pass", digest, digest, checked=checked_evidence(["ISSUE-001", "ISSUE-002"])
        )
        review.write_text(complete, encoding="utf-8")
        kwargs = dict(expected_input_sha256=digest, expected_spec=self.spec,
                      expected_spec_sha256=self.spec_digest)
        self.assertEqual(validate_ticket_review_report(
            review, self.proposal_path, candidate, **kwargs)["gate"], "advance")
        review.write_text(
            review_report("pass", digest, digest, checked=checked_evidence(["ISSUE-001"])),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContractError, "Checked.*ISSUE-002"):
            validate_ticket_review_report(review, self.proposal_path, candidate, **kwargs)

    def test_blocked_tickets_review_keeps_evidence_shape_without_full_coverage(self):
        digest = self.write_proposal()["sha256"]
        review = self.root / "review.md"
        candidate = self.root / "candidate.json"
        partial = checked_evidence(["ISSUE-001"])
        blocker = "- The approved specification leaves the rollout decision unresolved."
        kwargs = dict(
            expected_input_sha256=digest,
            expected_spec=self.spec,
            expected_spec_sha256=self.spec_digest,
        )
        review.write_text(
            review_report("blocked", digest, digest, blockers=blocker, checked=partial),
            encoding="utf-8",
        )
        blocked = validate_ticket_review_report(review, self.proposal_path, candidate, **kwargs)
        self.assertEqual(blocked["gate"], "blocked")
        review.write_text(
            review_report("pass", digest, digest, checked=partial), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "Checked is missing references: ISSUE-002"):
            validate_ticket_review_report(review, self.proposal_path, candidate, **kwargs)
        review.write_text(
            review_report("blocked", digest, digest, blockers=blocker, checked="- None"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContractError, "Checked must contain evidence bullets"):
            validate_ticket_review_report(review, self.proposal_path, candidate, **kwargs)
        review.write_text(
            review_report("blocked", digest, digest, checked=partial), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "blocked tickets review must state"):
            validate_ticket_review_report(review, self.proposal_path, candidate, **kwargs)

    def test_v2_modes_are_required_and_exact(self):
        data = mixed_proposal(self.spec)
        result = self.write_proposal(data)
        self.assertEqual(result["ready_frontier"], ["ISSUE-001", "ISSUE-002"])
        for value in (None, "human", "afk", " HITL ", 2, [], {}):
            with self.subTest(value=value):
                data = mixed_proposal(self.spec)
                if value is None:
                    del data["tickets"][1]["execution_mode"]
                else:
                    data["tickets"][1]["execution_mode"] = value
                with self.assertRaises(ContractError):
                    self.write_proposal(data)

    def test_mixed_tracker_renders_validates_and_loads_in_issue_chain(self):
        result = self.write_proposal(mixed_proposal(self.spec))
        summary = render_summary(result)
        self.assertIn("### 2. ISSUE-002 — Build on the first behavior [HITL]", summary)
        self.assertEqual(summary.count("[HITL]"), 1)
        tracker = self.root / "mixed"
        native = stage_native_tracker(tracker, result, approved_spec=self.spec)
        self.assertEqual(native["ready_frontier"], ["ISSUE-001", "ISSUE-002"])
        for item in result["tickets"]:
            body = next((tracker / "issues").glob(item["id"] + "-*.md")).read_text()
            label = "ready-for-human" if item["execution_mode"] == "HITL" else "ready-for-agent"
            self.assertIn(f"slice_type: {item['slice_type']}\n", body)
            self.assertNotIn("wide_refactor_phase:", body)
            self.assertIn(f"type: {item['execution_mode']}\nstatus: todo\nlabels:\n  - {label}\n---", body)
        checked = self.contract_cli("native-tracker", str(tracker))
        self.assertEqual(checked.returncode, 0, checked.stderr)
        chain = subprocess.run([sys.executable, str(ISSUE_STATE), "list", "--tracker", str(tracker), "--json"], capture_output=True, text=True, timeout=30)
        self.assertEqual(chain.returncode, 0, chain.stderr)
        self.assertEqual([(i["id"], i["ready"]) for i in json.loads(chain.stdout)], [("ISSUE-001", True), ("ISSUE-002", False)])
        before = {p.name: p.read_bytes() for p in (tracker / "issues").glob("*.md")}
        adopted = subprocess.run(
            [sys.executable, str(ISSUE_STATE.with_name("adopt_tracker.py")), "--tracker", str(tracker)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (tracker / "issues").glob("*.md")})
        issue = next((tracker / "issues").glob("ISSUE-002-*.md"))
        original = issue.read_text()
        for changed in (original.replace("ready-for-human", "ready-for-agent"), original.replace("type: HITL", "type: AFK"), original.replace("type: HITL", "type: OTHER")):
            issue.write_text(changed)
            with self.assertRaises(ContractError):
                validate_native_tracker(tracker)
        issue.write_text(original)

    def test_native_slice_metadata_accepts_legacy_and_valid_values_through_cli(self):
        tracker = self.root / "metadata"
        native = stage_native_tracker(tracker, self.write_proposal(), approved_spec=self.spec)
        issue = next((tracker / "issues").glob("ISSUE-001-*.md"))
        original = issue.read_text()
        legacy = original.replace("slice_type: vertical\n", "")
        metadata = ["", "slice_type: vertical\n", "slice_type: prefactor\n",
                    "slice_type: wide-refactor\n"]
        metadata += [f"slice_type: wide-refactor\nwide_refactor_phase: {phase}\n"
                     for phase in ("expand", "migrate", "contract", "integration")]
        for fields in metadata:
            with self.subTest(fields=fields):
                issue.write_text(legacy.replace("type: AFK\n", fields + "type: AFK\n"))
                checked = self.contract_cli("native-tracker", str(tracker))
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertEqual(json.loads(checked.stdout)["ready_frontier"], native["ready_frontier"])

    def test_native_slice_metadata_rejects_invalid_values_with_filename_through_cli(self):
        tracker = self.root / "metadata"
        stage_native_tracker(tracker, self.write_proposal(), approved_spec=self.spec)
        issue = next((tracker / "issues").glob("ISSUE-001-*.md"))
        legacy = issue.read_text().replace("slice_type: vertical\n", "")
        cases = [
            ("slice_type: frontend\n", "slice_type"),
            ("slice_type:\n", "slice_type"),
            ("wide_refactor_phase: expand\n", "wide_refactor_phase"),
            ("slice_type: vertical\nwide_refactor_phase: expand\n", "wide_refactor_phase"),
            ("slice_type: prefactor\nwide_refactor_phase: expand\n", "wide_refactor_phase"),
            ("slice_type: wide-refactor\nwide_refactor_phase: deploy\n", "wide_refactor_phase"),
            ("slice_type: wide-refactor\nwide_refactor_phase:\n", "wide_refactor_phase"),
        ]
        for fields, message in cases:
            with self.subTest(fields=fields):
                issue.write_text(legacy.replace("type: AFK\n", fields + "type: AFK\n"))
                checked = self.contract_cli("native-tracker", str(tracker))
                self.assertEqual(checked.returncode, 1, checked.stdout)
                self.assertIn(issue.name, checked.stderr)
                self.assertIn(message, checked.stderr)

    def test_staging_rejects_wrong_or_missing_approved_slice_type(self):
        result = self.write_proposal()
        renderers = {
            "wrong": lambda item: render_issue({**item, "slice_type": "prefactor"}),
            "missing": lambda item: render_issue(item).replace("slice_type: vertical\n", ""),
        }
        for kind, wrong_slice in renderers.items():
            with self.subTest(kind=kind):
                with patch("tracker_contract.render_issue", side_effect=wrong_slice):
                    with self.assertRaisesRegex(ContractError, "slice type.*approved"):
                        stage_native_tracker(self.root / kind, result, approved_spec=self.spec)

    def test_staging_rejects_valid_native_issue_with_wrong_approved_mode(self):
        result = self.write_proposal(mixed_proposal(self.spec))
        def wrong_mode(item):
            return render_issue({**item, "execution_mode": "AFK" if item["execution_mode"] == "HITL" else "HITL"})
        with patch("tracker_contract.render_issue", side_effect=wrong_mode):
            with self.assertRaisesRegex(ContractError, "execution mode"):
                stage_native_tracker(self.root / "wrong", result, approved_spec=self.spec)

    def test_staging_rejects_wrong_or_missing_approved_wide_refactor_phase(self):
        result = self.write_proposal(wide_proposal(self.spec))
        for item in result["tickets"]:
            phase_line = f"wide_refactor_phase: {item['wide_refactor']['phase']}\n"
            for kind, replacement in (("wrong", "wide_refactor_phase: integration\n"), ("missing", "")):
                with self.subTest(issue=item["id"], kind=kind):
                    def changed_phase(rendered):
                        text = render_issue(rendered)
                        return text.replace(phase_line, replacement) if rendered["id"] == item["id"] else text
                    with patch("tracker_contract.render_issue", side_effect=changed_phase):
                        with self.assertRaisesRegex(
                            ContractError, rf"{item['id']}-.*\.md.*wide_refactor_phase.*approved"
                        ):
                            stage_native_tracker(
                                self.root / f"{item['id']}-{kind}", result, approved_spec=self.spec
                            )

    def test_staging_accepts_padded_approved_wide_refactor_phase(self):
        data = wide_proposal(self.spec)
        data["tickets"][0]["wide_refactor"]["phase"] = " expand "
        result = self.write_proposal(data)
        self.assertEqual(result["tickets"][0]["wide_refactor"]["phase"], "expand")
        stage_native_tracker(self.root / "padded", result, approved_spec=self.spec)

    def test_unrecorded_staging_checks_approved_wide_refactor_phase_through_cli(self):
        from test_planning_flow import PlanningFlow, file_contents
        flow = PlanningFlow()
        flow.setUp()
        try:
            original_handoff = flow.write_tickets_handoff
            def handoff():
                state = json.loads((flow.run_dir / "state.json").read_text())
                return original_handoff(data=wide_proposal(Path(state["approved_spec"]["path"])))
            with patch.object(flow, "write_tickets_handoff", side_effect=handoff):
                result = flow.reach_ticket_approval()
            state = json.loads((flow.run_dir / "state.json").read_text())
            self.assertIsNone(state["staged_tracker"])
            staged = flow.run_dir / "publication-stage"
            stage_native_tracker(staged, result, approved_spec=Path(state["approved_spec"]["path"]))
            issue = next((staged / "issues").glob("ISSUE-001-*.md"))
            original = issue.read_text()
            target = flow.repo / "trackers" / result["tracker"]["slug"]
            # Failing kinds leave the run untouched, so they share one flow; the correct kind approves and runs last.
            for kind, replacement in (
                ("wrong", "wide_refactor_phase: migrate\n"), ("missing", ""), ("correct", "wide_refactor_phase: expand\n")
            ):
                with self.subTest(kind=kind):
                    issue.write_text(original.replace("wide_refactor_phase: expand\n", replacement))
                    staged_bytes = file_contents(staged)
                    approved = flow.ticket_approval("approve", "Check recovered phase", target=target)
                    if kind == "correct":
                        self.assertEqual(approved.returncode, 0, approved.stderr)
                    else:
                        self.assertNotEqual(approved.returncode, 0)
                        self.assertIn(issue.name, approved.stderr)
                        self.assertIn("wide_refactor_phase differs from approved", approved.stderr)
                        state = json.loads((flow.run_dir / "state.json").read_text())
                        self.assertEqual(state["current_stage"], "awaiting-ticket-approval")
                        self.assertIsNone(state["staged_tracker"])
                    self.assertFalse(target.exists())
                    self.assertEqual(staged_bytes, file_contents(staged))
        finally:
            flow.tearDown()

    def test_v1_and_v2_afk_produce_identical_output_bytes(self):
        expected = {
            "issues/ISSUE-001-deliver-the-first-behavior.md": "ed218d536cf5cff0311b9c3cc4deb6196b60051d5fd900f86ffdced242da8549",
            "issues/ISSUE-002-build-on-the-first-behavior.md": "c783d7ab1fa2266f6354bd88aefb6d89404b4de59c5f14237e6661bcb9bc85c0",
            "README.md": "38c03ed4f45ef2b4e454c1305cd3678166ed561670b7f96b3dec857fc64eb764",
            "decisions.md": "507553905fec583977cbea80d9a4c6189e2a802548d0669b44150327156e1e11",
            "map.md": "024bade90da167b05576bba1ea9f71f47984d75ed63a817541f601ebbad080fc",
            "spec.md": "a3f72996485006dfb58fedda12d240b07c5a6afa8657dda64f91b648fff0f80d",
        }
        for version in (1, 2):
            data = proposal(self.spec)
            data["schema_version"] = version
            if version == 2:
                for item in data["tickets"]:
                    item["execution_mode"] = "AFK"
            result = self.write_proposal(data)
            native = stage_native_tracker(self.root / str(version), result, approved_spec=self.spec)
            self.assertEqual(native["artifacts"], expected)

    def test_unrecorded_staging_rejects_wrong_or_missing_approved_slice_type(self):
        from test_planning_flow import PlanningFlow
        for kind in ("wrong", "missing"):
            with self.subTest(kind=kind):
                flow = PlanningFlow()
                flow.setUp()
                try:
                    result = flow.reach_ticket_approval()
                    state = json.loads((flow.run_dir / "state.json").read_text())
                    self.assertIsNone(state["staged_tracker"])
                    staged = flow.run_dir / "publication-stage"
                    stage_native_tracker(staged, result, approved_spec=Path(state["approved_spec"]["path"]))
                    issue = next((staged / "issues").glob("ISSUE-001-*.md"))
                    original = issue.read_text()
                    self.assertIn("slice_type: vertical\n", original)
                    replacement = "slice_type: prefactor\n" if kind == "wrong" else ""
                    issue.write_text(original.replace("slice_type: vertical\n", replacement))
                    target = flow.repo / "trackers" / result["tracker"]["slug"]
                    approved = flow.ticket_approval("approve", "Check recovered slice type", target=target)
                    self.assertNotEqual(approved.returncode, 0)
                    self.assertIn(issue.name, approved.stderr)
                    self.assertIn("slice type differs from approved", approved.stderr)
                    self.assertFalse(target.exists())
                    self.assertTrue(staged.exists())
                    state = json.loads((flow.run_dir / "state.json").read_text())
                    self.assertEqual(state["current_stage"], "awaiting-ticket-approval")
                finally:
                    flow.tearDown()

    def test_v1_and_mixed_v2_approval_publish_unchanged_through_cli(self):
        # Reuse the real CLI lifecycle fixture without inheriting its unrelated tests.
        from test_planning_flow import PlanningFlow, STATE
        for version in (1, 2):
            with self.subTest(version=version):
                flow = PlanningFlow()
                flow.setUp()
                try:
                    original = flow.write_tickets_handoff
                    def handoff():
                        state = json.loads((flow.run_dir / "state.json").read_text())
                        spec = Path(state["approved_spec"]["path"])
                        return original(data=mixed_proposal(spec) if version == 2 else proposal(spec))
                    with patch.object(flow, "write_tickets_handoff", side_effect=handoff):
                        result = flow.reach_ticket_approval()
                    target = flow.repo / "trackers" / result["tracker"]["slug"]
                    approved = flow.ticket_approval("approve", "Approve mixed tracker", target=target)
                    self.assertEqual(approved.returncode, 0, approved.stderr)
                    state = json.loads((flow.run_dir / "state.json").read_text())
                    staged = Path(state["staged_tracker"]["path"])
                    before = {str(p.relative_to(staged)): p.read_bytes() for p in staged.rglob("*") if p.is_file()}
                    published = flow.cli(STATE, "publish", "--run-dir", str(flow.run_dir))
                    self.assertEqual(published.returncode, 0, published.stderr)
                    self.assertEqual(before, {str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()})
                    for item in result["tickets"]:
                        self.assertEqual(next((target / "issues").glob(item["id"] + "-*.md")).read_text(), render_issue(item))
                finally:
                    flow.tearDown()

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

    def test_readme_uses_neutral_canonical_command_label(self):
        result = self.write_proposal()
        readme = render_readme(result)
        self.assertIn(
            "- Canonical check commands:\n  - `python3 -m unittest discover -s tests`\n",
            readme,
        )
        self.assertNotIn("run as the baseline suite", readme)

    def check_native_readme(self, tracker: Path, command_rules: str) -> subprocess.CompletedProcess:
        (tracker / "README.md").write_text(
            f"# Tracker\n\n## Ground rules\n\n- Working branch: `main`\n{command_rules}",
            encoding="utf-8",
        )
        return self.contract_cli("native-tracker", str(tracker))

    def test_native_readme_accepts_legacy_neutral_and_targeted_forms(self):
        tracker = self.root / "planned-feature"
        stage_native_tracker(tracker, self.write_proposal(), approved_spec=self.spec)
        for label, extra in (
            ("Canonical check commands, run as the baseline suite by every worker", ""),
            ("Canonical check commands", ""),
            ("Canonical check commands", "\n- Targeted check commands for implement, simplify, and review:\n  - `python3 -m unittest tests.test_cli`\n"),
        ):
            with self.subTest(label=label, targeted=bool(extra)):
                checked = self.check_native_readme(
                    tracker, f"- {label}:\n  - `python3 -m unittest discover -s tests`\n{extra}"
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_native_readme_rejects_missing_runnable_canonical_command(self):
        tracker = self.root / "planned-feature"
        stage_native_tracker(tracker, self.write_proposal(), approved_spec=self.spec)
        for commands, extra in (
            ("", ""),
            ("  - `   `\n", ""),
            ("  - `<TODO: canonical test command>`\n", ""),
            ("", "- Targeted check commands for implement, simplify, and review:\n  - `python3 -m unittest tests.test_cli`\n"),
            ("", "\n## Notes\n\n  - `python3 -m unittest discover -s tests`\n"),
        ):
            with self.subTest(commands=commands, extra=extra):
                checked = self.check_native_readme(tracker, f"- Canonical check commands:\n{commands}{extra}")
                self.assertNotEqual(checked.returncode, 0)
                self.assertIn("no runnable canonical check command", checked.stderr)

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
