#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from grilling_input import GrillingInputError, normalize_revalidation, validate_pair  # noqa: E402


def decision(status: str = "open") -> dict:
    value = {
        "id": "D1",
        "question": "Welche Variante?",
        "why_open": "product",
        "context": "Repository evidence leaves a product choice.",
        "evidence": ["round 1", "src/example.py:1"],
        "options": [
            {"label": "A", "implication": "First behavior"},
            {"label": "B", "implication": "Second behavior"},
        ],
        "recommendation": "A",
        "rationale": "Matches the current product language.",
        "status": status,
    }
    if status != "open":
        value["decision"] = "A"
    return value


class GrillingPair(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "--allow-empty", "-qm", "init"], check=True)
        self.markdown = self.repo / "grill.md"
        self.artifact = self.repo / "grill.json"
        self.markdown.write_text(
            """# Grill

## Aufgabe

Eine Aufgabe

## Definierte Annahmen

- Annahme eins
- Annahme zwei

## Entscheidungen

### D1

Welche Variante?

## Prämissen-Korrekturen

- Alter Pfad wurde umbenannt.
""",
            encoding="utf-8",
        )
        self.data = {
            "run_id": "grill-1",
            "task": "Eine Aufgabe",
            "codebasePath": str(self.repo),
            "maxQuestions": 3,
            "questionsAsked": 1,
            "stopReason": "griller-done",
            "qa": [{"question": "Q", "answer": "A", "evidence": ["src/example.py:1"]}],
            "assumptions": ["Annahme eins", "Annahme zwei"],
            "open_decisions": [decision()],
            "markdownPath": str(self.markdown),
            "jsonPath": str(self.artifact),
        }
        self.artifact.write_text(json.dumps(self.data), encoding="utf-8")
        self.task = self.repo / "task.md"
        self.task.write_text("Eine Aufgabe", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_pair_preserves_exact_bytes_and_extracts_corrections(self):
        imported = validate_pair(self.artifact, self.markdown, self.repo)
        self.assertEqual(imported["json_bytes"], self.artifact.read_bytes())
        self.assertEqual(imported["markdown_bytes"], self.markdown.read_bytes())
        self.assertEqual(imported["premise_corrections"], ["Alter Pfad wurde umbenannt."])

    def test_missing_malformed_mismatched_and_ambiguous_pairs_stop(self):
        with self.subTest("missing markdown"):
            self.markdown.unlink()
            with self.assertRaises(GrillingInputError):
                validate_pair(self.artifact, None, self.repo)
            self.markdown.write_text("## Aufgabe\nx\n## Definierte Annahmen\nAnnahme eins\nAnnahme zwei\n## Entscheidungen\nD1", encoding="utf-8")
        with self.subTest("malformed json"):
            original = self.artifact.read_text(encoding="utf-8")
            self.artifact.write_text("{", encoding="utf-8")
            with self.assertRaises(GrillingInputError):
                validate_pair(self.artifact, self.markdown, self.repo)
            self.artifact.write_text(original, encoding="utf-8")
        with self.subTest("repository mismatch"):
            other = self.root / "other"
            other.mkdir()
            with self.assertRaises(GrillingInputError):
                validate_pair(self.artifact, self.markdown, other)
        with self.subTest("ambiguous markdown"):
            self.markdown.write_text(self.markdown.read_text() + "\n## Aufgabe\nDoppelt\n", encoding="utf-8")
            with self.assertRaisesRegex(GrillingInputError, "duplicate"):
                validate_pair(self.artifact, self.markdown, self.repo)

    def test_a_longer_decision_id_does_not_satisfy_a_missing_one(self):
        self.markdown.write_text(
            self.markdown.read_text(encoding="utf-8").replace("### D1", "### D12"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(GrillingInputError, "D1"):
            validate_pair(self.artifact, self.markdown, self.repo)

    def test_relative_pair_identities_resolve_from_the_repository_and_nested_duplicates_stop(self):
        self.data["codebasePath"] = "."
        self.data["jsonPath"] = self.artifact.name
        self.data["markdownPath"] = self.markdown.name
        self.artifact.write_text(json.dumps(self.data), encoding="utf-8")
        imported = validate_pair(self.artifact, self.markdown, self.repo, cwd=self.repo)
        self.assertEqual(imported["markdown_path"], self.markdown.resolve())

        raw = self.artifact.read_text(encoding="utf-8").replace(
            '"status": "open"', '"status": "open", "status": "open"'
        )
        self.artifact.write_text(raw, encoding="utf-8")
        with self.assertRaisesRegex(GrillingInputError, "duplicate JSON fields"):
            validate_pair(self.artifact, self.markdown, self.repo, cwd=self.repo)

    def test_normalized_handoff_is_complete_for_confirm_correct_discard_and_decisions(self):
        imported = validate_pair(self.artifact, self.markdown, self.repo)
        normalized = normalize_revalidation(
            imported,
            {
                "accepted": True,
                "premise_corrections": [{"index": 1, "outcome": "confirmed", "reason": ""}],
                "assumptions": [
                    {"index": 1, "outcome": "corrected", "value": "Korrigiert", "reason": "Aktueller Code"},
                    {"index": 2, "outcome": "discarded", "reason": "Nicht mehr relevant"},
                ],
                "decisions": [{"id": "D1", "status": "deferred", "decision": "Follow-up", "reason": "Scope"}],
            },
            task_path=self.task,
            repository=self.repo,
        )
        assert normalized is not None
        self.assertEqual(normalized["assumptions"][0]["value"], "Korrigiert")
        self.assertIsNone(normalized["assumptions"][1]["value"])
        self.assertEqual(normalized["decisions"][0]["status"], "deferred")
        self.assertEqual(normalized["source"]["json_sha256"], imported["json_sha256"])
        self.assertEqual(normalized["checkout"]["repository"], str(self.repo.resolve()))
        self.assertEqual(normalized["evidence"], self.data["qa"])

    def test_refusal_returns_no_handoff(self):
        imported = validate_pair(self.artifact, self.markdown, self.repo)
        self.assertIsNone(
            normalize_revalidation(
                imported,
                {"accepted": False},
                task_path=self.task,
                repository=self.repo,
            )
        )

    def test_pair_fixture_matches_the_sibling_decision_contract_without_runtime_imports(self):
        sibling = Path(__file__).resolve().parents[2] / "cmux-grilling" / "scripts" / "run_state.py"
        if not sibling.is_file():
            self.skipTest("cmux-grilling is absent from this independent installation")
        planning_runtime = (Path(__file__).parent / "grilling_input.py").read_text(encoding="utf-8")
        self.assertNotRegex(planning_runtime, r"(?:from|import)\s+cmux[-_]grilling")
        self.assertNotIn("/cmux-grilling", planning_runtime)
        proc = subprocess.run(
            [sys.executable, str(sibling), "validate-artifact", "--artifact", str(self.artifact)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("open_decisions=1 valid", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
