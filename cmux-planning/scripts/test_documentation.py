#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
README = REPOSITORY / "README.md"
NOTICE_MARKER = "> **Coordinated upgrade required:**"
# Discovered, so a fourth skill cannot ship without the notice while this test still passes.
GUIDES = tuple(sorted(REPOSITORY.glob("cmux-*/SKILL.md")))
PLANNING = REPOSITORY / "cmux-planning" / "SKILL.md"


def notice(text: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith(NOTICE_MARKER)]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one coordinated-upgrade notice, found {len(lines)}")
    return lines[0]


class CoordinatedUpgradeDocumentation(unittest.TestCase):
    def test_every_shipped_guide_requires_a_coordinated_schema_v2_upgrade(self):
        if not README.is_file():
            self.skipTest("repository README is not present in this independent installation")
        # The README line is the single source; asserting the copies equal it is what actually
        # matters, and it keeps the test from becoming one more copy that can drift.
        canonical = notice(README.read_text(encoding="utf-8"))
        for required in (
            "cmux-planning",
            "cmux-grilling",
            "cmux-issue-chain",
            "schema v2",
            "older separately installed sibling skills",
        ):
            self.assertIn(required, canonical.lower())

        for guide in GUIDES:
            with self.subTest(guide=guide.relative_to(REPOSITORY)):
                self.assertEqual(canonical, notice(guide.read_text(encoding="utf-8")))

    def test_every_shipped_guide_documents_explicit_read_only_migration(self):
        if not README.is_file():
            self.skipTest("repository README is not present in this independent installation")
        for guide in (README, *GUIDES):
            with self.subTest(guide=guide.relative_to(REPOSITORY)):
                normalized = " ".join(guide.read_text(encoding="utf-8").split()).lower()
                for required in (
                    "validate",
                    "show-resolved",
                    "read-only",
                    "migrate --accept",
                    "no write bit",
                    "hard link",
                    "symlink",
                    "claude-opus-xhigh",
                    "profile name",
                    "harness",
                    "model",
                    "effort",
                    "without inferring relative quality",
                ):
                    self.assertIn(required, normalized)
                self.assertNotIn("migrates a schema-v1 file as a side effect", normalized)


class PlanningOperatorDocumentation(unittest.TestCase):
    def test_complete_operator_path_and_workflow_boundaries_are_documented(self):
        if not README.is_file():
            self.skipTest("repository README is not present in this independent installation")
        guide = PLANNING.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")
        normalized_guide = " ".join(guide.split())
        for required in (
            "## Prerequisites and installation",
            "planning.reviewer",
            "--grilling-json",
            "explicit human",
            "planning_state.py status",
            "planning_state.py resume",
            "planning_state.py context",
            "--decision relaunch",
            "pass_with_fixes",
            "digest-bound",
            "already moved but not recorded",
            "baseline-untracked",
            "contact no model provider",
            "cmux-issue-chain",
        ):
            self.assertIn(required, normalized_guide)
        self.assertIn("They form an optional progression, not a mandatory pipeline", readme)
        self.assertIn("No workflow automatically invokes another", readme)
        self.assertNotIn("first vertical slice currently ends", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
