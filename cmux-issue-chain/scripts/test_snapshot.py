#!/usr/bin/env python3
"""Snapshot CLI regressions, vendored with each independently installed skill."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from run_state import untracked_content


RUN_STATE = Path(__file__).resolve().with_name("run_state.py")


class SnapshotCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        (self.run_dir / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
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

    def failed_snapshot(self, env=None):
        result = subprocess.run(
            [sys.executable, str(RUN_STATE), "snapshot", "--run-dir", str(self.run_dir),
             "--label", "incomplete-capture"],
            cwd=self.repo, env=env or self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.run_dir / "events.jsonl").exists())
        return result.stderr

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode-000 files")
    def test_unreadable_untracked_path_fails_closed_then_recovers(self):
        blocked = self.repo / "blocked"
        blocked.write_bytes(b"secret")
        blocked.chmod(0)
        self.addCleanup(blocked.chmod, 0o644)
        stderr = self.failed_snapshot()
        self.assertIn("cannot hash untracked path 'blocked'", stderr)
        self.assertIn("integrity capture is incomplete", stderr)
        self.assertIn("Permission denied", stderr)
        blocked.chmod(0o644)
        self.assertEqual(self.snapshot()["untracked_hashed"], 1)

    def test_vanished_untracked_path_fails_closed_then_recovers(self):
        # A status shim reports a path that no longer exists, as when it vanishes before hashing.
        real_git = shutil.which("git")
        shim_dir = self.root / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "if 'status' in sys.argv[1:]:\n"
            "    sys.stdout.buffer.write(b'?? vanished\\0')\n"
            "    sys.exit(0)\n"
            f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n"
        )
        shim.chmod(0o755)
        stderr = self.failed_snapshot(dict(self.env, PATH=str(shim_dir) + os.pathsep + self.env["PATH"]))
        self.assertIn("cannot hash untracked path 'vanished'", stderr)
        self.assertIn("integrity capture is incomplete", stderr)
        self.assertIn("No such file or directory", stderr)
        self.assertEqual(self.snapshot()["untracked_hashed"], 0)

    def test_status_failure_and_malformed_output_have_cli_diagnostics(self):
        # Exercise the real snapshot CLI with only git status replaced by a shim.
        real_git = shutil.which("git")
        shim_dir = self.root / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        cases = (
            ("failure", "    sys.stderr.write('status unavailable\\n')\n    sys.exit(128)\n",
             "failed: status unavailable"),
            ("malformed", "    sys.stdout.buffer.write(b'x\\0')\n    sys.exit(0)\n",
             "git status returned an unparseable porcelain entry"),
            ("rename", "    sys.stdout.buffer.write(b'R  destination\\0')\n    sys.exit(0)\n",
             "git status rename/copy entry is incomplete"),
        )
        for mode, body, expected in cases:
            with self.subTest(mode=mode):
                shim.write_text(
                    f"#!{sys.executable}\n"
                    "import os, sys\n"
                    "if 'status' in sys.argv[1:]:\n"
                    + body
                    + f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n"
                )
                shim.chmod(0o755)
                env = dict(self.env, PATH=str(shim_dir) + os.pathsep + self.env["PATH"])
                result = subprocess.run(
                    [sys.executable, str(RUN_STATE), "snapshot", "--run-dir", str(self.run_dir),
                     "--label", "failure-regression"],
                    cwd=self.repo, env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertFalse((self.run_dir / "events.jsonl").exists())

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

    def test_staged_paths_and_raw_digest_track_index_only(self):
        for content in (b"text change\n", b"\x00binary change\xff"):
            with self.subTest(content=content):
                self.file.write_bytes(content)
                before = self.snapshot()
                self.git("add", "tracked.txt")
                staged = self.snapshot()
                self.assertEqual(self.file.read_bytes(), content)
                self.assertEqual(staged["staged_paths"], ["tracked.txt"])
                self.assertNotEqual(before["staged_diff_sha256"], staged["staged_diff_sha256"])
                self.assertEqual(staged["staged_diff_sha256"], hashlib.sha256(
                    self.git("diff", "--cached", "--binary", "--no-ext-diff")).hexdigest())
                unchanged = self.snapshot()
                self.assertEqual(staged["staged_paths"], unchanged["staged_paths"])
                self.assertEqual(staged["staged_diff_sha256"], unchanged["staged_diff_sha256"])
                self.file.write_bytes(content + b"restaged")
                self.git("add", "tracked.txt")
                restaged = self.snapshot()
                self.assertEqual(staged["staged_paths"], restaged["staged_paths"])
                self.assertNotEqual(staged["staged_diff_sha256"], restaged["staged_diff_sha256"])

    def test_staged_paths_exclude_untracked_and_worktree_only_changes(self):
        self.file.write_text("worktree only")
        (self.repo / "loose").write_text("untracked")
        before = self.snapshot()
        self.assertEqual(before["staged_paths"], [])
        self.git("add", "tracked.txt", "loose")
        self.assertEqual(self.snapshot()["staged_paths"], ["loose", "tracked.txt"])

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

    def test_untracked_content_and_byte_paths_change_fingerprint(self):
        path = self.repo / "new\nname-é"
        path.write_bytes(b"\xff\x00before")
        first = self.snapshot()
        path.write_bytes(b"\xfe\x00after")
        second = self.snapshot()
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(second["untracked_hashed"], 1)
        self.assertEqual(second["dirty_paths"], 1)
        self.assertEqual(second["untracked_skipped"], [])
        self.assertEqual(second, self.snapshot())

    def test_untracked_limit_is_recorded(self):
        path = self.repo / "large"
        with path.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        first = self.snapshot()
        with path.open("r+b") as stream:
            stream.write(b"b")
        self.assertEqual(first, self.snapshot())
        self.assertEqual(first["untracked_hashed"], 0)
        self.assertEqual(first["untracked_skipped"], [
            {"path": "large", "reason": "size exceeds 8 MiB limit"},
        ])
        path.write_bytes(b"a" * (8 * 1024 * 1024))
        self.assertEqual(self.snapshot()["untracked_hashed"], 1)

    def test_non_utf8_path_bytes_and_unsupported_status_entry(self):
        # APFS rejects raw non-UTF-8 names, and Git normally omits special files.
        raw = b"?? raw-\xff\n\0?? pipe\0"
        with patch("run_state.os.lstat", side_effect=[
                 SimpleNamespace(st_mode=stat.S_IFREG, st_size=2),
                 SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0),
             ]), patch("builtins.open", return_value=io.BytesIO(b"\xff\x00")) as opened:
            entries, states, block = untracked_content(self.repo, raw)
        opened.assert_called_once_with(os.fsencode(self.repo) + b"/raw-\xff\n", "rb")
        path = os.fsdecode(b"raw-\xff\n")
        digest = hashlib.sha256(b"\xff\x00").hexdigest()
        self.assertEqual(entries, [("??", path), ("??", "pipe")])
        self.assertEqual(states[path], {"content_sha256": digest})
        self.assertEqual(states["pipe"], {"skipped": "unsupported file type"})
        self.assertEqual(block, b"raw-\xff\n\0" + digest.encode() + b"\n")

    def test_symlinks_hash_target_bytes_without_following(self):
        link = self.repo / "link"
        target = self.root / "external"
        target.write_text("before")
        link.symlink_to(target)
        first = self.snapshot()
        target.write_text("after")
        self.assertEqual(first, self.snapshot())
        link.unlink()
        os.symlink(b"missing-\xff", os.fsencode(link))
        second = self.snapshot()
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(second["untracked_hashed"], 1)

    def test_binary_changes_are_distinct_working_and_cached(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.file.write_bytes(b"\x00before")
                if staged:
                    self.git("add", "tracked.txt")
                first = self.snapshot()
                self.file.write_bytes(b"\x00after")
                if staged:
                    self.git("add", "tracked.txt")
                self.assertNotEqual(first["fingerprint"], self.snapshot()["fingerprint"])

    def test_rename_source_and_ignored_paths(self):
        self.git("mv", "tracked.txt", "renamed\nfile")
        self.file.write_bytes(b"new untracked source")
        first = self.snapshot()
        self.assertEqual(first["untracked_hashed"], 1)
        self.file.write_bytes(b"changed untracked source")
        self.assertNotEqual(first["fingerprint"], self.snapshot()["fingerprint"])
        (self.repo / ".git" / "info" / "exclude").write_text("ignored\n")
        first = self.snapshot()
        (self.repo / "ignored").write_bytes(b"ignored")
        self.assertEqual(first, self.snapshot())

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
