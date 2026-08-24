#!/usr/bin/env python3
"""Harness-aware prompt rendering tests. Run: python3 scripts/test_render_prompt.py"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import render_prompt
from test_stage_preparation import AGENTS_CONFIG, FAKE_HARNESS, ISSUE, RUN_STATE


SCRIPT_DIR = Path(__file__).resolve().parent
RENDER_PROMPT = SCRIPT_DIR / "render_prompt.py"
CLAUDE_MARKERS = ("/code-review max --fix", "/simplify", "in Claude Code")


class RenderFunction(unittest.TestCase):
    def render(self, role: str, harness: str) -> str:
        return render_prompt.render(role, "ISSUE-001", ISSUE, {}, harness=harness, snapshot_id="snap-1")

    def test_header_records_harness_and_snapshot(self):
        text = self.render("implement", "codex")
        self.assertIn("Harness: codex\n", text)
        self.assertIn("Stage snapshot: snap-1\n", text)

    def test_claude_code_review_and_simplify_keep_bundled_skill_commands(self):
        review = self.render("review", "claude-code")
        self.assertIn("Run `/code-review max --fix` in Claude Code", review)
        self.assertIn("- `/code-review max --fix`: outcome", review)
        self.assertNotIn("Smell baseline", review)
        simplify = self.render("simplify", "claude-code")
        self.assertIn("Run `/simplify` in Claude Code", simplify)

    def test_other_harness_gets_inline_review_and_simplify_contracts(self):
        review = self.render("review", "codex")
        for marker in CLAUDE_MARKERS:
            self.assertNotIn(marker, review)
        for axis in ("Standards:", "Spec:", "Correctness:"):
            self.assertIn(axis, review)
        self.assertIn("Never ask for a fixed point or a spec location", review)
        self.assertIn("- Mysterious Name", review)
        self.assertIn("- `review pass (standards, spec, correctness)`: outcome", review)
        self.assertIn("Recommendation: ask-user", review)
        simplify = self.render("simplify", "codex")
        for marker in CLAUDE_MARKERS:
            self.assertNotIn(marker, simplify)
        self.assertIn("Run a simplify pass yourself", simplify)
        self.assertIn("## Change Summary", simplify)

    def test_implement_and_test_are_identical_across_harnesses(self):
        for role in ("implement", "test"):
            claude = self.render(role, "claude-code").replace("Harness: claude-code", "Harness: X")
            codex = self.render(role, "codex").replace("Harness: codex", "Harness: X")
            self.assertEqual(
                strip_created(claude), strip_created(codex), role
            )


def strip_created(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("Created: "))


class RenderCli(unittest.TestCase):
    """The CLI takes the harness from the prepared stage snapshot, never from an argument."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        issue_dir = self.repo / ".scratch" / "tracker" / "issues"
        issue_dir.mkdir(parents=True)
        (issue_dir / "ISSUE-001-prepared.md").write_text(ISSUE, encoding="utf-8")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name in ("codex", "claude"):
            path = bin_dir / name
            path.write_text(FAKE_HARNESS, encoding="utf-8")
            path.chmod(0o755)
        self.env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
        self.runs_root = self.repo / ".scratch" / "orchestrator" / "runs"
        self.run_dir = self.runs_root / "render-run"
        config_path = self.repo / ".scratch" / "orchestrator" / "agents.json"
        initialized = self.run_script(AGENTS_CONFIG, "init", "--config", str(config_path))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=30,
        )

    def init(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            RUN_STATE, "init", "--tracker", ".scratch/tracker", "--issue", "ISSUE-001",
            "--run-id", "render-run", "--runs-root", str(self.runs_root), "--workspace-id", "WORKSPACE", *extra,
        )

    def render(self, role: str, pass_num: int = 1) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            RENDER_PROMPT, "--tracker", ".scratch/tracker", "--issue", "ISSUE-001",
            "--role", role, "--pass", str(pass_num), "--run-dir", str(self.run_dir),
        )

    def test_refuses_without_a_prepared_snapshot_for_the_stage(self):
        self.assertEqual(self.init().returncode, 0)
        rendered = self.render("simplify")
        self.assertNotEqual(rendered.returncode, 0)
        self.assertIn("cannot render simplify-1", rendered.stderr)
        self.assertFalse((self.run_dir / "prompts" / "simplify-1.md").exists())

    def test_renders_the_snapshot_harness_variant(self):
        self.assertEqual(self.init("--harness", "implement=claude-code").returncode, 0)
        rendered = self.render("implement")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        text = (self.run_dir / "prompts" / "implement-1.md").read_text(encoding="utf-8")
        self.assertIn("Harness: claude-code\n", text)
        self.assertIn("Stage snapshot: ", text)

        gate = self.run_script(
            RUN_STATE, "gate", "--run-dir", str(self.run_dir), "--stage", "implement",
            "--decision", "advance", "--reason", "test", "--next-stage", "review",
        )
        self.assertEqual(gate.returncode, 0, gate.stderr)
        prepared = self.run_script(
            RUN_STATE, "prepare", "--run-dir", str(self.run_dir), "--stage", "review", "--pass", "1",
            "--harness", "review=codex", "--model", "review=gpt-test", "--executable", "review=codex",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        rendered = self.render("review")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        text = (self.run_dir / "prompts" / "review-1.md").read_text(encoding="utf-8")
        self.assertIn("Harness: codex\n", text)
        self.assertIn("review pass (standards, spec, correctness)", text)
        self.assertNotIn("/code-review", text)


if __name__ == "__main__":
    unittest.main()
