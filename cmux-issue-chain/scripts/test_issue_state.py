#!/usr/bin/env python3
"""Tracker preflight regression tests. Run: python3 .agents/skills/cmux-issue-chain/scripts/test_issue_state.py"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator_lib import TrackerFormatError, load_issues  # noqa: E402


TO_TICKETS_MARKDOWN = """# 01 — Sample issue

**What to build:** the thing.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] One criterion
"""


def issue_markdown(issue_id: str) -> str:
    return f"""---
id: {issue_id}
title: Sample issue
type: AFK
status: todo
---

# {issue_id} — Sample issue

## Blocked by

- None

## Acceptance Criteria

- [ ] One criterion
"""


def make_tracker(root: Path, files: dict[str, str]) -> Path:
    issue_dir = root / "issues"
    issue_dir.mkdir(parents=True)
    for name, text in files.items():
        (issue_dir / name).write_text(text, encoding="utf-8")
    return root


class Preflight(unittest.TestCase):
    def test_conforming_tracker_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp),
                {
                    "ISSUE-001-sample.md": issue_markdown("ISSUE-001"),
                    "README.md": "# tracker notes\n",
                    "_index.md": "# index\n",
                },
            )
            issues = load_issues(tracker)
        self.assertEqual(list(issues), ["ISSUE-001"])

    def test_to_tickets_filenames_load_with_normalized_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp),
                {
                    "01-sample.md": issue_markdown("ISSUE-001"),
                    "02-other.md": issue_markdown("ISSUE-002"),
                },
            )
            issues = load_issues(tracker)
        self.assertEqual(list(issues), ["ISSUE-001", "ISSUE-002"])

    def test_slugless_filenames_still_load(self):
        """Regression: ISSUE-002.md was rejected as stray after the NN-*.md relaxation."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp),
                {"ISSUE-001.md": issue_markdown("ISSUE-001"), "02.md": issue_markdown("ISSUE-002")},
            )
            issues = load_issues(tracker)
        self.assertEqual(sorted(issues), ["ISSUE-001", "ISSUE-002"])

    def test_prose_numbers_beside_explicit_ids_are_not_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = issue_markdown("ISSUE-002").replace("- None", "- ISSUE-001 (see PR 42)")
            tracker = make_tracker(
                Path(tmp),
                {"ISSUE-001-a.md": issue_markdown("ISSUE-001"), "ISSUE-002-b.md": blocked},
            )
            issues = load_issues(tracker)
        self.assertEqual(issues["ISSUE-002"].blocked_by, ["ISSUE-001"])

    def test_bare_number_blockers_resolve_to_issue_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = issue_markdown("ISSUE-002").replace("- None", "- 01")
            tracker = make_tracker(
                Path(tmp),
                {"01-sample.md": issue_markdown("ISSUE-001"), "02-other.md": blocked},
            )
            issues = load_issues(tracker)
        self.assertEqual(issues["ISSUE-002"].blocked_by, ["ISSUE-001"])

    def test_stray_filenames_fail_loudly_and_are_named(self):
        """Regression: unnumbered *.md files were silently ignored — zero issues listed, exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp),
                {
                    "notes-sample.md": issue_markdown("ISSUE-001"),
                    "ISSUE-002-ok.md": issue_markdown("ISSUE-002"),
                },
            )
            with self.assertRaises(TrackerFormatError) as ctx:
                load_issues(tracker)
        self.assertIn("notes-sample.md", str(ctx.exception))
        self.assertNotIn("ISSUE-002-ok.md", str(ctx.exception))

    def test_unadopted_issue_fails_loudly_and_points_at_adopt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"01-sample.md": TO_TICKETS_MARKDOWN})
            with self.assertRaises(TrackerFormatError) as ctx:
                load_issues(tracker)
        self.assertIn("01-sample.md", str(ctx.exception))
        self.assertIn("adopt_tracker.py", str(ctx.exception))

    def test_zero_issues_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"README.md": "# only docs\n"})
            with self.assertRaises(TrackerFormatError):
                load_issues(tracker)

    def test_missing_issue_dir_still_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_issues(Path(tmp))


class Cli(unittest.TestCase):
    script = str(Path(__file__).parent / "issue_state.py")

    def run_list(self, tracker: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, self.script, "list", "--tracker", str(tracker)],
            capture_output=True,
            text=True,
        )

    def test_list_on_stray_tracker_exits_nonzero_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"notes-sample.md": issue_markdown("ISSUE-001")})
            proc = self.run_list(tracker)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("notes-sample.md", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_list_on_empty_tracker_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"README.md": "# docs\n"})
            proc = self.run_list(tracker)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_list_on_conforming_tracker_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"ISSUE-001-sample.md": issue_markdown("ISSUE-001")})
            proc = self.run_list(tracker)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("ISSUE-001", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
