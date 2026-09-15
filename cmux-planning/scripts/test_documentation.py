#!/usr/bin/env python3

from __future__ import annotations

import unittest
import ast
from functools import lru_cache
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
README = REPOSITORY / "README.md"
NOTICE_MARKER = "> **Coordinated upgrade required:**"
# Discovered, so a fourth skill cannot ship without the notice while this test still passes.
GUIDES = tuple(sorted(REPOSITORY.glob("cmux-*/SKILL.md")))
PLANNING = REPOSITORY / "cmux-planning" / "SKILL.md"
# The three skills bound by the shared migration contract. Outside the repository the glob above
# also matches unrelated cmux-* skills sharing the installation directory.
SIBLINGS = tuple(
    guide
    for name in ("cmux-planning", "cmux-grilling", "cmux-issue-chain")
    if (guide := REPOSITORY / name / "SKILL.md").is_file()
)


@lru_cache(maxsize=None)
def normalized(guide: Path) -> str:
    return " ".join(guide.read_text(encoding="utf-8").split()).lower()


def notice(text: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith(NOTICE_MARKER)]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one coordinated-upgrade notice, found {len(lines)}")
    return lines[0]


class CoordinatedUpgradeDocumentation(unittest.TestCase):
    def test_vendored_run_helpers_are_byte_identical(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        for name in ("slugify", "run_identifier", "ensure_runs_root_ignored"):
            sources = []
            for guide in SIBLINGS:
                filename = "orchestrator_lib.py" if name != "ensure_runs_root_ignored" else ("planning_state.py" if guide == PLANNING else "run_state.py")
                source = (guide.parent / "scripts" / filename).read_text()
                function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
                sources.append(ast.get_source_segment(source, function))
            self.assertEqual(sources, [sources[0]] * 3, name)

    def test_shared_root_and_legacy_documentation(self):
        if not README.is_file():
            self.skipTest("repository README is absent")
        for guide in (README, PLANNING):
            text = guide.read_text()
            self.assertIn(".scratch/orchestrator/runs/<run-id>/", text)
            self.assertIn("deliverables", text)
            for line in text.splitlines():
                if "planning-runs" in line:
                    self.assertIn("legacy", line.lower())

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
                text = normalized(guide)
                for required in (
                    "validate",
                    "show-resolved",
                    "read-only",
                    "migrate --accept",
                    "no write bit",
                    "hard link",
                    "symlink",
                    "claude-fable-high",
                    "profile name",
                    "harness",
                    "model",
                    "effort",
                    "without inferring relative quality",
                ):
                    self.assertIn(required, text)
                self.assertNotIn("migrates a schema-v1 file as a side effect", text)


class PlanningOperatorDocumentation(unittest.TestCase):
    def test_run_artifact_and_product_tree_integrity_boundaries_are_documented(self):
        text = normalized(PLANNING)
        for required in (
            "two explicit integrity boundaries",
            "ignored product files",
            "content changes to product files already untracked",
            "artifact manifest",
            "canonical run-relative path",
            "byte size",
            "sha-256",
            "attempt identity",
            "`-attempt-n` suffix",
            "unexpected files",
            "never attached implicitly",
            "before run-state schema 3",
            "human decision to restart",
            "separately reviewed migration procedure",
        ):
            self.assertIn(required, text)

    def test_model_diversity_confirmation_gate_is_documented(self):
        text = normalized(PLANNING)
        for required in (
            "planning.spec",
            "planning.tickets",
            "planning.reviewer",
            "same harness and model",
            "before a launchable snapshot exists",
            "ask the confirmation question in the user's language",
            "never substitute or fall back to another profile automatically",
            "diversity-confirmation",
            "--decision confirm",
            "--decision refuse",
            "human-authored reason",
            "exit code 2",
            "pending-diversity-confirmation",
            "awaiting confirmation",
            "recorded refusal",
            "human inspection and configuration recovery",
            "shared configuration file",
            "refusal never prepares a snapshot even when the resolved combination changed",
        ):
            self.assertIn(required, text)

    def test_launch_json_is_documented_as_the_only_post_launch_surface_identity(self):
        text = normalized(PLANNING)
        for required in (
            "`surface_id` is the new pane's stable uuid",
            "copy that exact value into every later pane command",
            "the auxiliary `surface_ref`",
            "positional refs shift when panes close",
            "must never be used as a planning worker's post-launch identity",
            "`close` is the one recovery exception",
        ):
            self.assertIn(required, text)

    def test_migration_guidance_output_stream_contract_is_documented(self):
        # Named siblings rather than the glob, so an independent installation alongside unrelated
        # cmux-* skills still checks every guide that ships this contract.
        for guide in ((README, *SIBLINGS) if README.is_file() else SIBLINGS):
            with self.subTest(guide=guide.relative_to(REPOSITORY)):
                text = normalized(guide)
                self.assertIn("complete migration guidance once on stdout", text)
                self.assertRegex(
                    text, r"stderr contains only (?:its short|the short read-only) refusal"
                )
                self.assertRegex(text, r"(?:never repeats|does not repeat) either command")
                self.assertIn("planning initialization leaves stdout empty", text)
                self.assertIn("one complete actionable guidance block on stderr", text)
                self.assertIn(
                    "candidate digest and exact preview and acceptance commands once each", text
                )

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
            "`configuration_created_and_accepted`",
            "`configuration_created_or_migrated_and_accepted`",
            "without rewriting the run merely because it was read",
            "conflicting values are rejected",
        ):
            self.assertIn(required, normalized_guide)
        self.assertIn("They form an optional progression, not a mandatory pipeline", readme)
        self.assertIn("No workflow automatically invokes another", readme)
        self.assertNotIn("first vertical slice currently ends", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
