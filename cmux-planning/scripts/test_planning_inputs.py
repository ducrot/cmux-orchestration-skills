"""Input manifest location contracts."""
import tempfile
import unittest
from pathlib import Path

from artifact_manifest import ArtifactIntegrityError, record_artifact, verify_entry


class InputManifest(unittest.TestCase):
    def test_legacy_inline_sources_keep_their_source_identity(self):
        from planning_inputs import planning_inputs

        for source in ("explicit-text", "conversation-summary"):
            with self.subTest(source=source):
                task = {"path": "task.md", "source": source, "sha256": "digest",
                        "manifest_id": "task-1"}
                self.assertEqual(planning_inputs({"task": task}),
                                 [{**task, "kind": "task-file", "original_path": source}])

    def test_malformed_inputs_are_rejected_instead_of_using_legacy_task(self):
        from planning_inputs import planning_inputs

        for inputs in (None, {}, [], ["bad"]):
            with self.subTest(inputs=inputs):
                with self.assertRaisesRegex(ValueError, "non-empty list of pointers"):
                    planning_inputs({"inputs": inputs, "task": {"path": "task.md"}})

    def test_input_kinds_only_accept_their_designated_locations(self):
        cases = (
            ("task-file", "inputs/task-files/01-plan.md", True),
            ("task-file", "inputs/task-files/100-plan.md", True),
            ("task-file", "inputs/task-files/plan.md", False),
            ("task-file", "inputs/01-plan.md", False),
            ("task-file", "inputs/task-files/01-folder/plan.md", False),
            ("conversation-brief", "inputs/conversation-brief.md", True),
            ("conversation-brief", "inputs/task-files/01-brief.md", False),
            ("task", "task.md", True),
        )
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for kind, relative, allowed in cases:
                with self.subTest(kind=kind, path=relative):
                    path = run_dir / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("Planning input")
                    state = {}
                    entry = record_artifact(state, run_dir, relative, kind=kind,
                                            stage="input", pass_num=1, attempt=1, producer="test")
                    if allowed:
                        self.assertEqual(verify_entry(state, run_dir, entry["id"]), entry)
                    else:
                        with self.assertRaises(ArtifactIntegrityError):
                            verify_entry(state, run_dir, entry["id"])


class ConversationBriefInputs(unittest.TestCase):
    def test_removed_inline_options_are_not_accepted_as_abbreviations(self):
        import contextlib
        import io
        from planning_state import build_parser

        for option in ("--task", "--conversation-summary"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit):
                    build_parser().parse_args(["init", option, "old inline input"])
                self.assertIn("unrecognized arguments", output.getvalue())

    def test_template_is_accepted_and_pinned_as_a_brief(self):
        from planning_state import build_parser, task_inputs

        template = Path(__file__).parents[1] / "references" / "conversation-brief.md"
        args = build_parser().parse_args([
            "init", "--conversation-brief", str(template), "--brief-confirmed",
        ])
        self.assertEqual(task_inputs(args), [(template.read_bytes(), str(template.resolve()),
                                             template.name, "conversation-brief")])

    def test_nested_shorter_fences_cannot_supply_a_missing_brief_heading(self):
        from agents_config import ConfigError
        from planning_state import BRIEF_HEADINGS, build_parser, task_inputs

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brief.md"
            for fence in ("````", "~~~~"):
                with self.subTest(fence=fence):
                    example = (f"{fence}\n{fence[:3]}python\n## Goal\nHidden goal\n"
                               f"{fence[:3]}\n{fence}\n")
                    headings = "\n".join(f"## {heading}\nNone" for heading in BRIEF_HEADINGS
                                         if heading != "Goal")
                    path.write_text(example + headings, encoding="utf-8")
                    args = build_parser().parse_args([
                        "init", "--conversation-brief", str(path), "--brief-confirmed",
                    ])
                    with self.assertRaisesRegex(ConfigError, "lacks headings: Goal"):
                        task_inputs(args)
                    # A real heading after the outer closing fence still counts.
                    path.write_text(example + "## Goal\nVisible goal\n" + headings,
                                    encoding="utf-8")
                    self.assertEqual(task_inputs(args), [(
                        path.read_bytes(), str(path.resolve()), path.name, "conversation-brief")])

    def test_brief_rejects_empty_non_utf8_and_fenced_headings(self):
        from agents_config import ConfigError
        from planning_state import BRIEF_HEADINGS, build_parser, task_inputs

        headings = "\n".join(f"## {heading}" for heading in BRIEF_HEADINGS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brief.md"
            for payload, diagnostic in ((b"", "empty"), (b"\xff", "UTF-8"),
                                        (("```markdown\n" + headings + "\n```\n").encode(), "Goal")):
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    args = build_parser().parse_args([
                        "init", "--conversation-brief", str(path), "--brief-confirmed",
                    ])
                    with self.assertRaisesRegex(ConfigError, diagnostic):
                        task_inputs(args)
