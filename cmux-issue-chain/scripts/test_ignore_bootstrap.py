"""Regression coverage for resolved standard/custom ignore placement."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_state import ensure_runs_root_ignored


class IgnoreBootstrap(unittest.TestCase):
    def test_resolved_standard_publishes_complete_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            runs = repo / ".scratch/orchestrator/runs"
            ignore = runs.parent / ".gitignore"
            observed = []
            replace = os.replace
            def publish(source, target):
                self.assertEqual(Path(target), ignore.resolve())
                self.assertFalse(ignore.exists())
                observed.append(Path(source).read_bytes())
                replace(source, target)
            with patch("run_state.os.replace", side_effect=publish):
                ensure_runs_root_ignored(runs / ".." / "runs", repo)
            self.assertEqual(observed, [b"*\n"])
            self.assertEqual(ignore.read_bytes(), b"*\n")
            self.assertFalse(list(ignore.parent.glob("*.tmp")))

    def test_custom_roots_only_change_the_runs_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            for name in ("runs", "custom"):
                with self.subTest(name=name):
                    parent = Path(tmp) / name
                    parent.mkdir()
                    sentinel = parent / ".gitignore"
                    sentinel.write_bytes(b"parent rules\n")
                    before = sentinel.stat().st_mtime_ns
                    root = parent / name
                    ensure_runs_root_ignored(root, repo)
                    self.assertEqual((root / ".gitignore").read_bytes(), b"*\n")
                    self.assertEqual(set(parent.iterdir()), {sentinel, root})
                    self.assertEqual(sentinel.read_bytes(), b"parent rules\n")
                    self.assertEqual(sentinel.stat().st_mtime_ns, before)
                    local = root / ".gitignore"
                    local.write_bytes(b"local rules\n")
                    local_before = local.stat().st_mtime_ns
                    ensure_runs_root_ignored(root, repo)
                    self.assertEqual(local.read_bytes(), b"local rules\n")
                    self.assertEqual(local.stat().st_mtime_ns, local_before)
                    local.unlink()
                    ensure_runs_root_ignored(root, repo)
                    self.assertEqual(local.read_bytes(), b"*\n")
