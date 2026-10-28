#!/usr/bin/env python3
"""Run-state regression tests. Run: python3 scripts/test_run_state.py"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_launch_wave as wave_tests  # noqa: E402
from test_launch_wave import file_contents  # noqa: E402

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


class CommitModes(unittest.TestCase):
    setUp = wave_tests.PreparedLaunchWaveCli.setUp
    tearDown = wave_tests.PreparedLaunchWaveCli.tearDown
    env = wave_tests.PreparedLaunchWaveCli.env
    run_state = wave_tests.PreparedLaunchWaveCli.run_state
    initialize_config = wave_tests.PreparedLaunchWaveCli.initialize_config
    init_for = wave_tests.PreparedLaunchWaveCli.init_for

    def test_commit_modes_and_legacy_default(self):
        for mode in (None, "commit", "propose"):
            run_id = "mode-" + str(mode)
            extra = [] if mode is None else ["--commit-mode", mode]
            result = self.init_for(run_id, *extra)
            self.assertEqual(result.returncode, 0, result.stderr)
            run_dir = self.runs_root / run_id
            state_path = run_dir / "state.json"
            state = json.loads(state_path.read_text())
            self.assertEqual(set(state["commit_baseline"]), {"head", "captured_at", "paths"})
            self.assertIsInstance(state["commit_baseline"]["paths"], list)
            effective = mode or "propose"
            self.assertEqual(state["commit_mode"], effective)
            for legacy in (False, True):
                if legacy:
                    state.pop("commit_mode")
                    state.pop("commit_baseline")
                    state_path.write_text(json.dumps(state))
                    effective = "propose"
                before = file_contents(run_dir)
                for event_type in ("commit.proposed", "commit.created", "commit.anything"):
                    refused_event = self.run_state("event", "--run-dir", str(run_dir), "--type", event_type, "--message", "forbidden")
                    self.assertNotEqual(refused_event.returncode, 0)
                    self.assertIn("commit events are recorded by run_commit.py", refused_event.stderr)
                    self.assertEqual(file_contents(run_dir), before)
                shown = self.run_state("status", "--run-dir", str(run_dir))
                self.assertEqual(shown.returncode, 0, shown.stderr)
                self.assertEqual(json.loads(shown.stdout)["state"]["commit_mode"], effective)
                for extra in ([], ["--commit-mode", effective]):
                    repeated = self.init_for(run_id, *extra)
                    self.assertEqual(repeated.returncode, 0, repeated.stderr)
                extra = ["--commit-mode", "commit" if effective == "propose" else "propose"]
                refused = self.init_for(run_id, *extra)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(f"run {run_id} already exists with commit mode {effective}; --commit-mode {extra[-1]} cannot change it", refused.stderr)
                self.assertEqual(file_contents(run_dir), before)


class SkillDirectoryRunsRoot(unittest.TestCase):
    setUp = wave_tests.PreparedLaunchWaveCli.setUp
    tearDown = wave_tests.PreparedLaunchWaveCli.tearDown
    env = wave_tests.PreparedLaunchWaveCli.env
    initialize_config = wave_tests.PreparedLaunchWaveCli.initialize_config

    def test_init_from_the_skill_directory_refuses_a_runs_root_inside_it(self):
        skill = wave_tests.SCRIPT_DIR.parent
        stray = skill / ".scratch"
        self.assertFalse(stray.exists(), "remove the stray skill-local runs root before testing")
        self.addCleanup(shutil.rmtree, stray, ignore_errors=True)
        result = subprocess.run(
            [sys.executable, str(wave_tests.RUN_STATE), "init", "--task", "Grill this plan",
             "--run-id", "skill-cwd", "--config", str(self.config_path),
             "--output-dir", str(self.repo / "grilling"), "--workspace-id", "WORKSPACE"],
            cwd=skill, env=self.env(), capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("inside the skill directory", result.stderr)
        self.assertFalse(stray.exists())


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

    def test_run_identifier_cleans_keys_and_formats_local_minute(self):
        from orchestrator_lib import run_identifier, slugify
        now = "2026-09-15T02:47:19+00:00"
        try:
            with patch.dict(os.environ, {"TZ": "America/Los_Angeles"}):
                time.tzset()
                self.assertEqual(run_identifier("chain", slugify("ISSUE-001"), now), "2026-09-14-1947-chain-issue-001")
                self.assertEqual(run_identifier("plan", "A key?!", now), "2026-09-14-1947-plan-A-key")
        finally:
            time.tzset()

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
                ensure_runs_root_ignored(root, Path(tmp))
            self.assertEqual(observed, [b"*\n"])
            self.assertEqual(ignore.read_bytes(), b"*\n")
            ignore.write_text("existing rules\n")
            before = ignore.stat().st_mtime_ns
            ensure_runs_root_ignored(root, Path(tmp))
            self.assertEqual(ignore.read_text(), "existing rules\n")
            self.assertEqual(ignore.stat().st_mtime_ns, before)
            ignore.unlink()
            ignore.mkdir()
            with self.assertRaises(OSError):
                ensure_runs_root_ignored(root, Path(tmp))
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
                result = fixture.run_state("init", "--task", "Completion " + mode, "--no-workspace", "--tracker", ".scratch/completion", *extra)
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
                pending = fixture.run_state("pending-decisions")
                self.assertEqual(pending.returncode, 0, pending.stderr)
                self.assertIn("D1", pending.stdout)
                reopened = fixture.run_state("decision", "--run-dir", str(run_dir), "--artifact", str(artifact), "--id", "D1", "--status", "decided", "--decision", "Ab 12 Jahren")
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
        (self.run_dir / "state.json").write_text(json.dumps({"workflow": "grilling", "layout_version": 2, "max_rounds": 4}))

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

    def test_unmatched_or_empty_custom_choice_is_refused_without_writes(self):
        for choice in ("Unlisted choice", "[custom]", "[custom]   ", "Ab 12 Jahren plus more"):
            with self.subTest(choice=choice):
                before = self.artifact.read_bytes()
                with self.assertRaises(SystemExit) as caught:
                    self.record(decision=choice)
                self.assertIn("Ab 12 Jahren", str(caught.exception))
                self.assertIn("12 bis offen", str(caught.exception))
                self.assertIn("[custom]", str(caught.exception))
                self.assertEqual(self.artifact.read_bytes(), before)
                self.assertFalse((self.run_dir / "events.jsonl").exists())

    def test_explicit_custom_choice_preserves_choice_in_artifact_and_event(self):
        choice = "[custom] Ab 14 Jahren"
        self.assertIn(choice, self.record(decision=choice))
        entry = json.loads(self.artifact.read_text())["open_decisions"][0]
        self.assertEqual(entry["decision"], choice)
        event = json.loads((self.run_dir / "events.jsonl").read_text())
        self.assertEqual(event["data"]["decision"], choice)

    def test_collect_the_missing_facts_first_counterexample_is_traceable_not_semantically_checked(self):
        label = "collect the missing facts first"
        options = [{"label": label, "implication": "Fakten zuerst"}, {"label": "Ab 12 Jahren", "implication": "Kürzer"}]
        self.artifact.write_text(json.dumps({"run_id": "grill-x", "open_decisions": [valid_decision(options=options)]}))
        self.record(decision=label)
        entry = json.loads(self.artifact.read_text())["open_decisions"][0]
        self.assertEqual((entry["status"], entry["decision"]), ("decided", label))

    def test_other_presented_label_is_recorded_verbatim(self):
        self.record(decision="12 bis offen")
        entry = json.loads(self.artifact.read_text())["open_decisions"][0]
        self.assertEqual(entry["decision"], "12 bis offen")

    def test_cli_selection_traceability_help_and_recording(self):
        command = [sys.executable, str(wave_tests.RUN_STATE)]
        help_result = subprocess.run([*command, "decision", "--help"], capture_output=True, text=True)
        help_text = " ".join(help_result.stdout.split())
        for phrase in ("Selection traceability", "exact option label", "[custom]", "free text",
                       "does not prove the chosen option resolves missing facts"):
            self.assertIn(phrase, help_text)
        for choice, accepted in (("Unlisted choice", False), ("12 bis offen", True)):
            with self.subTest(choice=choice):
                before = self.artifact.read_bytes()
                result = subprocess.run([*command, "decision", "--run-dir", str(self.run_dir),
                                         "--artifact", str(self.artifact), "--id", "D1",
                                         "--status", "decided", "--decision", choice],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                if accepted:
                    entry = json.loads(self.artifact.read_text())["open_decisions"][0]
                    self.assertEqual((entry["status"], entry["decision"]), ("decided", choice))
                    self.assertIn(f"Ausgang (decided): {choice}", result.stdout)
                else:
                    self.assertEqual(self.artifact.read_bytes(), before)
                    self.assertFalse((self.run_dir / "events.jsonl").exists())

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
    script = Path(__file__).with_name("run_state.py").resolve()
    empty = (f"dir={NO_TRACKER_OUTPUT_DIR} artifact=none open=none deferred=none unreviewed_assumptions=none "
             "open_facts=none unreviewed_premise_corrections=none")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = Path(".scratch/feature-a/grilling")
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.tmp.cleanup()

    def write(self, name: str, statuses: list[str], mtime: float, **extra) -> Path:
        path = self.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        decisions = [valid_decision(id=f"D{index + 1}", status=status, decision="x") for index, status in enumerate(statuses)]
        path.write_text(json.dumps({"open_decisions": decisions, **extra}), encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def run_command(self) -> str:
        return run_quietly(print_pending_decisions, argparse.Namespace())

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.script), "pending-decisions", *args],
                              capture_output=True, text=True)

    def test_new_form_reports_only_unreviewed_assumptions_and_open_facts_via_cli(self):
        self.write("../../feature-b/grilling/old.json", ["open"], 1000, assumption_review=[{"index": 99, "outcome": "unreviewed"}],
                   open_facts=[{"id": "OLD", "status": "open"}])
        newest = self.write(
            "new.json", ["decided", "open", "deferred"], 2000,
            assumption_review=[{"index": index, "outcome": outcome} for index, outcome in
                               enumerate(["confirmed", "unreviewed", "corrected", "discarded", "unreviewed"], 1)],
            premise_correction_review=[{"index": index, "outcome": outcome} for index, outcome in
                                       enumerate(["unreviewed", "confirmed", "corrected", "discarded", "unreviewed"], 1)],
            open_facts=[{"id": "F1", "status": "answered"}, {"id": "F2", "status": "open"},
                        {"id": "F3", "status": "open"}],
        )
        before = {path: path.read_bytes() for path in self.out.iterdir()}
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         f"dir={self.out} artifact={newest} open=D2 deferred=D3 "
                         "unreviewed_assumptions=2,5 open_facts=F2,F3 unreviewed_premise_corrections=1,5")
        self.assertEqual({path: path.read_bytes() for path in self.out.iterdir()}, before)

    def test_pending_review_and_facts_without_open_decisions(self):
        newest = self.write("new.json", ["decided"], 1000, assumption_review=[{"index": 1, "outcome": "unreviewed"}],
                            open_facts=[{"id": "F1", "status": "open"}])
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=none deferred=none "
                         "unreviewed_assumptions=1 open_facts=F1 unreviewed_premise_corrections=none")

    def test_malformed_review_and_facts_do_not_crash(self):
        newest = self.write("new.json", ["open"], 1000, assumption_review=None, premise_correction_review=[],
                            open_facts=[{"status": "open"}, {"id": "F2", "status": "open"}])
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=D1 deferred=none "
                         "unreviewed_assumptions=none open_facts=F2 unreviewed_premise_corrections=none")

    def test_completed_review_and_facts_report_none(self):
        newest = self.write("new.json", ["deferred"], 1000, assumption_review=[{"index": 1, "outcome": "confirmed"}],
                            open_facts=[{"id": "F1", "status": "answered"}],
                            premise_correction_review=[{"index": 1, "outcome": "confirmed"}])
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=none deferred=D1 "
                         "unreviewed_assumptions=none open_facts=none unreviewed_premise_corrections=none")

    def test_empty_directory(self):
        self.assertEqual(self.run_command(), self.empty)

    def test_open_and_deferred_of_the_newest_artifact_stay_apart(self):
        self.write("old.json", ["open"], 1000)
        newest = self.write("new.json", ["decided", "open", "deferred"], 2000)
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=D2 deferred=D3 unreviewed_assumptions=none open_facts=none unreviewed_premise_corrections=none")

    def test_fully_decided_newest_artifact_reports_nothing(self):
        self.write("old.json", ["open"], 1000)
        newest = self.write("new.json", ["decided"], 2000)
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=none deferred=none unreviewed_assumptions=none open_facts=none unreviewed_premise_corrections=none")

    def test_foreign_json_never_wins_the_newest_comparison(self):
        newest = self.write("artifact.json", ["open"], 1000)
        (self.out / "notes.json").write_text(json.dumps(["not an artifact"]), encoding="utf-8")
        (self.out / "broken.json").write_text("{oops", encoding="utf-8")
        os.utime(self.out / "notes.json", (3000, 3000))
        os.utime(self.out / "broken.json", (4000, 4000))
        self.assertEqual(self.run_command(), f"dir={self.out} artifact={newest} open=D1 deferred=none unreviewed_assumptions=none open_facts=none unreviewed_premise_corrections=none")

    def test_newest_comparison_uses_mtime_then_name_across_features(self):
        newest = self.write("z.json", ["open"], 2000)
        self.write("../../feature-b/grilling/a.json", ["deferred"], 2000)
        self.write("../../feature-c/grilling/later-name.json", ["decided"], 1000)
        self.assertIn(f"dir={self.out} artifact={newest} open=D1", self.run_command())
        # A newer mtime beats the name, even in another feature without issues/.
        self.write("../../feature-b/grilling/a.json", ["deferred"], 3000)
        self.assertIn("dir=.scratch/feature-b/grilling artifact=.scratch/feature-b/grilling/a.json open=none deferred=D1", self.run_command())

    def test_multiple_trackers_do_not_block_discovery(self):
        make_tracker(Path("."), "feature-a")
        make_tracker(Path("."), "feature-b")
        newest = self.write("new.json", ["open"], 1000)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"dir={self.out} artifact={newest} open=D1", result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_fallback_and_deeper_artifacts_are_not_discovered(self):
        self.write("../../grilling/legacy.json", ["open"], 4000)
        self.write("nested/deeper.json", ["open"], 4000)
        self.write("../../feature-b/nested/grilling/deeper.json", ["open"], 4000)
        self.assertEqual(self.run_command(), self.empty)

    def test_folder_options_are_rejected(self):
        for option in ("--tracker", "--output-dir"):
            with self.subTest(option=option):
                result = self.run_cli(option, "anywhere")
                self.assertEqual(result.returncode, 2)
                self.assertIn("unrecognized arguments", result.stderr)


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


class ReviewArtifactPair(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.artifact = Path(self.tmp.name) / "plan.json"
        self.markdown = self.artifact.with_suffix(".md")
        self.data = {
            "open_decisions": [], "assumptions": ["Neutral premise."],
            "assumption_review": [{"index": 1, "outcome": "unreviewed",
                                   "corrected_text": "", "reason": "", "reviewed_at": ""}],
            "open_facts": [{"id": "F1", "question": "Which value applies?",
                            "why_needed": "The plan needs the value.", "status": "open",
                            "answer": "", "answered_at": ""}],
            "markdownPath": str(self.markdown),
        }

    def write_pair(self):
        labels = {"unreviewed": "ungeprüft", "confirmed": "bestätigt",
                  "corrected": "korrigiert", "discarded": "verworfen"}
        lines = ["## Definierte Annahmen"]
        for text, review in zip(self.data["assumptions"], self.data["assumption_review"]):
            marker = {"Ergebnis": labels.get(review.get("outcome"), "unbekannt"),
                      "Korrektur": review.get("corrected_text", ""),
                      "Grund": review.get("reason", "")}
            lines.append(f"{review.get('index')}. {text} [Prüfung: {json.dumps(marker, ensure_ascii=False)}]")
        lines.append("## Offene Fakten")
        lines.extend("- " + json.dumps(fact, ensure_ascii=False) for fact in self.data["open_facts"])
        self.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.write_json()

    def write_json(self):
        self.artifact.write_text(json.dumps(self.data), encoding="utf-8")

    def check_pair(self):
        return run_quietly(validate_artifact, argparse.Namespace(artifact=str(self.artifact)))

    def test_all_review_outcomes_and_answered_fact(self):
        self.data["open_facts"][0].update(status="answered", answer="A value.",
                                          answered_at="2026-10-26T09:00:00Z")
        for outcome in ("unreviewed", "confirmed", "corrected", "discarded"):
            with self.subTest(outcome=outcome):
                self.data["assumption_review"][0].update(
                    outcome=outcome, corrected_text="Revised premise." if outcome == "corrected" else "",
                    reason="Human supplied context." if outcome in ("corrected", "discarded") else "",
                    reviewed_at="2026-10-26T09:00:00Z" if outcome != "unreviewed" else "")
                self.write_pair()
                self.assertEqual(self.check_pair(), "open_decisions=0 assumption_review=1 open_facts=1 valid")

    def test_invalid_review_entries_name_entry(self):
        mutations = [lambda r: r.clear(), lambda r: r.update(index=2),
                     lambda r: r.update(index=True), lambda r: r.update(outcome="other"),
                     lambda r: r.update(outcome="corrected", corrected_text=""),
                     lambda r: r.update(outcome="discarded", reason=" "),
                     lambda r: r.update(outcome="confirmed", reviewed_at="yesterday")]
        original = self.data["assumption_review"][0]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.data["assumption_review"][0] = dict(original)
                mutate(self.data["assumption_review"][0])
                self.write_json()
                with self.assertRaisesRegex(SystemExit, "assumption_review.*1"):
                    self.check_pair()

    def test_review_length_and_missing_companion_list(self):
        original = dict(self.data)
        for field, value in (("assumption_review", []), ("open_facts", None)):
            with self.subTest(field=field):
                self.data = dict(original, **{field: value})
                self.write_json()
                with self.assertRaisesRegex(SystemExit, field):
                    self.check_pair()

    def test_multiple_entries_empty_lists_and_verbatim_quotes(self):
        self.data["assumptions"].append('A "quoted" premise [with brackets].')
        self.data["assumption_review"].append(dict(self.data["assumption_review"][0], index=2))
        self.write_pair()
        self.assertIn("assumption_review=2", self.check_pair())
        self.data["assumption_review"].reverse()
        self.write_json()
        with self.assertRaisesRegex(SystemExit, "entry 1: index must be 1"):
            self.check_pair()
        self.data.update(assumptions=[], assumption_review=[], open_facts=[])
        self.write_pair()
        self.assertIn("assumption_review=0 open_facts=0", self.check_pair())

    def test_malformed_markdown_entries_and_duplicate_sections(self):
        for change in (lambda text: text.replace('"Ergebnis"', 'Ergebnis'),
                       lambda text: text.replace('- {', '- broken {'),
                       lambda text: text + '\n## Definierte Annahmen\n',
                       lambda text: text.replace('1. Neutral premise.', '2. Neutral premise.'),
                       lambda text: text + '- {}\n'):
            with self.subTest(change=change):
                self.write_pair()
                self.markdown.write_text(change(self.markdown.read_text()))
                with self.assertRaises(SystemExit):
                    self.check_pair()

    def test_prose_and_trailing_whitespace_in_sections_are_ignored(self):
        self.data["open_facts"] = []
        self.write_pair()
        text = self.markdown.read_text().replace("## Offene Fakten", "## Offene Fakten\nKeine.")
        self.markdown.write_text(text.replace("]\n", "]  \n", 1))
        self.assertIn("open_facts=0", self.check_pair())

    def test_extension_keeps_decision_validation(self):
        self.data["open_decisions"] = [valid_decision(context="")]
        self.write_pair()
        with self.assertRaisesRegex(SystemExit, "D1: missing or empty field: context"):
            self.check_pair()

    def test_new_pair_falls_back_to_sibling_markdown(self):
        del self.data["markdownPath"]
        self.write_pair()
        self.assertIn("assumption_review=1", self.check_pair())

    def test_invalid_facts_name_entry(self):
        original = self.data["open_facts"][0]
        for changes in ({"id": ""}, {"question": " "}, {"why_needed": 3},
                        {"status": "other"}, {"status": "answered"},
                        {"status": "answered", "answer": "Value", "answered_at": "today"}):
            with self.subTest(changes=changes):
                self.data["open_facts"][0] = dict(original, **changes)
                self.write_json()
                with self.assertRaisesRegex(SystemExit, "open_facts.*(F1|1)"):
                    self.check_pair()
        self.data["open_facts"][0] = original
        self.data["open_facts"] *= 2
        self.write_json()
        with self.assertRaisesRegex(SystemExit, "F1.*duplicate"):
            self.check_pair()

    def test_markdown_disagreements_fail(self):
        self.data["assumption_review"][0].update(
            outcome="corrected", corrected_text="Revised premise.", reason="Human context.",
            reviewed_at="2026-10-26T09:00:00Z")
        for old, new, diagnostic in (
            ("korrigiert", "ungeprüft", "assumption_review.*1"),
            ("Revised premise.", "Other premise.", "assumption_review.*1"),
            ("Human context.", "Other reason.", "assumption_review.*1"),
            ("Neutral premise.", "Changed premise.", "assumption_review.*1"),
            ('"status": "open"', '"status": "answered"', "open_facts.*F1"),
            ("## Offene Fakten", "## Other", "Offene Fakten"),
        ):
            with self.subTest(old=old):
                self.write_pair()
                self.markdown.write_text(self.markdown.read_text().replace(old, new))
                with self.assertRaisesRegex(SystemExit, diagnostic):
                    self.check_pair()

    def test_cli_reads_both_halves_and_legacy_output_stays_unchanged(self):
        self.write_pair()
        cli = [sys.executable, str(Path(__file__).with_name("run_state.py")),
               "validate-artifact", "--artifact", str(self.artifact)]
        result = subprocess.run(cli, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("assumption_review=1 open_facts=1", result.stdout)
        self.markdown.unlink()
        result = subprocess.run(cli, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Markdown", result.stderr)
        self.artifact.write_text(json.dumps({"open_decisions": []}))
        result = subprocess.run(cli, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "open_decisions=0 valid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
