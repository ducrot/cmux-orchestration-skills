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
