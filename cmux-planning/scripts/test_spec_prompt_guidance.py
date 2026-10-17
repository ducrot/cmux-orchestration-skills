#!/usr/bin/env python3
"""Spec language fallback and approval presentation contract."""

import re
import unittest
from pathlib import Path

from render_prompt import SPEC_CONTRACT, SPEC_TEMPLATE, spec_language
from spec_contract import SPEC_SECTIONS


class SpecPromptGuidance(unittest.TestCase):
    def test_legacy_language_matches_explicit_english(self):
        self.assertEqual(spec_language({}), spec_language({"artifact_language": "English"}))
        self.assertIn("Artifact language: English", spec_language({}))

    def test_template_headings_match_enforced_sections(self):
        self.assertEqual(tuple(re.findall(r"^## (.+)$", SPEC_TEMPLATE, re.MULTILINE)), SPEC_SECTIONS)

    def test_template_carries_to_spec_guidance(self):
        for guidance in ("LONG, numbered list", "As a mobile bank customer",
                         "Als <Rolle> möchte ich", "modules that will be built/modified",
                         "interfaces of those modules", "Technical clarifications",
                         "Architectural decisions", "Schema changes", "API contracts",
                         "Specific interactions", "state machine, reducer, schema, type shape",
                         "came from a prototype", "Trim to the decision-rich parts",
                         "only test external behavior", "Which modules will be tested",
                         "Prior art for the tests", "[AFK addition]", "each with its evidence or basis",
                         "question, context, options, recommendation", "why it remains open",
                         "Preserve literal product copy", "never by file path"):
            self.assertIn(guidance, SPEC_TEMPLATE)
        self.assertNotIn("recommendation", SPEC_CONTRACT)
        self.assertNotIn("product copy", SPEC_CONTRACT)

    def test_seams_are_a_separate_block_before_spec_at_approval(self):
        skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()
        approval = skill.split("At `awaiting-spec-approval`,", 1)[1].split(
            "Load the complete deterministic walkthrough", 1)[0]
        seam = "- proposed test seams as a separate block before the specification;"
        self.assertIn(seam, approval)
        self.assertLess(approval.index(seam), approval.index("- the complete reviewed specification"))


if __name__ == "__main__":
    unittest.main()
