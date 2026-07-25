#!/usr/bin/env python3
"""Adoption regression tests. Run: python3 .agents/skills/cmux-issue-chain/scripts/test_adopt_tracker.py"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator_lib import load_issues  # noqa: E402

SCRIPT = str(Path(__file__).parent / "adopt_tracker.py")


def ticket(number: str, title: str, status: str = "ready-for-agent", blocked: str = "None — can start immediately") -> str:
    return f"""# {number} — {title}

**What to build:** the end-to-end behaviour.

**Blocked by:** {blocked}

**Status:** {status}

- [ ] One criterion
- [x] Another criterion
"""


def make_tracker(root: Path, files: dict[str, str]) -> Path:
    issue_dir = root / "issues"
    issue_dir.mkdir(parents=True)
    for name, text in files.items():
        (issue_dir / name).write_text(text, encoding="utf-8")
    return root


def adopt(tracker: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCRIPT, "--tracker", str(tracker), *extra], capture_output=True, text=True)


class Adoption(unittest.TestCase):
    def test_adopted_tracker_loads_with_types_and_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp),
                {
                    "01-first.md": ticket("01", "First slice"),
                    "02-second.md": ticket("02", "Second slice", blocked="01"),
                    "03-release.md": ticket("03", "Ship it", status="ready-for-human"),
                },
            )
            proc = adopt(tracker, "--check-command", "pnpm test", "--branch", "feature/x")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            issues = load_issues(tracker)

            self.assertEqual(sorted(issues), ["ISSUE-001", "ISSUE-002", "ISSUE-003"])
            self.assertEqual(issues["ISSUE-001"].type, "AFK")
            self.assertEqual(issues["ISSUE-001"].title, "First slice")
            self.assertEqual(issues["ISSUE-002"].blocked_by, ["ISSUE-001"])
            self.assertEqual(issues["ISSUE-003"].type, "HITL")
            self.assertEqual(issues["ISSUE-001"].status, "todo")
            self.assertEqual((issues["ISSUE-001"].acceptance_done, issues["ISSUE-001"].acceptance_total), (1, 2))
            self.assertIn("pnpm test", (tracker / "README.md").read_text())
            self.assertTrue((tracker / "decisions.md").exists())

    def test_acceptance_criteria_stay_out_of_the_blocked_by_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"01-first.md": ticket("01", "First", blocked="None")})
            adopt(tracker)
            body = (Path(tmp) / "issues" / "01-first.md").read_text()
        self.assertLess(body.index("## Acceptance Criteria"), body.index("## Blocked by"))
        self.assertNotIn("- [ ]", body[body.index("## Blocked by") :])

    def test_inline_status_and_blocked_lines_are_removed(self):
        """They would otherwise contradict the frontmatter the chain keeps updating."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"02-second.md": ticket("02", "Second", blocked="01")})
            adopt(tracker)
            body = (Path(tmp) / "issues" / "02-second.md").read_text()
        self.assertNotIn("**Status:**", body)
        self.assertNotIn("**Blocked by:**", body)
        self.assertIn("**What to build:**", body)

    def test_adoption_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"01-first.md": ticket("01", "First")})
            adopt(tracker)
            path = Path(tmp) / "issues" / "01-first.md"
            path.write_text(path.read_text().replace("status: todo", "status: done"), encoding="utf-8")
            first = path.read_text()
            proc = adopt(tracker)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(first, path.read_text() if path.exists() else first)
        self.assertIn("already adopted", proc.stdout)

    def test_unknown_status_aborts_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp),
                {"01-first.md": ticket("01", "First"), "02-second.md": ticket("02", "Second", status="in-review")},
            )
            before = (Path(tmp) / "issues" / "01-first.md").read_text()
            proc = adopt(tracker)
            after = (Path(tmp) / "issues" / "01-first.md").read_text()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("in-review", proc.stderr)
        self.assertEqual(before, after)
        self.assertFalse((Path(tmp) / "README.md").exists())

    def test_missing_status_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            no_status = ticket("01", "First").replace("**Status:** ready-for-agent\n\n", "")
            tracker = make_tracker(Path(tmp), {"01-first.md": no_status})
            proc = adopt(tracker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("AFK/HITL", proc.stderr)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp), {"01-first.md": ticket("01", "First")})
            before = (Path(tmp) / "issues" / "01-first.md").read_text()
            proc = adopt(tracker, "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("would adopt", proc.stdout)
            self.assertEqual(before, (Path(tmp) / "issues" / "01-first.md").read_text())
            self.assertFalse((Path(tmp) / "README.md").exists())

    def test_partially_adopted_file_without_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = "---\nid: ISSUE-001\ntitle: First\nstatus: todo\n---\n\n# First\n"
            tracker = make_tracker(Path(tmp), {"01-first.md": broken})
            proc = adopt(tracker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("type", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
