"""Exercise gate enforcement through the run-state CLI in isolated run directories."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_state import EVIDENCE_GATED_STAGES as STAGES
from test_support import passing_gate_evidence, seed_capture, seed_evidence


SCRIPT = Path(__file__).with_name("run_state.py")


class GateEvidenceCli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name)
        self.reset()

    def reset(self, stage="implement"):
        self.state = {"workflow": "issue-chain", "layout_version": 1,
                      "current_stage": stage, "prepared_stage": {"pass": 99}}
        (self.run_dir / "state.json").write_text(json.dumps(self.state))
        (self.run_dir / "events.jsonl").write_text("")

    def capture(self, stage, pass_num):
        seed_capture(self.run_dir, stage, pass_num, time="same timestamp")

    def evidence(self, stage, pass_num, verdict="pass", **fields):
        seed_evidence(self.run_dir, stage, pass_num, verdict, time="same timestamp", **fields)

    def gate(self, stage, decision="advance"):
        return subprocess.run([
            sys.executable, str(SCRIPT), "gate", "--run-dir", str(self.run_dir),
            "--stage", stage, "--decision", decision, "--reason", "test",
            "--next-stage", "next"], capture_output=True, text=True, timeout=30)

    def refused(self, stage, pass_text):
        before = {p.relative_to(self.run_dir): p.read_bytes()
                  for p in self.run_dir.rglob("*") if p.is_file()}
        result = self.gate(stage)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(stage, result.stderr)
        self.assertIn(pass_text, result.stderr)
        self.assertIn("evidence", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(before, {p.relative_to(self.run_dir): p.read_bytes()
                                 for p in self.run_dir.rglob("*") if p.is_file()})

    def test_missing_evidence_refuses_each_reporting_stage_without_mutation(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.reset(stage)
                self.capture(stage, 2)
                self.refused(stage, "2")

    def test_no_capture_refused_even_with_passing_event(self):
        self.evidence("implement", 2)
        self.refused("implement", "pass unknown")

    def test_pass_comes_from_latest_capture_and_event_order_not_timestamps(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.reset(stage)
                passing_gate_evidence(self.run_dir, stage, 7)
                self.capture(stage, 2)
                self.refused(stage, "2")
                self.evidence(stage, 2)
                # Another stage's capture does not invalidate this evidence.
                self.capture("triage", 3)
                result = self.gate(stage)
                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads((self.run_dir / "state.json").read_text())
                self.assertEqual(state["current_stage"], "next")
                self.assertEqual(state["gate_decisions"][-1]["decision"], "advance")
                self.assertTrue(list((self.run_dir / "gate-decisions").glob("*.json")))

    def test_recapture_same_pass_invalidates_old_evidence(self):
        passing_gate_evidence(self.run_dir, "implement", 2)
        self.capture("implement", 2)
        self.refused("implement", "2")

    def test_new_launch_refuses_old_evidence_until_captured_and_verified(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.reset(stage)
                passing_gate_evidence(self.run_dir, stage, 1)
                seed_capture(self.run_dir, stage, 2, message=f"launched {stage}-2",
                             time="same timestamp")
                self.refused(stage, f"pass 2: launched without a later report-captured snapshot")
                # Evidence alone cannot replace the missing report capture.
                self.evidence(stage, 2)
                self.refused(stage, "pass 2: launched without a later report-captured snapshot")
                self.capture(stage, 2)
                self.refused(stage, "pass 2")
                self.evidence(stage, 2)
                # A launch for another stage does not invalidate this stage.
                seed_capture(self.run_dir, "triage", 3, message="launched triage-3")
                result = self.gate(stage)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_null_fields_do_not_crash(self):
        self.capture("implement", 2)
        with (self.run_dir / "events.jsonl").open("a") as stream:
            stream.write(json.dumps({"type": "tree.snapshot", "message": None}) + "\n")
            stream.write(json.dumps({"type": "orchestrator.verified", "message": "test evidence",
                                     "data": None}) + "\n")
        self.refused("implement", "2")

    def test_event_command_cannot_forge_test_evidence(self):
        self.capture("implement", 2)
        forged = subprocess.run([
            sys.executable, str(SCRIPT), "event", "--run-dir", str(self.run_dir),
            "--type", "orchestrator.verified", "--message", "test evidence",
            "--data", json.dumps({"stage": "implement", "pass": 2, "verdict": "pass"})],
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(forged.returncode, 0)
        self.assertIn("check_evidence.py", forged.stderr)
        self.refused("implement", "2")

    def test_unrelated_failed_and_wrong_pass_events_do_not_authorize(self):
        self.capture("implement", 2)
        self.evidence("review", 2)
        self.evidence("implement", 1)
        self.evidence("implement", 2, "fail")
        self.evidence("implement", 2, message="some other verification")
        self.evidence("implement", 2, type="worker.finished")
        self.refused("implement", "2")

    def test_triage_and_all_nonadvance_decisions_need_no_evidence(self):
        for stage in (*STAGES, "triage"):
            for decision in ("stop", "blocked", "hitl", "pending", *(["advance"] if stage == "triage" else [])):
                with self.subTest(stage=stage, decision=decision):
                    self.reset(stage)
                    result = self.gate(stage, decision)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    state = json.loads((self.run_dir / "state.json").read_text())
                    self.assertEqual(state["gate_decisions"][-1]["decision"], decision)


if __name__ == "__main__":
    unittest.main()
