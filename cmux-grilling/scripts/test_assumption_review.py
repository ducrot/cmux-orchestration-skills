"""Exercise recording, interrupted transcription, and pair repair through the CLI."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_run_state as fixtures
from artifact_pair import render_assumption, timestamp


class RecordAssumptionReview(unittest.TestCase):
    setUp = fixtures.ReviewArtifactPair.setUp
    write_pair = fixtures.ReviewArtifactPair.write_pair
    write_json = fixtures.ReviewArtifactPair.write_json

    def prepare(self):
        self.write_pair()
        self.run_dir = self.artifact.parent / "run"
        self.run_dir.mkdir(exist_ok=True)
        (self.run_dir / "state.json").write_text(json.dumps(
            {"workflow": "grilling", "layout_version": 2, "max_rounds": 4}))
        self.events = self.run_dir / "events.jsonl"
        self.events.write_text("")

    def cli(self, *args):
        return subprocess.run([sys.executable, str(Path(__file__).with_name("run_state.py")),
                               *args, "--artifact", str(self.artifact)],
                              capture_output=True, text=True)

    def record(self, *args):
        return self.cli("assumption-review", "--run-dir", str(self.run_dir), *args)

    def test_outcomes_emit_one_matching_event_and_transcribable_line(self):
        for outcome in ("confirmed", "corrected", "discarded"):
            with self.subTest(outcome=outcome):
                self.prepare()
                correction = 'Änderung mit "Zitat" [Text]' if outcome == "corrected" else ""
                reason = "Neue Fakten.\nWeitere Details." if outcome != "confirmed" else ""
                result = self.record("--index", "1", "--outcome", outcome,
                                     "--corrected-text", correction, "--reason", reason)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(self.artifact.read_text())
                review = data["assumption_review"][0]
                self.assertEqual(data["assumptions"], self.data["assumptions"])
                self.assertEqual(review["outcome"], outcome)
                self.assertEqual(review["corrected_text"], correction)
                self.assertEqual(review["reason"], reason)
                self.assertTrue(timestamp(review["reviewed_at"]))
                events = [json.loads(line) for line in self.events.read_text().splitlines()]
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["type"], "grill.assumptions_triaged")
                self.assertEqual(events[0]["time"], review["reviewed_at"])
                self.assertEqual(events[0]["data"], dict(review, artifact=str(self.artifact)))
                mismatch = self.cli("validate-artifact")
                self.assertNotEqual(mismatch.returncode, 0)
                self.assertIn("assumption_review entry 1", mismatch.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 1)
                # A resumed walkthrough can reconstruct lost stdout without recording twice.
                self.assertEqual(render_assumption(data["assumptions"][0], review), lines[0])
                markdown = self.markdown.read_text()
                self.markdown.write_text(markdown.replace(markdown.splitlines()[1], lines[0]))
                repaired = self.cli("validate-artifact")
                self.assertEqual(repaired.returncode, 0, repaired.stderr)

    def test_invalid_outcomes_leave_artifact_and_events_unchanged(self):
        self.prepare()
        for args, diagnostic in (
            (("--index", "0", "--outcome", "confirmed"), "index"),
            (("--index", "2", "--outcome", "confirmed"), "index"),
            (("--index", "1", "--outcome", "corrected", "--reason", "why"), "corrected_text"),
            (("--index", "1", "--outcome", "corrected", "--corrected-text", "new"), "reason"),
            (("--index", "1", "--outcome", "discarded", "--reason", "  "), "reason"),
            (("--index", "1", "--outcome", "confirmed", "--corrected-text", "new"), "corrected-text"),
        ):
            with self.subTest(args=args):
                before = (self.artifact.read_bytes(), self.events.read_bytes())
                refused = self.record(*args)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(diagnostic, refused.stderr)
                self.assertEqual((self.artifact.read_bytes(), self.events.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
