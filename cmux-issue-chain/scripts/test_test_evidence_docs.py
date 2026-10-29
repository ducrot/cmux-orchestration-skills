"""Protect the authoritative selection policy and its consumer references."""
from pathlib import Path
import unittest

import render_prompt

ROOT = Path(__file__).resolve().parents[1]


class EvidenceDocumentation(unittest.TestCase):
    def test_evidence_and_citation_bullets_are_path_only(self):
        policy = " ".join((ROOT / "references/test-evidence.md").read_text().split())
        self.assertIn(
            "Each `evidence:` or `cited:` bullet must contain only the path after the label, "
            "with no trailing annotations; put the command and outcome on a separate bullet.",
            policy,
        )

    def test_authoritative_policy_and_references(self):
        policy = (ROOT / "references/test-evidence.md").read_text()
        for phrase in ("analysis of the diff", "orientation", "regression test",
                       "dependent modules", "protection tests", "next larger unit",
                       "`- evidence:", "`- cited:", "`- selection:",
                       "Copy the path from the wrapper's", "run-directory-relative",
                       "Only logs named", "unlisted_logs", "checked_logs",
                       "gate-checks this explanation", "full canonical suite", "without citations",
                       "Review selects the affected tests", "identical launch and capture HEAD",
                       "A changed review must name its own", "Review checks only named"):
            self.assertIn(phrase, policy)
        self.assertIn("references/test-evidence.md", (ROOT / "SKILL.md").read_text())
        self.assertIn("(test-evidence.md)", (ROOT / "references/worker-report-contract.md").read_text())

    def test_prompt_guardrails_and_final_test_contract(self):
        rules = "- Canonical check commands:\n  - `python3 check.py`"
        implement = render_prompt.test_duties("implement", "artifacts/implement-1", False, rules)
        for phrase in ("tests of changed modules", "ticket's regression test",
                       "tests of dependent modules", "repository protection tests",
                       "next larger unit", "references/test-evidence.md",
                       "exactly one `- selection:`", "not gate-checked"):
            self.assertIn(phrase, implement)
        for harness in ("claude-code", "codex", "other-harness"):
            review = render_prompt.render("review", "ISSUE-004", "# Issue", {},
                                          harness=harness, ground_rules=rules)
            for phrase in ("tests of changed modules", "ticket's regression test",
                           "tests of dependent modules", "repository protection tests",
                           "next larger unit", "exactly one `- selection:`",
                           "`- evidence: <path>`", "`- cited: <path>`",
                           "Canonical commands for orientation and fallback"):
                self.assertIn(phrase, review)
            self.assertNotIn("byte-for-byte", review)
            self.assertNotIn("never substitute a different suite", review)
        skill = (ROOT / "SKILL.md").read_text()
        chain = skill.split("## Default Chain", 1)[-1].split("## Canonical Check Commands", 1)[0]
        self.assertIn("[test selection and evidence policy](references/test-evidence.md)", chain)
        final = render_prompt.test_duties("test", "artifacts/test-1", False, rules)
        for phrase in ("byte-for-byte", "never substitute a different suite",
                       "full canonical suite", "Do not cite earlier evidence", "`python3 check.py`"):
            self.assertIn(phrase, final)

    def test_shared_comparison_policy_and_consumer_links(self):
        policy = " ".join((ROOT / "references/test-evidence.md").read_text().split())
        for phrase in ("both sides are mandatory for every chosen command",
                       "before the first edit", "distinct green own after-run",
                       "even for a no-op", "only from citations", "derives commands from named",
                       "Targeted commands need your own before-runs", "only canonical commands"):
            self.assertIn(phrase, policy)
        for path in ("SKILL.md", "references/follow-up-pass.md"):
            text = (ROOT / path).read_text()
            self.assertIn("test-evidence.md#simplify-and-marked-follow-up-implement", text)
            self.assertNotIn("full applicable suite", text)
        for role, followup in (("simplify", False), ("implement", True)):
            duties = render_prompt.test_duties(role, "artifacts/stage", followup,
                                              "- Canonical check commands:\n  - `check`")
            for phrase in ("before the first edit", "distinct green own after-run", "selection:",
                           "Canonical commands for orientation and fallback"):
                self.assertIn(phrase, duties)
