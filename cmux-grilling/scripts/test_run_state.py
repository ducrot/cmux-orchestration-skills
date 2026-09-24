#!/usr/bin/env python3
"""Run-state regression tests. Run: python3 scripts/test_run_state.py"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
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
    validate_artifact,
    validate_decision,
)


def output_args(tracker: str | None = None, output_dir: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(tracker=tracker, output_dir=output_dir)


def run_quietly(command, args: argparse.Namespace) -> str:
    """Call a subcommand and return its stdout, so the suite's own output stays clean."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command(args)
    return buffer.getvalue().strip()


def make_tracker(root: Path, name: str) -> Path:
    (root / ".scratch" / name / "issues").mkdir(parents=True)
    return root / ".scratch" / name


class OutputPathDerivation(unittest.TestCase):
    def test_slug_stops_at_word_boundary_and_uses_shared_fallback(self):
        from orchestrator_lib import slugify
        self.assertEqual(
            slugify("Task: Static teaser website for cmux Orchestration skills"),
            "task-static-teaser-website-for",
        )
        self.assertEqual(slugify("!!!"), "task")
        self.assertEqual(slugify("A" * 40), "a" * 30)
        self.assertEqual(slugify("abc defghi", 5), "abc")
        self.assertEqual(slugify("ABC---123"), "abc-123")

    def test_run_identifier_cleans_keys_and_formats_utc_minute(self):
        from orchestrator_lib import run_identifier, slugify
        now = "2026-09-15T09:47:19+00:00"
        self.assertEqual(run_identifier("chain", slugify("ISSUE-001"), now), "chain-issue-001-2026-09-15-0947")
        self.assertEqual(run_identifier("plan", "A key?!", now), "plan-A-key--2026-09-15-0947")

    def test_ignore_bootstrap_publishes_complete_bytes_and_preserves_existing_file(self):
        from run_state import ensure_runs_root_ignored
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            ignore = root / ".gitignore"
            replace = os.replace
            observed = []
            def publish(source, target):
                observed.append(Path(source).read_bytes())
                self.assertFalse(ignore.exists())
                replace(source, target)
            with patch("run_state.os.replace", side_effect=publish):
                ensure_runs_root_ignored(root)
            self.assertEqual(observed, [b"*\n"])
            self.assertEqual(ignore.read_bytes(), b"*\n")
            ignore.write_text("existing rules\n")
            before = ignore.stat().st_mtime_ns
            ensure_runs_root_ignored(root)
            self.assertEqual(ignore.read_text(), "existing rules\n")
            self.assertEqual(ignore.stat().st_mtime_ns, before)
            ignore.unlink()
            ignore.mkdir()
            with self.assertRaises(OSError):
                ensure_runs_root_ignored(root)
            self.assertTrue(ignore.is_dir())

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


class CompletionMapping(unittest.TestCase):
    def test_complete_cli_requires_paths_and_preserves_output_mapping(self):
        from test_launch_wave import PreparedLaunchWaveCli
        # Reuse the real CLI fixture with local fake harness executables.
        fixture = PreparedLaunchWaveCli()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        for mode, extra in (
            ("default", []),
            ("custom-id", ["--run-id", "custom-run"]),
            ("custom-root", ["--runs-root", str(fixture.repo / "custom-runs"), "--slug", "custom-artifact"]),
        ):
            with self.subTest(mode=mode):
                result = fixture.run_state("init", "--task", "Completion " + mode, "--no-workspace", *extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                run_dir = fixture.repo / result.stdout.strip()
                state_path = run_dir / "state.json"
                state = json.loads(state_path.read_text())
                output = fixture.repo / state["output_dir"]
                output.mkdir(parents=True, exist_ok=True)
                md = output / (state["slug"] + ".md")
                artifact = output / (state["slug"] + ".json")
                md.write_text("# Complete\n")
                artifact.write_text(json.dumps({"run_id": state["run_id"], "open_decisions": [valid_decision()]}))
                before = state_path.read_bytes()
                missing = fixture.run_state("complete", "--run-dir", str(run_dir), "--json", str(artifact))
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn("--markdown", missing.stderr)
                for paths in ((fixture.repo / "outside.md", artifact), (md, fixture.repo / "outside.json")):
                    outside = fixture.run_state("complete", "--run-dir", str(run_dir), "--markdown", str(paths[0]), "--json", str(paths[1]))
                    self.assertNotEqual(outside.returncode, 0)
                    self.assertIn("output_dir", outside.stderr)
                    self.assertEqual(before, state_path.read_bytes())
                finished = fixture.run_state("complete", "--run-dir", str(run_dir), "--markdown", str(md), "--json", str(artifact), "--data", '{"stop_reason":"done"}')
                self.assertEqual(finished.returncode, 0, finished.stderr)
                final = json.loads(state_path.read_text())
                self.assertEqual(final["current_stage"], "done")
                self.assertEqual(final["output_dir"], state["output_dir"])
                self.assertEqual(final["tracker"], state["tracker"])
                self.assertEqual(final["deliverables"], {"markdown": str(md.resolve()), "json": str(artifact.resolve())})
                event = json.loads((run_dir / "events.jsonl").read_text().splitlines()[-1])
                self.assertEqual(event["data"]["stop_reason"], "done")
                pending = fixture.run_state("pending-decisions", "--output-dir", str(output))
                self.assertEqual(pending.returncode, 0, pending.stderr)
                self.assertIn("D1", pending.stdout)
                reopened = fixture.run_state("decision", "--run-dir", str(run_dir), "--artifact", str(artifact), "--id", "D1", "--status", "decided", "--decision", "Accepted")
                self.assertEqual(reopened.returncode, 0, reopened.stderr)

    def test_legacy_lifecycle_refuses_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            state = run_dir / "state.json"
            state.write_text('{"current_stage":"research"}')
            script = Path(__file__).with_name("run_state.py")
            for argv in (("event", "--type", "x", "--message", "x"),
                         ("gate", "--stage", "research", "--decision", "advance", "--reason", "x"),
                         ("snapshot", "--label", "x"),
                         ("complete", "--markdown", "x.md", "--json", "x.json")):
                result = subprocess.run([sys.executable, str(script), argv[0], "--run-dir", tmp, *argv[1:]], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsupported legacy layout", result.stderr)
                self.assertEqual(state.read_text(), '{"current_stage":"research"}')
                self.assertEqual(list(run_dir.iterdir()), [state])


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
        (self.run_dir / "state.json").write_text(json.dumps({"workflow": "grilling", "layout_version": 1, "max_rounds": 4}))

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, **overrides) -> str:
        args = argparse.Namespace(
            run_dir=str(self.run_dir),
            artifact=str(self.artifact),
            id="D1",
            status="decided",
            decision="Ab 12 Jahren",
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return run_quietly(record_decision, args)

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
        return run_quietly(print_pending_decisions, output_args(output_dir=str(self.out)))

    def test_empty_directory(self):
        self.assertEqual(self.run_command(), f"dir={self.out} artifact=none open=none deferred=none")

    def test_open_and_deferred_of_the_newest_artifact_stay_apart(self):
        self.write("old.json", ["open"], 1000)
        newest = self.write("new.json", ["decided", "open", "deferred"], 2000)
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=D2 deferred=D3")

    def test_fully_decided_newest_artifact_reports_nothing(self):
        self.write("old.json", ["open"], 1000)
        newest = self.write("new.json", ["decided"], 2000)
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=none deferred=none")

    def test_foreign_json_never_wins_the_newest_comparison(self):
        newest = self.write("artifact.json", ["open"], 1000)
        (self.out / "notes.json").write_text(json.dumps(["not an artifact"]), encoding="utf-8")
        (self.out / "broken.json").write_text("{oops", encoding="utf-8")
        os.utime(self.out / "notes.json", (3000, 3000))
        os.utime(self.out / "broken.json", (4000, 4000))
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=D1 deferred=none")

    def test_directory_is_resolved_like_init(self):
        """No output dir passed: the resume check derives the same path init would."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                run_quietly(print_pending_decisions, output_args(tracker=tmp + "/.scratch/t12")),
                f"dir={tmp}/.scratch/t12/grilling artifact=none open=none deferred=none",
            )


class ValidateArtifact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifact = Path(self.tmp.name) / "plan.json"

    def tearDown(self):
        self.tmp.cleanup()

    def validate(self, decisions) -> str:
        self.artifact.write_text(json.dumps({"open_decisions": decisions}), encoding="utf-8")
        return run_quietly(validate_artifact, argparse.Namespace(artifact=str(self.artifact)))

    def test_clean_artifact_passes(self):
        self.assertEqual(self.validate([valid_decision(), valid_decision(id="D2")]), "open_decisions=2 valid")

    def test_thin_entry_is_caught_at_finalize_naming_its_id(self):
        with self.assertRaises(SystemExit) as caught:
            self.validate([valid_decision(), valid_decision(id="D2", context="")])
        self.assertIn("D2: missing or empty field: context", str(caught.exception))

    def test_missing_list_stops(self):
        self.artifact.write_text(json.dumps({"run_id": "grill-x"}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            run_quietly(validate_artifact, argparse.Namespace(artifact=str(self.artifact)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
