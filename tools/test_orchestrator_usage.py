#!/usr/bin/env python3
"""Regression tests for orchestrator_usage.py: workflow detection and call classification."""

import json
import tempfile
import unittest
from pathlib import Path

import orchestrator_usage as ou

CHAIN = ou.WORKFLOWS["issue-chain"]
PLANNING = ou.WORKFLOWS["planning"]
GRILLING = ou.WORKFLOWS["grilling"]


def evidence_for(workflow, *commands):
    evidence = ou.new_evidence()
    for command in commands:
        ou.scan_command(command, evidence, workflow)
    return evidence


class WorkflowDetection(unittest.TestCase):
    def test_skill_directory_identifies_the_workflow(self):
        command = "python3 ~/.claude/skills/cmux-planning/scripts/pane_ctl.py observe"
        self.assertTrue(ou.is_orchestrator(evidence_for(PLANNING, command)))
        self.assertFalse(ou.is_orchestrator(evidence_for(CHAIN, command)))
        self.assertFalse(ou.is_orchestrator(evidence_for(GRILLING, command)))

    def test_workflow_only_script_identifies_the_workflow_behind_a_variable(self):
        self.assertTrue(ou.is_orchestrator(evidence_for(GRILLING, 'python3 "$S/launch_wave.py" --round 1')))
        self.assertTrue(ou.is_orchestrator(evidence_for(PLANNING, "python3 $S/tree_integrity.py baseline")))
        self.assertTrue(ou.is_orchestrator(evidence_for(CHAIN, "python3 $S/issue_state.py set")))
        # A sibling's only-script is never evidence for another workflow.
        self.assertFalse(evidence_for(CHAIN, "python3 $S/launch_wave.py")["soft"])
        self.assertFalse(evidence_for(GRILLING, "python3 $S/tree_integrity.py")["soft"])

    def test_composite_scripts_count_as_orchestrator_executions(self):
        for script in ("stage.py capture", "wave.py round", "baseline_delta.py --run-dir r"):
            with self.subTest(script=script):
                self.assertTrue(evidence_for(PLANNING, f"python3 $S/{script}")["soft"])

    def test_shared_script_behind_a_variable_needs_the_skill_directory(self):
        command = "python3 $S/run_state.py event"
        self.assertFalse(ou.is_orchestrator(evidence_for(PLANNING, command)))
        self.assertTrue(ou.is_orchestrator(evidence_for(
            PLANNING, "S=~/.claude/skills/cmux-planning/scripts", command)))

    def test_mixed_session_counts_where_it_touched_a_run_of_the_workflow(self):
        commands = ("S=/x/cmux-planning/scripts; T=/x/cmux-grilling/scripts",
                    "python3 $S/run_state.py event --run-dir .scratch/orchestrator/runs/plan-demo-1")
        self.assertTrue(ou.is_orchestrator(evidence_for(PLANNING, *commands)))
        self.assertFalse(ou.is_orchestrator(evidence_for(GRILLING, *commands)))

    def test_run_prefix_attributes_runs(self):
        self.assertTrue(PLANNING.owns_run("plan-demo-2026-09-22-1702"))
        self.assertTrue(GRILLING.owns_run("grill-demo"))
        self.assertTrue(CHAIN.owns_run("chain-issue-001"))
        for run in ("plan-demo", "grill-demo"):
            self.assertFalse(CHAIN.owns_run(run))
        self.assertFalse(PLANNING.owns_run("grill-demo"))
        self.assertFalse(GRILLING.owns_run("chain-issue-001"))

    def test_quoted_invocation_is_discussion_not_execution(self):
        command = "grep -n 'python3 cmux-grilling/scripts/launch_wave.py' README.md"
        self.assertFalse(ou.is_orchestrator(evidence_for(GRILLING, command)))


class Classification(unittest.TestCase):
    def test_stage_capture_after_monitor_is_bookkeeping(self):
        previous = ou.classify_tool("Monitor", None)
        self.assertEqual(previous, "wait")
        self.assertEqual(ou.classify_bash("python3 $S/stage.py capture --run-dir r", previous),
                         "bookkeeping")
        # The plain screen read after a wait stays a wait.
        self.assertEqual(ou.classify_bash("cmux read-screen --surface s", previous), "wait")

    def test_composite_verbs_are_classified_by_verb(self):
        expected = {"open": "pane-lifecycle", "round": "pane-lifecycle",
                    "deliver": "pane-lifecycle", "started": "pane-lifecycle",
                    "mark-started": "pane-lifecycle", "capture": "bookkeeping",
                    "gate": "bookkeeping"}
        for verb, category in expected.items():
            for script in ("stage.py", "wave.py"):
                with self.subTest(script=script, verb=verb):
                    self.assertEqual(ou.classify_bash(f"python3 $S/{script} {verb} --run-dir r",
                                                      "wait"), category)

    def test_baseline_delta_is_bookkeeping(self):
        self.assertEqual(ou.classify_bash("python3 $S/baseline_delta.py --run-dir r"), "bookkeeping")

    def test_existing_rules_are_unchanged(self):
        self.assertEqual(ou.classify_bash("python3 $S/pane_ctl.py deliver"), "pane-lifecycle")
        self.assertEqual(ou.classify_bash("cmux read-screen --surface s"), "pane-lifecycle")
        self.assertEqual(ou.classify_bash("python3 $S/await_report.py --run-dir r"), "wait")


def write_transcript(path: Path, commands: list[str], first_user: str = "run the grilling"):
    lines = [{"type": "user", "cwd": "/repo", "message": {"content": first_user}}]
    for index, command in enumerate(commands):
        lines.append({
            "type": "assistant", "requestId": f"req-{index}", "cwd": "/repo",
            "timestamp": f"2026-09-13T10:0{index}:00Z",
            "message": {"usage": {"input_tokens": 10, "output_tokens": 5,
                                  "cache_read_input_tokens": 1000},
                        "content": [{"type": "tool_use", "name": "Bash",
                                     "input": {"command": command}}]},
        })
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


class ClaudeSessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"

    def test_grilling_session_is_selected_only_for_grilling(self):
        write_transcript(self.path, [
            "python3 cmux-grilling/scripts/run_state.py init --run-dir .scratch/orchestrator/runs/grill-demo",
        ])
        session = ou.parse_claude(self.path, GRILLING)
        self.assertIsNotNone(session)
        self.assertEqual(session["run_ids"], ["grill-demo"])
        self.assertIsNone(ou.parse_claude(self.path, CHAIN))
        self.assertIsNone(ou.parse_claude(self.path, PLANNING))

    def test_worker_session_is_never_an_orchestrator(self):
        write_transcript(
            self.path, ["python3 cmux-grilling/scripts/run_state.py status"],
            first_user="Your round task is in .scratch/orchestrator/runs/grill-demo/prompts/round-1-web.md.")
        self.assertIsNone(ou.parse_claude(self.path, GRILLING))


class GrillingRounds(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        run_dir = self.root / ".scratch" / "orchestrator" / "runs" / "grill-demo"
        (run_dir / "reports").mkdir(parents=True)
        for name in ("round-1-web", "round-1-docs", "round-2-web", "round-2-docs", "notes"):
            (run_dir / "reports" / f"{name}.md").write_text("x", encoding="utf-8")
        events = [
            {"type": "run.init", "time": "2026-09-13T10:00:00+00:00"},
            {"type": "grill.question", "time": "2026-09-13T10:02:30+00:00"},
            {"type": "grill.question", "time": "2026-09-13T10:05:00+00:00"},
        ]
        (run_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events), encoding="utf-8")
        self.run_dir = run_dir

    def call(self, minute, total):
        call = ou.Call(f"2026-09-13T10:0{minute}:00+00:00", total, 0, 0, 0, None)
        call.category = "other-bash"
        call.run_id = "grill-demo"
        return call

    def test_rounds_are_the_stage_unit(self):
        state = ou.read_run_state(self.run_dir, GRILLING)
        self.assertEqual(state["stages_completed"], 2)
        self.assertEqual(state["first_question"], "2026-09-13T10:02:30+00:00")
        # Without the workflow every report file stays its own stage, as before.
        self.assertEqual(ou.read_run_state(self.run_dir)["stages_completed"], 5)

    def test_session_start_is_reported_apart_from_the_rounds(self):
        calls = [self.call(0, 100), self.call(1, 100), self.call(2, 100),
                 self.call(3, 400), self.call(4, 400), self.call(5, 400), self.call(6, 400)]
        session = ou.build_session("claude", "s1", "p", str(self.root), calls)
        [row] = ou.aggregate_runs([session], GRILLING)
        self.assertEqual(row["session_start_calls"], 3)
        self.assertEqual(row["session_start_tokens"], 300)
        self.assertEqual(row["calls_per_stage"], 2.0)
        self.assertEqual(row["tokens_per_stage"], 800)

    def test_other_workflows_keep_their_columns(self):
        calls = [self.call(0, 100)]
        session = ou.build_session("claude", "s1", "p", str(self.root), calls)
        self.assertEqual(ou.aggregate_runs([session], PLANNING), [])
        chain_rows = ou.aggregate_runs([session])
        self.assertTrue(chain_rows)
        self.assertNotIn("session_start_calls", chain_rows[0])


if __name__ == "__main__":
    unittest.main()
