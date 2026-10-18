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
        fields, raw = self.read_log(next(self.artifacts.glob("*.log")))
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
        original = log.read_bytes()
        second = self.run_check(command)
        self.assertEqual(second.returncode, 7)
        logs = sorted(self.artifacts.glob("*.log"))
        self.assertEqual(len(logs), 2)
        self.assertEqual(log.read_bytes(), original)
        self.assertIn(log.with_stem(log.stem + "-2"), logs)
        for path in logs:
            fields, raw = self.read_log(path)
            self.assertEqual(fields["exit_code"], "7")
            self.assertEqual(raw, first.stdout)

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


if __name__ == "__main__":
    unittest.main()
