"""Planning board projection and fail-soft transition boundary regressions."""
import argparse
import contextlib
import io
import itertools
import json
import shlex
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import planning_state
import planning_recovery
import planning_diversity
import orchestrator_lib
import run_briefing


class PlanningBoard(unittest.TestCase):
    def state(self, stage, **extra):
        return dict(workflow="planning", current_stage=stage, tracker_slug="feature",
                    spec_pass=2, spec_review_pass=3, tickets_pass=4, tickets_review_pass=5, **extra)

    def test_projection_table(self):
        rows = [
            ("input", "running", "input validation", 0, "Input · Validation"),
            ("awaiting-grilling-revalidation", "waiting", "grilling input revalidation", 0, "Input · Revalidation"),
            ("spec", "running", "feature", 0, "Spec · Author 2"),
            ("spec-review", "running", "feature", 1/7, "Spec · Review 3"),
            ("awaiting-spec-approval", "waiting", "spec approval", 2/7, "Spec · Approval"),
            ("tickets", "running", "feature", 3/7, "Tickets · Author 4"),
            ("tickets-review", "running", "feature", 4/7, "Tickets · Review 5"),
            ("awaiting-ticket-approval", "waiting", "ticket approval", 5/7, "Tickets · Approval"),
            ("ready-to-publish", "running", "feature", 6/7, "Publish"),
            ("complete", "done", "2 tickets published", 1, "Complete"),
            ("future", "running", "feature", 0, "future"),
        ]
        for stage, *expected in rows:
            with self.subTest(stage=stage):
                state = self.state(stage, published_tracker={"ticket_ids": ["A", "B"]})
                self.assertEqual(run_briefing.project_board(state, []), tuple(expected))
                if stage in run_briefing.PLANNING_VALUE_ORDER:
                    halted = self.state("integrity-violation", gate_decisions=[{"stage": stage, "reason": "changed"}])
                    self.assertEqual(run_briefing.project_board(halted, []), ("hitl", f"{stage}: changed", expected[2], expected[3]))
        for stage in run_briefing.PLANNING_STAGES:
            base = run_briefing.project_board(self.state(stage), [])
            for status in ("pending", "refused", "confirmed"):
                state = self.state(stage, diversity_confirmation={"stage": stage, "status": status})
                actual = run_briefing.project_board(state, [])
                self.assertEqual(actual, ("waiting", "author/reviewer model diversity confirmation", *base[2:]) if status != "confirmed" else base)
            for blocked in (stage + "-blocked", "integrity-violation"):
                state = self.state(blocked, gate_decisions=[{"stage": "old", "reason": "old"}, {"stage": stage, "reason": "bad · input\nnow"}])
                self.assertEqual(run_briefing.project_board(state, []), ("hitl" if blocked == "integrity-violation" else "blocked", f"{stage}: bad - input now", *base[2:]))
        state = self.state("integrity-violation", gate_decisions=[{"stage": "run", "reason": "artifact changed"}])
        self.assertEqual(run_briefing.project_board(state, []), ("hitl", "run: artifact changed", 0, "run"))

    def test_watcher_attempt_boundaries(self):
        def event(kind, **data):
            return {"type": kind, "data": {"stage": "spec", "pass": 2, "surface_id": "A", **data}}
        state = self.state("spec", prepared_stage={"snapshot_id": "new"})
        launch = event("pane.launched", stage_snapshot_id="new")
        dead = event("worker.waiting", outcome="pane_dead")
        deadline = event("worker.waiting", outcome="deadline", extension=0)
        extended = event("worker.waiting", outcome="deadline", extension=1)
        approved = event("worker.waiting", outcome="extension_approved")
        for stop, reason in ((dead, "worker pane dead, relaunch decision needed"),
                             (deadline, "report deadline exceeded, extension decision needed"),
                             (extended, "extended deadline exceeded, relaunch decision needed")):
            with self.subTest(reason=reason):
                self.assertEqual(run_briefing.project_board(state, [launch, stop])[:2], ("hitl", "spec-2: " + reason))
                self.assertEqual(run_briefing.project_board(state, [launch, stop, approved])[0], "running")
        for events in ([dead], [dead, launch],
                       [event("pane.launched", stage_snapshot_id="old"), dead],
                       [launch, dead, launch],
                       [launch, dead, event("worker.launch_sent")],
                       [launch, event("worker.waiting", outcome="not_started")]):
            self.assertEqual(run_briefing.project_board(state, events)[0], "running")
        for stop, outcome in ((deadline, "report"), (dead, "pending")):
            with self.subTest(outcome=outcome):
                self.assertEqual(run_briefing.project_board(
                    state, [launch, stop, event("worker.waiting", outcome=outcome)])[0], "running")
        new_launch = event("pane.launched", stage_snapshot_id="new", surface_id="B")
        self.assertEqual(run_briefing.project_board(state, [launch, dead, new_launch, dead])[0], "running")
        complete = {**state, "current_stage": "complete"}
        self.assertEqual(run_briefing.project_board(complete, [launch, dead])[::2], ("done", 1.0))

    def test_watcher_projection_agrees_with_recovery(self):
        reasons = {
            "dead": "worker pane dead, relaunch decision needed",
            "deadline": "report deadline exceeded, extension decision needed",
            "watcher-expired": "extended deadline exceeded, relaunch decision needed",
        }
        outcomes = ("pane_dead", "deadline", "extension_approved", "pending",
                    "report", "not_started", "future-outcome")
        stages = ("spec", "spec-review", "tickets", "tickets-review")
        # Neither side may shell out: projection is event-only, and
        # recovery has no workspace_id with which to probe health.
        with patch.object(run_briefing.subprocess, "run", side_effect=AssertionError(
                "unexpected health probe")) as subprocess_run:
            for stage, first, extension in itertools.product(stages, ("pane_dead", "deadline"), (0, 1)):
                state = self.state(stage, prepared_stage={"snapshot_id": "current"})
                pass_num = state[planning_recovery.PASS_KEYS[stage]]

                def event(kind, **data):
                    return {"type": kind, "data": {
                        "stage": stage, "pass": pass_num, "surface_id": "A", **data}}

                launch = event("pane.launched", stage_snapshot_id="current")
                stop = event("worker.waiting", outcome=first, extension=extension)
                fixtures = [
                    (f"final-{final}", [launch, stop, event(
                        "worker.waiting", outcome=final, extension=extension)], final)
                    for final in outcomes
                ]
                fixtures.extend([
                    ("no-launch", [stop], None),
                    ("old-snapshot", [event("pane.launched", stage_snapshot_id="old"), stop], None),
                    ("launch-sent", [launch, stop, event("worker.launch_sent")], None),
                    ("new-surface", [launch, stop, event(
                        "pane.launched", stage_snapshot_id="current", surface_id="B"), stop], None),
                    ("late-other-surface", [launch, stop, event(
                        "worker.waiting", outcome="report", surface_id="B")], first),
                    ("late-other-pass", [launch, stop, event(
                        "worker.waiting", outcome="report", **{"pass": pass_num + 1})], first),
                ])
                for name, events, expected_outcome in fixtures:
                    with self.subTest(stage=stage, first=first, extension=extension, fixture=name):
                        board = run_briefing.project_board(state, events)
                        pane = planning_recovery.pane_status(state, events, stage, pass_num, "unused")
                        self.assertEqual(pane.get("last_wait_outcome"), expected_outcome)
                        stopped = expected_outcome in {"pane_dead", "deadline"}
                        self.assertEqual(board[0] == "hitl", stopped)
                        if stopped:
                            health = ("dead" if expected_outcome == "pane_dead" else
                                      "watcher-expired" if extension else "deadline")
                            self.assertEqual(pane["extension"], extension)
                            self.assertEqual(pane["status"], health)
                            self.assertEqual(board[1], f"{stage}-{pass_num}: {reasons[pane['status']]}")
                        else:
                            self.assertEqual(board[:2], ("running", "feature"))
        subprocess_run.assert_not_called()

    def test_planning_resume_events_supersede_halted_recap(self):
        gate = {"type": "gate", "stage": "spec-review", "decision": "blocked", "reason": "human choice"}
        recap = {"type": "run.recap", "data": {"outcome": {"status": "halted", "stage": "spec-review", "decision": "blocked"}}}
        state = self.state("spec", gate_decisions=[gate], diversity_confirmation={"stage": "spec", "status": "pending"})
        self.assertEqual(run_briefing.project_board(state, [gate, recap, {"type": "run.briefing"}])[0], "blocked")
        resumed = [gate, recap, {"type": "spec.revision_requested"}, {"type": "diversity.confirmation_required"}]
        self.assertEqual(run_briefing.project_board(state, resumed)[:2], ("waiting", "author/reviewer model diversity confirmation"))

    def test_mirrored_constants_and_documented_contract(self):
        self.assertEqual(run_briefing.PLANNING_STAGES, orchestrator_lib.STAGES)
        self.assertEqual(run_briefing.PLANNING_BLOCKED_STAGES, planning_recovery.BLOCKED_STAGES)
        self.assertEqual(run_briefing.PLANNING_PASS_KEYS, planning_recovery.PASS_KEYS)
        self.assertEqual(run_briefing.PLANNING_PENDING_STATUSES, planning_diversity.PENDING_STATUSES)
        text = (Path(__file__).parents[1] / "SKILL.md").read_text()
        for phrase in ("Exits 7 and 8 publish `hitl`", "recorded extension or relaunch decision returns the card to `running`", "publish the board automatically at transitions", "stderr note and never a stop", "`--no-status` suppresses pill and board", "`--clear-status` clears both pill and board"):
            self.assertIn(phrase, text)

    def test_every_transition_preserves_results_on_cmux_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "state.json"
            events = root / "events.jsonl"
            log = root / "cmux.log"
            fake = root / "fake_cmux.py"
            fake.write_text(
                "import pathlib, sys\n"
                f"with pathlib.Path({str(log)!r}).open('a') as handle: handle.write(repr(sys.argv[1:]) + '\\n')\n"
                "sys.exit('offline')\n"
            )
            cmux_command = shlex.join([sys.executable, str(fake)])
            for command in planning_state.PUBLISHING_COMMANDS:
                for exit_code in (0, 2):
                    with self.subTest(command=command, exit_code=exit_code):
                        path.write_text(json.dumps(self.state("input", workspace_id="TEST")))
                        events.write_text("")
                        log.write_text("")
                        before = path.read_bytes()
                        args = argparse.Namespace(command=command, run_dir=directory, cmux_cmd=cmux_command)
                        def dispatch(args):
                            if command == "init":
                                args._board_run_dir = root
                                args._board_before = before
                            path.write_text(json.dumps(self.state("spec", workspace_id="TEST")))
                            events.write_text('{"type":"test"}\n')
                            print("original output")
                            return exit_code
                        out, err = io.StringIO(), io.StringIO()
                        with patch.object(planning_state, "dispatch_command", side_effect=dispatch), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                            self.assertEqual(planning_state.run(args), exit_code)
                        self.assertEqual(out.getvalue(), "original output\n")
                        self.assertEqual(err.getvalue(), "sidebar board not updated: offline\n")
                        self.assertEqual(len(log.read_text().splitlines()), 1)
                        self.assertIn("workspace-action", log.read_text())
                        self.assertEqual(json.loads(path.read_text())["current_stage"], "spec")
                        self.assertEqual(events.read_text(), '{"type":"test"}\n')
            for command in ("status", "context", "approval-view", "ticket-approval-view", "show-revalidation", "resume"):
                args = argparse.Namespace(command=command, run_dir=directory, cmux_cmd=cmux_command)
                with patch.object(planning_state, "dispatch_command", return_value=0), patch.object(run_briefing, "publish_board") as publish:
                    self.assertEqual(planning_state.run(args), 0)
                    publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
