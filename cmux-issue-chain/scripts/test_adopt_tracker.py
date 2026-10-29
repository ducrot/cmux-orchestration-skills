#!/usr/bin/env python3
"""Adoption regression tests. Run: python3 .agents/skills/cmux-issue-chain/scripts/test_adopt_tracker.py"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import adopt_tracker  # noqa: E402
import run_briefing  # noqa: E402
from orchestrator_lib import load_issues  # noqa: E402

SCRIPT = str(Path(__file__).parent / "adopt_tracker.py")
DATED = "2026-10-28-tracker"


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
    def test_scaffold_uses_neutral_commands_and_preserves_readme_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": ticket("01", "First")})
            proc = adopt(tracker, "--check-command", "pnpm test", "--check-command", "pnpm lint")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            readme = tracker / "README.md"
            original = readme.read_bytes()
            self.assertIn(b"- Canonical check commands:\n  - `pnpm test`\n  - `pnpm lint`\n", original)
            self.assertNotIn(b"run as the baseline suite", original)
            proc = adopt(tracker, "--check-command", "different test command")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(readme.read_bytes(), original)

    def test_adoption_preserves_existing_legacy_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": ticket("01", "First")})
            readme = tracker / "README.md"
            original = b"# Existing\n\n## Ground rules\n\n- Canonical check commands, run as the baseline suite by every worker:\n  - `pnpm test`\n"
            readme.write_bytes(original)
            proc = adopt(tracker, "--check-command", "pnpm lint")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(readme.read_bytes(), original)

    def test_adopted_tracker_loads_with_types_and_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp) / DATED,
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
            self.assertEqual(
                (tracker / "decisions.md").read_text(encoding="utf-8"),
                "# Decisions\n\nApproved, rejected, and deferred recommendations, "
                "one line each: item, verdict, reason.\n",
            )

    def test_adoption_preserves_existing_human_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": ticket("01", "First")})
            ledger = tracker / "decisions.md"
            original = (
                "# Decisions\r\n\r\nRejected and deferred recommendations, "
                "one line each: item, verdict, reason.\r\n"
                "- API rename: rejected — preserve compatibility.\r\n"
                "- Parser cleanup: deferred — separate scope.\r\n"
                "- Test addition: approved — regression evidence.\r\n"
            ).encode("utf-8")
            ledger.write_bytes(original)
            for invocation in ("first adoption", "repeat adoption"):
                with self.subTest(invocation=invocation):
                    proc = adopt(tracker)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(ledger.read_bytes(), original)

    def test_acceptance_criteria_stay_out_of_the_blocked_by_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": ticket("01", "First", blocked="None")})
            adopt(tracker)
            body = (tracker / "issues" / "01-first.md").read_text()
        self.assertLess(body.index("## Acceptance Criteria"), body.index("## Blocked by"))
        self.assertNotIn("- [ ]", body[body.index("## Blocked by") :])

    def test_inline_status_and_blocked_lines_are_removed(self):
        """They would otherwise contradict the frontmatter the chain keeps updating."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"02-second.md": ticket("02", "Second", blocked="01")})
            adopt(tracker)
            body = (tracker / "issues" / "02-second.md").read_text()
        self.assertNotIn("**Status:**", body)
        self.assertNotIn("**Blocked by:**", body)
        self.assertIn("**What to build:**", body)

    def test_adoption_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": ticket("01", "First")})
            adopt(tracker)
            path = tracker / "issues" / "01-first.md"
            path.write_text(path.read_text().replace("status: todo", "status: done"), encoding="utf-8")
            first = path.read_text()
            proc = adopt(tracker)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(first, path.read_text() if path.exists() else first)
        self.assertIn("already adopted", proc.stdout)

    def test_unknown_status_aborts_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(
                Path(tmp) / DATED,
                {"01-first.md": ticket("01", "First"), "02-second.md": ticket("02", "Second", status="in-review")},
            )
            before = (tracker / "issues" / "01-first.md").read_text()
            proc = adopt(tracker)
            after = (tracker / "issues" / "01-first.md").read_text()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("in-review", proc.stderr)
        self.assertEqual(before, after)
        self.assertFalse((tracker / "README.md").exists())

    def test_missing_status_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            no_status = ticket("01", "First").replace("**Status:** ready-for-agent\n\n", "")
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": no_status})
            proc = adopt(tracker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("AFK/HITL", proc.stderr)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": ticket("01", "First")})
            before = (tracker / "issues" / "01-first.md").read_text()
            proc = adopt(tracker, "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("would adopt", proc.stdout)
            self.assertEqual(before, (tracker / "issues" / "01-first.md").read_text())
            self.assertFalse((tracker / "README.md").exists())

    def test_partially_adopted_file_without_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = "---\nid: ISSUE-001\ntitle: First\nstatus: todo\n---\n\n# First\n"
            tracker = make_tracker(Path(tmp) / DATED, {"01-first.md": broken})
            proc = adopt(tracker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("type", proc.stderr)


class AdoptionRename(unittest.TestCase):
    name = "2026-10-28-approved-name"

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
                for p in root.rglob("*")}

    def test_rename_adopt_and_chain_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            tracker = make_tracker(root / "foreign", {
                "01-first.md": ticket("01", "First", status="ready-for-human")})
            proc = adopt(tracker, "--feature", self.name, "--check-command", "python3 -V")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            target = root / self.name
            self.assertFalse(tracker.exists())
            self.assertEqual(load_issues(target)["ISSUE-001"].type, "HITL")
            self.assertIn(f"# {self.name}\n", (target / "README.md").read_text())
            invocation = f"/cmux-issue-chain --tracker {target} --issue ISSUE-001"
            result = subprocess.run([
                sys.executable, str(Path(SCRIPT).with_name("run_state.py")), "init",
                "--tracker", str(target), "--issue", "ISSUE-001", "--no-workspace",
                "--runs-root", str(root / "runs"), "--invocation", invocation,
            ], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(next((root / "runs").glob("*/state.json")).read_text())
            self.assertEqual(state["invocation"], invocation)
            prompt, unchanged = run_briefing.next_prompt(state, {
                "id": "ISSUE-002", "path": str(target / "issues/02-second.md")})
            self.assertFalse(unchanged)
            self.assertEqual(prompt, invocation.replace("ISSUE-001", "ISSUE-002"))

    def test_dry_run_announces_rename_and_preserves_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker = make_tracker(root / "foreign", {"01-first.md": ticket("01", "First")})
            before = self.snapshot(root)
            proc = adopt(tracker, "--feature", self.name, "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("would rename", proc.stdout)
            self.assertIn(str(root / self.name), proc.stdout)
            self.assertIn("would adopt", proc.stdout)
            self.assertEqual(self.snapshot(root), before)

    def test_invalid_or_missing_name_writes_nothing(self):
        for name in (None, "", "2026-02-30-invalid", "2026-10-28-Upper", "2026-10-28-",
                     "2026-10-28-" + "a" * 31, "../2026-10-28-escape",
                     "/tmp/2026-10-28-escape", "2026-10-28-double--dash"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tracker = make_tracker(root / "foreign", {"01-first.md": ticket("01", "First")})
                before = self.snapshot(root)
                proc = adopt(tracker, *(("--feature", name) if name is not None else ()))
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("--feature", proc.stderr)
                self.assertEqual(self.snapshot(root), before)

    def test_adoption_error_prevents_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker = make_tracker(root / "foreign", {
                "01-first.md": ticket("01", "First"),
                "02-broken.md": ticket("02", "Broken", status="unknown")})
            before = self.snapshot(root)
            proc = adopt(tracker, "--feature", self.name)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("unknown triage status", proc.stderr)
            self.assertEqual(self.snapshot(root), before)

    def test_existing_destination_is_refused(self):
        for kind in ("directory", "file", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tracker = make_tracker(root / "foreign", {"01-first.md": ticket("01", "First")})
                target = root / self.name
                if kind == "directory":
                    target.mkdir()
                elif kind == "file":
                    target.write_text("occupied")
                else:
                    target.symlink_to(root / "missing")
                before = self.snapshot(root)
                proc = adopt(tracker, "--feature", self.name)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(self.snapshot(root), before)
                self.assertTrue(target.exists() or target.is_symlink())

    def test_symlinked_undated_tracker_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = make_tracker(root / "real", {"01-first.md": ticket("01", "First")})
            link = root / "link"
            link.symlink_to(real)
            before = self.snapshot(root)
            proc = adopt(link, "--feature", self.name)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("symlinked --tracker", proc.stderr)
            self.assertEqual(self.snapshot(root), before)

    def test_dated_tracker_ignores_name_and_adopts_later_batch(self):
        for existing in ("2026-10-28-original", "2024-02-29-Odd_slug"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tracker = make_tracker(root / existing, {"01-first.md": ticket("01", "First")})
                self.assertEqual(adopt(tracker).returncode, 0)
                first = (tracker / "issues/01-first.md").read_bytes()
                (tracker / "issues/02-second.md").write_text(ticket("02", "Second"))
                proc = adopt(tracker, "--feature", "not-even-a-valid-name")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual((tracker / "issues/01-first.md").read_bytes(), first)
                self.assertEqual(len(load_issues(tracker)), 2)
                self.assertEqual(list(root.iterdir()), [tracker])

    def test_retry_after_interruption_following_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker = make_tracker(root / "foreign", {"01-first.md": ticket("01", "First")})
            with patch.object(sys, "argv", [SCRIPT, "--tracker", str(tracker), "--feature", self.name]), \
                    patch.object(Path, "write_text", side_effect=OSError("interrupted")), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    adopt_tracker.main()
            target = root / self.name
            self.assertFalse(tracker.exists())
            self.assertEqual((target / "issues/01-first.md").read_text(), ticket("01", "First"))
            proc = adopt(target)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(load_issues(target)), 1)
            self.assertTrue((target / "README.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
