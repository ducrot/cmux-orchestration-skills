"""Keep the finalize representation and validator reference discoverable."""

from pathlib import Path
import unittest

SKILL_DIR = Path(__file__).resolve().parents[1]


class ArtifactDocumentation(unittest.TestCase):
    def test_finalize_defines_pair_fields_and_initial_review_state(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        finalize = text.split("## Finalize and Artifact", 1)[1].split("## Assumptions Review", 1)[0]
        for phrase in ("assumption_review", "one-based", "corrected_text", "reviewed_at",
                       "every entry as unreviewed", "verbatim", "Prüfung:", "ungeprüft|bestätigt|korrigiert|verworfen",
                       "open_facts", "why_needed", "answered_at", "## Offene Fakten",
                       "both halves", "choice between options", "never a decision",
                       "clarify-first", "never write an option whose only", "later-decide option"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, finalize)
        self.assertLessEqual((SKILL_DIR / "SKILL.md").stat().st_size, 75894 * .7)

    def test_reference_explains_extended_validation_and_legacy_behavior(self):
        text = (SKILL_DIR / "references/script-reference.md").read_text()
        for phrase in ("validate-artifact", "assumption_review", "open_facts", "markdownPath",
                       "Prüfung:", "all-unreviewed", "Legacy artifacts", "open_decisions=N valid"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
