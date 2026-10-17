#!/usr/bin/env python3
"""Recovery consumes one attempt and expires before unrelated prompts are read."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from artifact_manifest import ROLE_KEYS, attempt_id, record_artifact, stage_paths
from planning_state import resume_inputs
from render_prompt import resumed_context


class RelaunchContext(unittest.TestCase):
    def test_only_latest_attempt_and_reviewed_author_handoffs_are_attached(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = {"artifact_manifest": {}, "attempt_history": []}

            def handoff(stage, number, attempt, kind):
                path = Path(stage_paths(root, stage, number, attempt)[ROLE_KEYS[kind]])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{path.name} contents")
                return record_artifact(state, root, path, kind=kind, stage=stage,
                                       pass_num=number, attempt=attempt, producer="test")

            stale = handoff("spec-review", 4, 1, "worker-report")
            draft = handoff("spec", 2, 2, "spec-draft")
            author_report = handoff("spec", 2, 2, "worker-report")
            handoff("spec", 1, 1, "spec-draft")
            handoff("tickets", 1, 1, "tickets-proposal")
            report = handoff("spec-review", 4, 2, "worker-report")
            candidate = handoff("spec-review", 4, 2, "reviewed-candidate")
            # Files which never entered the finalized manifest cannot become inputs.
            (root / "partial-report.md").write_text("partial")
            state["author_spec"] = {"draft_manifest_id": draft["id"],
                                    "report_manifest_id": author_report["id"]}
            state["attempt_history"] = [
                {"stage": "spec", "pass": 2, "attempt_id": attempt_id("spec", 2, 2)},
            ] + [
                {"stage": "spec-review", "pass": 4, "attempt_id": attempt_id("spec-review", 4, n)}
                for n in (1, 2)
            ]
            # An obsolete handoff must not be read or verified by the next recovery.
            (root / stale["path"]).unlink()
            inputs = resume_inputs(root, state, "spec-review", 4)
            self.assertEqual({item["manifest_id"] for item in inputs},
                             {item["id"] for item in (draft, author_report, report, candidate)})
            author_inputs = resume_inputs(root, state, "spec", 2)
            self.assertEqual({item["manifest_id"] for item in author_inputs},
                             {draft["id"], author_report["id"]})

    def test_unrelated_passes_do_not_even_verify_expired_recovery_artifacts(self):
        state = {"resume_context": {
            "to_stage": "spec", "to_pass": 2, "to_review_pass": 5,
            "prior_handoffs": [{"path": "/missing-expired-artifact"}],
        }}
        for stage, number in (("spec", 3), ("spec-review", 2), ("spec-review", 6),
                              ("tickets", 1), ("tickets-review", 5)):
            with self.subTest(stage=stage, number=number):
                self.assertEqual(resumed_context(Path("/tmp"), state, stage, number), "")


if __name__ == "__main__":
    unittest.main()
