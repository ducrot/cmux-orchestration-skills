#!/usr/bin/env python3
"""Untracked hashing and mixed-status planning integrity regressions."""

from __future__ import annotations

import errno
import hashlib
import io
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tree_integrity import IntegrityError, capture_tree, compare_tree, untracked_content


class UntrackedContent(unittest.TestCase):
    def test_byte_paths_rename_copy_tokens_and_unsupported_types(self):
        # APFS rejects non-UTF-8 names and Git omits FIFOs from real status output.
        # Supply the byte protocol directly to cover both without filesystem assumptions.
        raw = (b"R  renamed\npath\0?? not-an-entry\0C  copied\0source\0"
               b"?? raw-\xff\n\0?? pipe\0?? link\0")
        regular = SimpleNamespace(st_mode=stat.S_IFREG, st_size=2)
        fifo = SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0)
        link = SimpleNamespace(st_mode=stat.S_IFLNK, st_size=1)
        with patch("tree_integrity.os.lstat", side_effect=[regular, fifo, link]), \
             patch("builtins.open", return_value=io.BytesIO(b"\xff\x00")) as opened, \
             patch("tree_integrity.os.readlink", return_value=b"missing-\xfe"):
            entries, states, block = untracked_content(Path("/repo"), raw)
        self.assertEqual(entries[:4], [("R ", "renamed\npath"), ("R ", "?? not-an-entry"),
                                       ("C ", "copied"), ("C ", "source")])
        opened.assert_called_once_with(b"/repo/raw-\xff\n", "rb")
        digest = hashlib.sha256(b"\xff\x00").hexdigest()
        target_digest = hashlib.sha256(b"missing-\xfe").hexdigest()
        self.assertEqual(states[os.fsdecode(b"raw-\xff\n")], {"content_sha256": digest})
        self.assertEqual(states["pipe"], {"skipped": "unsupported file type"})
        self.assertEqual(block, b"link\0" + target_digest.encode() + b"\nraw-\xff\n\0" + digest.encode() + b"\n")


class PlanningTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        git_env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        environment = patch.dict(os.environ, git_env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Integrity Test")
        self.git("config", "user.email", "integrity@example.invalid")
        (self.repo / "tracked").write_bytes(b"baseline\n")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "baseline")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              check=True, capture_output=True).stdout

    def test_boundary_discloses_unreadable_directory_visibility_limit(self):
        self.assertIn(
            "contents of unreadable untracked directories that Git omits with a warning",
            capture_tree(self.repo)["boundary"]["not_covered"],
        )

    def test_status_failure_preserves_integrity_error_and_stderr(self):
        failed = subprocess.CompletedProcess([], 128, stdout=b"", stderr=b"status unavailable\xff\n")
        with patch("tree_integrity.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(IntegrityError, "git status .* failed: status unavailable"):
                capture_tree(self.repo)

    def test_status_preserves_thirty_second_timeout(self):
        def timeout(command, **kwargs):
            self.assertEqual(command[-4:], ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
            self.assertEqual(kwargs.get("timeout"), 30)
            self.assertIs(kwargs.get("text"), False)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with patch("tree_integrity.subprocess.run", side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                capture_tree(self.repo)

    def test_status_malformed_preserves_integrity_error(self):
        for raw in (b"x\0", b"R  destination\0"):
            with self.subTest(raw=raw):
                result = subprocess.CompletedProcess([], 0, stdout=raw, stderr=b"")
                with patch("tree_integrity.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(IntegrityError, "git status"):
                        capture_tree(self.repo)

    def test_unreadable_and_vanished_untracked_paths_fail_closed_then_recover(self):
        # Permissions differ under root, so both failures use seams scoped to the one product path.
        target = os.fsencode(self.repo.resolve() / "product")
        (self.repo / "product").write_bytes(b"content")

        def failing(real, cause, code):
            def call(path, *args, **kwargs):
                if path == target:
                    raise cause(code, os.strerror(code), path)
                return real(path, *args, **kwargs)
            return call

        failures = {
            "unreadable": (patch("builtins.open", side_effect=failing(open, PermissionError, errno.EACCES)),
                           PermissionError),
            "vanished": (patch("tree_integrity.os.lstat", side_effect=failing(os.lstat, FileNotFoundError, errno.ENOENT)),
                         FileNotFoundError),
        }
        for mode, (seam, cause) in failures.items():
            with self.subTest(mode=mode):
                with seam, self.assertRaises(IntegrityError) as raised:
                    capture_tree(self.repo)
                message = str(raised.exception)
                self.assertIn("cannot hash untracked path 'product'", message)
                self.assertIn("integrity capture is incomplete", message)
                error = raised.exception
                while error is not None and not isinstance(error, cause):
                    error = error.__cause__
                self.assertIsInstance(error, cause)
        recovered = capture_tree(self.repo)["path_states"]["product"]
        self.assertEqual(recovered["content_sha256"], hashlib.sha256(b"content").hexdigest())

    def test_staged_deletion_and_untracked_content_both_survive(self):
        self.git("rm", "--cached", "tracked")
        before = capture_tree(self.repo)
        state = before["path_states"]["tracked"]
        self.assertEqual(state["status"], "?? D ")
        self.assertIn("deleted file", state["staged_diff"])
        self.assertEqual(state["content_sha256"], hashlib.sha256(b"baseline\n").hexdigest())
        (self.repo / "tracked").write_bytes(b"new\x00content")
        after = capture_tree(self.repo)
        self.assertEqual(after["path_states"]["tracked"]["staged_diff"], state["staged_diff"])
        self.assertEqual(compare_tree(before, after, allowed_paths=[])["unauthorized_paths"], ["tracked"])

    def test_rename_source_content_is_compared_and_staged_diff_preserved(self):
        self.git("mv", "tracked", "renamed\npath")
        (self.repo / "tracked").write_text("new source")
        before = capture_tree(self.repo)
        state = before["path_states"]["tracked"]
        self.assertEqual(state["status"], "?? R ")
        self.assertTrue(state["staged_diff"])
        (self.repo / "tracked").write_text("changed source")
        after = capture_tree(self.repo)
        self.assertEqual(compare_tree(before, after, allowed_paths=[])["unauthorized_paths"], ["tracked"])

    def test_skipped_and_hashed_path_state_shapes(self):
        (self.repo / "small").write_bytes(b"\xff\x00")
        with (self.repo / "large").open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        states = capture_tree(self.repo)["path_states"]
        self.assertEqual(states["small"], {"status": "??", "content_sha256": hashlib.sha256(b"\xff\x00").hexdigest()})
        self.assertEqual(states["large"], {"status": "??", "skipped": "size exceeds 8 MiB limit"})


if __name__ == "__main__":
    unittest.main()
