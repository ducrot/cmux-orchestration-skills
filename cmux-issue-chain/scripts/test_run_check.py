"""End-to-end evidence wrapper regressions using an isolated Git repository."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

import test_snapshot

WRAPPER = Path(__file__).with_name("run_check.py").resolve()


class RunCheckCli(unittest.TestCase):
    git = test_snapshot.SnapshotCli.git
    snapshot = test_snapshot.SnapshotCli.snapshot

    def setUp(self):
        test_snapshot.SnapshotCli.setUp(self)
        # Ignore evidence as target repositories do; creating logs must not alter the tree.
        (self.repo / ".git" / "info" / "exclude").write_text(".scratch/\n")
        self.artifacts = self.repo / ".scratch" / "run" / "artifacts" / "implement-1"

    def run_check(self, command, cwd=None):
        return subprocess.run(
            [sys.executable, str(WRAPPER), "--artifact-dir", str(self.artifacts),
             "--command", command], cwd=cwd or self.repo, env=self.env, capture_output=True,
        )

    def read_log(self, path):
        header, output = path.read_bytes().split(b"---\n", 1)
        fields = dict(line.split(": ", 1) for line in header.decode().splitlines())
        self.assertEqual(list(fields), [
            "evidence_version", "command", "exit_code", "duration_seconds", "repository",
            "head_before", "fingerprint_before", "head_after", "fingerprint_after",
        ])
        return fields, output

    def test_wrapper_matches_snapshot_and_preserves_raw_output_without_events(self):
        before = self.snapshot()
        events = (self.run_dir / "events.jsonl").read_bytes()
        # Combined stdout/stderr and binary bytes must survive unchanged in the log.
        output = b"stdout\nstderr\n\xff\r\nRan 2 tests in 120.000s\n\nOK\n"
        command = shlex.join([sys.executable, "-c", f"import os; os.write(1, {output[:7]!r}); os.write(2, {output[7:]!r})"])
        result = self.run_check(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, output)
        log = next(self.artifacts.glob("*.log"))
        self.assertEqual(result.stderr, f"run_check: log written to {log.resolve()}\n".encode())
        fields, raw = self.read_log(log)
        self.assertEqual(raw, output)
        self.assertEqual(fields["evidence_version"], "1")
        self.assertEqual(json.loads(fields["command"]), command)
        self.assertEqual(json.loads(fields["repository"]), str(self.repo.resolve()))
        self.assertEqual(fields["exit_code"], "0")
        self.assertGreaterEqual(float(fields["duration_seconds"]), 0)
        self.assertEqual((self.run_dir / "events.jsonl").read_bytes(), events)
        after = self.snapshot()
        self.assertEqual(before, after)
        for when in ("before", "after"):
            self.assertEqual(fields[f"fingerprint_{when}"], after["fingerprint"])
            self.assertEqual(fields[f"head_{when}"], after["head"])
        self.assertEqual(list(self.artifacts.iterdir()), list(self.artifacts.glob("*.log")))

    def test_shell_runs_from_root_and_returns_failure_without_overwriting(self):
        nested = self.repo / "nested"
        nested.mkdir()
        command = "cat tracked.txt && printf 'failed\\n' >&2; exit 7"
        first = self.run_check(command, cwd=nested)
        self.assertEqual(first.returncode, 7, first.stderr)
        self.assertEqual(first.stdout, b"base\nfailed\n")
        log = next(self.artifacts.glob("*.log"))
        self.assertEqual(first.stderr, f"run_check: log written to {log.resolve()}\n".encode())
        original = log.read_bytes()
        second = self.run_check(command)
        self.assertEqual(second.returncode, 7)
        logs = sorted(self.artifacts.glob("*.log"))
        self.assertEqual(len(logs), 2)
        self.assertEqual(log.read_bytes(), original)
        repeated_log = log.with_stem(log.stem + "-2")
        self.assertIn(repeated_log, logs)
        self.assertEqual(second.stderr, f"run_check: log written to {repeated_log.resolve()}\n".encode())
        self.assertEqual(second.stdout, first.stdout)
        for path in logs:
            fields, raw = self.read_log(path)
            self.assertEqual(fields["exit_code"], "7")
            self.assertEqual(raw, first.stdout)

    def test_relative_artifacts_report_absolute_paths_including_repeats(self):
        self.artifacts = self.artifacts.relative_to(self.repo)
        command = "printf 'relative\\n'; exit 7"
        stem = "check-" + hashlib.sha256(command.encode()).hexdigest()
        for suffix in ("", "-2"):
            result = self.run_check(command)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(result.stdout, b"relative\n")
            path = (self.repo / self.artifacts / f"{stem}{suffix}.log").resolve()
            self.assertEqual(result.stderr, f"run_check: log written to {path}\n".encode())
            fields, raw = self.read_log(path)
            self.assertEqual(raw, result.stdout)
            self.assertEqual(fields["exit_code"], "7")
            self.assertEqual(json.loads(fields["command"]), command)

    def test_closed_stderr_preserves_output_exit_code_and_log(self):
        for status in (0, 7):
            with self.subTest(exit_code=status):
                output = b"stdout\n\xff\x00stderr\r\n"
                command = shlex.join([
                    sys.executable, "-c",
                    f"import os; os.write(1, {output[:7]!r}); "
                    f"os.write(2, {output[7:]!r}); raise SystemExit({status})",
                ])
                normal = self.run_check(command)
                # Close fd 2 before interpreter startup so sys.stderr is None.
                closed = subprocess.run(
                    [sys.executable, str(WRAPPER), "--artifact-dir", str(self.artifacts),
                     "--command", command], cwd=self.repo, env=self.env,
                    stdout=subprocess.PIPE, preexec_fn=lambda: os.close(2),
                )
                self.assertEqual(normal.returncode, status, normal.stderr)
                self.assertEqual(closed.returncode, normal.returncode)
                self.assertEqual(normal.stdout, output)
                self.assertEqual(closed.stdout, normal.stdout)
                stem = "check-" + hashlib.sha256(command.encode()).hexdigest()
                fields, raw = self.read_log(self.artifacts / f"{stem}.log")
                closed_fields, closed_raw = self.read_log(self.artifacts / f"{stem}-2.log")
                self.assertEqual(raw, output)
                self.assertEqual(closed_raw, raw)
                self.assertEqual(fields["exit_code"], str(status))
                self.assertEqual(fields["evidence_version"], "1")
                fields.pop("duration_seconds")
                closed_fields.pop("duration_seconds")
                self.assertEqual(closed_fields, fields)

    def test_broken_stderr_pipe_preserves_output_exit_code_and_log(self):
        for status in (0, 7):
            with self.subTest(exit_code=status):
                output = b"stdout\n\xff\x00stderr\r\n"
                command = shlex.join([
                    sys.executable, "-c",
                    f"import os; os.write(1, {output[:7]!r}); "
                    f"os.write(2, {output[7:]!r}); raise SystemExit({status})",
                ])
                normal = self.run_check(command)
                reader, writer = os.pipe()
                os.close(reader)
                try:
                    broken = subprocess.run(
                        [sys.executable, str(WRAPPER), "--artifact-dir", str(self.artifacts),
                         "--command", command], cwd=self.repo, env=self.env,
                        stdout=subprocess.PIPE, stderr=writer,
                    )
                finally:
                    os.close(writer)
                self.assertEqual(normal.returncode, status, normal.stderr)
                self.assertEqual(broken.returncode, normal.returncode)
                self.assertEqual(normal.stdout, output)
                self.assertEqual(broken.stdout, normal.stdout)
                stem = "check-" + hashlib.sha256(command.encode()).hexdigest()
                fields, raw = self.read_log(self.artifacts / f"{stem}.log")
                broken_fields, broken_raw = self.read_log(self.artifacts / f"{stem}-2.log")
                self.assertEqual(raw, output)
                self.assertEqual(broken_raw, raw)
                self.assertEqual(fields["exit_code"], str(status))
                self.assertEqual(fields["evidence_version"], "1")
                fields.pop("duration_seconds")
                broken_fields.pop("duration_seconds")
                self.assertEqual(broken_fields, fields)

    def test_multiline_command_has_one_header_line_and_deterministic_name(self):
        command = "printf 'first\\n'\nprintf 'second\\n'"
        result = self.run_check(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = next(self.artifacts.glob("*.log"))
        self.assertEqual(path.name, "check-" + hashlib.sha256(command.encode()).hexdigest() + ".log")
        fields, raw = self.read_log(path)
        self.assertEqual(json.loads(fields["command"]), command)
        self.assertEqual(raw, b"first\nsecond\n")

    def test_shared_fingerprint_function_is_read_only(self):
        from run_state import tree_fingerprint
        expected = self.snapshot()
        events = (self.run_dir / "events.jsonl").read_bytes()
        # Same isolated Git config as the snapshot subprocess, so user config cannot skew diffs.
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(tree_fingerprint(self.repo), expected)
        self.assertEqual((self.run_dir / "events.jsonl").read_bytes(), events)
        self.assertFalse(self.artifacts.exists())

    def test_changed_tree_records_distinct_before_and_after(self):
        before = self.snapshot()
        result = self.run_check("printf 'changed\\n' >> tracked.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        fields, _ = self.read_log(next(self.artifacts.glob("*.log")))
        after = self.snapshot()
        self.assertEqual(fields["fingerprint_before"], before["fingerprint"])
        self.assertEqual(fields["fingerprint_after"], after["fingerprint"])
        self.assertNotEqual(fields["fingerprint_before"], fields["fingerprint_after"])


class CanonicalSuiteGuard(unittest.TestCase):
    """Editing roles leave canonical suites to the final test unless they name a reason."""

    git = test_snapshot.SnapshotCli.git

    def setUp(self):
        test_snapshot.SnapshotCli.setUp(self)
        (self.repo / ".git" / "info" / "exclude").write_text(".scratch/\n")
        scratch = self.repo / ".scratch"
        self.marker = self.root / "ran"
        self.canonical = f"touch {shlex.quote(str(self.marker))}"
        self.tracker = scratch / "2026-10-31-tracker"
        self.tracker.mkdir(parents=True)
        (self.tracker / "README.md").write_text(
            f"# Tracker\n\n## Ground rules\n\n- Canonical check commands:\n  - `{self.canonical}`\n")
        self.guarded_run = scratch / "orchestrator" / "runs" / "chain"
        self.guarded_run.mkdir(parents=True)
        (self.guarded_run / "state.json").write_text(json.dumps({
            "workflow": "issue-chain", "layout_version": 2,
            "deliverables": {"tracker": str(self.tracker)}}))

    def wrap(self, stage, command, *extra):
        return subprocess.run(
            [sys.executable, str(WRAPPER), "--artifact-dir",
             str(self.guarded_run / "artifacts" / stage), "--command", command, *extra],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )

    def test_editing_roles_are_refused_before_the_suite_starts(self):
        for stage in ("implement-1", "simplify-1", "review-1", "implement-2"):
            with self.subTest(stage=stage):
                result = self.wrap(stage, self.canonical)
                self.assertEqual(result.returncode, 64)
                self.assertIn("--full-suite-reason", result.stderr)
                self.assertFalse(self.marker.exists())
                self.assertFalse((self.guarded_run / "artifacts" / stage).exists())

    def test_named_reason_runs_the_suite_and_writes_normal_evidence(self):
        result = self.wrap("implement-1", self.canonical,
                           "--full-suite-reason", "Changed the shared state reader.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())
        log = result.stderr.removeprefix("run_check: log written to ").strip()
        self.assertEqual(Path(f"{log}.reason").read_text(), "Changed the shared state reader.\n")

    def test_blank_reason_is_refused(self):
        result = self.wrap("review-1", self.canonical, "--full-suite-reason", "   ")
        self.assertEqual(result.returncode, 64)
        self.assertFalse(self.marker.exists())

    def test_selected_commands_need_no_reason(self):
        result = self.wrap("implement-1", f"{self.canonical} -c")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())

    def test_final_test_runs_canonical_commands_without_reason(self):
        result = self.wrap("test-1", self.canonical)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())

    def test_relative_tracker_path_from_a_nested_directory_is_still_guarded(self):
        state = json.loads((self.guarded_run / "state.json").read_text())
        state["deliverables"]["tracker"] = ".scratch/2026-10-31-tracker"
        (self.guarded_run / "state.json").write_text(json.dumps(state))
        nested = self.repo / "nested"
        nested.mkdir(exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(WRAPPER), "--artifact-dir",
             str(self.guarded_run / "artifacts" / "implement-1"), "--command", self.canonical],
            cwd=nested, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 64)

    def test_unreadable_declarations_do_not_block_checks(self):
        (self.tracker / "README.md").unlink()
        result = self.wrap("implement-1", self.canonical)
        self.assertEqual(result.returncode, 0, result.stderr)
        for state in ("", json.dumps({"workflow": "issue-chain", "layout_version": 1})):
            with self.subTest(state=state):
                (self.guarded_run / "state.json").write_text(state)
                result = self.wrap("implement-1", self.canonical)
                self.assertEqual(result.returncode, 0, result.stderr)
        (self.guarded_run / "state.json").unlink()
        result = self.wrap("implement-1", self.canonical)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
