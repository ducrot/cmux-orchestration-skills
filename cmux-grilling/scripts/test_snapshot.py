#!/usr/bin/env python3
"""Snapshot CLI regressions, vendored with each independently installed skill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUN_STATE = Path(__file__).resolve().with_name("run_state.py")


class SnapshotCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_dir = self.root / "run"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q")
        self.git("config", "user.name", "Snapshot Test")
        self.git("config", "user.email", "snapshot@example.invalid")
        self.git("config", "core.hooksPath", os.devnull)
        self.file = self.repo / "tracked.txt"
        self.file.write_bytes(b"base\n")
        self.git("add", "tracked.txt")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "baseline")

    def git(self, *args, input=None):
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, input=input,
            capture_output=True, check=True,
        ).stdout

    def snapshot(self):
        result = subprocess.run(
            [sys.executable, str(RUN_STATE), "snapshot", "--run-dir", str(self.run_dir),
             "--label", "regression"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        event = json.loads((self.run_dir / "events.jsonl").read_text().splitlines()[-1])
        self.assertEqual(event["type"], "tree.snapshot")
        self.assertEqual(event["message"], "regression")
        self.assertIn(event["data"]["fingerprint"], result.stdout)
        return event["data"]

    def test_conflicted_non_utf8_contents_have_distinct_fingerprints(self):
        # A combined diff has a zero worktree OID, so its headers cannot compensate
        # for collapsing different invalid bytes into the same replacement character.
        blobs = [self.git("hash-object", "-w", "--stdin", input=data).strip()
                 for data in (b"base\n", b"ours\n", b"theirs\n")]
        self.git("update-index", "--force-remove", "tracked.txt")
        entries = b"".join(b"100644 " + oid + f" {stage}\ttracked.txt\n".encode()
                           for stage, oid in enumerate(blobs, 1))
        self.git("update-index", "--index-info", input=entries)
        self.assertEqual(self.git("status", "--porcelain"), b"UU tracked.txt\n")
        self.file.write_bytes(b"\xff\n")
        first = self.snapshot()
        self.file.write_bytes(b"\xfe\n")
        second = self.snapshot()
        self.assertEqual(first["head"], second["head"])
        self.assertEqual(first["dirty_paths"], 1)
        self.assertEqual(second["dirty_paths"], 1)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_non_utf8_diff_can_be_snapshotted_unstaged_and_staged(self):
        self.file.write_bytes(b"descriptor: \xec\n")
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    self.git("add", "tracked.txt")
                diff_args = ("diff", "--cached") if staged else ("diff",)
                self.assertIn(b"\xec", self.git(*diff_args))
                before = self.git("status", "--porcelain")
                event = self.snapshot()
                self.assertEqual(event["dirty_paths"], 1)
                self.assertEqual(self.git("status", "--porcelain"), before)
                self.assertEqual(self.file.read_bytes(), b"descriptor: \xec\n")

    def test_unchanged_tree_is_stable_and_ascii_edit_changes_fingerprint(self):
        clean = self.snapshot()
        # SHA-256 of the empty status + empty diff, preserving the existing clean-tree contract.
        self.assertEqual(clean["fingerprint"], "e3b0c44298fc1c14")
        self.assertEqual(clean["dirty_paths"], 0)
        self.file.write_bytes(b"changed\n")
        changed = self.snapshot()
        self.assertEqual(changed["dirty_paths"], 1)
        self.assertNotEqual(clean["fingerprint"], changed["fingerprint"])
        self.assertEqual(changed, self.snapshot())


if __name__ == "__main__":
    unittest.main()
