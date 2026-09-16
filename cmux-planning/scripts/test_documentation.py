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
    def test_grilling_session_start_captures_and_compares_delivery_baseline(self):
        guide = REPOSITORY / "cmux-grilling" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("grilling skill is absent in this independent installation")
        text = normalized(guide)
        start = "session start:"
        end = "lane panes stay open across rounds"
        self.assertIn(start, text, "grilling guide is missing the session-start delimiter")
        self.assertIn(end, text, "grilling guide is missing the session-start end delimiter")
        procedure = text.split(start, 1)[1].split(end, 1)[0]
        for phrase in (
            'before sending any session prompt, capture',
            'run_state.py snapshot --label "launched session"',
            'delivery baselines and staged deltas',
            'after all lanes adopt their session contracts, capture',
            'run_state.py snapshot --label "adopted session"',
            'compare it with the session baseline before arming the first round',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, procedure)
        self.assertLess(procedure.index('snapshot --label "launched session"'),
                        procedure.index('pane_ctl.py deliver'))
        self.assertLess(procedure.index('pane_ctl.py deliver'),
                        procedure.index('snapshot --label "adopted session"'))

    def test_sibling_guides_gate_staged_deltas_at_every_delivery_boundary(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        chain = normalized(REPOSITORY / "cmux-issue-chain" / "SKILL.md")
        grilling = normalized(REPOSITORY / "cmux-grilling" / "SKILL.md")
        for phrase in (
            'every role (implement, simplify, review, and test)',
            'run_state.py snapshot --label "launched <role>-<pass>"` right before prompt delivery',
            'launch snapshot (`launched <role>-<pass>`) against the capture snapshot (`report-captured <role>-<pass>`)',
            '`staged_paths`', '`staged_diff_sha256`', 'gate `hitl` even with a clean report',
            "staged path lists in the gate reason", "never unstages on the worker's behalf",
            'index and head check applies to test',
        ):
            with self.subTest(guide="issue-chain", phrase=phrase):
                self.assertIn(phrase, chain)
        for phrase in (
            'baseline snapshot before initial lane delivery', 'after all lanes adopt',
            'compare the session baseline before arming the first round',
            'before each round delivery', '`reports-captured round-<n>` snapshot',
            'never replace a baseline before checking the interval it covers',
            '`staged_paths`', '`staged_diff_sha256`', 'gate `hitl` even with clean reports',
            'staged path lists in the gate reason', 'attribution-first',
            'before accusing a lane', "never unstage on a lane's behalf",
        ):
            with self.subTest(guide="grilling", phrase=phrase):
                self.assertIn(phrase, grilling)
        for phrase in ('whole before/after `staged_diff` independently of the allowed-write list',
                       'any difference gates `integrity-violation`',
                       'unchanged pre-staged human baseline remain allowed'):
            self.assertIn(phrase, normalized(PLANNING))

    def test_sibling_guides_gate_head_changes_at_every_delivery_boundary(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        chain = normalized(REPOSITORY / "cmux-issue-chain" / "SKILL.md")
        grilling = normalized(REPOSITORY / "cmux-grilling" / "SKILL.md")
        for guide, text, phrases in (
            ("issue-chain", chain, (
                'also compare `head` between the same two snapshots',
                'any head change is an unauthorized delta that gates `hitl` even with a clean report',
                'before and after head values in the gate reason',
                'compare the launch/capture staged fields and head',
            )),
            ("grilling", grilling, (
                'also compare `head` for each interval',
                'any head change prevents advance and gates `hitl` even with clean reports',
                'before and after head values in the gate reason',
                'compare the staged fields and head against the round delivery baseline',
            )),
        ):
            for phrase in phrases:
                with self.subTest(guide=guide, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_issue_chain_relays_reverted_simplify_decisions_as_findings(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        start = "### diff inspection at code-changing gates"
        end = "## canonical check commands"
        self.assertIn(start, text)
        self.assertIn(end, text)
        inspection = text.split(start, 1)[1].split(end, 1)[0]
        for phrase in (
            "at the review gate, compare the review diff against the simplify report's `## not applied` list",
            "documented kept choices", "without an `ask-user` finding gates `stop`",
            "record the reverted item in the `orchestrator.verified` event",
            "relay it to the human verbatim as a finding, not a recommendation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, inspection)
        policy = text.split("## review self-fix policy", 1)[1].split("## gate rule", 1)[0]
        self.assertIn("earlier-stage decision", policy)
        self.assertIn("`## not applied`", policy)
        self.assertIn("`## change summary` or `## notes`", policy)
        self.assertIn(
            "correcting a regression introduced by an earlier refactoring remains a must-fix "
            "when the correction preserves the documented intended behavior; changing that "
            "intended behavior still requires ask-user.", policy,
        )
        self.assertIn(
            "correcting a regression while preserving documented intended behavior is not a "
            "decision reversion and does not trigger this stop rule", inspection,
        )
        self.assertIn("\n## Not Applied\n- None", guide.read_text(encoding="utf-8"))

    def test_vendored_run_helpers_are_byte_identical(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        helper_files = {
            "slugify": {guide: "orchestrator_lib.py" for guide in SIBLINGS},
            "run_identifier": {guide: "orchestrator_lib.py" for guide in SIBLINGS},
            "ensure_runs_root_ignored": {
                guide: "planning_state.py" if guide == PLANNING else "run_state.py"
                for guide in SIBLINGS
            },
        }
        for name, files in helper_files.items():
            sources = []
            for guide in SIBLINGS:
                filename = files[guide]
                source = (guide.parent / "scripts" / filename).read_text(encoding="utf-8")
                function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
                sources.append(ast.get_source_segment(source, function))
            self.assertEqual(sources, [sources[0]] * 3, name)

    def test_vendored_untracked_hashing_is_byte_identical(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        sources = []
        for guide in SIBLINGS:
            filename = "tree_integrity.py" if guide == PLANNING else "run_state.py"
            source = (guide.parent / "scripts" / filename).read_text(encoding="utf-8")
            nodes = ast.parse(source).body
            function = next(node for node in nodes if isinstance(node, ast.FunctionDef) and node.name == "untracked_content")
            limit = next(node for node in nodes if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "UNTRACKED_HASH_LIMIT_BYTES" for target in node.targets))
            sources.append((ast.get_source_segment(source, function), ast.get_source_segment(source, limit)))
        self.assertEqual(sources, [sources[0]] * 3)

    def test_shared_root_and_legacy_documentation(self):
        if not README.is_file():
            self.skipTest("repository README is absent")
        for guide in (README, PLANNING):
            text = guide.read_text(encoding="utf-8")
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
            "skipped untracked content",
            "unreadable or vanished untracked path fails capture",
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

    def test_valid_schema_v2_configuration_needs_no_question(self):
        for guide in ((README, *SIBLINGS) if README.is_file() else SIBLINGS):
            text = normalized(guide)
            for required in (
                "a schema-v2 file needs no migration question",
                "needs no start confirmation",
                "never offer profile overrides the human did not ask for",
            ):
                with self.subTest(guide=guide.relative_to(REPOSITORY), required=required):
                    self.assertIn(required, text)

    def test_frozen_slug_gates_and_optional_contract_flags_are_documented(self):
        for path in (PLANNING, PLANNING.parent / "references/spec-contract.md"):
            text = normalized(path)
            with self.subTest(path=path):
                self.assertIn("`tracker.slug` must equal the frozen `tracker_slug`", text)
                for gate in ("author", "review", "approval", "publication"):
                    self.assertIn(gate, text)
                for command in ("proposal", "author-report", "review-report"):
                    self.assertIn(f"`{command}`", text)
                self.assertIn("optional `--tracker-slug`", text)

    def test_untracked_upgrade_and_visibility_limits_are_documented(self):
        self.assertIn("pre-change untracked baselines must restart after upgrading", normalized(PLANNING))
        if README.is_file():
            self.assertIn("git may omit contents of unreadable untracked directories", normalized(README))

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
            "symlink target bytes",
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
