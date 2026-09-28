#!/usr/bin/env python3
"""Run-local research draft prompt regression tests."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

import render_prompt


EXPECTED_INDEX_HEAD_PROHIBITION = 'Never run `git add`, `git rm --cached`, `git stash`, `git commit`, `git reset`, or any other command that changes the index or HEAD; staging and committing happen after the run, outside the worker.'


class RenderFunction(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / "run"
        self.run_dir.mkdir()
        (self.run_dir / "task.md").write_text("Research task\n", encoding="utf-8")
        self.state = {"run_id": "test-run", "max_rounds": 5, "task_file": "task.md"}

    def render(self, lane="codebase", round_number=1, questions=("What exists?",), **kwargs):
        report = self.run_dir / "reports" / f"round-{round_number}-{lane}.md"
        return render_prompt.render_round(
            lane, self.state, self.run_dir, round_number, list(questions), report, **kwargs
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
                    command = prompt.split("```bash\n", 1)[1].splitlines()[0]
                    self.assertEqual(shlex.split(command), ["python3", render_prompt.parser_path(), str(draft), "--questions", "1"])
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

    def test_session_first_step_and_marker_boundary(self):
        for lane in render_prompt.LANES:
            prompt = render_prompt.render_session(lane, self.state, self.run_dir)
            marker = str(self.run_dir / "artifacts" / f"session-{lane}" / "started")
            self.assertEqual(prompt.splitlines()[2], "## First Step")
            first = prompt.split("## First Step", 1)[1].split("## Session Shape", 1)[0]
            for phrase in (marker, "create or overwrite", "parent directory", "modification time"):
                self.assertIn(phrase, first)
            boundary = prompt.split("## Boundaries", 1)[1].split("## Task", 1)[0]
            self.assertIn(marker, boundary)
            self.assertIn("one write outside the per-round draft and report", boundary)

    def test_session_and_round_forbid_index_changes(self):
        for lane in render_prompt.LANES:
            with self.subTest(lane=lane):
                session = render_prompt.render_session(lane, self.state, self.run_dir)
                self.assertIn(EXPECTED_INDEX_HEAD_PROHIBITION, session.split("## Boundaries", 1)[1])
                self.assertIn(EXPECTED_INDEX_HEAD_PROHIBITION, self.render(lane))

    def test_explicit_draft_path_and_shell_quoting(self):
        draft = self.run_dir / "drafts" / "custom draft.md"
        prompt = self.render(draft_path=draft)
        self.assertIn(f"- Draft path: `{draft}`", prompt)
        command = prompt.split("```bash\n", 1)[1].splitlines()[0]
        self.assertEqual(shlex.split(command), ["python3", render_prompt.parser_path(), str(draft), "--questions", "1"])

    def test_round_lists_every_question_and_validates_with_the_count(self):
        questions = ["What exists?", "Which version is pinned?", "Is there a precedent?"]
        prompt = self.render(questions=questions)
        self.assertIn("## Questions (3)", prompt)
        for number, question in enumerate(questions, start=1):
            self.assertIn(f"### Q{number}\n\n{question}", prompt)
        self.assertIn("Q1..Q3", prompt)
        command = prompt.split("```bash\n", 1)[1].splitlines()[0]
        self.assertEqual(shlex.split(command)[-2:], ["--questions", "3"])

    def test_round_does_not_recommend_answers(self):
        prompt = self.render(questions=["A?", "B?"])
        self.assertNotIn("recommend", prompt.lower())

    def test_round_requires_a_question(self):
        with self.assertRaisesRegex(ValueError, "at least one question"):
            self.render(questions=[])

    def test_session_contract_describes_question_blocks_and_max_rounds(self):
        prompt = render_prompt.render_session("codebase", self.state, self.run_dir)
        self.assertIn("Max rounds: 5", prompt)
        self.assertNotIn("Max questions", prompt)
        self.assertIn("## Q1\n### Result", prompt)
        self.assertIn("--questions <number-of-questions>", prompt)
        self.assertIn("Q2's answer must not shape Q1's", prompt)

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
        self.assertEqual(shlex.split(command)[-3], str(draft))


class RenderCli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / "run"
        self.run_dir.mkdir()
        (self.run_dir / "task.md").write_text("Research task\n", encoding="utf-8")
        (self.run_dir / "state.json").write_text(
            json.dumps({"workflow": "grilling", "layout_version": 1, "run_id": "r", "max_rounds": 2, "task_file": "task.md"}),
            encoding="utf-8",
        )

    def render(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(__file__).parent / "render_prompt.py"), "round", "--run-dir", str(self.run_dir),
             "--lane", "docs", *args],
            capture_output=True, text=True,
        )

    def test_repeated_question_flags_become_numbered_questions(self):
        question_file = self.run_dir / "q3.md"
        question_file.write_text("Third from file\n", encoding="utf-8")
        proc = self.render("--round", "1", "--question", "First", "--question", "Second",
                           "--question-file", str(question_file))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        prompt = Path(proc.stdout.strip()).read_text(encoding="utf-8")
        self.assertIn("## Questions (3)", prompt)
        self.assertIn("### Q3\n\nThird from file", prompt)

    def test_round_beyond_budget_is_rejected(self):
        proc = self.render("--round", "3", "--question", "Late?")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("exceeds max_rounds 2", proc.stderr)

    def test_missing_or_blank_question_is_rejected(self):
        self.assertIn("At least one", self.render("--round", "1").stderr)
        self.assertIn("Question text is empty", self.render("--round", "1", "--question", "  ").stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
