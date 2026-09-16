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
CLAUDE_MARKERS = ("/code-review medium --fix", "/simplify", "in Claude Code")
REGRESSION_CLARIFICATION = (
    "Correcting a regression introduced by an earlier refactoring remains a must-fix "
    "when the correction preserves the documented intended behavior; changing that "
    "intended behavior still requires ask-user."
)

SAME_RUN_BOUNDARY = "Reports from unrelated runs are outside this same-run protection."
SUPERSESSION_RULE = (
    "Protection of Not Applied items and documented intended behavior persists until recorded "
    "human approval explicitly supersedes the earlier decision. The approval must identify the "
    "decision and the authorized replacement or scope. An agent proposal, a later report, or an "
    "unapproved recommendation alone does not supersede it. Report unresolved scope or precedence "
    "ambiguity as `Recommendation: ask-user`; do not apply the disputed change."
)


class RenderFunction(unittest.TestCase):
    def render(self, role: str, harness: str) -> str:
        return render_prompt.render(role, "ISSUE-001", ISSUE, {}, harness=harness, snapshot_id="snap-1")

    def test_header_records_harness_and_snapshot(self):
        text = self.render("implement", "codex")
        self.assertIn("Harness: codex\n", text)
        self.assertIn("Stage snapshot: snap-1\n", text)

    def test_claude_code_review_and_simplify_keep_bundled_skill_commands(self):
        review = self.render("review", "claude-code")
        self.assertIn("Run `/code-review medium --fix` in Claude Code", review)
        self.assertIn("- `/code-review medium --fix`: outcome", review)
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

    def test_review_preserves_earlier_report_decisions_for_both_harnesses(self):
        rule = (
            "Relevant earlier-stage decisions recorded in reports of the same run, including prior passes, "
            "are documented decisions: every item "
            "under a `## Not Applied` section and every behavior-preserving choice explained under "
            "`## Change Summary` or `## Notes`. Unless explicitly superseded by recorded human approval, "
            "reverting one requires a finding with "
            "`Recommendation: ask-user` and a reason; never revert silently. If the fix pass reverted "
            "such an item without that approval, restore it before running the baseline suite and report the proposal as ask-user."
        )
        for harness in ("claude-code", "codex"):
            with self.subTest(harness=harness):
                self.assertIn(rule, self.render("review", harness))

    def test_review_requires_human_supersession_with_same_run_boundary(self):
        for harness in ("claude-code", "codex"):
            with self.subTest(harness=harness):
                text = self.render("review", harness)
                self.assertIn(SAME_RUN_BOUNDARY, text)
                self.assertIn(SUPERSESSION_RULE, text)
                self.assertNotIn("earlier reports of this pass", text)

    def test_review_allows_regression_correction_preserving_intent_for_both_harnesses(self):
        for harness in ("claude-code", "codex"):
            with self.subTest(harness=harness):
                self.assertIn(REGRESSION_CLARIFICATION, self.render("review", harness))

    def test_simplify_records_not_applied_for_both_harnesses(self):
        for harness in ("claude-code", "codex"):
            with self.subTest(harness=harness):
                text = self.render("simplify", harness)
                self.assertIn("Include a `## Not Applied` section", text)
                self.assertIn("one bullet per considered-but-not-applied refactoring and a one-line reason, or `- None`", text)
                self.assertIn("\n## Not Applied\n- None", text)
                self.assertIn("`## Not Applied` is not gate-parsed", text)

    def test_every_role_forbids_index_changes(self):
        for role in render_prompt.ROLES:
            for harness in ("claude-code", "codex"):
                with self.subTest(role=role, harness=harness):
                    contract = self.render(role, harness).split("## Orchestrator Contract", 1)[1]
                    self.assertIn('Never run `git add`, `git rm --cached`, `git stash`, `git commit`, `git reset`, or any other command that changes the index or HEAD; staging and committing belong to the human after the run.', contract)

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

    def test_artifact_path_stays_in_run_when_handoff_paths_are_overridden(self):
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        for pass_num in (1, 2):
            if pass_num == 2:
                prepared = self.run_script(
                    RUN_STATE, "prepare", "--run-dir", str(self.run_dir),
                    "--stage", "implement", "--pass", str(pass_num),
                )
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
            for custom_paths in (False, True):
                with self.subTest(pass_num=pass_num, custom_paths=custom_paths):
                    out = self.repo / "custom-prompt.md" if custom_paths else (
                        self.run_dir / "prompts" / f"implement-{pass_num}.md"
                    )
                    extra = (
                        ("--out", str(out), "--report-path", str(self.repo / "custom-report.md"))
                        if custom_paths else ()
                    )
                    rendered = self.run_script(
                        RENDER_PROMPT, "--tracker", ".scratch/tracker", "--issue", "ISSUE-001",
                        "--role", "implement", "--pass", str(pass_num),
                        "--run-dir", str(self.run_dir), *extra,
                    )
                    self.assertEqual(rendered.returncode, 0, rendered.stderr)
                    expected = self.run_dir / "artifacts" / f"implement-{pass_num}"
                    text = out.read_text(encoding="utf-8")
                    self.assertIn(f"Worker artifact directory: `{expected}`", text)

    def test_cli_renders_decision_contracts_for_both_harnesses(self):
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        previous_role = "implement"
        for role in ("simplify", "review"):
            gate = self.run_script(
                RUN_STATE, "gate", "--run-dir", str(self.run_dir), "--stage", previous_role,
                "--decision", "advance", "--reason", "test", "--next-stage", role,
            )
            self.assertEqual(gate.returncode, 0, gate.stderr)
            previous_role = role
            for pass_num, harness in enumerate(("claude-code", "codex"), start=1):
                with self.subTest(role=role, harness=harness):
                    prepared = self.run_script(
                        RUN_STATE, "prepare", "--run-dir", str(self.run_dir),
                        "--stage", role, "--pass", str(pass_num),
                        "--harness", f"{role}={harness}",
                        "--executable", f"{role}={'claude' if harness == 'claude-code' else 'codex'}",
                    )
                    self.assertEqual(prepared.returncode, 0, prepared.stderr)
                    rendered = self.render(role, pass_num)
                    self.assertEqual(rendered.returncode, 0, rendered.stderr)
                    text = (self.run_dir / "prompts" / f"{role}-{pass_num}.md").read_text(encoding="utf-8")
                    self.assertIn(f"Harness: {harness}", text)
                    self.assertIn("## Not Applied", text)
                    if role == "review":
                        self.assertIn("restore it before running the baseline suite", text)
                        self.assertIn("Recommendation: ask-user", text)
                        self.assertIn(REGRESSION_CLARIFICATION, text)
                    else:
                        self.assertIn("\n## Not Applied\n- None", text)

    def test_prior_pass_context_and_supersession_contract_through_cli(self):
        """Verify delivered evidence and instructions, not a live model's decisions."""
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        gate = self.run_script(
            RUN_STATE, "gate", "--run-dir", str(self.run_dir), "--stage", "implement",
            "--decision", "advance", "--reason", "test", "--next-stage", "review",
        )
        self.assertEqual(gate.returncode, 0, gate.stderr)
        prior = self.run_dir / "reports" / "simplify-1.md"
        prior_body = (
            "## Not Applied\n- Keep separate input validators: preserve field diagnostics.\n"
            "## Notes\n- Intended behavior: invalid inputs retain field-specific errors.\n"
        )
        prior.write_text(prior_body, encoding="utf-8")
        scenarios = (
            ("unapproved-reversion", "Worker proposes merging validators and removing field diagnostics.",
             "- No human approval recorded.", SUPERSESSION_RULE),
            ("approved-supersession", "Worker proposes merging validators and removing field diagnostics.",
             "- Human approved superseding simplify-1's separate-validator decision and field-specific "
             "error behavior with a shared validator and one generic input error for this issue.",
             "Unless explicitly superseded by recorded human approval"),
            ("regression-correction", "Restore field-specific errors accidentally removed by refactoring.",
             "- No human approval to change intended behavior.", REGRESSION_CLARIFICATION),
        )
        pass_num = 1
        for harness in ("claude-code", "codex"):
            for name, proposal, decision, expected_rule in scenarios:
                pass_num += 1
                with self.subTest(harness=harness, scenario=name):
                    current = self.run_dir / "reports" / f"implement-{pass_num}.md"
                    current.write_text(f"## Notes\n- {proposal}\n", encoding="utf-8")
                    ledger = self.repo / ".scratch" / "tracker" / "decisions.md"
                    ledger.write_text(
                        f"# Decisions\n{decision}\n"
                        "- Rejected: rename public fields; preserve compatibility.\n"
                        "- Deferred: consolidate parsing; await a separate scope decision.\n",
                        encoding="utf-8",
                    )
                    prepared = self.run_script(
                        RUN_STATE, "prepare", "--run-dir", str(self.run_dir),
                        "--stage", "review", "--pass", str(pass_num),
                        "--harness", f"review={harness}",
                        "--executable", f"review={'claude' if harness == 'claude-code' else 'codex'}",
                    )
                    self.assertEqual(prepared.returncode, 0, prepared.stderr)
                    rendered = self.run_script(
                        RENDER_PROMPT, "--tracker", ".scratch/tracker", "--issue", "ISSUE-001",
                        "--role", "review", "--pass", str(pass_num), "--run-dir", str(self.run_dir),
                        "--context-file", str(prior), "--context-file", str(current),
                    )
                    self.assertEqual(rendered.returncode, 0, rendered.stderr)
                    text = (self.run_dir / "prompts" / f"review-{pass_num}.md").read_text(encoding="utf-8")
                    self.assertIn(f"Harness: {harness}", text)
                    self.assertIn(f"### {prior}", text)
                    self.assertIn(prior_body.rstrip(), text)
                    self.assertIn(f"### {current}", text)
                    self.assertIn(proposal, text)
                    decisions_block = text.split("## Tracker Decisions\n", 1)[1].split(
                        "## Blocker Status", 1
                    )[0]
                    self.assertIn(decision, decisions_block)
                    self.assertIn("approved, rejected, or deferred", decisions_block)
                    self.assertIn(
                        "Do not re-report or re-apply rejected or deferred items unless the code "
                        "now presents a materially different problem.", decisions_block,
                    )
                    self.assertIn(
                        "Only explicit recorded human approval identifying the earlier decision and "
                        "the authorized replacement or scope supersedes a protected decision; "
                        "apply that approval only within its authorized scope.", decisions_block,
                    )
                    self.assertIn("Rejected: rename public fields", decisions_block)
                    self.assertIn("Deferred: consolidate parsing", decisions_block)
                    self.assertNotIn("The human already rejected or deferred these items", decisions_block)
                    if name == "approved-supersession":
                        self.assertIn("Human approved superseding simplify-1", decisions_block)
                        self.assertNotIn("No human approval", decisions_block)
                    else:
                        self.assertIn("No human approval", decisions_block)
                        self.assertNotIn("Human approved superseding", decisions_block)
                    self.assertIn(expected_rule, text)
                    self.assertIn(SAME_RUN_BOUNDARY, text)
                    self.assertIn(SUPERSESSION_RULE, text)
                    self.assertIn(REGRESSION_CLARIFICATION, text)
                    self.assertNotIn("earlier reports of this pass", text)

    def test_renders_the_snapshot_harness_variant(self):
        self.assertEqual(self.init("--harness", "implement=claude-code").returncode, 0)
        rendered = self.render("implement")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        text = (self.run_dir / "prompts" / "implement-1.md").read_text(encoding="utf-8")
        self.assertIn("Harness: claude-code\n", text)
        self.assertIn("Stage snapshot: ", text)
        self.assertIn(f"Worker artifact directory: `{self.run_dir / 'artifacts' / 'implement-1'}`", text)

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
        self.assertIn(f"Worker artifact directory: `{self.run_dir / 'artifacts' / 'review-1'}`", text)


if __name__ == "__main__":
    unittest.main()
