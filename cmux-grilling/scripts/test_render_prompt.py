#!/usr/bin/env python3
"""Run-local research draft prompt regression tests."""

from pathlib import Path
import shlex
import tempfile
import unittest

import render_prompt


class RenderFunction(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / "run"
        self.run_dir.mkdir()
        (self.run_dir / "task.md").write_text("Research task\n", encoding="utf-8")
        self.state = {"run_id": "test-run", "max_questions": 5, "task_file": "task.md"}

    def render(self, lane="codebase", round_number=1, **kwargs):
        report = self.run_dir / "reports" / f"round-{round_number}-{lane}.md"
        return render_prompt.render_round(
            lane, self.state, self.run_dir, round_number, "What exists?", report, **kwargs
        )

    def test_round_names_distinct_run_local_draft_and_validates_exact_path(self):
        for lane in render_prompt.LANES:
            for number in (1, 2):
                with self.subTest(lane=lane, round=number):
                    draft = self.run_dir / "drafts" / f"round-{number}-{lane}.md"
                    report = self.run_dir / "reports" / f"round-{number}-{lane}.md"
                    prompt = self.render(lane, number)
                    self.assertIn(f"- Draft path: `{draft}`", prompt)
                    self.assertIn(f"- Report handoff path: `{report}`", prompt)
                    self.assertIn(f"python3 {render_prompt.parser_path()} {draft}\n", prompt)
                    self.assertNotEqual(draft, report)

    def test_session_limits_writes_to_draft_and_handoff(self):
        for lane in render_prompt.LANES:
            with self.subTest(lane=lane):
                prompt = render_prompt.render_session(lane, self.state, self.run_dir)
                self.assertNotIn("temporary file of your own", prompt)
                self.assertIn("the draft path named in each round prompt", prompt)
                boundaries = prompt.split("## Boundaries\n", 1)[1].split("## Task", 1)[0]
                self.assertIn("exactly two files per round", boundaries)
                self.assertIn(f"{self.run_dir}/drafts/round-<N>-{lane}.md", boundaries)
                self.assertIn("report handoff path", boundaries)

    def test_explicit_draft_path_and_shell_quoting(self):
        draft = self.run_dir / "drafts" / "custom draft.md"
        prompt = self.render(draft_path=draft)
        self.assertIn(f"- Draft path: `{draft}`", prompt)
        command = prompt.split("```bash\n", 1)[1].splitlines()[0]
        self.assertEqual(shlex.split(command), ["python3", render_prompt.parser_path(), str(draft)])

    def test_rejects_draft_equal_to_report(self):
        report = self.run_dir / "reports" / "round-1-codebase.md"
        for draft in (report, report.parent / ".." / "reports" / report.name):
            with self.subTest(draft=draft), self.assertRaisesRegex(ValueError, "differ"):
                self.render(draft_path=draft)

    def test_rejects_draft_outside_run(self):
        for draft in (self.run_dir.parent / "outside.md", self.run_dir / ".." / "outside.md", self.run_dir):
            with self.subTest(draft=draft), self.assertRaisesRegex(ValueError, "inside the run directory"):
                self.render(draft_path=draft)
        (self.run_dir / "escape").symlink_to(self.run_dir.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "inside the run directory"):
            self.render(draft_path=self.run_dir / "escape" / "outside.md")

    def test_rejects_run_local_paths_outside_drafts(self):
        for name in (
            "state.json", "events.jsonl", "task.md", "drafts",
            "prompts/round-1-codebase.md", "prompts/session-codebase.md",
            "reports/round-1-docs.md", "synthesis/round-1.md",
            "drafts/../state.json",
        ):
            with self.subTest(draft=name), self.assertRaisesRegex(ValueError, "drafts directory"):
                self.render(draft_path=self.run_dir / name)

    def test_rejects_symlink_escape_from_drafts(self):
        drafts = self.run_dir / "drafts"
        drafts.mkdir()
        (drafts / "to-run").symlink_to(self.run_dir, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "drafts directory"):
            self.render(draft_path=drafts / "to-run" / "state.json")
        (drafts / "to-outside").symlink_to(self.run_dir.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "inside the run directory"):
            self.render(draft_path=drafts / "to-outside" / "outside.md")

    def test_accepts_nested_custom_draft_with_spaces(self):
        draft = self.run_dir / "drafts" / "nested dir" / "custom draft.md"
        prompt = self.render(draft_path=draft)
        command = prompt.split("```bash\n", 1)[1].splitlines()[0]
        self.assertEqual(shlex.split(command)[-1], str(draft))


if __name__ == "__main__":
    unittest.main(verbosity=2)
