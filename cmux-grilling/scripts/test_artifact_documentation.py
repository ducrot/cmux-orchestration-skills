"""Keep the finalize representation and validator reference discoverable."""

from pathlib import Path
import unittest

SKILL_DIR = Path(__file__).resolve().parents[1]


class ArtifactDocumentation(unittest.TestCase):
    def test_feature_location_and_name_approval_replace_old_location_rules(self):
        skill = (SKILL_DIR / "SKILL.md").read_text()
        reference = (SKILL_DIR / "references/script-reference.md").read_text()
        overview = (SKILL_DIR.parent / "README.md").read_text()
        for text in (skill, reference, overview):
            for phrase in ("--feature", "YYYY-MM-DD-<slug>", "local date", "short slug",
                           "same dialog", "commit", "resume", "re-init", "smoke tests", "finalize"):
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, text)
        for path in [SKILL_DIR / "SKILL.md", SKILL_DIR.parent / "README.md",
                     *(SKILL_DIR / "references").glob("*.md")]:
            text = path.read_text()
            for obsolete in ("--output-dir", "--tracker", "--slug", ".scratch/grilling/",
                             "Autodetected", "First match wins", "<slug>-<timestamp>"):
                with self.subTest(path=path.name, obsolete=obsolete):
                    self.assertNotIn(obsolete, text)
        for phrase in ("feature_dir", "timestamp", "YYYY-MM-DD-HHMM", "<timestamp>.md",
                       "<timestamp>.json", "existing feature", "Init never creates"):
            self.assertIn(phrase, skill)
        description = skill.split("---", 2)[1]
        for phrase in ("feature folder", "<timestamp>.md", "<timestamp>.json", "feature-name approval", "commit mode"):
            self.assertIn(phrase, description)

    def test_entrypoint_reserves_room_for_remaining_grilling_work(self):
        self.assertLessEqual((SKILL_DIR / "SKILL.md").stat().st_size, 75894 * .7 - 4000)

    def test_wait_policy_routes_to_complete_watcher_procedure(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        wait = text.split("## Lane Wait Policy", 1)[1].split("## Artifact Location", 1)[0]
        self.assertIn("Read when arming or re-arming a round watcher, waiting for lane reports, or interpreting watcher exits:", wait)
        self.assertIn("[references/lane-wait.md](references/lane-wait.md).", wait)
        reference = (SKILL_DIR / "references/lane-wait.md").read_text()
        for phrase in ("one watcher per round, not per lane", "Never run two watchers",
                       "persisted on first arm", "re-arming, including after a host timeout",
                       "one `worker.started` per `launch_id`", "Health is checked only",
                       "| 0 ", "| 7 ", "| 8 ", "| 9 ",
                       "sole emitter of `worker.waiting`", "Exactly one deadline extension",
                       "Never close a lane pane while its report is pending"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, reference)

    def test_late_review_recap_refresh_contract(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        closing = text.split("In both commit modes, a late review follows this order:", 1)[1].split("When the loop", 1)[0]
        steps = ("run_state.py transcribe-artifact", "run_state.py validate-artifact",
                 "proposal refresh (or follow-up)", "recap-draft --refresh", "recap-show")
        positions = [closing.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        recap = text.split("## Run Recap", 1)[1].split("## Worker input readiness", 1)[0]
        for phrase in ("plain drafting never overwrites", "recap-draft --refresh",
                       "latest shown recap", "content digests", "current artifact",
                       "keeping earlier recap events", "neither file nor events change",
                       "never shown stays untouched", "Legacy pairs"):
            self.assertIn(phrase, recap)
        vocabulary = (SKILL_DIR / "references/event-vocabulary.md").read_text()
        row = next(line for line in vocabulary.splitlines() if "`run.recap`" in line)
        for phrase in ("path", "outcome", "next_step", "pill", "file_digests", "SHA-256",
                       "recap_sha256", "keeping earlier events"):
            self.assertIn(phrase, row)

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

    def test_premise_correction_review_contract_is_documented(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        finalize = " ".join(text.split("## Finalize and Artifact", 1)[1].split("## Assumptions Review", 1)[0].split())
        for phrase in ("premise_corrections", "premise_correction_review", "correction texts verbatim",
                       "one entry per correction", "same fields, requirements and all-unreviewed initial state",
                       "## Prämissen-Korrekturen", "`- ` entries", "absent or empty section"):
            self.assertIn(phrase, finalize)
        review = text.split("## Assumptions Review", 1)[1].split("## Decision Walkthrough", 1)[0]
        for phrase in ("run_state.py premise-correction-review", "same flags", "premise_correction_review",
                       "grill.premise_corrections_triaged", "## Prämissen-Korrekturen"):
            self.assertIn(phrase, review)
        reference = (SKILL_DIR / "references/script-reference.md").read_text()
        for phrase in ("premise-correction-review", "premise_correction_review=N", "Legacy pairs",
                       "render_review", "PREMISE_CORRECTION_REVIEW", "without a second recording"):
            self.assertIn(phrase, reference)
        event = (SKILL_DIR / "references/event-vocabulary.md").read_text()
        line = next(line for line in event.splitlines() if "grill.premise_corrections_triaged" in line)
        self.assertIn("{index, outcome, corrected_text, reason, reviewed_at, artifact}", line)

    def test_final_message_preserves_review_status_and_human_handoff_choice(self):
        text = " ".join((SKILL_DIR / "SKILL.md").read_text().split())
        review = text.split("## Assumptions Review", 1)[1].split("## Decision Walkthrough", 1)[0]
        recap = text.split("## Run Recap", 1)[1].split("## Worker input readiness", 1)[0]
        for section in (review, recap):
            for phrase in ("technically finished with review outstanding",
                           "not complete", "unreviewed assumption count", "unreviewed premise-correction count in the final message",
                           "advisory and non-blocking", "choice", "finishing the review and continuing in planning", "human"):
                with self.subTest(phrase=phrase, review=section is review):
                    self.assertIn(phrase, section)
        for phrase in ("recommends finishing", "with counts", "/cmux-planning <artifact.json>",
                       "Planning revalidates every assumption and treats open facts as missing information"):
            self.assertIn(phrase, recap)

    def test_resume_reports_the_whole_unfinished_walkthrough(self):
        text = (SKILL_DIR / "references/resume-walkthrough.md").read_text()
        for phrase in ("key=value", "newest artifact", "one-based indexes", "comma-separated",
                       "unreviewed_assumptions", "open_facts", "assumption_review",
                       "unreviewed_premise_corrections", "premise_correction_review",
                       "finish the premise-correction review", "all five lists",
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
                       "--reason", "run_state.py transcribe-artifact --artifact <artifact.json>", "Validate both halves",
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

    def test_transcription_command_replaces_hand_transcription_guidance(self):
        skill = (SKILL_DIR / "SKILL.md").read_text()
        for start, end in (("The order of the closing steps is fixed:", "When the loop"),
                           ("## Assumptions Review", "## Decision Walkthrough"),
                           ("## Decision Walkthrough", "## Commit Proposal")):
            self.assertIn("run_state.py transcribe-artifact", skill.split(start, 1)[1].split(end, 1)[0])
        for name in ("script-reference.md", "resume-walkthrough.md"):
            text = (SKILL_DIR / "references" / name).read_text()
            self.assertIn("run_state.py transcribe-artifact --artifact <artifact.json>", text)
        reference = (SKILL_DIR / "references/script-reference.md").read_text()
        for phrase in ("in memory", "before replacing", "byte-identical", "no write",
                       "sibling `.md`", "Legacy pairs", "still print their lines"):
            self.assertIn(phrase, reference)
        self.assertNotIn("Transcribe the printed", skill + reference)

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
