"""Exercise evidence verdicts through real wrapper, snapshot, and check CLIs."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

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

    def rules(self, legacy=False, commands=None):
        wording = ", run as the baseline suite by every worker" if legacy else ""
        (self.tracker / "README.md").write_text(
            "# Tracker\n\n## Ground rules\n\n- Canonical check commands" + wording + ":\n"
            + "".join(f"  - `{command}`\n" for command in (commands or self.commands))
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

    def capture(self, stage="implement", pass_num=1):
        result = self.cli("run_state.py", "snapshot", "--run-dir", self.run_dir,
                          "--label", f"report-captured {stage}-{pass_num}")
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

    def green(self, stage="implement", pass_num=1):
        for command in self.commands:
            result = self.wrap(command, stage, pass_num)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.capture(stage, pass_num)

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
                self.green(stage, 2)
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
