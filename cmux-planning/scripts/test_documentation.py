#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
README = REPOSITORY / "README.md"
NOTICE_MARKER = "> **Coordinated upgrade required:**"
# Discovered, so a fourth skill cannot ship without the notice while this test still passes.
GUIDES = tuple(sorted(REPOSITORY.glob("cmux-*/SKILL.md")))


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
