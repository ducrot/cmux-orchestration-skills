"""Exercise evidence verdicts through real wrapper, snapshot, and check CLIs."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from orchestrator_lib import append_jsonl
import test_snapshot


SCRIPTS = Path(__file__).resolve().parent
CHECK = SCRIPTS / "check_evidence.py"


class EvidenceCli(unittest.TestCase):
    git = test_snapshot.SnapshotCli.git

    def setUp(self):
        test_snapshot.SnapshotCli.setUp(self)
        self.tracker = self.root / "tracker"
        self.tracker.mkdir()
        self.command = "printf 'green\\n'"
        self.commands = [self.command, "printf 'second\\n'"]
        self.rules()
        self.state = {"workflow": "issue-chain", "layout_version": 1,
                      "deliverables": {"tracker": str(self.tracker)}}
        (self.run_dir / "state.json").write_text(json.dumps(self.state))
        self.report = self.root / "report.md"
        self.report_text()

    def rules(self, legacy=False, commands=None, targeted=None):
        wording = ", run as the baseline suite by every worker" if legacy else ""
        (self.tracker / "README.md").write_text(
            "# Tracker\n\n## Ground rules\n\n- Canonical check commands" + wording + ":\n"
            + "".join(f"  - `{command}`\n" for command in (commands or self.commands))
            + (("- Targeted check commands for implement, simplify, and review:\n"
                + "".join(f"  - `{command}`\n" for command in targeted)) if targeted is not None else "")
            + "- Unrelated rule: `never execute this`\n\n## Other\n"
            + "- Canonical check commands:\n  - `false`\n")

    def report_text(self, blockers="None", drift="None"):
        self.report.write_text(
            "## Result\nNO FINDINGS\n\n## Tests / Checks\n- `example`: passed\n\n"
            f"## Findings\n- None\n\n## Blockers\n- {blockers}\n\n## Plan Drift\n- {drift}\n")

    def cli(self, script, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                              cwd=cwd or self.repo, env=self.env, capture_output=True,
                              text=True, timeout=30)

    def wrap(self, command=None, stage="implement", pass_num=1, cwd=None):
        return self.cli("run_check.py", "--artifact-dir",
                        self.run_dir / "artifacts" / f"{stage}-{pass_num}",
                        "--command", command or self.command, cwd=cwd)

    BASELINE_STAGES = (("simplify", 1), ("implement", 2))

    def prepared(self, followup, stage="implement", pass_num=2):
        append_jsonl(self.run_dir / "events.jsonl", {"type": "stage.prepared", "data": {
            "stage": stage, "pass": pass_num, "followup": followup}})

    def capture(self, stage="implement", pass_num=1, prefix="report-captured"):
        result = self.cli("run_state.py", "snapshot", "--run-dir", self.run_dir,
                          "--label", f"{prefix} {stage}-{pass_num}")
        self.assertEqual(result.returncode, 0, result.stderr)

    def check(self, stage="implement", pass_num=1, report=True, cwd=None):
        args = ["--run-dir", self.run_dir, "--stage", stage, "--pass", pass_num]
        if report:
            args += ["--report", self.report]
        return self.cli("check_evidence.py", *args, cwd=cwd)

    def log_path(self):
        return next((self.run_dir / "artifacts/implement-1").glob("*.log"))

    def event(self):
        return json.loads((self.run_dir / "events.jsonl").read_text().splitlines()[-1])

    def green(self, stage="implement", pass_num=1, followup=False):
        if stage == "implement":
            self.prepared(followup, stage, pass_num)
        needs_before = stage == "simplify" or (stage == "implement" and followup)
        if needs_before or stage == "review":
            self.capture(stage, pass_num, prefix="launched")
        if needs_before:
            for command in self.commands:
                self.assertEqual(self.wrap(command, stage, pass_num).returncode, 0)
        for command in self.commands:
            result = self.wrap(command, stage, pass_num)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.capture(stage, pass_num)

    def phase_results(self, phase):
        return [item for item in self.event()["data"]["results"] if item["phase"] == phase]

    def assert_citations_rejected(self, reason):
        rejected = self.phase_results("citation")
        self.assertEqual({item["command"] for item in rejected}, set(self.commands))
        self.assertTrue(all(item["verdict"] == "missing" and item["cited"] for item in rejected))
        self.assertEqual({item["error"] for item in rejected}, {reason})

    def test_gate_accepts_real_check_then_refuses_after_recapture(self):
        self.green()
        checked = self.check()
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        args = ("gate", "--run-dir", self.run_dir, "--stage", "implement",
                "--decision", "advance", "--reason", "verified", "--next-stage", "simplify")
        accepted = self.cli("run_state.py", *args)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads((self.run_dir / "state.json").read_text())["current_stage"], "simplify")
        self.capture()
        before = (self.run_dir / "events.jsonl").read_bytes()
        refused = self.cli("run_state.py", *args)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("implement pass 1", refused.stderr)
        self.assertEqual((self.run_dir / "events.jsonl").read_bytes(), before)

    def cite(self, paths=None):
        paths = paths or sorted((self.run_dir / "artifacts/implement-1").glob("*.log"))
        bullets = "\n".join(f"- cited: {path.relative_to(self.run_dir)}" for path in paths)
        self.report.write_text(self.report.read_text().replace("- `example`: passed", bullets))

    def test_corrective_pass_after_red_test_owes_only_after_evidence(self):
        self.assertNotEqual(self.wrap("false", "test").returncode, 0)
        self.capture("test")
        self.assertEqual(self.check("test").returncode, 3)
        self.prepared(True)
        self.prepared(False)  # Latest preparation replaces the earlier follow-up choice.
        for command in self.commands:
            self.assertEqual(self.wrap(command, "implement", 2).returncode, 0)
        self.capture("implement", 2)
        checked = self.check("implement", 2)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual({item["phase"] for item in self.event()["data"]["results"]}, {"after"})

    def test_targeted_commands_for_each_stage_through_real_clis(self):
        canonical = self.commands[:]
        targeted = ["printf 'targeted one\\n'", "printf 'targeted two\\n'"]
        self.rules(targeted=targeted)
        for stage, number, followup in (("implement", 1, False), ("implement", 2, True),
                                        ("simplify", 1, False), ("review", 1, False),
                                        ("test", 1, False)):
            with self.subTest(stage=stage, followup=followup):
                expected, wrong = (canonical, targeted) if stage == "test" else (targeted, canonical)
                self.commands = wrong
                self.green(stage, number, followup)
                checked = self.check(stage, number)
                self.assertEqual(checked.returncode, 3, checked.stdout + checked.stderr)
                self.assertEqual({item["command"] for item in self.event()["data"]["results"]}, set(expected))
                self.assertTrue(all(item["verdict"] == "missing" for item in self.event()["data"]["results"]))
                self.commands = expected
                self.green(stage, number, followup)
                checked = self.check(stage, number)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertEqual({item["command"] for item in self.event()["data"]["results"]}, set(expected))

    def test_targeted_triage_still_exempt_without_capture_or_logs(self):
        self.rules(targeted=["false"])
        checked = self.check("triage")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("verdict=exempt", checked.stdout)

    def test_before_evidence_follows_marker_not_pass_number(self):
        self.prepared(True, pass_num=1)
        self.capture(prefix="launched")
        for command in self.commands:
            self.wrap(command)
        self.capture()
        checked = self.check()
        self.assertEqual(checked.returncode, 3, checked.stdout + checked.stderr)
        self.assertTrue(self.phase_results("before"))
        for command in self.commands:
            self.wrap(command)
        self.assertEqual(self.check().returncode, 0)

    def test_unchanged_review_accepts_citations_and_records_identities(self):
        self.green()
        self.capture("review", prefix="launched")
        self.capture("review")
        self.cite()
        result = self.check("review")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(all(log["cited"] for log in self.event()["data"]["checked_logs"]))
        self.assertTrue(all(item["cited"] for item in self.event()["data"]["results"]))

    def test_review_stale_citations_and_changed_review_rejects_citations(self):
        for movement in ("tree", "HEAD"):
            with self.subTest(movement=movement):
                self.report_text()
                self.green()
                if movement == "tree":
                    self.file.write_text("moved\n")
                else:
                    self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "moved")
                self.capture("review", prefix="launched")
                self.capture("review")
                self.cite()
                result = self.check("review")
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("stale:", result.stdout)
                self.assertIn("cited", result.stdout)
        self.report_text()
        self.green()
        self.capture("review", prefix="launched")
        self.file.write_text("review changed\n")
        self.capture("review")
        self.cite()
        result = self.check("review")
        self.assertEqual(result.returncode, 3)
        self.assertIn("cited", result.stdout)
        self.assertIn("missing:", result.stdout)
        self.report_text()
        for command in self.commands:
            self.wrap(command, "review")
        self.assertEqual(self.check("review").returncode, 0)

    def test_changed_review_citation_reason_requires_own_logs(self):
        for pass_num, movement in enumerate(("fingerprint", "HEAD"), start=1):
            with self.subTest(movement=movement):
                self.report_text()
                self.green()
                self.capture("review", pass_num, prefix="launched")
                if movement == "fingerprint":
                    self.file.write_text("review changed the tree\n")
                else:
                    self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "review moved HEAD")
                for command in self.commands:
                    self.assertEqual(self.wrap(command, "review", pass_num).returncode, 0)
                self.capture("review", pass_num)
                self.cite()
                result = self.check("review", pass_num)
                self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                self.assert_citations_rejected("review changed the tree; own logs required")
                self.assertTrue(all(item["verdict"] == "pass" for item in self.phase_results("after")))

    def test_test_stage_rejects_citations_even_with_own_logs(self):
        self.green()
        self.cite()
        self.green("test")
        result = self.check("test")
        self.assertEqual(result.returncode, 3)
        self.assertIn("cited", result.stdout)
        self.assert_citations_rejected("citations are not allowed for this stage")
        self.report_text()
        self.assertEqual(self.check("test").returncode, 0)

    def test_baseline_citation_matches_launch_and_own_after_matches_capture(self):
        for stage, number in self.BASELINE_STAGES:
            with self.subTest(stage=stage):
                if stage == "implement":
                    self.prepared(True, stage, number)
                self.report_text()
                self.green()
                self.capture(stage, number, prefix="launched")
                self.cite()
                self.file.write_text(f"changed by {stage}\n")
                for command in self.commands:
                    self.wrap(command, stage, number)
                self.capture(stage, number)
                result = self.check(stage, number)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                results = self.event()["data"]["results"]
                self.assertEqual({item["phase"] for item in results}, {"before", "after"})
                self.assertTrue(all(item["cited"] for item in results if item["phase"] == "before"))
                self.assertTrue(all(not item["cited"] for item in results if item["phase"] == "after"))

    def test_baseline_only_never_satisfies_after_even_for_noop(self):
        for stage, number in self.BASELINE_STAGES:
            for changed in (False, True):
                with self.subTest(stage=stage, changed=changed):
                    if stage == "implement":
                        self.prepared(True, stage, number)
                    self.report_text()
                    self.green()
                    self.capture(stage, number, prefix="launched")
                    self.cite()
                    if changed:
                        self.file.write_text(f"{stage} changed\n")
                    self.capture(stage, number)
                    result = self.check(stage, number)
                    self.assertEqual(result.returncode, 3)
                    after = self.phase_results("after")
                    self.assertTrue(all(item["verdict"] == "missing" for item in after))

    def test_own_before_and_after_and_missing_before(self):
        for stage, number in self.BASELINE_STAGES:
            with self.subTest(stage=stage):
                if stage == "implement":
                    self.prepared(True, stage, number)
                self.capture(stage, number, prefix="launched")
                self.file.write_text(f"{stage} after\n")
                for command in self.commands:
                    self.wrap(command, stage, number)
                self.capture(stage, number)
                result = self.check(stage, number)
                self.assertEqual(result.returncode, 3)
                self.assertIn("before", result.stdout)
                before = self.phase_results("before")
                self.assertTrue(all(item["verdict"] == "missing" for item in before))
                self.file.write_text("base\n")
                self.capture(stage, number, prefix="launched")
                for command in self.commands:
                    self.wrap(command, stage, number)
                self.file.write_text(f"{stage} after\n")
                self.capture(stage, number)
                self.assertEqual(self.check(stage, number).returncode, 0)

    def test_noop_own_before_requires_distinct_after(self):
        for stage, number in self.BASELINE_STAGES:
            with self.subTest(stage=stage):
                if stage == "implement":
                    self.prepared(True, stage, number)
                self.capture(stage, number, prefix="launched")
                for command in self.commands:
                    self.wrap(command, stage, number)
                self.capture(stage, number)
                self.assertEqual(self.check(stage, number).returncode, 3)
                for command in self.commands:
                    self.wrap(command, stage, number)
                self.assertEqual(self.check(stage, number).returncode, 0)

    def test_cited_baseline_rejects_wrong_launch_identity(self):
        for stage, number in self.BASELINE_STAGES:
            with self.subTest(stage=stage):
                if stage == "implement":
                    self.prepared(True, stage, number)
                self.report_text()
                self.green()
                self.cite()
                self.file.write_text(f"new launch {stage}\n")
                self.capture(stage, number, prefix="launched")
                for command in self.commands:
                    self.wrap(command, stage, number)
                self.capture(stage, number)
                result = self.check(stage, number)
                self.assertEqual(result.returncode, 3)
                before = self.phase_results("before")
                self.assertTrue(all(item["verdict"] == "stale" and item["cited"] for item in before))

    def test_unsafe_or_headerless_citation_is_missing_and_named(self):
        self.green()
        self.capture("review", prefix="launched")
        self.capture("review")
        outside = self.run_dir / "outside.log"
        outside.write_bytes(self.log_path().read_bytes())
        bad = self.run_dir / "artifacts/implement-1/bad.log"
        bad.write_text("no wrapper header\n")
        link = self.run_dir / "artifacts/implement-1/link.log"
        link.symlink_to(outside)
        for path in ("", "outside.log", "../run/outside.log", str(outside),
                     "artifacts/implement-1/bad.log", "artifacts/implement-1/link.log"):
            with self.subTest(path=path):
                self.report_text()
                self.report.write_text(self.report.read_text().replace("- `example`: passed", f"- cited: {path}"))
                result = self.check("review")
                self.assertEqual(result.returncode, 3)
                self.assertIn("missing:", result.stdout)
                self.assertIn(path, result.stdout)
                self.assertIn("cited", result.stdout)

    def test_citing_own_baseline_does_not_reuse_it_as_after_evidence(self):
        self.capture("simplify", prefix="launched")
        for command in self.commands:
            self.wrap(command, "simplify")
        self.capture("simplify")
        self.cite(sorted((self.run_dir / "artifacts/simplify-1").glob("*.log")))
        self.assertEqual(self.check("simplify").returncode, 3)

    def test_missing_and_red_cited_commands_are_identified(self):
        self.rules(commands=["exit 7", self.command])
        self.wrap("exit 7")
        self.capture("review", prefix="launched")
        self.capture("review")
        self.cite()
        result = self.check("review")
        self.assertEqual(result.returncode, 3)
        self.assertIn("red: exit 7 exit_code=7 phase=after source=cited", result.stdout)
        self.assertIn(f"missing: {self.command} phase=after source=own", result.stdout)
        self.assertEqual([(item["verdict"], item["cited"]) for item in self.event()["data"]["results"]],
                         [("red", True), ("missing", False)])

    def test_unchanged_review_missing_source_with_partial_or_broken_citations(self):
        for number, baseline in enumerate(("pass", "stale", "broken"), start=1):
            with self.subTest(baseline=baseline):
                self.report_text()
                self.file.write_text(f"baseline {baseline}\n")
                baseline_dir = self.run_dir / "artifacts/test-1"
                previous = set(baseline_dir.glob("*.log"))
                wrapped = self.wrap(self.command, "test")
                self.assertEqual(wrapped.returncode, 0, wrapped.stderr)
                path, = set(baseline_dir.glob("*.log")) - previous
                if baseline == "stale":
                    self.file.write_text("different review tree\n")
                elif baseline == "broken":
                    path.write_text("broken wrapper header\n")
                self.capture("review", number, prefix="launched")
                self.capture("review", number)
                self.cite([path])
                checked = self.check("review", number)
                self.assertEqual(checked.returncode, 3, checked.stdout + checked.stderr)
                self.assertIn(f"missing: {self.commands[1]} phase=after source=own", checked.stdout)
                self.assertEqual(self.event()["type"], "orchestrator.verified")
                after = {item["command"]: item for item in self.phase_results("after")}
                self.assertEqual(after[self.commands[1]]["verdict"], "missing")
                self.assertIs(after[self.commands[1]]["cited"], False)
                broken = baseline == "broken"
                verdict, source = ("missing", "own") if broken else (baseline, "cited")
                detail = " differed=fingerprint" if baseline == "stale" else ""
                self.assertEqual(after[self.command]["verdict"], verdict)
                self.assertIs(after[self.command]["cited"], not broken)
                self.assertIn(
                    f"{verdict}: {self.command}{detail} phase=after source={source}", checked.stdout)
                if broken:
                    citations = self.phase_results("citation")
                    self.assertEqual({item["command"] for item in citations}, set(self.commands))
                    self.assertTrue(all(item["verdict"] == "missing" and item["cited"]
                                        for item in citations))
                    self.assertTrue(all(item["citation"] == str(path.relative_to(self.run_dir))
                                        for item in citations))

    def test_missing_launch_fails_closed_for_roles_using_baselines(self):
        for stage, number in (("review", 1), ("simplify", 1), ("implement", 2)):
            if stage == "implement":
                self.prepared(True, stage, number)
            self.capture(stage, number)
            result = self.check(stage, number)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing snapshot: launched", result.stderr)

    def test_citations_default_to_stage_report_path_and_remain_valid_on_recheck(self):
        self.green()
        self.capture("review", prefix="launched")
        self.capture("review")
        self.cite()
        reports = self.run_dir / "reports"
        reports.mkdir()
        (reports / "review-1.md").write_text(self.report.read_text())
        self.assertEqual(self.check("review", report=False).returncode, 0)
        self.assertEqual(self.check("review", report=False).returncode, 0)

    def test_backticked_citation_is_accepted(self):
        self.green()
        self.capture("review", prefix="launched")
        self.capture("review")
        bullets = "\n".join(f"- cited: `{path.relative_to(self.run_dir)}`"
                             for path in sorted((self.run_dir / "artifacts/implement-1").glob("*.log")))
        self.report.write_text(self.report.read_text().replace("- `example`: passed", bullets))
        result = self.check("review")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_baseline_mixes_cited_and_own_before_per_command(self):
        self.rules(commands=[self.command, "true"])
        self.wrap(self.command)
        self.capture()
        self.capture("simplify", prefix="launched")
        self.cite()
        self.wrap("true", "simplify")
        self.file.write_text("changed\n")
        for command in (self.command, "true"):
            self.wrap(command, "simplify")
        self.capture("simplify")
        result = self.check("simplify")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_before_source_is_per_command_with_partial_or_broken_citations(self):
        for stage, number in self.BASELINE_STAGES:
            for baseline in ("pass", "red", "stale", "broken"):
                with self.subTest(stage=stage, baseline=baseline):
                    self.report_text()
                    self.file.write_text("base\n")
                    command = "exit 7" if baseline == "red" else self.command
                    self.rules(commands=[command, self.commands[1]])
                    baseline_dir = self.run_dir / "artifacts/test-1"
                    previous = set(baseline_dir.glob("*.log"))
                    wrapped = self.wrap(command, "test")
                    self.assertEqual(wrapped.returncode, 7 if baseline == "red" else 0)
                    path, = set(baseline_dir.glob("*.log")) - previous
                    if baseline == "broken":
                        path.write_text("broken wrapper header\n")
                    if baseline == "stale":
                        self.file.write_text("different launch tree\n")
                    if stage == "implement":
                        self.prepared(True, stage, number)
                    self.capture(stage, number, prefix="launched")
                    self.cite([path])
                    # All own logs belong to the after tree, leaving no own before-runs.
                    self.file.write_text(f"after {stage} {baseline}\n")
                    for after_command in (command, self.commands[1]):
                        self.wrap(after_command, stage, number)
                    self.capture(stage, number)
                    checked = self.check(stage, number)
                    self.assertEqual(checked.returncode, 3, checked.stdout + checked.stderr)
                    self.assertIn(
                        f"missing: {self.commands[1]} phase=before source=own", checked.stdout)
                    self.assertEqual(self.event()["type"], "orchestrator.verified")
                    before = {item["command"]: item for item in self.phase_results("before")}
                    self.assertEqual(before[self.commands[1]]["verdict"], "missing")
                    self.assertIs(before[self.commands[1]]["cited"], False)
                    if baseline == "broken":
                        self.assertEqual(before[command]["verdict"], "missing")
                        self.assertIs(before[command]["cited"], False)
                        citations = self.phase_results("citation")
                        self.assertTrue(citations)
                        self.assertTrue(all(item["cited"] for item in citations))
                        self.assertTrue(all(item["citation"] == str(path.relative_to(self.run_dir))
                                            for item in citations))
                    else:
                        self.assertEqual(before[command]["verdict"], baseline)
                        self.assertIs(before[command]["cited"], True)
                        detail = (" exit_code=7" if baseline == "red" else
                                  " differed=fingerprint" if baseline == "stale" else "")
                        self.assertIn(
                            f"{baseline}: {command}{detail} phase=before source=cited", checked.stdout)

    def test_pass_event_has_separate_logs_and_invocation_and_does_not_mutate(self):
        self.green()
        state = (self.run_dir / "state.json").read_bytes()
        index = (self.repo / ".git/index").read_bytes()
        head = self.git("rev-parse", "HEAD")
        before = (self.run_dir / "events.jsonl").read_bytes()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verdict=pass gate=advance", result.stdout)
        event = self.event()
        self.assertEqual(event["type"], "orchestrator.verified")
        data = event["data"]
        self.assertEqual(data["verdict"], "pass")
        self.assertEqual(data["capture"]["label"], "report-captured implement-1")
        self.assertEqual(data["capture"]["repository"], str(self.repo.resolve()))
        self.assertEqual(len(data["commands"]), 1)
        self.assertIn("check_evidence.py", data["commands"][0])
        self.assertEqual({log["command"] for log in data["checked_logs"]}, set(self.commands))
        for log in data["checked_logs"]:
            self.assertEqual(log["exit_code"], 0)
            self.assertGreaterEqual(log["duration_seconds"], 0)
            for when in ("before", "after"):
                self.assertEqual(log[f"head_{when}"], data["capture"]["head"])
                self.assertEqual(log[f"fingerprint_{when}"], data["capture"]["fingerprint"])
        self.assertTrue((self.run_dir / "events.jsonl").read_bytes().startswith(before))
        self.assertEqual((self.run_dir / "state.json").read_bytes(), state)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_legacy_and_relative_tracker(self):
        self.rules(legacy=True)
        self.state["deliverables"]["tracker"] = "../tracker"
        (self.run_dir / "state.json").write_text(json.dumps(self.state))
        self.green()
        self.assertEqual(self.check(report=False).returncode, 0)

    def test_missing_own_log_and_nonzero_log(self):
        self.rules(commands=["exit 7", self.command])
        self.assertEqual(self.wrap("exit 7").returncode, 7)
        # Another stage's log never satisfies the stage being checked.
        self.wrap(stage="review")
        self.capture()
        result = self.check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("red: exit 7 exit_code=7", result.stdout)
        self.assertIn(f"missing: {self.command}", result.stdout)

    def test_fingerprint_stale_and_passing_repeat_supersedes_before_run(self):
        self.green()
        self.file.write_text("changed\n")
        self.capture()
        result = self.check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn(f"stale: {self.command} differed=fingerprint", result.stdout)
        self.green()
        self.assertEqual(self.check().returncode, 0)

    def test_both_before_and_after_identities_must_match(self):
        command = "printf changed > tracked.txt"
        self.rules(commands=[command])
        self.wrap(command)
        self.capture()
        result = self.check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("differed=fingerprint", result.stdout)
        self.file.write_text("base\n")
        self.capture()
        self.assertIn("differed=fingerprint", self.check().stdout)

    def test_clean_tree_head_change_is_stale(self):
        self.green()
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "new HEAD")
        self.capture()
        result = self.check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("differed=HEAD", result.stdout)
        self.assertNotIn("differed=HEAD,fingerprint", result.stdout)

    def test_another_repository_is_stale_even_with_identical_commit(self):
        other = self.root / "other"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(other)], env=self.env, check=True)
        for command in self.commands:
            self.wrap(command, cwd=other)
        self.capture()
        result = self.check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("differed=repository", result.stdout)

    def test_each_stage_and_followup_pass_uses_its_own_capture_and_logs(self):
        for stage in ("implement", "simplify", "review", "test"):
            with self.subTest(stage=stage):
                self.green(stage, 1)
                self.file.write_text(f"{stage} pass 2\n")
                self.green(stage, 2, followup=stage == "implement")
                self.assertEqual(self.check(stage, 2).returncode, 0)
                self.assertEqual(self.event()["data"]["capture"]["label"], f"report-captured {stage}-2")
                self.file.write_text("later\n")
                self.capture(stage, 2)
                self.assertEqual(self.check(stage, 2).returncode, 3)

    def test_combined_gate_preserves_report_severity(self):
        self.capture()
        for blockers, drift, gate, code in (("None", "None", "stop", 3),
                                            ("blocked", "None", "blocked", 4),
                                            ("None", "changed plan", "hitl", 5)):
            with self.subTest(gate=gate):
                self.report_text(blockers, drift)
                result = self.check()
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(f"verdict=fail gate={gate}", result.stdout)
        self.report_text()
        self.green()
        self.assertIn("verdict=pass gate=advance", self.check().stdout)

    def test_triage_exempt_without_capture_or_logs(self):
        result = self.check("triage")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verdict=exempt", result.stdout)
        self.assertFalse((self.run_dir / "events.jsonl").exists())

    def test_invalid_log_is_not_evidence_and_output_cannot_spoof_header(self):
        self.rules(commands=[self.command])
        self.wrap()
        path = self.log_path()
        payload = path.read_bytes()
        path.write_bytes(b"arbitrary runner output\n---\n" + payload)
        self.capture()
        result = self.check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn(f"missing: {self.command}", result.stdout)
        self.assertIn("invalid log:", result.stdout)

    def test_missing_capture_or_canonical_commands_fails_closed(self):
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing snapshot", result.stderr)
        (self.tracker / "README.md").write_text("# No commands\n")
        self.assertNotEqual(self.check().returncode, 0)

    def test_malformed_headers_cannot_satisfy_a_command(self):
        self.rules(commands=[self.command])
        self.wrap()
        self.capture()
        path = self.log_path()
        original = path.read_bytes()
        for before, after in ((b"evidence_version: 1", b"evidence_version: 2"),
                              (b"exit_code: 0", b"exit_code: invalid"),
                              (b"duration_seconds: ", b"duration_seconds: nan"),
                              (b"head_before: ", b"head_before: invalid"),
                              (b"fingerprint_after: ", b"fingerprint_after: invalid"),
                              (b"---\n", b"no separator\n")):
            with self.subTest(field=before):
                path.write_bytes(original.replace(before, after, 1))
                result = self.check()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn(f"missing: {self.command}", result.stdout)

    def test_requires_repository_root(self):
        nested = self.repo / "nested"
        nested.mkdir()
        result = self.check(cwd=nested)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("repository root", result.stderr)


if __name__ == "__main__":
    unittest.main()
