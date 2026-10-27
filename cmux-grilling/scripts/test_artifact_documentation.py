"""Keep the finalize representation and validator reference discoverable."""

from pathlib import Path
import unittest

SKILL_DIR = Path(__file__).resolve().parents[1]


class ArtifactDocumentation(unittest.TestCase):
    def test_late_review_proposal_refresh_and_followup_contract(self):
        text = (SKILL_DIR / 'SKILL.md').read_text()
        closing = text.split('The order of the closing steps is fixed:', 1)[1].split('When the loop', 1)[0]
        proposal = text.split('## Commit Proposal', 1)[1].split('## Run Recap', 1)[0]
        for phrase in ('late review', 'propose mode', 'created', 'follow-up', 'changed pair'):
            self.assertIn(phrase, closing)
        for phrase in ('per-file content digests', 'current\nunresolved ids', 'unchanged inputs replay',
                       'before any attempt', 'commit.followup_proposed', 'follows_commit',
                       'human to commit', 'still replays the created outcome', 'never re-propose a changed draft'):
            self.assertIn(phrase, proposal)
        vocabulary = (SKILL_DIR / 'references/event-vocabulary.md').read_text()
        for phrase in ('file_digests', 'proposal_id', 'commit.followup_proposed', 'follows_commit', 'SHA-256'):
            self.assertIn(phrase, vocabulary)

    def test_final_message_preserves_review_status_and_human_handoff_choice(self):
        text = " ".join((SKILL_DIR / "SKILL.md").read_text().split())
        review = text.split("## Assumptions Review", 1)[1].split("## Decision Walkthrough", 1)[0]
        recap = text.split("## Run Recap", 1)[1].split("## Worker input readiness", 1)[0]
        for section in (review, recap):
            for phrase in ("unreviewed count in the final message", "technically finished with review outstanding",
                           "not complete", "choice", "finishing the review and continuing in planning", "human"):
                with self.subTest(phrase=phrase, review=section is review):
                    self.assertIn(phrase, section)
        for phrase in ("recommends finishing", "with counts", "/cmux-planning <artifact.json>",
                       "Planning revalidates every assumption and treats open facts as missing information"):
            self.assertIn(phrase, recap)

    def test_resume_reports_the_whole_unfinished_walkthrough(self):
        text = (SKILL_DIR / "references/resume-walkthrough.md").read_text()
        for phrase in ("key=value", "newest artifact", "one-based indexes", "comma-separated",
                       "unreviewed_assumptions", "open_facts", "assumption_review",
                       "unreviewed_assumptions=none open_facts=none", "Legacy artifacts",
                       "offer to finish the assumptions review", "clarify the open facts",
                       "finish open decisions", "do not re-ask them", "advisory and non-blocking"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_walkthrough_deferral_rule_and_counterexample(self):
        skill = (SKILL_DIR / "SKILL.md").read_text()
        walkthrough = skill.split("## Decision Walkthrough", 1)[1].split("## Commit Proposal", 1)[0]
        resume = (SKILL_DIR / "references/resume-walkthrough.md").read_text()
        for text in (walkthrough, resume):
            for phrase in ("collect the missing facts first", "recommended option",
                           "human selects it by label", "record `deferred`", "name the facts",
                           "each missing fact", "open_facts", "both halves", "validate-artifact"):
                with self.subTest(phrase=phrase, resume=text is resume):
                    self.assertIn(phrase, text)
        reference = (SKILL_DIR / "references/script-reference.md").read_text()
        for phrase in ("selection traceability", "does not prove", "resolves missing facts",
                       "[custom]", "exact option label", "free text", "decision"):
            self.assertIn(phrase, reference)

    def test_review_recording_transcription_and_resume_contract(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        review = text.split("## Assumptions Review", 1)[1].split("## Decision Walkthrough", 1)[0]
        for phrase in ("run_state.py assumption-review", "--index", "--outcome", "--corrected-text",
                       "--reason", "Transcribe the printed lines", "Validate both halves",
                       "after transcription and before the commit proposal and recap",
                       "resumed walkthrough", "Repair interrupted transcription from recorded outcomes",
                       "before presenting", "advisory and non-blocking", "unreviewed"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, review)
        reference = (SKILL_DIR / "references/script-reference.md").read_text()
        for phrase in ("assumption-review", "render_assumption", "without a second recording",
                       "reviewed_at", "Unknown indexes", "before the commit proposal and recap"):
            self.assertIn(phrase, reference)
        event = (SKILL_DIR / "references/event-vocabulary.md").read_text()
        self.assertIn("{index, outcome, corrected_text, reason, reviewed_at, artifact}", event)
        resume = (SKILL_DIR / "references/resume-walkthrough.md").read_text()
        self.assertIn("repair interrupted assumption-marker", resume)
        self.assertIn("before the commit proposal and recap", resume)

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
