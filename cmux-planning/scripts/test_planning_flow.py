#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from spec_contract import validate_spec  # noqa: E402
from test_spec_contract import review_report, spec  # noqa: E402
from test_tracker_contract import proposal as tracker_proposal  # noqa: E402
from tracker_contract import render_summary, validate_proposal  # noqa: E402
from tree_integrity import capture_tree, compare_tree  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
AGENTS = SCRIPT_DIR / "agents_config.py"
STATE = SCRIPT_DIR / "planning_state.py"
RENDER = SCRIPT_DIR / "render_prompt.py"
TREE = SCRIPT_DIR / "tree_integrity.py"
PANE = SCRIPT_DIR / "pane_ctl.py"
AWAIT = SCRIPT_DIR / "await_report.py"

FAKE_HARNESS = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
program = os.path.basename(sys.argv[0])
if args == ["--version"]:
    print(program + " 99-test")
elif args == ["--help"]:
    print("--model --sandbox --config --ask-for-approval --effort login auth")
    print("--safe-mode --print --no-session-persistence --permission-mode --tools")
elif args in (["login", "--help"], ["auth", "--help"]):
    print("status")
elif args in (["login", "status"], ["auth", "status"]):
    print("authenticated")
elif args == ["exec", "--help"]:
    print("--ephemeral --skip-git-repo-check --sandbox --model --config")
else:
    raise SystemExit("unexpected harness call: " + repr(args))
'''

FAKE_CMUX = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_CMUX_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if "new-split" in sys.argv:
    print(json.dumps({"surface_id": "SURF-1", "surface_ref": "surface:1", "pane_id": "PANE-1"}))
elif "surface-health" in sys.argv:
    print(json.dumps({"surfaces": [{"id": "SURF-1", "ref": "surface:1", "type": "terminal"}]}))
elif "read-screen" in sys.argv:
    print("worker screen")
else:
    print("OK")
'''


class PlanningFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "product.txt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "product.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "init"], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("claude", "codex"):
            path = self.bin / name
            path.write_text(FAKE_HARNESS, encoding="utf-8")
            path.chmod(0o755)
        self.cmux = self.root / "cmux"
        self.cmux.write_text(FAKE_CMUX, encoding="utf-8")
        self.cmux.chmod(0o755)
        self.cmux_log = self.root / "cmux.log"
        self.config = self.repo / ".scratch" / "orchestrator" / "agents.json"
        initialized = self.cli(AGENTS, "init", "--config", str(self.config))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.runs = self.repo / ".scratch" / "orchestrator" / "planning-runs"
        self.run_dir = self.runs / "plan-test"

    def tearDown(self):
        self.temp.cleanup()

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_CMUX_LOG": str(self.cmux_log),
        }

    def cli(self, script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.repo,
            env=env or self.env(),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def init_direct(self, run_id: str = "plan-test") -> subprocess.CompletedProcess[str]:
        return self.cli(
            STATE,
            "init",
            "--task",
            "Bitte sichere Planung erstellen.",
            "--repo",
            str(self.repo),
            "--run-id",
            run_id,
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )

    def render_and_baseline(self, stage: str, pass_num: int = 1, run_dir: Path | None = None) -> None:
        selected = run_dir or self.run_dir
        rendered = self.cli(RENDER, "--run-dir", str(selected), "--stage", stage, "--pass", str(pass_num))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        baseline = self.cli(TREE, "baseline", "--run-dir", str(selected), "--stage", stage, "--pass", str(pass_num))
        self.assertEqual(baseline.returncode, 0, baseline.stderr)

    def write_author_handoff(self, pass_num: int = 1, run_dir: Path | None = None) -> Path:
        selected = run_dir or self.run_dir
        draft = selected / "artifacts" / f"spec-{pass_num}.md"
        draft.write_text(spec(), encoding="utf-8")
        report = selected / "reports" / f"spec-{pass_num}.md"
        report.write_text(
            f"""## Result
PASS

## Repository Sources / Methods
- `product.txt`: existing repository behavior inspected

## Proposed Test Seams
- dependency-free CLI integration test

## Blockers
- None

## Plan Drift
- None

## Draft Path
`{draft.resolve()}`
""",
            encoding="utf-8",
        )
        return draft

    def approve_spec_to_tickets(self) -> Path:
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        self.assertEqual(
            self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode, 0
        )
        self.render_and_baseline("spec-review")
        digest = validate_spec(draft)["sha256"]
        (self.run_dir / "reports" / "spec-review-1.md").write_text(
            review_report("pass", digest, digest), encoding="utf-8"
        )
        self.assertEqual(
            self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir)).returncode, 0
        )
        approved = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Approved after independent review",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "tickets")
        self.assertEqual(state["prepared_stage"]["stage"], "tickets")
        return draft

    def write_tickets_handoff(self, pass_num: int = 1, *, data: dict | None = None) -> dict:
        state = json.loads((self.run_dir / "state.json").read_text())
        spec_path = Path(state["approved_spec"]["path"])
        proposal_path = self.run_dir / "artifacts" / f"tickets-{pass_num}.json"
        proposal_path.write_text(
            json.dumps(data or tracker_proposal(spec_path), indent=2) + "\n", encoding="utf-8"
        )
        result = validate_proposal(proposal_path)
        summary = self.run_dir / "artifacts" / f"tickets-{pass_num}.md"
        summary.write_text(render_summary(result), encoding="utf-8")
        report = self.run_dir / "reports" / f"tickets-{pass_num}.md"
        frontier = "\n".join(f"- {issue_id}" for issue_id in result["ready_frontier"])
        report.write_text(
            f"""## Result
PASS

## Repository Sources / Methods
- `product.txt`: implementation context inspected

## Source Spec Identity
sha256 {state['approved_spec']['sha256']}

## Ticket Count
{result['ticket_count']}

## Ready Frontier
{frontier}

## Blockers
- None

## Plan Drift
- None

## Proposal Paths
- `{proposal_path.resolve()}`
- `{summary.resolve()}`
""",
            encoding="utf-8",
        )
        return result

    def write_tickets_review(
        self,
        verdict: str = "pass",
        *,
        resulting_digest: str | None = None,
        corrections: str = "- None",
        blockers: str = "- None",
    ) -> None:
        state = json.loads((self.run_dir / "state.json").read_text())
        digest = state["author_tickets"]["proposal_sha256"]
        (self.run_dir / "reports" / f"tickets-review-{state['tickets_pass']}.md").write_text(
            f"""## Verdict
{verdict}

## Findings
- None

## Methods
- `product.txt`: independently inspected implementation and tests

## Input Identity
sha256 {digest}

## Resulting Candidate Identity
sha256 {resulting_digest or digest}

## Corrections
{corrections}

## Blockers
{blockers}

## Plan Drift
- None
""",
            encoding="utf-8",
        )

    def launch_prepared_stage(self, stage: str, pass_num: int = 1) -> None:
        def pane(verb: str, *tail: str) -> subprocess.CompletedProcess[str]:
            result = self.cli(
                PANE, "--cmux-cmd", str(self.cmux), verb,
                "--run-dir", str(self.run_dir),
                "--stage", stage, "--pass", str(pass_num), *tail,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result

        surface = json.loads(pane("launch", "--anchor", "CALLER").stdout)["surface_id"]
        pane("start-agent", "--surface", surface, "--settle-seconds", "0")
        pane(
            "deliver",
            "--surface", surface,
            "--prompt", str(self.run_dir / "prompts" / f"{stage}-{pass_num}.md"),
            "--settle-seconds", "0",
        )

    def ticket_approval(
        self, decision: str, reason: str, *, target: Path | None = None, scope: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        args = ["ticket-approval", "--run-dir", str(self.run_dir), "--decision", decision]
        if scope:
            args += ["--scope", scope]
        args += ["--reason", reason]
        if target is not None:
            args += ["--target", str(target)]
        return self.cli(STATE, *args)

    def reach_ticket_approval(self, *, launch_panes: bool = False) -> dict:
        self.approve_spec_to_tickets()
        self.render_and_baseline("tickets")
        author_prompt = (self.run_dir / "prompts" / "tickets-1.md").read_text()
        self.assertIn("small number of cohesive tracer-bullet vertical slices", author_prompt)
        self.assertIn("Never decompose by frontend, backend, database", author_prompt)
        self.assertIn("expand, bounded migrate, and contract", author_prompt)
        self.assertIn("Approved Specification", author_prompt)
        if launch_panes:
            self.launch_prepared_stage("tickets")
        proposal_result = self.write_tickets_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "tickets-review")
        self.assertEqual(state["prepared_stage"]["stage"], "tickets-review")
        self.render_and_baseline("tickets-review")
        reviewer_prompt = (self.run_dir / "prompts" / "tickets-review-1.md").read_text()
        self.assertIn("Harness: codex (Codex is mandatory)", reviewer_prompt)
        self.assertIn(state["author_tickets"]["proposal_sha256"], reviewer_prompt)
        self.assertIn(state["author_tickets"]["summary_sha256"], reviewer_prompt)
        self.assertIn("Do not invent scope", reviewer_prompt)
        if launch_panes:
            self.launch_prepared_stage("tickets-review")
        self.write_tickets_review()
        reviewed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        return proposal_result

    def test_direct_task_runs_end_to_end_through_review_and_explicit_approval(self):
        initialized = self.init_direct()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "spec")
        self.assertEqual((self.run_dir / "task.md").read_text(), "Bitte sichere Planung erstellen.")
        self.assertIsNotNone(state["prepared_stage"])
        self.assertIsNone(state["tree_baseline"])

        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "spec-review")
        snapshot = json.loads((self.run_dir / state["prepared_stage"]["path"]).read_text())
        self.assertEqual(snapshot["selected_worker"]["harness"], "codex")

        self.render_and_baseline("spec-review")
        digest = validate_spec(draft)["sha256"]
        (self.run_dir / "reports" / "spec-review-1.md").write_text(
            review_report("pass", digest, digest), encoding="utf-8"
        )
        reviewed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        self.assertEqual(json.loads((self.run_dir / "state.json").read_text())["current_stage"], "awaiting-spec-approval")
        view = self.cli(STATE, "approval-view", "--run-dir", str(self.run_dir))
        self.assertEqual(view.returncode, 0, view.stderr)
        walkthrough = json.loads(view.stdout)
        self.assertTrue(walkthrough["no_open_decisions"])
        self.assertEqual(walkthrough["diff"], "")

        approved = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Reviewed with no open decisions",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        final = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(final["current_stage"], "tickets")
        self.assertEqual(final["approved_spec"]["sha256"], digest)
        self.assertEqual(final["prepared_stage"]["stage"], "tickets")

    def test_tickets_cannot_prepare_without_same_run_approved_spec(self):
        self.assertEqual(self.init_direct().returncode, 0)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text())
        state["current_stage"] = "tickets"
        state["prepared_stage"] = None
        state_path.write_text(json.dumps(state), encoding="utf-8")

        prepared = self.cli(
            STATE,
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "tickets",
            "--pass",
            "1",
        )

        self.assertNotEqual(prepared.returncode, 0)
        self.assertIn("explicitly approved specification", prepared.stderr)

    def test_complete_ticket_flow_publishes_native_tracker_once(self):
        proposal_result = self.reach_ticket_approval(launch_panes=True)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "awaiting-ticket-approval")
        self.assertIsNone(state["prepared_stage"], "a clean review goes to the human, not another model")
        view = self.cli(STATE, "ticket-approval-view", "--run-dir", str(self.run_dir))
        self.assertEqual(view.returncode, 0, view.stderr)
        walkthrough = json.loads(view.stdout)
        self.assertEqual(walkthrough["ticket_count"], 2)
        self.assertEqual(walkthrough["ready_frontier"], ["ISSUE-001"])
        self.assertEqual(walkthrough["blocking_edges"], [{"blocked": "ISSUE-002", "prerequisite": "ISSUE-001"}])

        target = self.repo / ".scratch" / proposal_result["tracker"]["slug"]
        approved = self.ticket_approval("approve", "Granularity and dependencies approved", target=target)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertFalse(target.exists(), "approval stages but does not partially publish")
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "ready-to-publish")
        self.assertEqual(len(state["staged_tracker"]["artifacts"]), 6)

        published = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertTrue((target / "issues").is_dir())
        final = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(final["current_stage"], "complete")
        self.assertEqual(final["published_tracker"]["ready_frontier"], ["ISSUE-001"])

        duplicate = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("already published", duplicate.stderr)

    def test_safe_ticket_review_fixes_reach_human_without_automatic_re_review(self):
        self.approve_spec_to_tickets()
        self.render_and_baseline("tickets")
        original = self.write_tickets_handoff()
        self.assertEqual(
            self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode, 0
        )
        self.render_and_baseline("tickets-review")
        state = json.loads((self.run_dir / "state.json").read_text())
        corrected = tracker_proposal(Path(state["approved_spec"]["path"]))
        corrected["tickets"][0]["delivered_behavior"] = "The clarified first behavior works"
        candidate = self.run_dir / "artifacts" / "tickets-reviewed-1.json"
        candidate.write_text(json.dumps(corrected, indent=2) + "\n", encoding="utf-8")
        candidate_digest = validate_proposal(candidate)["sha256"]
        self.write_tickets_review(
            "pass_with_fixes",
            resulting_digest=candidate_digest,
            corrections="- Clarified wording already established by the approved specification.",
        )
        accepted = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "awaiting-ticket-approval")
        self.assertIsNone(state["prepared_stage"])
        view = json.loads(
            self.cli(STATE, "ticket-approval-view", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertIn("clarified", view["diff"])
        self.assertNotEqual(original["sha256"], view["candidate_sha256"])

    def test_ticket_revision_preserves_artifacts_and_requires_fresh_review(self):
        self.reach_ticket_approval()
        original = self.run_dir / "artifacts" / "tickets-1.json"
        revised = self.ticket_approval("revise", "Merge the two slices because their verification story is shared")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "tickets")
        self.assertEqual(state["tickets_pass"], 2)
        self.assertTrue(original.is_file())
        self.assertEqual(state["prepared_stage"]["pass"], 2)
        premature = self.ticket_approval("approve", "too soon", target=self.repo / ".scratch" / "planned-feature")
        self.assertNotEqual(premature.returncode, 0)

    def test_blocked_ticket_review_can_roll_back_approved_spec_and_invalidates_proposal(self):
        self.approve_spec_to_tickets()
        self.render_and_baseline("tickets")
        self.write_tickets_handoff()
        self.assertEqual(
            self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode, 0
        )
        self.render_and_baseline("tickets-review")
        self.write_tickets_review(
            "blocked",
            blockers="- The approved specification leaves the rollout behavior undecided.",
        )
        blocked = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        rolled_back = self.ticket_approval("revise", "Resolve rollout behavior in the specification", scope="spec")
        self.assertEqual(rolled_back.returncode, 0, rolled_back.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "spec")
        self.assertEqual(state["spec_pass"], 2)
        self.assertEqual(state["tickets_pass"], 2)
        self.assertIsNone(state["approved_spec"])
        self.assertIsNone(state["author_tickets"])
        self.assertEqual(state["prepared_stage"]["stage"], "spec")

    def test_publication_refuses_collision_escape_and_changed_staging_without_touching_target(self):
        proposal_result = self.reach_ticket_approval()
        slug = proposal_result["tracker"]["slug"]
        collision = self.repo / slug
        collision.mkdir()
        refused = self.ticket_approval("approve", "approve", target=collision)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(list(collision.iterdir()), [])
        escaped = self.ticket_approval("approve", "approve", target=self.repo / ".." / slug)
        self.assertNotEqual(escaped.returncode, 0)

        target = self.repo / ".scratch" / slug
        approved = self.ticket_approval("approve", "approve", target=target)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        staged_spec = self.run_dir / "publication-stage" / "spec.md"
        staged_spec.write_text("tampered\n", encoding="utf-8")
        failed = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(target.exists(), "failed validation must leave the target unchanged")
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "ready-to-publish")
        events = [json.loads(line) for line in (self.run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual(events[-1]["type"], "publication.failed")

    def test_reviewer_cannot_self_certify_a_rewritten_author_draft(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        self.assertEqual(self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode, 0)
        self.render_and_baseline("spec-review")
        draft.write_text(draft.read_text(encoding="utf-8") + "\nReviewer smuggled this in.\n", encoding="utf-8")
        rewritten = validate_spec(draft)["sha256"]
        (self.run_dir / "reports" / "spec-review-1.md").write_text(
            review_report("pass", rewritten, rewritten), encoding="utf-8"
        )

        reviewed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))

        self.assertNotEqual(reviewed.returncode, 0)
        self.assertIn("changed after its own gate", reviewed.stderr)
        self.assertEqual(
            json.loads((self.run_dir / "state.json").read_text())["current_stage"], "spec-review"
        )

    def test_a_second_baseline_cannot_relaunder_an_armed_pass(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        (self.repo / "product.txt").write_text("worker changed product\n", encoding="utf-8")

        again = self.cli(
            TREE, "baseline", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )

        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already has a launch baseline", again.stderr)
        self.write_author_handoff()
        gated = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(gated.returncode, 2, gated.stdout)

    def test_rearming_a_prepared_pass_cannot_adopt_a_worker_delta_as_its_baseline(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        (self.repo / "product.txt").write_text("worker changed product\n", encoding="utf-8")

        # Preparing again mints a fresh snapshot_id and clears tree_baseline, so the
        # same-snapshot guard cannot see the rearm its own message recommends.
        prepared = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        rendered = self.cli(RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        rearmed = self.cli(
            TREE, "baseline", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )

        self.assertNotEqual(rearmed.returncode, 0, rearmed.stdout)
        self.assertIn("already armed against a different working tree", rearmed.stderr)
        self.write_author_handoff()
        self.assertNotEqual(
            self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode,
            0,
            "an unarmed pass must not advance",
        )

    def test_a_committed_worker_edit_does_not_pass_the_integrity_gate(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        (self.repo / "product.txt").write_text("worker changed product\n", encoding="utf-8")
        for argv in (["add", "-A"], ["commit", "-qm", "worker commit"]):
            subprocess.run(["git", "-C", str(self.repo), *argv], check=True)
        self.write_author_handoff()

        gated = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))

        self.assertEqual(gated.returncode, 2, gated.stdout)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "integrity-violation")
        self.assertTrue(state["gate_decisions"][-1]["head_moved"])

    def test_safe_reviewer_fixes_reach_human_without_auto_review_and_revision_requires_new_review(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        self.assertEqual(self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode, 0)
        self.render_and_baseline("spec-review")
        candidate = self.run_dir / "artifacts" / "spec-reviewed-1.md"
        candidate.write_text(spec(solution="Implement the clarified requested workflow."), encoding="utf-8")
        input_digest = validate_spec(draft)["sha256"]
        candidate_digest = validate_spec(candidate)["sha256"]
        (self.run_dir / "reports" / "spec-review-1.md").write_text(
            review_report(
                "pass_with_fixes",
                input_digest,
                candidate_digest,
                corrections="- Clarified wording already established by the task.",
            ),
            encoding="utf-8",
        )
        accepted = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "awaiting-spec-approval")
        self.assertIsNone(state["prepared_stage"], "safe fixes must not trigger automatic re-review")
        view = json.loads(self.cli(STATE, "approval-view", "--run-dir", str(self.run_dir)).stdout)
        self.assertIn("clarified", view["diff"])

        revised = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "revise",
            "--reason",
            "Human requested a product-level revision",
        )
        self.assertEqual(revised.returncode, 0, revised.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "spec")
        self.assertEqual(state["spec_pass"], 2)
        self.assertEqual(state["prepared_stage"]["stage"], "spec")
        self.assertTrue(draft.is_file())
        self.assertTrue(candidate.is_file())
        premature = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "too soon",
        )
        self.assertNotEqual(premature.returncode, 0)

    def test_stage_cannot_launch_before_baseline_then_uses_stable_visible_pane(self):
        self.assertEqual(self.init_direct().returncode, 0)
        blocked = self.cli(
            PANE,
            "--cmux-cmd",
            str(self.cmux),
            "launch",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--anchor",
            "CALLER",
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertFalse(self.cmux_log.exists())
        self.render_and_baseline("spec")
        launched = self.cli(
            PANE,
            "--cmux-cmd",
            str(self.cmux),
            "launch",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--anchor",
            "CALLER",
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        result = json.loads(launched.stdout)
        self.assertEqual(result["surface_id"], "SURF-1")
        self.assertIn("Spec Author 1", result["label"])

    def test_armed_watcher_reports_pane_death_and_existing_handoff(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        dead = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "MISSING", "--cmux-cmd", str(self.cmux),
            "--deadline-minutes", "0.1", "--poll-seconds", "0.01",
        )
        self.assertEqual(dead.returncode, 7, dead.stderr)
        self.assertIn("pane_dead", dead.stdout)
        alive = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-1", "--cmux-cmd", str(self.cmux),
            "--deadline-minutes", "0.02", "--poll-seconds", "0.01",
        )
        self.assertEqual(alive.returncode, 8, alive.stderr)
        self.assertIn("deadline", alive.stdout)
        broken = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-1", "--cmux-cmd", str(self.root / "missing-cmux"),
            "--deadline-minutes", "0.02", "--poll-seconds", "0.01",
        )
        self.assertEqual(broken.returncode, 8, "a broken health command must not end the wait")
        report = self.run_dir / "reports" / "spec-1.md"
        report.write_text("handoff", encoding="utf-8")
        captured = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--deadline-minutes", "0.1", "--poll-seconds", "0.01",
        )
        self.assertEqual(captured.returncode, 0, captured.stderr)
        self.assertIn("outcome=report", captured.stdout)

    def test_unauthorized_tracked_write_gates_hitl_even_with_clean_report(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        self.write_author_handoff()
        (self.repo / "product.txt").write_text("worker changed product\n", encoding="utf-8")
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 2, accepted.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "integrity-violation")
        self.assertIn("product.txt", state["gate_decisions"][-1]["unauthorized_paths"])

    def test_detector_boundary_excludes_ignored_and_baseline_untracked_content(self):
        (self.repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "ignore"], check=True)
        (self.repo / "loose.txt").write_text("before\n", encoding="utf-8")
        before = capture_tree(self.repo)
        (self.repo / "loose.txt").write_text("after\n", encoding="utf-8")
        (self.repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")
        after = capture_tree(self.repo)
        result = compare_tree(before, after, allowed_paths=[])
        self.assertTrue(result["ok"])
        (self.repo / "new.txt").write_text("new path\n", encoding="utf-8")
        changed = compare_tree(before, capture_tree(self.repo), allowed_paths=[])
        self.assertEqual(changed["unauthorized_paths"], ["new.txt"])

    def test_first_use_checkpoint_creates_config_but_no_run_without_acceptance(self):
        fresh_config = self.repo / "other" / "agents.json"
        run_dir = self.runs / "not-created"
        proc = self.cli(
            STATE,
            "init",
            "--task",
            "Task",
            "--repo",
            str(self.repo),
            "--run-id",
            "not-created",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(fresh_config),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(fresh_config.is_file())
        self.assertFalse(run_dir.exists())
        self.assertIn('"planning"', proc.stdout)

    def test_version_one_migration_checkpoint_warns_about_older_sibling_skills(self):
        legacy = json.loads(self.config.read_text(encoding="utf-8"))
        legacy["schema_version"] = 1
        del legacy["workflows"]["planning"]
        legacy_bytes = (json.dumps(legacy, indent=2) + "\n").encode("utf-8")
        self.config.write_bytes(legacy_bytes)
        run_dir = self.runs / "migration-warning"

        proc = self.cli(
            STATE,
            "init",
            "--task",
            "Task",
            "--repo",
            str(self.repo),
            "--run-id",
            "migration-warning",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(run_dir.exists())
        self.assertEqual(self.config.read_bytes(), legacy_bytes)
        self.assertIn('"schema_version": 2', proc.stdout)
        self.assertIn("upgrade all three skills together", proc.stderr.lower())
        self.assertIn("older separately installed", proc.stderr.lower())
        self.assertIn("cmux-grilling", proc.stderr)
        self.assertIn("cmux-issue-chain", proc.stderr)

        accepted = self.cli(
            STATE,
            "init",
            "--task",
            "Task",
            "--repo",
            str(self.repo),
            "--run-id",
            "migration-warning",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
            "--accept-config",
        )

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["schema_version"], 2)
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["configuration_created_or_migrated_and_accepted"])

    def grilling_pair(self) -> tuple[Path, Path]:
        markdown = self.repo / "grilling-result.md"
        artifact = self.repo / "grilling-result.json"
        markdown.write_text(
            """# Result
## Aufgabe
Planung
## Definierte Annahmen
- Eins
- Zwei
- Drei
## Entscheidungen
### D1
Option?
## Prämissen-Korrekturen
- Alte Benennung korrigieren.
""",
            encoding="utf-8",
        )
        artifact.write_text(
            json.dumps(
                {
                    "run_id": "grill-1",
                    "task": "Planung",
                    "codebasePath": str(self.repo),
                    "maxQuestions": 2,
                    "questionsAsked": 1,
                    "stopReason": "griller-done",
                    "qa": [{"answer": "evidence"}],
                    "assumptions": ["Eins", "Zwei", "Drei"],
                    "open_decisions": [
                        {
                            "id": "D1",
                            "question": "Option?",
                            "why_open": "product",
                            "context": "Product choice.",
                            "evidence": ["product.txt:1"],
                            "options": [
                                {"label": "A", "implication": "One"},
                                {"label": "B", "implication": "Two"},
                            ],
                            "recommendation": "A",
                            "rationale": "Existing behavior.",
                            "status": "open",
                        }
                    ],
                    "markdownPath": str(markdown),
                    "jsonPath": str(artifact),
                }
            ),
            encoding="utf-8",
        )
        return artifact, markdown

    def test_grilling_input_requires_revalidation_and_normalizes_every_outcome(self):
        artifact, markdown = self.grilling_pair()
        run_dir = self.runs / "plan-grilling"
        initialized = self.cli(
            STATE, "init", "--task", "Planung",
            "--grilling-json", str(artifact), "--grilling-markdown", str(markdown),
            "--repo", str(self.repo), "--run-id", "plan-grilling",
            "--runs-root", str(self.runs), "--workspace-id", "WORKSPACE-1",
            "--config", str(self.config),
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "awaiting-grilling-revalidation")
        self.assertIsNone(state["prepared_stage"])
        self.assertEqual((run_dir / state["grilling_import"]["copied_json"]).read_bytes(), artifact.read_bytes())
        shown = self.cli(STATE, "show-revalidation", "--run-dir", str(run_dir))
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("not freshness", shown.stdout)
        self.assertIn("Alte Benennung", shown.stdout)

        refused_path = self.root / "refused.json"
        refused_path.write_text('{"accepted": false}', encoding="utf-8")
        refused = self.cli(STATE, "revalidate", "--run-dir", str(run_dir), "--outcomes", str(refused_path))
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertEqual(json.loads((run_dir / "state.json").read_text())["current_stage"], "awaiting-grilling-revalidation")

        outcomes = self.root / "outcomes.json"
        outcomes.write_text(
            json.dumps(
                {
                    "accepted": True,
                    "premise_corrections": [{"index": 1, "outcome": "confirmed", "reason": ""}],
                    "assumptions": [
                        {"index": 1, "outcome": "confirmed", "reason": ""},
                        {"index": 2, "outcome": "corrected", "value": "Zwei korrigiert", "reason": "Current code"},
                        {"index": 3, "outcome": "discarded", "reason": "Outside scope"},
                    ],
                    "decisions": [{"id": "D1", "status": "decided", "decision": "A", "reason": "Human choice"}],
                }
            ),
            encoding="utf-8",
        )
        accepted = self.cli(STATE, "revalidate", "--run-dir", str(run_dir), "--outcomes", str(outcomes))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "spec")
        normalized = json.loads((run_dir / "grilling-input.json").read_text())
        self.assertEqual(normalized["assumptions"][1]["value"], "Zwei korrigiert")
        self.assertIsNone(normalized["assumptions"][2]["value"])
        self.assertEqual(normalized["decisions"][0]["status"], "decided")
        rendered = self.cli(RENDER, "--run-dir", str(run_dir), "--stage", "spec", "--pass", "1")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        prompt = (run_dir / "prompts" / "spec-1.md").read_text()
        self.assertIn("grilling-input.json", prompt)
        self.assertNotIn("inputs/grilling-source.json", prompt)

    def test_invalid_grilling_pair_fails_before_run_or_pane(self):
        artifact, markdown = self.grilling_pair()
        markdown.unlink()
        run_dir = self.runs / "bad-grilling"
        failed = self.cli(
            STATE, "init", "--task", "Planung", "--grilling-json", str(artifact),
            "--repo", str(self.repo), "--run-id", "bad-grilling",
            "--runs-root", str(self.runs), "--workspace-id", "WORKSPACE-1",
            "--config", str(self.config),
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(run_dir.exists())
        self.assertFalse(self.cmux_log.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
