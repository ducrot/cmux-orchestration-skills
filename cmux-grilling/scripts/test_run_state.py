#!/usr/bin/env python3
"""Run-state regression tests. Run: python3 scripts/test_run_state.py"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_state import (  # noqa: E402
    DECISION_STATUSES,
    DECISION_WHY_OPEN,
    NO_TRACKER_OUTPUT_DIR,
    detect_tracker,
    print_pending_decisions,
    record_decision,
    resolve_output,
    validate_decision,
)


def output_args(tracker: str | None = None, output_dir: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(tracker=tracker, output_dir=output_dir)


def make_tracker(root: Path, name: str) -> Path:
    (root / ".scratch" / name / "issues").mkdir(parents=True)
    return root / ".scratch" / name


class OutputPathDerivation(unittest.TestCase):
    def test_explicit_tracker_wins_over_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tracker(root, "other")
            tracker, output = resolve_output(output_args(tracker=".scratch/chosen"), root)
            self.assertEqual(tracker, Path(".scratch/chosen"))
            self.assertEqual(output, Path(".scratch/chosen/grilling"))

    def test_single_tracker_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tracker(root, "t12")
            tracker, output = resolve_output(output_args(), root)
            self.assertEqual(tracker, root / ".scratch/t12")
            self.assertEqual(output, root / ".scratch/t12/grilling")

    def test_several_trackers_stop_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tracker(root, "t12")
            make_tracker(root, "t13")
            with self.assertRaises(SystemExit) as caught:
                resolve_output(output_args(), root)
            self.assertIn("--tracker", str(caught.exception))

    def test_no_tracker_falls_back(self):
        """Grilling a free-standing plan without a tracker must stay possible."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker, output = resolve_output(output_args(), Path(tmp))
            self.assertIsNone(tracker)
            self.assertEqual(output, Path(NO_TRACKER_OUTPUT_DIR))

    def test_output_dir_overrides_and_skips_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_tracker(root, "t12")
            make_tracker(root, "t13")  # ambiguous, but never consulted
            tracker, output = resolve_output(output_args(output_dir="somewhere/else"), root)
            self.assertIsNone(tracker)
            self.assertEqual(output, Path("somewhere/else"))

    def test_output_dir_keeps_an_explicit_tracker(self):
        tracker, output = resolve_output(output_args(tracker=".scratch/t12", output_dir="out"), Path("."))
        self.assertEqual(tracker, Path(".scratch/t12"))
        self.assertEqual(output, Path("out"))

    def test_detection_ignores_directories_without_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".scratch" / "orchestrator" / "runs").mkdir(parents=True)
            make_tracker(root, "t12")
            self.assertEqual(detect_tracker(root), root / ".scratch/t12")


def valid_decision(**overrides) -> dict:
    entry = {
        "id": "D1",
        "question": "Halboffene Altersspanne anzeigen?",
        "why_open": "product",
        "context": "Was heute im Code steht und was auf dem Spiel steht.",
        "evidence": ["Runde 2 — Wortlaut", "Project.php:411-414"],
        "options": [
            {"label": "Ab 12 Jahren", "implication": "Kürzer, aber unpräzise"},
            {"label": "12 bis offen", "implication": "Präziser, aber sperrig"},
        ],
        "recommendation": "Ab 12 Jahren",
        "rationale": "Deckt sich mit der bestehenden Wortwahl.",
        "status": "open",
    }
    entry.update(overrides)
    return entry


class DecisionSchema(unittest.TestCase):
    def test_valid_entry_has_no_problems(self):
        self.assertEqual(validate_decision(valid_decision()), [])

    def test_statuses_and_reasons_are_the_documented_vocabulary(self):
        self.assertEqual(DECISION_STATUSES, ["open", "decided", "deferred"])
        self.assertEqual(DECISION_WHY_OPEN, ["product", "spec-deviation", "tie"])

    def test_missing_required_fields_are_reported(self):
        entry = valid_decision()
        del entry["context"]
        self.assertIn("missing or empty field: context", validate_decision(entry))

    def test_unknown_status_and_why_open_are_rejected(self):
        self.assertTrue(validate_decision(valid_decision(status="pending")))
        self.assertTrue(validate_decision(valid_decision(why_open="taste")))

    def test_evidence_must_be_non_empty_strings(self):
        self.assertTrue(validate_decision(valid_decision(evidence=["ok", ""])))
        self.assertTrue(validate_decision(valid_decision(evidence="Runde 2")))

    def test_a_fork_needs_at_least_two_options(self):
        self.assertTrue(validate_decision(valid_decision(options=[{"label": "A", "implication": "B"}])))
        self.assertTrue(validate_decision(valid_decision(options=[{"label": "A"}, {"label": "B"}])))

    def test_resolved_entries_need_an_outcome(self):
        self.assertTrue(validate_decision(valid_decision(status="decided")))
        self.assertEqual(validate_decision(valid_decision(status="decided", decision="Ab 12 Jahren")), [])
        self.assertEqual(validate_decision(valid_decision(status="deferred", decision="später")), [])


class RecordDecision(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifact = self.root / "plan-20260725.json"
        self.artifact.write_text(
            json.dumps({"run_id": "grill-x", "open_decisions": [valid_decision(), valid_decision(id="D2")]}),
            encoding="utf-8",
        )
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, **overrides) -> int:
        args = argparse.Namespace(
            run_dir=str(self.run_dir),
            artifact=str(self.artifact),
            id="D1",
            status="decided",
            decision="Ab 12 Jahren",
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return record_decision(args)

    def test_records_outcome_and_event(self):
        self.record()
        entry = json.loads(self.artifact.read_text(encoding="utf-8"))["open_decisions"][0]
        self.assertEqual(entry["status"], "decided")
        self.assertEqual(entry["decision"], "Ab 12 Jahren")
        self.assertTrue(entry["decided_at"])
        events = [json.loads(line) for line in (self.run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual(events[0]["type"], "grill.decision_recorded")
        self.assertEqual(events[0]["data"]["id"], "D1")

    def test_deferred_is_a_regular_outcome(self):
        self.record(status="deferred", decision="später entscheiden")
        entry = json.loads(self.artifact.read_text(encoding="utf-8"))["open_decisions"][0]
        self.assertEqual(entry["status"], "deferred")

    def test_unknown_id_stops(self):
        with self.assertRaises(SystemExit) as caught:
            self.record(id="D9")
        self.assertIn("D9", str(caught.exception))

    def test_artifact_without_decisions_stops(self):
        self.artifact.write_text(json.dumps({"run_id": "grill-x"}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.record()

    def test_schema_violation_stops_and_leaves_the_file_alone(self):
        broken = [valid_decision(evidence=[])]
        self.artifact.write_text(json.dumps({"open_decisions": broken}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.record()
        self.assertEqual(json.loads(self.artifact.read_text(encoding="utf-8"))["open_decisions"], broken)


class PendingDecisions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, statuses: list[str], mtime: float) -> Path:
        path = self.out / name
        decisions = [valid_decision(id=f"D{index + 1}", status=status, decision="x") for index, status in enumerate(statuses)]
        path.write_text(json.dumps({"open_decisions": decisions}), encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def run_command(self) -> str:
        from io import StringIO

        buffer, stdout = StringIO(), sys.stdout
        sys.stdout = buffer
        try:
            print_pending_decisions(argparse.Namespace(output_dir=str(self.out)))
        finally:
            sys.stdout = stdout
        return buffer.getvalue().strip()

    def test_empty_directory(self):
        self.assertEqual(self.run_command(), "artifact=none pending=none")

    def test_reports_open_and_deferred_of_the_newest_artifact(self):
        self.write("old.json", ["open"], 1000)
        newest = self.write("new.json", ["decided", "open", "deferred"], 2000)
        self.assertEqual(self.run_command(), f"artifact={newest} pending=D2,D3")

    def test_fully_decided_newest_artifact_reports_nothing(self):
        self.write("old.json", ["open"], 1000)
        newest = self.write("new.json", ["decided"], 2000)
        self.assertEqual(self.run_command(), f"artifact={newest} pending=none")


if __name__ == "__main__":
    unittest.main(verbosity=2)
