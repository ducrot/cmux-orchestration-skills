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
from test_spec_contract import checked_evidence, review_report, spec  # noqa: E402
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
        self.runs = self.repo / ".scratch" / "orchestrator" / "runs"
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
        if getattr(self, "relative_cli_paths", False):
            argv = list(args)
            for index, value in enumerate(argv[:-1]):
                if value in {"--runs-root", "--run-dir"}:
                    path = Path(argv[index + 1])
                    if path.is_absolute():
                        argv[index + 1] = os.path.relpath(path, self.repo)
            args = tuple(argv)
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
            "--slug",
            "planned-feature",
            "--repo",
            str(self.repo),
            "--run-id",
            run_id,
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )

    def test_shared_identity_slug_override_and_sibling_discovery(self):
        sibling = self.runs / "grill-sibling"
        sibling.mkdir(parents=True)
        (sibling / "state.json").write_text(json.dumps({"workflow": "grilling", "layout_version": 1, "slug": "sibling"}))
        result = self.cli(STATE, "init", "--task", "Task: Static teaser website for cmux Orchestration skills", "--workspace-id", "WORKSPACE-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.repo / result.stdout.strip().splitlines()[-1]
        self.assertEqual(run_dir.parent, self.runs)
        self.assertRegex(run_dir.name, r"^plan-task-static-teaser-website-for-\d{4}-\d{2}-\d{2}-\d{4}$")
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual(state["tracker_slug"], "task-static-teaser-website-for")
        self.assertEqual(state["workflow"], "planning")
        self.assertEqual(state["layout_version"], 1)
        self.assertEqual(state["schema_version"], 3)
        self.assertEqual(state["deliverables"], {})
        offered = self.cli(STATE, "init", "--task", "Another task", "--workspace-id", "WORKSPACE-1")
        self.assertEqual(json.loads(offered.stdout)["unfinished_run"]["run_id"], run_dir.name)
        override = self.cli(STATE, "init", "--task", "Another task", "--slug", "frozen-name", "--new-run", "--workspace-id", "WORKSPACE-1")
        self.assertEqual(override.returncode, 0, override.stderr)
        overridden = self.repo / override.stdout.strip().splitlines()[-1]
        self.assertTrue(overridden.name.startswith("plan-frozen-name-"))
        self.assertEqual(json.loads((overridden / "state.json").read_text())["tracker_slug"], "frozen-name")
        reinit = self.cli(STATE, "init", "--task", "Changed task", "--run-id", overridden.name, "--slug", "different-name", "--workspace-id", "WORKSPACE-1")
        self.assertEqual(reinit.returncode, 0, reinit.stderr)
        self.assertEqual(json.loads((overridden / "state.json").read_text())["tracker_slug"], "frozen-name")
        for slug in ("", "Upper", "a--b", "../x", "x" * 31):
            invalid = self.cli(STATE, "init", "--task", "Task", "--run-id", "invalid", "--slug", slug, "--new-run", "--workspace-id", "WORKSPACE-1")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("--slug", invalid.stderr)
            self.assertFalse((self.runs / "invalid").exists())

    def test_schema_two_and_legacy_root_are_read_only(self):
        self.assertEqual(self.init_direct().returncode, 0)
        state_path = self.run_dir / "state.json"
        original = json.loads(state_path.read_text())
        for change in ({"schema_version": 2}, {"workflow": "grilling"}, {"layout_version": 0}):
            state_path.write_text(json.dumps({**original, **change}))
            before = {str(p.relative_to(self.run_dir)): p.read_bytes() for p in self.run_dir.rglob("*") if p.is_file()}
            for command in ("publish", "resume"):
                refused = self.cli(STATE, command, "--run-dir", str(self.run_dir))
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("legacy layout", refused.stderr)
                self.assertIn(".scratch/orchestrator/planning-runs/", refused.stderr)
                self.assertIn("reviewed migration", refused.stderr)
            refused_close = self.cli(PANE, "--cmux-cmd", str(self.cmux), "close", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1", "--surface", "SURFACE-1")
            self.assertNotEqual(refused_close.returncode, 0)
            self.assertIn("legacy layout", refused_close.stderr)
            self.assertFalse(self.cmux_log.exists())
            for command in ("status", "context"):
                options = ["--cmux-cmd", str(self.cmux)] if command == "status" else []
                inspected = self.cli(STATE, command, "--run-dir", str(self.run_dir), *options)
                self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.cmux_log.unlink(missing_ok=True)
            self.assertEqual(before, {str(p.relative_to(self.run_dir)): p.read_bytes() for p in self.run_dir.rglob("*") if p.is_file()})
        state_path.write_text(json.dumps(original))
        legacy_dir = self.repo / ".scratch/orchestrator/planning-runs" / self.run_dir.name
        legacy_dir.parent.mkdir(parents=True)
        self.run_dir.rename(legacy_dir)
        refused = self.cli(STATE, "prepare", "--run-dir", str(legacy_dir), "--stage", "spec", "--pass", "1")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(".scratch/orchestrator/planning-runs/", refused.stderr)
        before = {str(p.relative_to(legacy_dir)): p.read_bytes() for p in legacy_dir.rglob("*") if p.is_file()}
        reinit = self.cli(STATE, "init", "--task", "Task", "--run-id", legacy_dir.name, "--runs-root", str(legacy_dir.parent), "--workspace-id", "WORKSPACE-1")
        self.assertNotEqual(reinit.returncode, 0)
        self.assertIn("legacy layout", reinit.stderr)
        self.assertIn("human decision to restart", reinit.stderr)
        self.assertIn("reviewed migration", reinit.stderr)
        self.assertEqual(before, {str(p.relative_to(legacy_dir)): p.read_bytes() for p in legacy_dir.rglob("*") if p.is_file()})

    def test_initialization_supports_default_relative_and_absolute_roots(self):
        for mode, root_args in (
            ("default", []),
            ("relative", ["--runs-root", ".scratch/orchestrator/runs"]),
            ("absolute", ["--runs-root", str(self.runs)]),
        ):
            with self.subTest(mode=mode):
                result = self.cli(
                    STATE, "init", "--task", "Title\nSecond line\nThird line",
                    "--run-id", f"plan-{mode}", "--workspace-id", "WORKSPACE-1",
                    "--new-run", *root_args,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                run_dir = self.runs / f"plan-{mode}"
                state = json.loads((run_dir / "state.json").read_text())
                self.assertEqual(state["current_stage"], "spec")
                self.assertEqual(state["artifact_audit"]["unexpected"], [])
                self.assertEqual((run_dir / "task.md").read_text(), "Title\nSecond line\nThird line")
                for entry in state["artifact_manifest"].values():
                    self.assertFalse(Path(entry["path"]).is_absolute())
                    self.assertEqual(
                        hashlib.sha256((run_dir / entry["path"]).read_bytes()).hexdigest(),
                        entry["sha256"],
                    )
                printed = result.stdout.strip().splitlines()[-1]
                expected = run_dir if mode == "absolute" else run_dir.relative_to(self.repo)
                self.assertEqual(printed, str(expected))

    def test_initialization_retries_a_directory_without_state(self):
        (self.run_dir / "inputs").mkdir(parents=True)
        (self.run_dir / "task.md").write_text("Task left by a failed initialization\n")
        orphan = self.run_dir / "inputs" / "unclaimed.md"
        orphan.write_text("Preserve this evidence\n")

        result = self.init_direct()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.run_dir / "task.md").read_text(), "Bitte sichere Planung erstellen.")
        self.assertEqual(orphan.read_text(), "Preserve this evidence\n")
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["artifact_audit"]["unexpected"], ["inputs/unclaimed.md"])

    def test_reinitialization_preserves_existing_run_without_reloading_configuration(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        self.write_author_handoff()
        before = {p.relative_to(self.run_dir): p.read_bytes() for p in self.run_dir.rglob("*") if p.is_file()}
        self.config.write_text("invalid configuration: must not be reloaded\n")

        for extra in ([], ["--new-run"]):
            with self.subTest(extra=extra):
                result = self.cli(
                    STATE, "init", "--task", "Replacement task must not be used",
                    "--run-id", "plan-test", *extra,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(self.run_dir.relative_to(self.repo)))
                after = {p.relative_to(self.run_dir): p.read_bytes() for p in self.run_dir.rglob("*") if p.is_file()}
                self.assertEqual(after, before)

    def test_reinitialization_refuses_configuration_inputs_without_changing_run(self):
        self.assertEqual(self.init_direct().returncode, 0)
        before = (self.run_dir / "state.json").read_bytes()
        for extra in (
            ["--config", str(self.config)], ["--accept-config"],
            ["--model", "spec=opus"], ["--probe-profiles"], ["--probe-timeout", "10"],
        ):
            with self.subTest(extra=extra):
                result = self.cli(STATE, "init", "--task", "Same run", "--run-id", "plan-test", *extra)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("not to re-initialization", result.stderr)
                self.assertEqual((self.run_dir / "state.json").read_bytes(), before)

    def test_reinitialization_preserves_pending_human_confirmation(self):
        self.assign_planning_profile("spec", "codex-astra-xhigh")
        result = self.init_direct()
        self.assertEqual(result.returncode, 2, result.stderr)
        before = (self.run_dir / "state.json").read_bytes()
        repeated = self.cli(STATE, "init", "--task", "Same run", "--run-id", "plan-test")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), before)
        self.assertFalse(list((self.run_dir / "stage-snapshots").iterdir()))

    def test_reinitialization_refuses_a_run_owned_by_another_repository(self):
        self.assertEqual(self.init_direct().returncode, 0)
        other_repo = self.root / "other-repo"
        subprocess.run(["git", "init", "-q", str(other_repo)], check=True)
        before = (self.run_dir / "state.json").read_bytes()
        repeated = self.cli(
            STATE, "init", "--task", "Another repository", "--run-id", "plan-test",
            "--repo", str(other_repo),
        )
        self.assertEqual(repeated.returncode, 1, repeated.stderr)
        self.assertIn("belongs to another repository", repeated.stderr)
        self.assertEqual((self.run_dir / "state.json").read_bytes(), before)

    def test_relative_run_path_still_rejects_a_symlink_to_an_artifact_inside_the_run(self):
        self.relative_cli_paths = True
        self.assertEqual(self.init_direct().returncode, 0)
        task = self.run_dir / "task.md"
        moved = self.run_dir / "inputs" / "moved-task.md"
        task.rename(moved)
        task.symlink_to("inputs/moved-task.md")

        result = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("artifact path uses a symlink", result.stderr)
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "integrity-violation")

    def test_relative_run_paths_reach_publication_without_false_integrity_gates(self):
        self.relative_cli_paths = True
        proposal = self.reach_ticket_approval(launch_panes=True)
        view = self.cli(STATE, "ticket-approval-view", "--run-dir", str(self.run_dir))
        self.assertEqual(view.returncode, 0, view.stderr)
        target = self.repo / ".scratch" / proposal["tracker"]["slug"]
        approved = self.ticket_approval("approve", "Approved for path regression", target=target)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        published = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertTrue((target / "issues").is_dir())
        state = json.loads((self.run_dir / "state.json").read_text())
        self.assertEqual(state["current_stage"], "complete")
        self.assertEqual(state["deliverables"]["tracker"], state["published_tracker"]["path"])
        self.assertEqual(state["artifact_audit"]["unexpected"], [])
        self.assertNotIn("artifact_integrity_violation", state)

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

    def assert_gated_prepare(
        self, stage: str, confirmation_command: str, pass_num: int = 1
    ) -> dict:
        """Prepare a gated author stage and assert it exits 2 without publishing anything."""
        prepared = self.cli(
            STATE,
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            stage,
            "--pass",
            str(pass_num),
        )
        self.assertEqual(prepared.returncode, 2, prepared.stderr)
        self.assertEqual(prepared.stderr, "")
        payload = json.loads(prepared.stdout)
        self.assertIsNone(payload["prepared"])
        self.assertEqual(
            payload["diversity_warning"]["confirmation_command"], confirmation_command
        )
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["prepared_stage"])
        self.assertIsNone(state["tree_baseline"])
        self.assertFalse(
            list((self.run_dir / "stage-snapshots").glob(f"{stage}-{pass_num}-*.json"))
        )
        return payload

    def render_and_baseline(self, stage: str, pass_num: int = 1, run_dir: Path | None = None) -> None:
        selected = run_dir or self.run_dir
        rendered = self.cli(RENDER, "--run-dir", str(selected), "--stage", stage, "--pass", str(pass_num))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        if stage in {"tickets", "tickets-review"}:
            state = json.loads((selected / "state.json").read_text())
            prompt = Path(state["current_attempt"]["paths"]["prompt"]).read_text()
            self.assertIn(f'Tracker slug (fixed): `{state["tracker_slug"]}`', prompt)
            self.assertIn(f'--tracker-slug {state["tracker_slug"]}', prompt)
            self.assertIn("`tracker.slug` must equal", prompt)
        baseline = self.cli(TREE, "baseline", "--run-dir", str(selected), "--stage", stage, "--pass", str(pass_num))
        self.assertEqual(baseline.returncode, 0, baseline.stderr)

    def write_author_handoff(self, pass_num: int = 1, run_dir: Path | None = None) -> Path:
        selected = run_dir or self.run_dir
        state = json.loads((selected / "state.json").read_text(encoding="utf-8"))
        paths = state["current_attempt"]["paths"]
        draft = Path(paths["draft"])
        draft.write_text(spec(), encoding="utf-8")
        report = Path(paths["report"])
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
        reviewer_prompt = (self.run_dir / "prompts" / "spec-review-1.md").read_text()
        self.assertIn("## Checked\n- `<reference>`: <what was checked>: <outcome>", reviewer_prompt)
        self.assertIn("must cover all input sections", reviewer_prompt)
        self.assertIn("A `blocked` verdict is\nthe only exception to coverage", reviewer_prompt)
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
        paths = state["current_attempt"]["paths"]
        proposal_path = Path(paths["proposal"])
        proposal_path.write_text(
            json.dumps(data or tracker_proposal(spec_path), indent=2) + "\n", encoding="utf-8"
        )
        result = validate_proposal(proposal_path)
        summary = Path(paths["summary"])
        summary.write_text(render_summary(result), encoding="utf-8")
        report = Path(paths["report"])
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
        checked: str | None = None,
    ) -> None:
        state = json.loads((self.run_dir / "state.json").read_text())
        digest = state["author_tickets"]["proposal_sha256"]
        ticket_ids = [
            ticket["id"]
            for ticket in json.loads(Path(state["author_tickets"]["proposal"]).read_text())["tickets"]
        ]
        evidence = checked_evidence(ticket_ids) if checked is None else checked
        Path(state["current_attempt"]["paths"]["report"]).write_text(
            f"""## Verdict
{verdict}

## Findings
- None

## Checked
{evidence}

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
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        pane(
            "deliver",
            "--surface", surface,
            "--prompt", state["tree_baseline"]["prompt_path"],
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
        self.assertIn("## Checked\n- `<reference>`: <what was checked>: <outcome>", reviewer_prompt)
        self.assertIn("must cover all input ticket ids", reviewer_prompt)
        self.assertIn("A `blocked` verdict is\nthe only exception to coverage", reviewer_prompt)
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
        self.assertEqual(state["artifact_manifest_version"], 1)
        self.assertEqual(state["current_attempt"]["attempt_id"], "spec-1-attempt-1")
        task_entries = [
            entry
            for entry in state["artifact_manifest"].values()
            if entry["kind"] == "task"
        ]
        self.assertEqual(len(task_entries), 1)
        self.assertEqual(task_entries[0]["path"], "task.md")
        self.assertTrue(task_entries[0]["finalized"])
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

    def test_manifest_binds_every_spec_flow_artifact_with_complete_identity(self):
        self.approve_spec_to_tickets()
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        entries = list(state["artifact_manifest"].values())
        kinds = {entry["kind"] for entry in entries}
        self.assertTrue(
            {
                "task",
                "stage-snapshot",
                "prompt",
                "tree-baseline",
                "tree-verification",
                "spec-draft",
                "worker-report",
                "approved-spec",
            }.issubset(kinds)
        )
        for entry in entries:
            self.assertEqual(
                set(entry).issuperset(
                    {
                        "id",
                        "path",
                        "kind",
                        "stage",
                        "pass",
                        "attempt",
                        "attempt_id",
                        "byte_size",
                        "sha256",
                        "producer",
                        "finalized",
                        "finalized_at",
                    }
                ),
                True,
                entry,
            )
            self.assertFalse(Path(entry["path"]).is_absolute())
            self.assertNotIn("..", Path(entry["path"]).parts)
            self.assertGreater(entry["byte_size"], 0)
            self.assertRegex(entry["sha256"], r"\A[0-9a-f]{64}\Z")
            self.assertTrue(entry["finalized"])
        approved = state["approved_spec"]
        approved_entry = state["artifact_manifest"][approved["manifest_id"]]
        reviewed_entry = state["artifact_manifest"][approved_entry["source_manifest_id"]]
        self.assertEqual(approved_entry["sha256"], reviewed_entry["sha256"])
        self.assertEqual(approved_entry["path"], reviewed_entry["path"])

    def test_tampered_or_missing_finalized_prompt_gates_hitl_without_rearming(self):
        self.assertEqual(self.init_direct().returncode, 0)
        rendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        prompt = Path(state["current_attempt"]["paths"]["prompt"])
        original = prompt.read_bytes()
        rerendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(rerendered.returncode, 0, rerendered.stderr)
        self.assertEqual(prompt.read_bytes(), original)
        prompt.write_bytes(b"")

        refused = self.cli(
            TREE,
            "baseline",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
        )

        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("empty", refused.stderr)
        failed = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["current_stage"], "integrity-violation")
        self.assertEqual(failed["attempt_history"][-1]["status"], "integrity-violation")
        self.assertIsNone(failed["current_attempt"])
        self.assertEqual(
            failed["artifact_manifest"][state["current_attempt"]["prompt_manifest_id"]][
                "sha256"
            ],
            hashlib.sha256(original).hexdigest(),
        )

    def test_missing_task_and_artifact_kind_substitution_gate_before_transition(self):
        self.assertEqual(self.init_direct().returncode, 0)
        (self.run_dir / "task.md").unlink()
        missing = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("missing", missing.stderr)
        self.assertEqual(
            json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
                "current_stage"
            ],
            "integrity-violation",
        )

        second = self.runs / "plan-kind"
        initialized = self.cli(
            STATE,
            "init",
            "--task",
            "Plan kind binding",
            "--repo",
            str(self.repo),
            "--run-id",
            "plan-kind",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
            "--new-run",
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        second_state_path = second / "state.json"
        second_state = json.loads(second_state_path.read_text(encoding="utf-8"))
        manifest_id = second_state["task"]["manifest_id"]
        second_state["artifact_manifest"][manifest_id]["kind"] = "prompt"
        second_state_path.write_text(json.dumps(second_state), encoding="utf-8")
        substituted = self.cli(
            STATE, "prepare", "--run-dir", str(second), "--stage", "spec", "--pass", "1"
        )
        self.assertNotEqual(substituted.returncode, 0)
        self.assertIn("manifest identity was substituted", substituted.stderr)

    def test_directory_substitution_of_finalized_artifact_records_integrity_gate(self):
        self.assertEqual(self.init_direct().returncode, 0)
        rendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        state_path = self.run_dir / "state.json"
        before = json.loads(state_path.read_text(encoding="utf-8"))
        task_manifest_id = before["task"]["manifest_id"]
        task_identity = dict(before["artifact_manifest"][task_manifest_id])
        task_path = self.run_dir / task_identity["path"]
        task_path.unlink()
        task_path.mkdir()

        refused = self.cli(
            TREE,
            "baseline",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec",
            "--pass",
            "1",
        )

        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not a regular file", refused.stderr)
        failed = json.loads(state_path.read_text(encoding="utf-8"))
        violation = failed["artifact_integrity_violation"]
        self.assertEqual(failed["current_stage"], "integrity-violation")
        self.assertEqual(violation["decision"], "hitl")
        self.assertEqual(violation["reason"], "run artifact integrity violation")
        self.assertIn("not a regular file", violation["error"])
        self.assertEqual(failed["gate_decisions"][-1], violation)
        self.assertEqual(failed["attempt_history"][-1]["status"], "integrity-violation")
        self.assertIsNone(failed["current_attempt"])
        self.assertEqual(failed["artifact_manifest"][task_manifest_id], task_identity)
        self.assertTrue(task_path.is_dir())
        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(events[-1]["type"], "artifact.integrity_violation")

    def test_artifact_path_substitution_and_symlink_escape_gate_before_launch(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        outside = self.root / "outside-report.md"
        outside.write_text("untrusted\n", encoding="utf-8")
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_attempt"]["paths"]["report"] = str(outside)
        state_path.write_text(json.dumps(state), encoding="utf-8")

        substituted = self.cli(
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

        self.assertNotEqual(substituted.returncode, 0)
        self.assertIn("escapes the pinned planning run", substituted.stderr)
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["current_stage"],
            "integrity-violation",
        )

        # A separate run proves filesystem resolution, not just JSON path validation.
        second = self.runs / "plan-symlink"
        initialized = self.cli(
            STATE,
            "init",
            "--task",
            "Plan symlink safety",
            "--repo",
            str(self.repo),
            "--run-id",
            "plan-symlink",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
            "--new-run",
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(
            self.cli(RENDER, "--run-dir", str(second), "--stage", "spec", "--pass", "1").returncode,
            0,
        )
        second_state = json.loads((second / "state.json").read_text(encoding="utf-8"))
        second_prompt = Path(second_state["current_attempt"]["paths"]["prompt"])
        second_prompt.unlink()
        second_prompt.symlink_to(outside)
        escaped = self.cli(
            TREE, "baseline", "--run-dir", str(second), "--stage", "spec", "--pass", "1"
        )
        self.assertNotEqual(escaped.returncode, 0)
        self.assertIn("escapes the pinned planning run", escaped.stderr)

    def test_malformed_reviewer_attempt_preserves_stale_candidate_and_clean_retry_ignores_it(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.render_and_baseline("spec-review")
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        stale_candidate = Path(state["current_attempt"]["paths"]["candidate"])
        stale_candidate.write_text(
            spec(solution="A stale correction from the malformed attempt."), encoding="utf-8"
        )
        stale_report = Path(state["current_attempt"]["paths"]["report"])
        stale_report.write_text("malformed\n", encoding="utf-8")

        malformed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))

        self.assertNotEqual(malformed.returncode, 0)
        failed = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["current_stage"], "spec-review")
        self.assertIsNone(failed["prepared_stage"])
        self.assertEqual(failed["attempt_history"][-1]["status"], "malformed")
        self.assertTrue(stale_candidate.is_file())
        prepared = self.cli(
            STATE,
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--stage",
            "spec-review",
            "--pass",
            "1",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        retry = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(retry["current_attempt"]["attempt_id"], "spec-review-1-attempt-2")
        self.assertNotEqual(
            Path(retry["current_attempt"]["paths"]["candidate"]), stale_candidate
        )
        self.render_and_baseline("spec-review")
        digest = validate_spec(draft)["sha256"]
        Path(retry["current_attempt"]["paths"]["report"]).write_text(
            review_report("pass", digest, digest), encoding="utf-8"
        )
        clean = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(clean.returncode, 0, clean.stderr)
        final = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(final["reviewed_spec"]["candidate"], str(draft.resolve()))
        self.assertIn(
            str(stale_candidate.relative_to(self.run_dir.resolve())),
            final["artifact_audit"]["stale"],
        )

    def test_unexpected_run_file_is_audited_but_never_consumed_by_retry(self):
        self.assertEqual(self.init_direct().returncode, 0)
        unexpected = self.run_dir / "artifacts" / "not-declared.md"
        unexpected.write_text("audit only\n", encoding="utf-8")
        prepared = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIn("artifacts/not-declared.md", state["artifact_audit"]["unexpected"])
        self.assertNotIn(
            "artifacts/not-declared.md",
            {entry["path"] for entry in state["artifact_manifest"].values()},
        )

    def test_failed_prompt_emission_preserves_bytes_and_retry_uses_fresh_paths(self):
        self.assertEqual(self.init_direct().returncode, 0)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        first_prompt = Path(state["current_attempt"]["paths"]["prompt"])
        first_prompt.write_text("orphan from interrupted renderer\n", encoding="utf-8")

        failed = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("unexpected prompt", failed.stderr)
        prepared = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        retry = json.loads(state_path.read_text(encoding="utf-8"))
        second_prompt = Path(retry["current_attempt"]["paths"]["prompt"])
        self.assertEqual(retry["current_attempt"]["attempt_id"], "spec-1-attempt-2")
        self.assertNotEqual(first_prompt, second_prompt)
        self.assertEqual(
            first_prompt.read_text(encoding="utf-8"), "orphan from interrupted renderer\n"
        )
        rendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        audited = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn("prompts/spec-1.md", audited["artifact_audit"]["unexpected"])

    def test_pre_manifest_run_requires_human_restart_or_reviewed_migration(self):
        self.assertEqual(self.init_direct().returncode, 0)
        state_path = self.run_dir / "state.json"
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy["schema_version"] = 1
        legacy.pop("artifact_manifest_version")
        legacy.pop("artifact_manifest")
        legacy.pop("artifact_attempt_counters")
        state_path.write_text(json.dumps(legacy), encoding="utf-8")

        refused = self.cli(
            STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "spec", "--pass", "1"
        )

        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("predates artifact-manifest format", refused.stderr)
        self.assertIn("human decision", refused.stderr)
        self.assertIn("restart", refused.stderr)

    def test_spec_author_collision_requires_recorded_confirmation_and_survives_resume(self):
        self.assign_planning_profile("spec", "codex-astra-medium")

        initialized = self.init_direct()

        self.assertEqual(initialized.returncode, 2, initialized.stderr)
        self.assertEqual(initialized.stderr, "")
        initialized_payload = json.loads(
            next(
                line
                for line in initialized.stdout.splitlines()
                if line.startswith('{"diversity_warning"')
            )
        )
        self.assertIsNone(initialized_payload["prepared"])
        self.assertIn("confirmation_command", initialized_payload["diversity_warning"])
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
                "profile": "codex-astra-medium",
                "harness": "codex",
                "model": "gpt-6-astra",
            },
        )
        self.assertEqual(
            pending["reviewer"],
            {
                "role": "planning.reviewer",
                "profile": "codex-astra-high",
                "harness": "codex",
                "model": "gpt-6-astra",
            },
        )
        for value in (
            "planning.spec",
            "planning.reviewer",
            "codex-astra-medium",
            "codex-astra-high",
            "codex",
            "gpt-6-astra",
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
        prepared_payload = self.assert_gated_prepare(
            "spec", status["recommended_next"]["command"]
        )
        self.assertEqual(
            prepared_payload["diversity_warning"]["author"], pending["author"]
        )
        self.assertEqual(
            prepared_payload["diversity_warning"]["reviewer"], pending["reviewer"]
        )
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
        self.assertNotIn("diversity_warning", prepared_again.stdout)
        self.render_and_baseline("spec")
        self.launch_prepared_stage("spec")

    def test_refusing_spec_author_collision_preserves_stage_and_configuration_guidance(self):
        self.assign_planning_profile("spec", "codex-astra-xhigh")
        self.assertEqual(self.init_direct().returncode, 2)

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
        self.assertIn("human inspection", status["recommended_next"]["action"])
        self.assertIn("shared configuration", status["recommended_next"]["action"])
        self.assertIn(" context ", f" {status['recommended_next']['command']} ")
        self.assertNotIn("diversity-confirmation", status["recommended_next"]["command"])

    def test_refusing_a_changed_diverse_resolution_records_it_without_preparing(self):
        self.assign_planning_profile("spec", "codex-astra-xhigh")
        self.assertEqual(self.init_direct().returncode, 2)
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
        self.assign_planning_profile("spec", "codex-astra-xhigh")
        self.assertEqual(self.init_direct().returncode, 2)
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
        self.assign_planning_profile("spec", "codex-astra-xhigh")
        self.assign_planning_profile("tickets", "codex-astra-xhigh")
        self.assertEqual(self.init_direct().returncode, 2)
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
        self.assign_planning_profile("tickets", "codex-astra-xhigh")

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

        self.assertEqual(approved.returncode, 2, approved.stderr)
        self.assertEqual(approved.stderr, "")
        approved_payload = json.loads(approved.stdout)
        self.assertIsNone(approved_payload["prepared"])
        self.assertEqual(
            approved_payload["diversity_warning"]["author"]["role"],
            "planning.tickets",
        )
        self.assertEqual(
            approved_payload["diversity_warning"]["reviewer"]["role"],
            "planning.reviewer",
        )
        self.assertIn(
            "--decision confirm",
            approved_payload["diversity_warning"]["confirmation_command"],
        )
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "tickets")
        self.assertIsNone(state["prepared_stage"])
        self.assertEqual(state["diversity_confirmation"]["author"]["role"], "planning.tickets")
        self.assertFalse(list((self.run_dir / "stage-snapshots").glob("tickets-1-*.json")))
        self.assertIn("planning.tickets", approved.stdout)

        self.assert_gated_prepare(
            "tickets", approved_payload["diversity_warning"]["confirmation_command"]
        )

        confirmed = self.decide_diversity(
            "confirm", "The alternate provider quota is exhausted"
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        prepared = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
            "prepared_stage"
        ]
        self.assertEqual(prepared["stage"], "tickets")

    def test_changed_collision_resolution_invalidates_confirmation_and_asks_again(self):
        self.assign_planning_profile("spec", "codex-astra-xhigh")
        self.assertEqual(self.init_direct().returncode, 2)
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

        self.assertEqual(prepared.returncode, 2, prepared.stderr)
        self.assertIsNone(json.loads(prepared.stdout)["prepared"])
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
        self.assertNotIn("diversity_warning", initialized.stdout)
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

    def test_approved_spec_tampering_gates_before_ticket_prompt_consumption(self):
        approved_path = self.approve_spec_to_tickets()
        approved_path.write_text(
            approved_path.read_text(encoding="utf-8") + "\nchanged after approval\n",
            encoding="utf-8",
        )

        rendered = self.cli(
            RENDER, "--run-dir", str(self.run_dir), "--stage", "tickets", "--pass", "1"
        )

        self.assertNotEqual(rendered.returncode, 0)
        self.assertIn("artifact", rendered.stderr)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_stage"], "integrity-violation")
        self.assertEqual(state["gate_decisions"][-1]["reason"], "run artifact integrity violation")

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
        self.assertEqual(final["deliverables"], {"tracker": final["published_tracker"]["path"]})
        event = json.loads((self.run_dir / "events.jsonl").read_text().splitlines()[-1])
        self.assertEqual(event["data"]["deliverables"], final["deliverables"])
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

        self.render_and_baseline("tickets", 2)
        self.write_tickets_handoff(2)
        accepted = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.render_and_baseline("tickets-review", 2)
        self.write_tickets_review()
        reviewed = self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir))
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        target = self.repo / ".scratch" / state["tracker_slug"]
        approved = self.ticket_approval("approve", "Accept revised tickets", target=target)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        published = self.cli(STATE, "publish", "--run-dir", str(self.run_dir))
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertTrue((target / "README.md").is_file())

    def test_ticket_revision_rejects_renamed_frozen_slug(self):
        self.reach_ticket_approval()
        revised = self.ticket_approval("revise", "Clarify acceptance criteria")
        self.assertEqual(revised.returncode, 0, revised.stderr)
        self.render_and_baseline("tickets", 2)
        state = json.loads((self.run_dir / "state.json").read_text())
        data = tracker_proposal(Path(state["approved_spec"]["path"]), slug="renamed-tracker")
        self.write_tickets_handoff(2, data=data)
        rejected = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
        self.assertIn("tracker.slug", rejected.stderr)
        self.assertIn("frozen", rejected.stderr)

    def test_ticket_approval_and_publication_enforce_frozen_slug(self):
        self.reach_ticket_approval()
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text())
        frozen = state["tracker_slug"]
        target = self.repo / ".scratch" / frozen
        # Model a digest-valid candidate that disagrees with the run's fixed identity.
        state["tracker_slug"] = "different-fixed-slug"
        state_path.write_text(json.dumps(state))
        rejected = self.ticket_approval("approve", "Approve tickets", target=target)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("tracker.slug must equal frozen", rejected.stderr)
        self.assertFalse(target.exists())
        state["tracker_slug"] = frozen
        state_path.write_text(json.dumps(state))
        approved = self.ticket_approval("approve", "Approve tickets", target=target)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        state = json.loads(state_path.read_text())
        state["tracker_slug"] = "different-fixed-slug"
        state_path.write_text(json.dumps(state))
        for result in (
            self.ticket_approval("approve", "Repeat approval", target=target),
            self.cli(STATE, "publish", "--run-dir", str(self.run_dir)),
        ):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("tracker.slug must equal frozen", result.stderr)
        self.assertFalse(target.exists())

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
            checked=checked_evidence(["ISSUE-001"]),
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
        self.assertIn("artifact byte size changed", reviewed.stderr)
        self.assertEqual(
            json.loads((self.run_dir / "state.json").read_text())["current_stage"],
            "integrity-violation",
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

    def test_reviewed_candidate_tampering_gates_before_spec_approval(self):
        self.assertEqual(self.init_direct().returncode, 0)
        self.render_and_baseline("spec")
        draft = self.write_author_handoff()
        self.assertEqual(
            self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir)).returncode, 0
        )
        self.render_and_baseline("spec-review")
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        candidate = Path(state["current_attempt"]["paths"]["candidate"])
        candidate.write_text(
            spec(solution="Implement the reviewed correction."), encoding="utf-8"
        )
        input_digest = validate_spec(draft)["sha256"]
        candidate_digest = validate_spec(candidate)["sha256"]
        Path(state["current_attempt"]["paths"]["report"]).write_text(
            review_report(
                "pass_with_fixes",
                input_digest,
                candidate_digest,
                corrections="- Corrected established wording.",
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            self.cli(STATE, "accept-review", "--run-dir", str(self.run_dir)).returncode, 0
        )
        candidate.write_text(candidate.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")

        refused = self.cli(
            STATE,
            "approval",
            "--run-dir",
            str(self.run_dir),
            "--decision",
            "approve",
            "--reason",
            "Must not approve changed bytes",
        )

        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(
            json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
                "current_stage"
            ],
            "integrity-violation",
        )
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
        gated = self.cli(STATE, "accept-author", "--run-dir", str(self.run_dir))
        self.assertNotEqual(gated.returncode, 0)
        self.assertEqual(
            json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))[
                "current_stage"
            ],
            "integrity-violation",
        )

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
        self.assertIn("artifact byte size changed", tampered.stderr)
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
        legacy["workflows"]["grilling"]["web"] = "codex-astra-xhigh"
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
        self.assertIn("workflow=grilling worker=web profile=codex-astra-xhigh field=harness", proc.stderr)
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
        self.relative_cli_paths = True
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
        self.assertEqual(
            {
                entry["kind"]
                for entry in state["artifact_manifest"].values()
                if entry["kind"].startswith("grilling-source")
            },
            {"grilling-source-json", "grilling-source-markdown"},
        )
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
        self.assertEqual(
            state["artifact_manifest"][state["normalized_grilling_input"]["manifest_id"]][
                "kind"
            ],
            "normalized-grilling-input",
        )
        normalized = json.loads((run_dir / "grilling-input.json").read_text())
        self.assertEqual(normalized["assumptions"][1]["value"], "Zwei korrigiert")
        self.assertIsNone(normalized["assumptions"][2]["value"])
        self.assertEqual(normalized["decisions"][0]["status"], "decided")
        rendered = self.cli(RENDER, "--run-dir", str(run_dir), "--stage", "spec", "--pass", "1")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        prompt = (run_dir / "prompts" / "spec-1.md").read_text()
        self.assertIn("grilling-input.json", prompt)
        self.assertNotIn("inputs/grilling-source.json", prompt)
        (run_dir / "grilling-input.json").write_text("{}\n", encoding="utf-8")
        gated = self.cli(
            TREE, "baseline", "--run-dir", str(run_dir), "--stage", "spec", "--pass", "1"
        )
        self.assertNotEqual(gated.returncode, 0)
        self.assertEqual(
            json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["current_stage"],
            "integrity-violation",
        )

    def test_imported_grilling_source_tampering_gates_before_revalidation_transition(self):
        artifact, markdown = self.grilling_pair()
        run_dir = self.runs / "plan-grilling-tamper"
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
            "plan-grilling-tamper",
            "--runs-root",
            str(self.runs),
            "--workspace-id",
            "WORKSPACE-1",
            "--config",
            str(self.config),
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        (run_dir / state["grilling_import"]["copied_json"]).write_text("{}\n", encoding="utf-8")
        outcomes = self.root / "unused-outcomes.json"
        outcomes.write_text('{"accepted": false}\n', encoding="utf-8")

        refused = self.cli(
            STATE,
            "revalidate",
            "--run-dir",
            str(run_dir),
            "--outcomes",
            str(outcomes),
        )

        self.assertNotEqual(refused.returncode, 0)
        failed = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["current_stage"], "integrity-violation")
        self.assertEqual(failed["gate_decisions"][-1]["reason"], "run artifact integrity violation")

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
        self.assertEqual(Path(state["author_spec"]["draft"]), draft.resolve())
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
        self.relative_cli_paths = True
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
        self.assertEqual(final["deliverables"], {"tracker": final["published_tracker"]["path"]})
        event = json.loads((self.run_dir / "events.jsonl").read_text().splitlines()[-1])
        self.assertEqual(event["data"]["deliverables"], final["deliverables"])
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
                # A blocked review stops before it reaches every section, so partial evidence
                # must still carry the real lifecycle transition.
                checked=checked_evidence(["Problem Statement", "Solution"]),
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
