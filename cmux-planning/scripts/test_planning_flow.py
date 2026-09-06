#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import orchestrator_lib  # noqa: E402
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
ISSUE_CHAIN_STATE = SCRIPT_DIR.parents[1] / "cmux-issue-chain" / "scripts" / "run_state.py"

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
    created = {"surface_ref": "surface:1", "pane_id": "PANE-1"}
    if not os.environ.get("FAKE_CMUX_POSITIONAL_ONLY"):
        created["surface_id"] = os.environ.get("FAKE_CMUX_SURFACE", "SURF-1")
    print(json.dumps(created))
elif "surface-health" in sys.argv:
    surfaces = [] if os.environ.get("FAKE_CMUX_DEAD") else [{"id": "SURF-1", "ref": "surface:1", "type": "terminal"}]
    print(json.dumps({"surfaces": surfaces}))
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

    def assign_planning_profile(self, role: str, profile: str) -> None:
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["workflows"]["planning"][role] = profile
        self.config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def decide_diversity(
        self, decision: str, reason: str, *, run_dir: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.cli(
            STATE,
            "diversity-confirmation",
            "--run-dir",
            str(run_dir or self.run_dir),
            "--decision",
            decision,
            "--reason",
            reason,
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
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        approvals = [entry for entry in events if entry.get("type") == "spec.approved"]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(set(approvals[0]), {"time", "type", "message", "data"})
        self.assertEqual(approvals[0]["data"]["sha256"], state["approved_spec"]["sha256"])
        self.assertEqual(approvals[0]["data"]["reason"], "Approved after independent review")
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
        author_snapshot = json.loads(
            (self.run_dir / state["prepared_stage"]["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            author_snapshot["selected_worker"]["argv"],
            [
                "claude", "--model", "fable", "--effort", "high",
                "--permission-mode", "auto",
            ],
        )

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

    def test_spec_author_collision_requires_recorded_confirmation_and_survives_resume(self):
        self.assign_planning_profile("spec", "codex-sol-medium")

        initialized = self.init_direct()

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "spec")
        self.assertIsNone(state["prepared_stage"])
        self.assertFalse(list((self.run_dir / "stage-snapshots").glob("spec-1-*.json")))
        pending = state["diversity_confirmation"]
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(
            pending["author"],
            {
                "role": "planning.spec",
                "profile": "codex-sol-medium",
                "harness": "codex",
                "model": "gpt-5.6-sol",
            },
        )
        self.assertEqual(
            pending["reviewer"],
            {
                "role": "planning.reviewer",
                "profile": "codex-sol-xhigh",
                "harness": "codex",
                "model": "gpt-5.6-sol",
            },
        )
        for value in (
            "planning.spec",
            "planning.reviewer",
            "codex-sol-medium",
            "codex-sol-xhigh",
            "codex",
            "gpt-5.6-sol",
        ):
            self.assertIn(value, initialized.stdout)

        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(status["classification"], "pending-diversity-confirmation")
        self.assertEqual(
            status["recommended_next"]["command"],
            status["diversity_confirmation"]["confirmation_command"],
        )
        self.assertIn("diversity-confirmation", status["recommended_next"]["command"])
        self.assertIn("--decision confirm", status["recommended_next"]["command"])
        blocked_launch = self.cli(
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
        self.assertNotEqual(blocked_launch.returncode, 0)
        self.assertIn("no matching prepared stage snapshot", blocked_launch.stderr)

        confirmed = self.decide_diversity(
            "confirm", "Only Codex capacity is currently available"
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        confirmed_state = json.loads(
            (self.run_dir / "state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(confirmed_state["diversity_confirmation"]["status"], "confirmed")
        self.assertEqual(
            confirmed_state["diversity_confirmation"]["reason"],
            "Only Codex capacity is currently available",
        )
        self.assertEqual(confirmed_state["prepared_stage"]["stage"], "spec")
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        confirmation = [event for event in events if event["type"] == "diversity.confirmed"]
        self.assertEqual(len(confirmation), 1)
        self.assertEqual(
            confirmation[0]["data"]["reason"],
            "Only Codex capacity is currently available",
        )

        resumed = self.cli(STATE, "resume", "--run-dir", str(self.run_dir))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["classification"], "spec-authoring")
        prepared_again = self.cli(
            STATE,
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
        )
        self.assertEqual(prepared_again.returncode, 0, prepared_again.stderr)
        self.assertIn('"stage": "spec"', prepared_again.stdout)
        self.render_and_baseline("spec")
        self.launch_prepared_stage("spec")

    def test_refusing_spec_author_collision_preserves_stage_and_configuration_guidance(self):
        self.assign_planning_profile("spec", "codex-sol-xhigh")
        self.assertEqual(self.init_direct().returncode, 0)

        refused = self.decide_diversity(
            "refuse", "Wait until the independent provider is available"
        )

        self.assertEqual(refused.returncode, 2, refused.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "spec")
        self.assertIsNone(state["prepared_stage"])
        self.assertEqual(state["diversity_confirmation"]["status"], "refused")
        self.assertEqual(
            state["diversity_confirmation"]["reason"],
            "Wait until the independent provider is available",
        )
        self.assertIn(str(self.config.resolve()), refused.stdout)
        self.assertIn("planning.spec", refused.stdout)
        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(status["classification"], "pending-diversity-confirmation")
        self.assertEqual(status["diversity_confirmation"]["status"], "refused")

    def test_refusing_a_changed_diverse_resolution_records_it_without_preparing(self):
        self.assign_planning_profile("spec", "codex-sol-xhigh")
        self.assertEqual(self.init_direct().returncode, 0)
        self.assign_planning_profile("spec", "claude-fable-high")

        refused = self.decide_diversity("refuse", "Do not launch before an independent check")

        self.assertEqual(refused.returncode, 2, refused.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "spec")
        self.assertIsNone(state["prepared_stage"])
        self.assertIsNone(state["diversity_confirmation"])
        self.assertEqual(
            [entry["status"] for entry in state["diversity_confirmation_history"]],
            ["invalidated", "refused"],
        )
        self.assertEqual(
            state["diversity_confirmation_history"][-1]["reason"],
            "Do not launch before an independent check",
        )
        self.assertIn(str(self.config.resolve()), refused.stdout)
        self.assertIn("planning.spec", refused.stdout)
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len([event for event in events if event["type"] == "diversity.refused"]), 1)
        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(status["classification"], "spec-authoring")

        prepared = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(
            json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))["prepared_stage"][
                "stage"
            ],
            "spec",
        )

    def test_refusing_a_changed_still_colliding_resolution_records_the_fresh_combination(self):
        self.assign_planning_profile("spec", "codex-sol-xhigh")
        self.assertEqual(self.init_direct().returncode, 0)
        first = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
            "diversity_confirmation"
        ]
        self.assign_planning_profile("spec", "codex-luna-medium")
        self.assign_planning_profile("reviewer", "codex-luna-medium")

        refused = self.decide_diversity("refuse", "No independent reviewer is reachable today")

        self.assertEqual(refused.returncode, 2, refused.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["prepared_stage"])
        record = state["diversity_confirmation"]
        self.assertEqual(record["status"], "refused")
        self.assertNotEqual(record["combination_id"], first["combination_id"])
        self.assertEqual(record["author"]["model"], "gpt-5.6-luna")
        self.assertEqual(record["reason"], "No independent reviewer is reachable today")
        self.assertEqual(
            [entry["status"] for entry in state["diversity_confirmation_history"]], ["invalidated"]
        )
        self.assertIn(str(self.config.resolve()), refused.stdout)

    def test_one_confirmation_covers_both_author_stages_for_the_same_combination(self):
        self.assign_planning_profile("spec", "codex-sol-xhigh")
        self.assign_planning_profile("tickets", "codex-sol-xhigh")
        self.assertEqual(self.init_direct().returncode, 0)
        self.assertEqual(
            self.decide_diversity(
                "confirm", "One provider is available for this complete planning run"
            ).returncode,
            0,
        )
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
            "Specification approved",
        )

        self.assertEqual(approved.returncode, 0, approved.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "tickets")
        self.assertEqual(state["prepared_stage"]["stage"], "tickets")
        self.assertEqual(state["diversity_confirmation"]["status"], "confirmed")
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            len([event for event in events if event["type"] == "diversity.confirmed"]),
            1,
        )
        self.assertEqual(
            len([event for event in events if event["type"] == "diversity.confirmation_required"]),
            1,
        )

    def test_tickets_author_collision_is_gated_before_its_snapshot(self):
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
        self.assign_planning_profile("tickets", "codex-sol-xhigh")

        approved = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Specification approved",
        )

        self.assertEqual(approved.returncode, 0, approved.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "tickets")
        self.assertIsNone(state["prepared_stage"])
        self.assertEqual(state["diversity_confirmation"]["author"]["role"], "planning.tickets")
        self.assertFalse(list((self.run_dir / "stage-snapshots").glob("tickets-1-*.json")))
        self.assertIn("planning.tickets", approved.stdout)

        confirmed = self.decide_diversity(
            "confirm", "The alternate provider quota is exhausted"
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        prepared = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
            "prepared_stage"
        ]
        self.assertEqual(prepared["stage"], "tickets")

    def test_changed_collision_resolution_invalidates_confirmation_and_asks_again(self):
        self.assign_planning_profile("spec", "codex-sol-xhigh")
        self.assertEqual(self.init_direct().returncode, 0)
        self.assertEqual(
            self.decide_diversity("confirm", "Temporary single-model operation").returncode,
            0,
        )
        first = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
            "diversity_confirmation"
        ]
        self.assign_planning_profile("spec", "codex-luna-medium")
        self.assign_planning_profile("reviewer", "codex-luna-medium")

        prepared = self.cli(
            STATE,
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
        )

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        changed = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(changed["prepared_stage"])
        self.assertEqual(changed["diversity_confirmation"]["status"], "pending")
        self.assertNotEqual(
            changed["diversity_confirmation"]["combination_id"], first["combination_id"]
        )
        self.assertEqual(changed["diversity_confirmation"]["author"]["model"], "gpt-5.6-luna")
        self.assertEqual(len(changed["diversity_confirmation_history"]), 1)
        self.assertEqual(
            changed["diversity_confirmation_history"][0]["status"], "invalidated"
        )

    def test_diverse_author_and_reviewer_prepare_without_confirmation(self):
        initialized = self.init_direct()

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(state["prepared_stage"])
        self.assertIsNone(state["diversity_confirmation"])
        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(status["classification"], "spec-authoring")
        self.assertIsNone(status["diversity_confirmation"])

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
        interrupted = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(interrupted["classification"], "awaiting-ticket-approval")
        self.assertIn("ticket-approval-view", interrupted["recommended_next"]["command"])
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
        reviewed_before_revision = json.loads(
            (self.run_dir / "state.json").read_text(encoding="utf-8")
        )["reviewed_tickets"]
        original = self.run_dir / "artifacts" / "tickets-1.json"
        revised = self.ticket_approval("revise", "Merge the two slices because their verification story is shared")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "tickets")
        self.assertEqual(state["tickets_pass"], 2)
        self.assertTrue(original.is_file())
        self.assertEqual(state["prepared_stage"]["pass"], 2)
        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(status["classification"], "requested-revision")
        self.assertEqual(
            status["latest_review"]["candidate_sha256"],
            reviewed_before_revision["candidate_sha256"],
        )
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
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        canonical_stage = Path(state["staged_tracker"]["path"])
        external_stage = self.root / "external-publication-stage"
        os.rename(canonical_stage, external_stage)
        state["staged_tracker"]["path"] = str(external_stage)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        unsafe = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertNotEqual(unsafe.returncode, 0)
        self.assertIn("outside the planning run's staging area", unsafe.stderr)
        self.assertTrue(external_stage.is_dir())
        self.assertFalse(target.exists())
        os.rename(external_stage, canonical_stage)
        state["staged_tracker"]["path"] = str(canonical_stage)
        state_path.write_text(json.dumps(state), encoding="utf-8")
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
        interrupted = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(interrupted["classification"], "awaiting-spec-approval")
        self.assertEqual(interrupted["latest_review"]["candidate_sha256"], candidate_digest)
        self.assertIn("approval-view", interrupted["recommended_next"]["command"])
        self.assertEqual(
            json.loads(self.cli(STATE, "approval-view", "--run-dir", str(self.run_dir)).stdout)[
                "candidate_sha256"
            ],
            candidate_digest,
        )

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
        revision_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(revision_status["classification"], "requested-revision")
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
        self.assertEqual(result["surface_ref"], "surface:1")
        self.assertIn("Spec Author 1", result["label"])

    def test_launch_refuses_to_record_a_positional_ref_as_the_stable_identity(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        env = self.env()
        env["FAKE_CMUX_POSITIONAL_ONLY"] = "1"
        launched = self.cli(
            PANE,
            "--cmux-cmd", str(self.cmux),
            "launch",
            "--run-dir", str(self.run_dir),
            "--stage", "spec",
            "--pass", "1",
            "--anchor", "CALLER",
            env=env,
        )
        self.assertNotEqual(launched.returncode, 0)
        self.assertIn("stable surface identity", launched.stderr)
        calls = [json.loads(line) for line in self.cmux_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 1)
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertNotIn("pane.launched", [event["type"] for event in events])

    def test_pane_commands_reject_positional_surface_before_any_cmux_call(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        launched = self.cli(
            PANE,
            "--cmux-cmd", str(self.cmux),
            "launch",
            "--run-dir", str(self.run_dir),
            "--stage", "spec",
            "--pass", "1",
            "--anchor", "CALLER",
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        cmux_before = self.cmux_log.read_text(encoding="utf-8")
        events_before = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        prompt = str(self.run_dir / "prompts" / "spec-1.md")
        commands = (
            ("start-agent", "--settle-seconds", "0"),
            ("deliver", "--prompt", prompt, "--settle-seconds", "0"),
            ("mark-started",),
            ("close",),
        )
        for command in commands:
            with self.subTest(command=command[0]):
                result = self.cli(
                    PANE,
                    "--cmux-cmd", str(self.cmux),
                    command[0],
                    "--run-dir", str(self.run_dir),
                    "--stage", "spec",
                    "--pass", "1",
                    "--surface", "surface:1",
                    *command[1:],
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SURF-1", result.stderr)
                self.assertEqual(self.cmux_log.read_text(encoding="utf-8"), cmux_before)
                self.assertEqual(
                    (self.run_dir / "events.jsonl").read_text(encoding="utf-8"),
                    events_before,
                )

    def test_close_closes_surface_and_records_enveloped_pane_closed_event(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        self.launch_prepared_stage("spec")
        closed = self.cli(
            PANE, "--cmux-cmd", str(self.cmux), "close",
            "--run-dir", str(self.run_dir),
            "--stage", "spec", "--pass", "1", "--surface", "SURF-1",
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        calls = [json.loads(line) for line in self.cmux_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            calls[-1],
            ["close-surface", "--workspace", "WORKSPACE-1", "--surface", "SURF-1"],
        )
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(events[-1]["type"], "pane.closed")
        self.assertEqual(set(events[-1]), {"time", "type", "message", "data"})
        self.assertEqual(
            events[-1]["data"], {"stage": "spec", "pass": 1, "surface_id": "SURF-1"}
        )

    def test_close_reaches_a_pane_orphaned_by_a_retried_launch(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        self.launch_prepared_stage("spec")
        retried_env = self.env()
        retried_env["FAKE_CMUX_SURFACE"] = "SURF-2"
        relaunched = self.cli(
            PANE, "--cmux-cmd", str(self.cmux), "launch",
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--anchor", "CALLER", env=retried_env,
        )
        self.assertEqual(relaunched.returncode, 0, relaunched.stderr)
        # Work verbs stay bound to the newest launch, and name it in the error.
        stale_work = self.cli(
            PANE, "--cmux-cmd", str(self.cmux), "start-agent",
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-1", "--settle-seconds", "0",
        )
        self.assertNotEqual(stale_work.returncode, 0)
        self.assertIn("SURF-2", stale_work.stderr)
        cmux_before = self.cmux_log.read_text(encoding="utf-8")
        unknown = self.cli(
            PANE, "--cmux-cmd", str(self.cmux), "close",
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-9",
        )
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("SURF-1", unknown.stderr)
        self.assertIn("SURF-2", unknown.stderr)
        self.assertEqual(self.cmux_log.read_text(encoding="utf-8"), cmux_before)
        orphan = self.cli(
            PANE, "--cmux-cmd", str(self.cmux), "close",
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-1",
        )
        self.assertEqual(orphan.returncode, 0, orphan.stderr)
        calls = [json.loads(line) for line in self.cmux_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            calls[-1], ["close-surface", "--workspace", "WORKSPACE-1", "--surface", "SURF-1"]
        )
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(events[-1]["type"], "pane.closed")
        self.assertEqual(events[-1]["data"]["surface_id"], "SURF-1")

    def test_armed_watcher_reports_pane_death_and_existing_handoff(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        launched = self.cli(
            PANE, "--cmux-cmd", str(self.cmux), "launch",
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--anchor", "CALLER",
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        cmux_before = self.cmux_log.read_text(encoding="utf-8")
        events_before = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        mismatched = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "surface:1", "--cmux-cmd", str(self.cmux),
            "--deadline-minutes", "0.1", "--poll-seconds", "0.01",
        )
        self.assertEqual(mismatched.returncode, 1)
        self.assertIn("SURF-1", mismatched.stderr)
        self.assertEqual(self.cmux_log.read_text(encoding="utf-8"), cmux_before)
        self.assertEqual(
            (self.run_dir / "events.jsonl").read_text(encoding="utf-8"), events_before
        )
        dead_env = self.env()
        dead_env["FAKE_CMUX_DEAD"] = "1"
        dead = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-1", "--cmux-cmd", str(self.cmux),
            "--deadline-minutes", "0.1", "--poll-seconds", "0.01",
            env=dead_env,
        )
        self.assertEqual(dead.returncode, 7, dead.stderr)
        self.assertIn("pane_dead", dead.stdout)
        dead_event = json.loads(
            (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertEqual(dead_event["data"]["surface_id"], "SURF-1")
        waiting_before = len(
            (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        )
        alive = self.cli(
            AWAIT,
            "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1",
            "--surface", "SURF-1", "--cmux-cmd", str(self.cmux),
            "--deadline-minutes", "0.02", "--poll-seconds", "0.01",
            "--heartbeat-seconds", "0.001",
        )
        self.assertEqual(alive.returncode, 8, alive.stderr)
        self.assertIn("deadline", alive.stdout)
        waiting_events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[waiting_before:]
        ]
        self.assertTrue(any(event["data"]["outcome"] == "pending" for event in waiting_events))
        self.assertEqual({event["data"]["surface_id"] for event in waiting_events}, {"SURF-1"})
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
            "--surface", "SURF-1",
            "--deadline-minutes", "0.1", "--poll-seconds", "0.01",
        )
        self.assertEqual(captured.returncode, 0, captured.stderr)
        self.assertIn("outcome=report", captured.stdout)
        capture_event = json.loads(
            (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertEqual(
            capture_event["data"]["report_sha256"], hashlib.sha256(report.read_bytes()).hexdigest()
        )
        captured_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertTrue(captured_status["report"]["ready"])
        self.assertIn("accept-author", captured_status["recommended_next"]["command"])
        report.write_text("changed after capture\n", encoding="utf-8")
        changed_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(changed_status["classification"], "inconsistent")

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
        before_path = self.run_dir / "tree-snapshots" / "spec-1-before.json"
        before_bytes = before_path.read_bytes()
        before_path.write_text("{}\n", encoding="utf-8")
        unsafe_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(unsafe_status["classification"], "inconsistent")
        tampered = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "Must not trust a changed launch baseline",
        )
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("baseline is missing or changed", tampered.stderr)
        before_path.write_bytes(before_bytes)
        unresolved = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "Human requested a clean recovery pass",
        )
        self.assertNotEqual(unresolved.returncode, 0)
        self.assertIn("restore the armed baseline", unresolved.stderr)
        (self.repo / "product.txt").write_text("baseline\n", encoding="utf-8")
        resumed = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "Human resolved the unauthorized change",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        recovered = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(recovered["current_stage"], "spec")
        self.assertEqual(recovered["spec_pass"], 2)

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

    def test_new_run_persists_only_the_creation_and_acceptance_state(self):
        fresh_config = self.repo / "new-config" / "agents.json"
        run_dir = self.runs / "created-config"

        initialized = self.cli(
            STATE,
            "init",
            "--task",
            "Task",
            "--repo",
            str(self.repo),
            "--run-id",
            "created-config",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(fresh_config),
            "--accept-config",
        )

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["configuration_created_and_accepted"])
        self.assertNotIn("configuration_created_or_migrated_and_accepted", state)

    def test_legacy_only_state_remains_resumable_without_rewriting_its_bytes(self):
        initialized = self.init_direct()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        recorded = state.pop("configuration_created_and_accepted")
        state["configuration_created_or_migrated_and_accepted"] = recorded
        legacy_bytes = (json.dumps(state, indent=3, sort_keys=False) + "\n").encode("utf-8")
        state_path.write_bytes(legacy_bytes)

        for command in ("status", "context", "resume"):
            with self.subTest(command=command):
                inspected = self.cli(STATE, command, "--run-dir", str(self.run_dir))
                self.assertEqual(inspected.returncode, 0, inspected.stderr)
                self.assertEqual(state_path.read_bytes(), legacy_bytes)

    def test_matching_dual_configuration_state_is_compatible_and_not_rewritten(self):
        initialized = self.init_direct()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["configuration_created_or_migrated_and_accepted"] = state[
            "configuration_created_and_accepted"
        ]
        dual_bytes = (json.dumps(state, indent=4, sort_keys=False) + "\n").encode("utf-8")
        state_path.write_bytes(dual_bytes)

        resumed = self.cli(STATE, "resume", "--run-dir", str(self.run_dir))

        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(state_path.read_bytes(), dual_bytes)

    def test_conflicting_dual_configuration_state_is_refused_actionably(self):
        initialized = self.init_direct()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["configuration_created_or_migrated_and_accepted"] = not state[
            "configuration_created_and_accepted"
        ]
        conflicting_bytes = (json.dumps(state, indent=2) + "\n").encode("utf-8")
        state_path.write_bytes(conflicting_bytes)

        for command in ("status", "context", "resume"):
            with self.subTest(command=command):
                refused = self.cli(STATE, command, "--run-dir", str(self.run_dir))
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("conflicting planning configuration state", refused.stderr)
                self.assertIn("configuration_created_and_accepted", refused.stderr)
                self.assertIn("configuration_created_or_migrated_and_accepted", refused.stderr)
                self.assertIn("make the values agree", refused.stderr)
                self.assertEqual(state_path.read_bytes(), conflicting_bytes)

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
        self.assertEqual(proc.stdout, "")
        self.assertIn('"schema_version": 2', proc.stderr)
        digest_match = re.search(r"candidate SHA-256: ([0-9a-f]{64})", proc.stderr)
        self.assertIsNotNone(digest_match, proc.stderr)
        digest = digest_match.group(1)
        preview_command = shlex.join(
            ["python3", str(AGENTS.resolve()), "migrate", "--config", str(self.config.resolve())]
        )
        acceptance_command = shlex.join(
            [
                "python3",
                str(AGENTS.resolve()),
                "migrate",
                "--accept",
                "--expect-sha256",
                digest,
                "--config",
                str(self.config.resolve()),
            ]
        )
        self.assertEqual(proc.stderr.count("Read-only schema-v1 migration preview"), 1)
        self.assertEqual(proc.stderr.count(f"Validated schema-v2 candidate SHA-256: {digest}"), 1)
        self.assertEqual(proc.stderr.count(f"Preview command: {preview_command}"), 1)
        self.assertEqual(proc.stderr.count(f"Acceptance command: {acceptance_command}"), 1)
        self.assertEqual(proc.stderr.lower().count("upgrade all three skills together"), 1)
        self.assertIn("upgrade all three skills together", proc.stderr.lower())
        self.assertIn("older separately installed", proc.stderr.lower())
        self.assertIn("cmux-grilling", proc.stderr)
        self.assertIn("cmux-issue-chain", proc.stderr)

        accepted = self.cli(
            AGENTS,
            "migrate",
            "--accept",
            "--config",
            str(self.config),
        )

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["schema_version"], 2)
        initialized = self.cli(
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
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["configuration_created_and_accepted"])
        self.assertNotIn("configuration_created_or_migrated_and_accepted", state)

    def test_invalid_version_one_migration_candidate_stops_initialization_without_mutation(self):
        legacy = json.loads(self.config.read_text(encoding="utf-8"))
        legacy["schema_version"] = 1
        del legacy["workflows"]["planning"]
        legacy["workflows"]["grilling"]["web"] = "codex-sol-xhigh"
        legacy_bytes = (json.dumps(legacy, indent=2) + "\n").encode("utf-8")
        self.config.write_bytes(legacy_bytes)
        self.config.chmod(0o640)
        before = self.config.stat()
        run_dir = self.runs / "invalid-migration-candidate"

        proc = self.cli(
            STATE,
            "init",
            "--task",
            "Task",
            "--repo",
            str(self.repo),
            "--run-id",
            "invalid-migration-candidate",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertIn("cannot produce a valid migration candidate", proc.stderr)
        self.assertIn("cannot migrate invalid version-one configuration", proc.stderr)
        self.assertIn("workflow=grilling worker=web profile=codex-sol-xhigh field=harness", proc.stderr)
        self.assertIn(
            "No configuration bytes, planning run, or launchable state were recorded", proc.stderr
        )
        self.assertNotIn("Preview command:", proc.stderr)
        self.assertNotIn("Acceptance command:", proc.stderr)
        self.assertFalse(run_dir.exists())
        self.assertFalse(any(self.runs.rglob("stage-snapshots/*.json")))
        self.assertEqual(self.config.read_bytes(), legacy_bytes)
        after = self.config.stat()
        for field in (
            "st_mode",
            "st_ino",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        ):
            self.assertEqual(getattr(after, field), getattr(before, field), field)

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

    def test_status_reports_exact_recovery_action_and_init_offers_newest_unfinished_run(self):
        initialized = self.init_direct()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

        status = self.cli(
            STATE,
            "status",
            "--run-dir",
            str(self.run_dir),
            "--cmux-cmd",
            str(self.cmux),
        )

        self.assertEqual(status.returncode, 0, status.stderr)
        payload = json.loads(status.stdout)
        self.assertEqual(payload["run_id"], "plan-test")
        self.assertEqual(payload["classification"], "spec-authoring")
        self.assertEqual(payload["stage"]["mode"], "author")
        self.assertEqual(payload["stage"]["pass"], 1)
        self.assertEqual(payload["pane"]["status"], "not-launched")
        self.assertTrue(payload["report"]["pending"])
        self.assertIn("render_prompt.py", payload["recommended_next"]["command"])
        self.assertEqual(payload["input"]["task"]["sha256"], json.loads(
            (self.run_dir / "state.json").read_text(encoding="utf-8")
        )["task"]["sha256"])
        recovered_context = json.loads(
            self.cli(STATE, "context", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(recovered_context["paths"]["task"], str((self.run_dir / "task.md").resolve()))
        self.assertEqual(recovered_context["paths"]["state"], str((self.run_dir / "state.json").resolve()))
        self.assertTrue(
            any("stage-snapshots/spec-1-" in item["path"] for item in recovered_context["history"])
        )

        duplicate = self.init_direct("new-plan")
        self.assertEqual(duplicate.returncode, 3, duplicate.stderr)
        offered = json.loads(duplicate.stdout)
        self.assertEqual(offered["unfinished_run"]["run_id"], "plan-test")
        self.assertIn("resume", offered["recommended_next"]["command"])

        spaced_runs = self.root / "runs with spaces"
        spaced_init = self.cli(
            STATE,
            "init",
            "--task",
            "Task in a spaced run root",
            "--repo",
            str(self.repo),
            "--run-id",
            "spaced-plan",
            "--runs-root",
            str(spaced_runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
            "--new-run",
        )
        self.assertEqual(spaced_init.returncode, 0, spaced_init.stderr)
        spaced_duplicate = self.cli(
            STATE,
            "init",
            "--task",
            "Another task",
            "--repo",
            str(self.repo),
            "--run-id",
            "unused-plan",
            "--runs-root",
            str(spaced_runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )
        self.assertEqual(spaced_duplicate.returncode, 3, spaced_duplicate.stderr)
        resume_argv = shlex.split(
            json.loads(spaced_duplicate.stdout)["recommended_next"]["command"]
        )
        self.assertEqual(resume_argv[-1], str((spaced_runs / "spaced-plan").resolve()))

        deliberate = self.cli(
            STATE,
            "init",
            "--task",
            "A separate deliberate planning session",
            "--repo",
            str(self.repo),
            "--run-id",
            "new-plan",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
            "--new-run",
        )
        self.assertEqual(deliberate.returncode, 0, deliberate.stderr)
        input_run = self.runs / "new-plan"
        input_state_path = input_run / "state.json"
        events_path = input_run / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        init_event = next(event for event in events if event["type"] == "run.init")
        input_state = init_event["data"]["state"]
        self.assertEqual(input_state["current_stage"], "input")
        input_state_path.write_text(json.dumps(input_state), encoding="utf-8")
        events_path.write_text(json.dumps(init_event) + "\n", encoding="utf-8")
        input_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(input_run)).stdout
        )
        self.assertEqual(input_status["classification"], "input-validation")
        self.assertTrue(input_status["prepared_snapshot"]["valid"])
        self.assertIn("--decision rejoin", input_status["recommended_next"]["command"])
        resumed_input = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(input_run),
            "--decision",
            "rejoin",
        )
        self.assertEqual(resumed_input.returncode, 0, resumed_input.stderr)
        self.assertEqual(json.loads(resumed_input.stdout)["classification"], "spec-authoring")

    def test_live_worker_is_rejoined_never_started_work_is_redelivered_and_dead_worker_needs_fresh_pass(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")

        def pane(verb: str, *tail: str) -> subprocess.CompletedProcess[str]:
            return self.cli(
                PANE,
                "--cmux-cmd",
                str(self.cmux),
                verb,
                "--run-dir",
                str(self.run_dir),
                "--stage",
                "spec",
                "--pass",
                "1",
                *tail,
            )

        launched = pane("launch", "--anchor", "CALLER")
        self.assertEqual(launched.returncode, 0, launched.stderr)
        status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertEqual(status["pane"]["status"], "live")
        self.assertFalse(status["pane"]["agent_launch_sent"])
        self.assertIn("start-agent", status["recommended_next"]["command"])

        started = pane("start-agent", "--surface", "SURF-1", "--settle-seconds", "0")
        self.assertEqual(started.returncode, 0, started.stderr)
        status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertTrue(status["pane"]["agent_launch_sent"])
        self.assertFalse(status["pane"]["prompt_sent"])
        self.assertIn("deliver", status["recommended_next"]["command"])

        delivered = pane(
            "deliver",
            "--surface",
            "SURF-1",
            "--prompt",
            str(self.run_dir / "prompts" / "spec-1.md"),
            "--settle-seconds",
            "0",
        )
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertNotEqual(status["classification"], "pending-report")
        self.assertIn("mark-started", status["recommended_next"]["command"])

        # The visible pane showed the known summarized-and-waiting case, so the same immutable
        # prompt may be re-delivered without creating a new worker or pass.
        redelivered = pane(
            "deliver",
            "--surface",
            "SURF-1",
            "--prompt",
            str(self.run_dir / "prompts" / "spec-1.md"),
            "--settle-seconds",
            "0",
        )
        self.assertEqual(redelivered.returncode, 0, redelivered.stderr)
        marked = pane("mark-started", "--surface", "SURF-1")
        self.assertEqual(marked.returncode, 0, marked.stderr)
        self.assertFalse(json.loads(marked.stdout)["already_recorded"])
        started_events_before = sum(
            json.loads(line)["type"] == "worker.started"
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        )
        repeated = pane("mark-started", "--surface", "SURF-1")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["already_recorded"])
        started_events_after = sum(
            json.loads(line)["type"] == "worker.started"
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(started_events_after, started_events_before)
        status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertEqual(status["classification"], "pending-report")
        self.assertTrue(status["pane"]["agent_launch_sent"])
        self.assertTrue(status["pane"]["prompt_sent"])
        self.assertTrue(status["pane"]["assignment_start_confirmed"])
        lifecycle_types = {
            "pane.launched", "pane.labeled", "worker.launch_sent", "worker.prompt_sent", "worker.started"
        }
        lifecycle_events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(line)["type"] in lifecycle_types
        ]
        self.assertEqual(
            {event["data"]["surface_id"] for event in lifecycle_events}, {"SURF-1"}
        )
        self.assertIn("await_report.py", status["recommended_next"]["command"])
        self.assertIn(str(self.cmux), shlex.split(status["recommended_next"]["command"]))
        partial_report = self.run_dir / "reports" / "spec-1.md"
        partial_report.write_text("partial handoff\n", encoding="utf-8")
        partial_status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertTrue(partial_status["report"]["uncertain"])
        self.assertEqual(partial_status["classification"], "pending-report")
        self.assertIn("await_report.py", partial_status["recommended_next"]["command"])
        partial_report.unlink()

        dead_env = self.env()
        dead_env["FAKE_CMUX_DEAD"] = "1"
        watched = self.cli(
            AWAIT,
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--surface",
            "SURF-1",
            "--cmux-cmd",
            str(self.cmux),
            "--deadline-minutes",
            "0.1",
            "--poll-seconds",
            "0.01",
            env=dead_env,
        )
        self.assertEqual(watched.returncode, 7, watched.stderr)
        status = json.loads(
            self.cli(
                STATE,
                "status",
                "--run-dir",
                str(self.run_dir),
                "--cmux-cmd",
                str(self.cmux),
                env=dead_env,
            ).stdout
        )
        self.assertEqual(status["classification"], "hitl")
        self.assertIn("--decision relaunch", status["recommended_next"]["command"])

        partial_report.write_text("uncertain dead-pane handoff\n", encoding="utf-8")
        uncertain = json.loads(
            self.cli(
                STATE,
                "status",
                "--run-dir",
                str(self.run_dir),
                "--cmux-cmd",
                str(self.cmux),
                env=dead_env,
            ).stdout
        )
        self.assertEqual(uncertain["classification"], "hitl")
        self.assertTrue(uncertain["report"]["uncertain"])
        self.assertIn("context", uncertain["recommended_next"]["command"])
        partial_report.unlink()

        unauthorized = self.repo / "worker-created-product-file.txt"
        unauthorized.write_text("must not become the next baseline\n", encoding="utf-8")
        refused = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "The human confirmed that the dead pane may be replaced",
            "--cmux-cmd",
            str(self.cmux),
            env=dead_env,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Git-visible product delta", refused.stderr)
        unauthorized.unlink()

        resumed = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "The human confirmed that the dead pane may be replaced",
            "--cmux-cmd",
            str(self.cmux),
            env=dead_env,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["spec_pass"], 2)
        self.assertEqual(state["current_stage"], "spec")
        self.assertEqual(state["prepared_stage"]["pass"], 2)
        self.assertTrue(list((self.run_dir / "stage-snapshots").glob("spec-1-*.json")))
        rendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "2"
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn(
            "The human confirmed that the dead pane may be replaced",
            (self.run_dir / "prompts" / "spec-2.md").read_text(encoding="utf-8"),
        )

    def test_dead_reviewer_relaunches_as_a_new_reviewer_pass_without_replacing_the_author(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.render_and_baseline("spec-review")
        self.launch_prepared_stage("spec-review")
        marked = self.cli(
            PANE,
            "--cmux-cmd",
            str(self.cmux),
            "mark-started",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec-review",
            "--pass",
            "1",
            "--surface",
            "SURF-1",
        )
        self.assertEqual(marked.returncode, 0, marked.stderr)
        live = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertEqual(live["classification"], "pending-report")
        self.assertEqual(live["stage"]["mode"], "reviewer")
        self.assertIn("await_report.py", live["recommended_next"]["command"])
        dead_env = self.env()
        dead_env["FAKE_CMUX_DEAD"] = "1"
        watched = self.cli(
            AWAIT,
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec-review",
            "--pass",
            "1",
            "--surface",
            "SURF-1",
            "--cmux-cmd",
            str(self.cmux),
            "--deadline-minutes",
            "0.1",
            "--poll-seconds",
            "0.01",
            env=dead_env,
        )
        self.assertEqual(watched.returncode, 7, watched.stderr)
        resumed = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "Reviewer pane died before producing a handoff",
            "--cmux-cmd",
            str(self.cmux),
            env=dead_env,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["spec_pass"], 1)
        self.assertEqual(state["spec_review_pass"], 2)
        self.assertEqual(state["current_stage"], "spec-review")
        self.assertEqual(Path(state["author_spec"]["draft"]), draft)
        rendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec-review", "--pass", "2"
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        prompt = (self.run_dir / "prompts" / "spec-review-2.md").read_text(encoding="utf-8")
        self.assertIn("Reviewer pane died before producing a handoff", prompt)
        self.assertIn(str(draft), prompt)

    def test_one_watcher_extension_can_be_rejoined_and_then_expires_to_hitl(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        self.launch_prepared_stage("spec")
        marked = self.cli(
            PANE,
            "--cmux-cmd",
            str(self.cmux),
            "mark-started",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--surface",
            "SURF-1",
        )
        self.assertEqual(marked.returncode, 0, marked.stderr)
        first = self.cli(
            AWAIT,
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--surface",
            "SURF-1",
            "--cmux-cmd",
            str(self.cmux),
            "--deadline-minutes",
            "0.001",
            "--poll-seconds",
            "0.01",
        )
        self.assertEqual(first.returncode, 8, first.stderr)
        status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertEqual(status["pane"]["status"], "deadline")
        self.assertIn("--decision extend", status["recommended_next"]["command"])
        extended = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "extend",
            "--reason",
            "The live worker is still making visible progress",
            "--cmux-cmd",
            str(self.cmux),
        )
        self.assertEqual(extended.returncode, 0, extended.stderr)
        self.assertIn("--extension 1", json.loads(extended.stdout)["recommended_next"]["command"])
        expired = self.cli(
            AWAIT,
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--surface",
            "SURF-1",
            "--cmux-cmd",
            str(self.cmux),
            "--deadline-minutes",
            "0.001",
            "--poll-seconds",
            "0.01",
            "--extension",
            "1",
        )
        self.assertEqual(expired.returncode, 8, expired.stderr)
        status = json.loads(
            self.cli(
                STATE, "status", "--run-dir", str(self.run_dir), "--cmux-cmd", str(self.cmux)
            ).stdout
        )
        self.assertEqual(status["pane"]["status"], "watcher-expired")
        self.assertEqual(status["classification"], "hitl")
        self.assertIn("--decision relaunch", status["recommended_next"]["command"])

    def test_tampered_prepared_snapshot_and_uncertain_handoff_stop_recovery(self):
        self.assertEqual(self.init_direct().returncode, 0)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        snapshot = self.run_dir / state["prepared_stage"]["path"]
        snapshot.write_text("{}\n", encoding="utf-8")
        status = self.cli(STATE, "status", "--run-dir", str(self.run_dir))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["classification"], "inconsistent")
        rejoin = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "rejoin",
        )
        self.assertNotEqual(rejoin.returncode, 0)

        # A non-empty uncertain report plus a tampered snapshot is never treated as success or
        # overwritten by a same-pass retry.
        snapshot.write_bytes(b"{}\n")
        (self.run_dir / "reports" / "spec-1.md").write_text("partial handoff\n", encoding="utf-8")
        relaunch = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "replace it",
        )
        self.assertNotEqual(relaunch.returncode, 0)
        self.assertEqual(
            (self.run_dir / "reports" / "spec-1.md").read_text(encoding="utf-8"),
            "partial handoff\n",
        )

    def test_interrupted_grilling_revalidation_preserves_partial_outcomes_and_cannot_launch(self):
        artifact, markdown = self.grilling_pair()
        run_dir = self.runs / "plan-grilling-interrupted"
        initialized = self.cli(
            STATE,
            "init",
            "--task",
            "Planung",
            "--grilling-json",
            str(artifact),
            "--grilling-markdown",
            str(markdown),
            "--repo",
            str(self.repo),
            "--run-id",
            "plan-grilling-interrupted",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        partial_path = self.root / "partial-revalidation.json"
        partial = {
            "accepted": True,
            "premise_corrections": [{"index": 1, "outcome": "confirmed", "reason": ""}],
        }
        partial_path.write_text(json.dumps(partial), encoding="utf-8")
        interrupted = self.cli(
            STATE,
            "revalidate",
            "--run-dir",
            str(run_dir),
            "--outcomes",
            str(partial_path),
        )
        self.assertNotEqual(interrupted.returncode, 0)
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "awaiting-grilling-revalidation")
        self.assertIsNone(state["prepared_stage"])
        self.assertEqual(
            json.loads((run_dir / state["grilling_revalidation"]["path"]).read_text(encoding="utf-8")),
            partial,
        )
        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(run_dir)).stdout
        )
        self.assertEqual(status["classification"], "grilling-revalidation-interrupted")
        shown = json.loads(
            self.cli(STATE, "show-revalidation", "--run-dir", str(run_dir)).stdout
        )
        self.assertEqual(shown["recorded_outcomes"], partial)
        progress_path = run_dir / state["grilling_revalidation"]["path"]
        progress_bytes = progress_path.read_bytes()
        progress_path.write_text("{}\n", encoding="utf-8")
        changed = self.cli(STATE, "show-revalidation", "--run-dir", str(run_dir))
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("progress is missing or changed", changed.stderr)
        progress_path.write_bytes(progress_bytes)
        launch = self.cli(
            PANE,
            "--cmux-cmd",
            str(self.cmux),
            "launch",
            "--run-dir",
            str(run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
            "--anchor",
            "CALLER",
        )
        self.assertNotEqual(launch.returncode, 0)

    def test_recorded_approvals_are_digest_bound_and_idempotent(self):
        approved_path = self.approve_spec_to_tickets()
        repeated = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Repeat the already recorded approval",
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["idempotent"])

        approved_path.write_text(
            approved_path.read_text(encoding="utf-8") + "\nChanged after approval.\n",
            encoding="utf-8",
        )
        stale = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Must not inherit the stale approval",
        )
        self.assertNotEqual(stale.returncode, 0)
        status = json.loads(self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout)
        self.assertEqual(status["classification"], "inconsistent")
        self.assertFalse(status["approval"]["spec"]["valid"])

    def test_publication_recovers_an_already_moved_tracker_and_refuses_duplicates(self):
        proposal = self.reach_ticket_approval()
        target = self.repo / ".scratch" / proposal["tracker"]["slug"]
        approved = self.ticket_approval(
            "approve", "Human approved the reviewed tracker", target=target
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        repeated = self.ticket_approval("approve", "Repeat the same approval", target=target)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["idempotent"])

        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        staged = Path(state["staged_tracker"]["path"])
        validated_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(validated_status["publication"]["phase"], "validated")
        readme = staged / "README.md"
        original_readme = readme.read_bytes()
        readme.write_bytes(original_readme + b"tampered\n")
        changed_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(changed_status["classification"], "inconsistent")
        self.assertEqual(changed_status["publication"]["phase"], "inconsistent")
        readme.write_bytes(original_readme)
        os.rename(staged, target)
        interrupted = json.loads(self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout)
        self.assertEqual(interrupted["publication"]["phase"], "published")
        recovered = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertTrue(json.loads(recovered.stdout)["recovered"])
        final = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(final["current_stage"], "complete")
        duplicate = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("already published", duplicate.stderr)

    def test_status_distinguishes_unrecorded_complete_staging_from_validated_state(self):
        proposal = self.reach_ticket_approval()
        target = self.repo / ".scratch" / proposal["tracker"]["slug"]
        approved = self.ticket_approval(
            "approve", "Human approved before the process interruption", target=target
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["approved_tickets"] = None
        state["staged_tracker"] = None
        state["current_stage"] = "awaiting-ticket-approval"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(status["publication"]["phase"], "fully-staged")
        self.assertEqual(status["classification"], "awaiting-ticket-approval")
        recovered = self.ticket_approval(
            "approve", "Human repeated approval after inspecting recovered staging", target=target
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        recovered_state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered_state["current_stage"], "ready-to-publish")
        recovered_status = json.loads(
            self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout
        )
        self.assertEqual(recovered_status["publication"]["phase"], "validated")

    def test_review_blocked_resume_routes_to_a_new_author_pass(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.render_and_baseline("spec-review")
        digest = validate_spec(draft)["sha256"]
        (self.run_dir / "reports" / "spec-review-1.md").write_text(
            review_report(
                "blocked",
                digest,
                digest,
                blockers="- Human must decide the rollout policy.",
            ),
            encoding="utf-8",
        )
        blocked = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        status = json.loads(self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout)
        self.assertEqual(status["classification"], "review-blocked")
        self.assertEqual(status["latest_review"]["verdict"], "blocked")
        resumed = self.cli(
            STATE,
            "resume",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "relaunch",
            "--reason",
            "Use staged rollout after the human decision",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "spec")
        self.assertEqual(state["spec_pass"], 2)
        self.assertIsNone(state["author_spec"])
        self.assertTrue(draft.is_file(), "the rejected author handoff remains preserved")

    def test_offline_smoke_runs_all_visible_stages_with_safe_correction_and_issue_chain_handoff(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        self.launch_prepared_stage("spec")
        draft = self.write_author_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        self.render_and_baseline("spec-review")
        self.launch_prepared_stage("spec-review")
        corrected = self.run_dir / "artifacts" / "spec-reviewed-1.md"
        corrected.write_text(
            spec(solution="Implement the clarified workflow already required by the task."),
            encoding="utf-8",
        )
        input_digest = validate_spec(draft)["sha256"]
        corrected_digest = validate_spec(corrected)["sha256"]
        (self.run_dir / "reports" / "spec-review-1.md").write_text(
            review_report(
                "pass_with_fixes",
                input_digest,
                corrected_digest,
                corrections="- Clarified established wording without changing scope.",
            ),
            encoding="utf-8",
        )
        reviewed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        approved = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Human approved the corrected specification and visible diff",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

        self.render_and_baseline("tickets")
        self.launch_prepared_stage("tickets")
        proposal = self.write_tickets_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.render_and_baseline("tickets-review")
        self.launch_prepared_stage("tickets-review")
        self.write_tickets_review()
        reviewed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)

        target = self.repo / ".scratch" / proposal["tracker"]["slug"]
        approved = self.ticket_approval(
            "approve", "Human approved ticket granularity and dependencies", target=target
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        published = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertEqual(published.returncode, 0, published.stderr)
        status = json.loads(self.cli(STATE, "status", "--run-dir", str(self.run_dir)).stdout)
        self.assertEqual(status["classification"], "completed")
        self.assertEqual(status["publication"]["phase"], "completed")

        downstream = self.cli(
            ISSUE_CHAIN_STATE,
            "init",
            "--tracker",
            str(target),
            "--issue",
            proposal["ready_frontier"][0],
            "--run-id",
            "downstream-first-frontier",
            "--runs-root",
            str(self.root / "issue-runs"),
            "--config",
            str(self.config),
            "--no-workspace",
        )
        self.assertEqual(downstream.returncode, 0, downstream.stderr)
        downstream_state = json.loads(
            (self.root / "issue-runs" / "downstream-first-frontier" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(downstream_state["current_stage"], "implement")
        self.assertTrue(downstream_state["ready"])
        self.assertEqual(downstream_state["prepared_stage"]["stage"], "implement")

        # Completed runs are discoverable by status but never block a deliberate new session.
        next_run = self.cli(
            STATE,
            "init",
            "--task",
            "A later planning task",
            "--repo",
            str(self.repo),
            "--run-id",
            "after-complete",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )
        self.assertEqual(next_run.returncode, 0, next_run.stderr)


class SurfaceIdentityRules(unittest.TestCase):
    def events(self, *surfaces):
        return [
            {
                "type": "pane.launched",
                "data": {"stage": "spec", "pass": 1, "surface_id": surface},
            }
            for surface in surfaces
        ]

    def test_work_verbs_take_only_the_latest_launch_identity(self):
        events = self.events("SURF-1", "SURF-2")
        self.assertEqual(
            orchestrator_lib.validate_recorded_surface(events, "spec", 1, "SURF-2"), "SURF-2"
        )
        with self.assertRaises(ValueError):
            orchestrator_lib.validate_recorded_surface(events, "spec", 1, "SURF-1")

    def test_close_may_target_any_launch_identity_of_the_stage_pass(self):
        events = self.events("SURF-1", "SURF-2")
        for surface in ("SURF-1", "SURF-2"):
            self.assertEqual(
                orchestrator_lib.validate_recorded_surface(
                    events, "spec", 1, surface, any_launch=True
                ),
                surface,
            )
        with self.assertRaises(ValueError) as unknown:
            orchestrator_lib.validate_recorded_surface(
                events, "spec", 1, "surface:1", any_launch=True
            )
        self.assertIn("SURF-1", str(unknown.exception))
        self.assertIn("SURF-2", str(unknown.exception))

    def test_blank_lines_do_not_make_the_event_stream_unusable(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = Path(root)
            orchestrator_lib.append_event(run_dir, "pane.launched", "launched", {"pass": 1})
            with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            self.assertEqual(len(orchestrator_lib.planning_events(run_dir)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
