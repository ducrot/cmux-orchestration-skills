#!/usr/bin/env python3

from __future__ import annotations

import unittest
import ast
import re
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[2]
README = REPOSITORY / "README.md"
NOTICE_MARKER = "> **Coordinated upgrade required:**"
# Discovered, so a fourth skill cannot ship without the notice while this test still passes.
GUIDES = tuple(sorted(REPOSITORY.glob("cmux-*/SKILL.md")))
PLANNING = REPOSITORY / "cmux-planning" / "SKILL.md"
INTEGRITY = PLANNING.parent / "references/integrity-boundaries.md"
STAGE_RUN = PLANNING.parent / "references/stage-run-details.md"
TICKET_STAGE = PLANNING.parent / "references/ticket-stage-details.md"
INITIALIZATION = PLANNING.parent / "references/initialization-details.md"
CONFIGURATION_COMPATIBILITY = PLANNING.parent / "references/configuration-compatibility.md"
STATUS_COMMANDS = PLANNING.parent / "references/status-commands.md"
STATUS_RECOVERY = PLANNING.parent / "references/status-recovery.md"
# The three skills bound by the shared migration contract. Outside the repository the glob above
# also matches unrelated cmux-* skills sharing the installation directory.
SIBLINGS = tuple(
    guide
    for name in ("cmux-planning", "cmux-grilling", "cmux-issue-chain")
    if (guide := REPOSITORY / name / "SKILL.md").is_file()
)


# Expand only explicit on-demand pointers in their original position, so section-level
# assertions read the owning reference, never a duplicate in SKILL.md.
ON_DEMAND = re.compile(
    r"^Read when [^\n]+: \[references/([^\]\n]+)\]\(references/\1\)\.\n(?:\n|\Z)",
    re.MULTILINE,
)


@lru_cache(maxsize=None)
def documentation(guide: Path) -> str:
    text = guide.read_text(encoding="utf-8")
    if guide.name != "SKILL.md":
        return text
    return ON_DEMAND.sub(
        lambda match: (guide.parent / "references" / match.group(1)).read_text(encoding="utf-8"),
        text,
    )


@lru_cache(maxsize=None)
def normalized(guide: Path) -> str:
    return " ".join(documentation(guide).split()).lower()


class OnDemandDocumentation(unittest.TestCase):
    # Entry-point sizes measured before conditional procedures moved to references/.
    BASELINE_BYTES = {"cmux-issue-chain": 109325, "cmux-grilling": 75894, "cmux-planning": 51689}
    CAP_RATIO = .7
    NORMAL_HEADINGS = {
        "cmux-issue-chain": ("## gate rule", "## default chain"),
        "cmux-grilling": ("## gate rule", "## round loop"),
        "cmux-planning": ("## initialize", "## run one stage", "## gate the author and reviewer"),
    }
    ON_DEMAND_PHRASES = {"cmux-grilling": ("run_in_background: true", "persisted on first arm")}

    def test_grilling_revalidation_keeps_recorded_assumption_and_premise_reviews_as_context(self):
        text = normalized(PLANNING.parent / "references" / "grilling-revalidation.md")
        for phrase in ("recorded grilling review outcome and value", "all open facts", "never pre-apply",
                       "recorded premise-correction reviews", "outcome, value and reason",
                       "fresh human outcome for every assumption and premise correction"):
            self.assertIn(phrase, text)

    def test_entrypoints_reduce_start_context_by_at_least_thirty_percent(self):
        for guide in SIBLINGS:
            with self.subTest(skill=guide.parent.name):
                name = guide.parent.name
                self.assertLessEqual(guide.stat().st_size,
                                     self.BASELINE_BYTES[name] * self.CAP_RATIO)

    def test_conditional_routes_resolve_to_nonempty_local_references(self):
        for guide in SIBLINGS:
            text = guide.read_text(encoding="utf-8")
            routes = list(ON_DEMAND.finditer(text))
            with self.subTest(skill=guide.parent.name):
                self.assertTrue(routes, "conditional procedures need explicit read-when routes")
                self.assertEqual(len(routes), text.count("Read when "))
                for route in routes:
                    target = guide.parent / "references" / route.group(1)
                    self.assertEqual(target.resolve().parent, (guide.parent / "references").resolve())
                    self.assertTrue(target.read_text(encoding="utf-8").strip(), target)

    def test_normal_run_stays_in_entrypoints(self):
        for guide in SIBLINGS:
            text = guide.read_text(encoding="utf-8").lower()
            with self.subTest(skill=guide.parent.name):
                on_demand = self.ON_DEMAND_PHRASES.get(guide.parent.name, ())
                for phrase in (" init ", "## run briefing", "## run recap", "run_commit.py propose",
                               "run_commit.py commit", "run_in_background: true", "persisted on first arm"):
                    self.assertIn(phrase, documentation(guide).lower() if phrase in on_demand else text)
                for heading in self.NORMAL_HEADINGS[guide.parent.name]:
                    self.assertIn(heading, text)


def notice(text: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith(NOTICE_MARKER)]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one coordinated-upgrade notice, found {len(lines)}")
    return lines[0]


class PathFreedomDocumentation(unittest.TestCase):
    def test_contract_preserves_handover_paths_and_safety_commands(self):
        contract = normalized(PLANNING.parent / "references/spec-contract.md")
        for rule in (
            "handover locations may be named by path: artifacts one ticket produces and another reads, "
            "and the tracker's documentation folder.",
            "prescribed commands whose flags carry the safety of a step may be stated verbatim.",
            "when removing ordinary file paths, keep exempt handover locations and safety-carrying commands verbatim.",
            "trimmed prototype snippet that encodes a decision more precisely than prose",
            "`canonical_check_commands` may contain paths",
            "specifications and tickets",
        ):
            self.assertIn(rule, contract)


class ProportionalEdgeCaseDocumentation(unittest.TestCase):
    def test_spec_contract_bounds_edge_case_review_to_realistic_use(self):
        contract = normalized(PLANNING.parent / "references/spec-contract.md")
        for phrase in (
            "the specification reviewer blocks on an edge case only when",
            "existing persisted data, a documented use, or a plausible input reaches it",
            "existing persisted data would be lost or corrupted silently",
            "a defect that appears only for inputs far beyond realistic use is reported once",
            "under findings with a `pass_with_fixes` correction that records the supported range under assumptions",
            "recording that range counts as an established-intent correction",
            "does not by itself require new validation, refusal paths, or a human decision",
            "the specification author states the supported range when it matters",
            "instead of designing behavior for every value the validators accept",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract)


class EnforcedRuleConflictDocumentation(unittest.TestCase):
    def test_spec_contract_states_author_and_independent_reviewer_duties(self):
        contract = normalized(PLANNING.parent / "references/spec-contract.md")
        for phrase in (
            "the specification author checks the requested behavior against existing enforced rules",
            "code guard, validation, constraint, documented rule, or test",
            "code guards, validations, and constraints, including those that reject user actions, remain enforced rules",
            "documented rules and observable contracts (documented or public output formats and user-visible behavior)",
            "a test that only pins an internal representation (a storage type, an internal format, or a private helper's shape) is not an enforced rule",
            "changing it while preserving observable behavior is the author's implementation choice",
            "the reviewer may correct it with `pass_with_fixes`",
            "the author names the test and why it is internal in the author report under `repository sources / methods`",
            "when requested behavior depends on changing a shared representation or seam that several later behaviors use",
            "describe that change as a behavior-preserving step where it can be one",
            "same observable results for supported data",
            "keep new rules, limits, refusals, and storage with the behaviors that need them",
            "a reviewer who finds such a change bundled with new behavior reports it as a finding",
            "may separate it with `pass_with_fixes` when the split preserves established intent",
            "block only when the separation needs a new behavior decision",
            "removed, weakened, or bypassed",
            "name the rule and its evidence by module, behavior, and test name",
            "paths and line references go in the author report under `repository sources / methods`",
            "under `open decisions` with options and a recommendation",
            "human input explicitly names the rule and how it changes",
            "a general request for the outcome does not",
            "human specification revision feedback counts as human input",
            "record an exempt change under `implementation decisions`",
            "follow the input precedence",
            "the specification reviewer independently checks the repository",
            "unresolved or was decided by the author alone, return `blocked`",
            "finding anchored in code or documentation",
            "include the `recommendation:` bullet inside blockers and name the concrete choices",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract)


class TicketApprovalQuizDocumentation(unittest.TestCase):
    def setUp(self):
        self.approval = normalized(PLANNING).split("## ticket approval, staging, and publication", 1)[1].split("## commit", 1)[0]

    def test_walkthrough_is_compact_with_details_on_request(self):
        for phrase in (
            "at `awaiting-ticket-approval`", "ticket-approval-view --run-dir <run-dir>",
            "compact numbered list", "title, blocked by, and what to build",
            "full acceptance criteria and merge/split rationale on request",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.approval)
        self.assertLess(self.approval.index("ticket-approval-view --run-dir <run-dir>"),
                        self.approval.index("one `askuserquestion` with three"))

    def test_walkthrough_shows_human_work_before_the_quiz(self):
        self.assertIn("show each ticket's execution mode (afk or hitl)", self.approval)
        self.assertIn("with slice type next to it", self.approval)
        self.assertIn("granularity and edges include the human work", self.approval)
        self.assertLess(self.approval.index("show each ticket's execution mode"),
                        self.approval.index("one `askuserquestion` with three"))

    def test_native_contract_describes_both_execution_modes(self):
        contract = normalized(PLANNING.parent / "references/spec-contract.md")
        for phrase in ("schema-version-two", "`execution_mode`", "version 1",
                       "afk issues with ready-for-agent", "hitl issues with ready-for-human"):
            self.assertIn(phrase, contract)

    def test_single_quiz_asks_all_three_dimensions_in_human_language(self):
        for phrase in (
            "one `askuserquestion` with three single-select questions in the human's language",
            "granularity: fits / too coarse / too fine",
            "edges: correct / needs correction",
            "merge/split: no change / change",
            "spec approval keeps its existing flow without a fixed quiz",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.approval)

    def test_feature_name_dialog_and_derived_publication_are_documented(self):
        guide = normalized(PLANNING)
        for phrase in ("same dialog as the commit-mode question", "after the human chooses a fresh run",
                       "explicit `--feature`", "on resume, re-init", "unfinished-run path",
                       "smoke tests", "do not ask for a target path"):
            self.assertIn(phrase, guide)
        self.assertNotIn("ask for the target path", guide)
        self.assertNotIn("--target <", guide)
        self.assertNotIn("init --slug", guide)
        for name in ("initialization-details.md", "ticket-publication-recovery.md"):
            text = normalized(PLANNING.parent / "references" / name)
            self.assertIn("feature", text)
            self.assertIn("yyyy-mm-dd-<slug>", text)
        readme = normalized(PLANNING.parent.parent / "README.md")
        self.assertIn("same dialog as commit mode", readme)
        self.assertIn("without a target-path question", readme)

    def test_grilling_feature_inheritance_is_documented(self):
        guide = normalized(PLANNING)
        self.assertIn("with grilling input, ask no name question", guide)
        self.assertIn("publish the tracker in that feature folder", guide)
        reference = normalized(PLANNING.parent / "references/grilling-revalidation.md")
        for phrase in ("ask no feature-name question", "inherits that feature folder and its pure slug",
                       "tracker is published in the same feature folder", "before any writes",
                       "json format and pair validation are unchanged"):
            self.assertIn(phrase, reference)

    def test_quiz_answers_route_to_approval_ticket_revision_or_spec_revision(self):
        for phrase in (
            "only when all three answers are positive (fits, correct, no change), approve using the frozen feature folder",
            "--decision approve --reason <human-reason>",
            "if any answer differs, ask a concrete follow-up",
            "--decision revise --reason <concrete-change>",
            "fresh ticket pass, a new review, and a new quiz",
            "if the follow-up reveals an approved-spec defect",
            "--decision revise --scope spec --reason <approved-spec-defect>",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.approval)


class WorkerStartDocumentation(unittest.TestCase):
    def test_shared_protocol_separates_normal_start_from_readiness(self):
        for guide in SIBLINGS:
            with self.subTest(skill=guide.parent.name):
                text = normalized(guide.parent / "references/worker-readiness.md")
                self.assertIn("## normal start", text)
                normal = text.split("## normal start", 1)[1].split("## ", 1)[0]
                for phrase in ("no readiness assessment", "start prompt", "first step",
                               "marker", "watcher writes `worker.started`",
                               "`worker.launch_sent`", "exit 9"):
                    self.assertIn(phrase, normal)
                for phrase in ("after a watcher exit 9", "after context recovery before any new input",
                               "before every `deliver`", "follow-ups", "re-delivery", "grilling rounds",
                               "codex can display a composer while still loading",
                               "pi renders its banner", "never paste a work order into it",
                               "do not restart into an existing tui", "without re-delivery"):
                    self.assertIn(phrase, text)
                self.assertNotIn("after every start", text)
                procedure = text.split("## observe, assess, then deliver", 1)[1].split("## ", 1)[0]
                self.assertNotIn("run `pane_ctl.py start-agent`", procedure)

    @unittest.skipUnless(README.is_file(), "repository README absent in independent installation")
    def test_readme_describes_marker_start_and_exception_path(self):
        text = normalized(README).split("## visibility, checks, and run artifacts", 1)[1].split("## ", 1)[0]
        for phrase in ("start prompt", "marker", "watcher writes `worker.started`", "exit 9",
                       "exception path", "`worker.launch_sent` and `worker.started`",
                       "every worker", "before every `deliver`", "after context recovery"):
            self.assertIn(phrase, text)
        self.assertNotIn("before sending each task", text)


class CoordinatedUpgradeDocumentation(unittest.TestCase):
    def test_grilling_round_start_captures_and_compares_delivery_baseline(self):
        guide = REPOSITORY / "cmux-grilling" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("grilling skill absent")
        text = normalized(guide)
        procedure = text.split("round start:", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
        commands = ("pane_ctl.py open-round", 'snapshot --run-dir <run-dir> --label "launched round-1"',
                    "pane_ctl.py start-round", "await_reports.py")
        positions = [procedure.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        for phrase in ("round lanes not started", "not_started", "16 kib utf-8", "--context-digest",
                       "depends_on", "fresh visible panes per round", "reports-captured round-<n>",
                       "after exit 9", "readiness identity remains `{lane}`"):
            self.assertIn(phrase, text)
        for removed in ("await_reports.py --session", "render_prompt.py session", "adopted session"):
            self.assertNotIn(removed, text)

    def test_watch_hosting_and_persisted_deadlines(self):
        for guide in SIBLINGS:
            text = normalized(guide)
            with self.subTest(guide=guide):
                for phrase in ("2.1.288 or later", "run_in_background: true", "no time limit",
                               "one wake-up at exit", "30 minutes by default", "up to 2 hours",
                               "persisted on first arm", "--deadline-reason", "idempotent"):
                    self.assertIn(phrase, text)
                for obsolete in ("persistent: true", "caps at 60 minutes", "caps at 600000",
                                 "waits up to 10 minutes"):
                    self.assertNotIn(obsolete, text)

    def test_issue_chain_start_sequence_and_exception_path(self):
        path = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not path.exists():
            self.skipTest("sibling absent")
        text = normalized(path)
        procedure = text.split("close completed worker panes promptly:", 1)[1]
        self.assertLess(procedure.index('snapshot --label "launched <role>-<pass>"'),
                        procedure.index('pane_ctl.py start-agent --role'))
        for phrase in ('| 9 | assignment not started', 'after exit 9, take one `observe` and `assess`',
                       'then re-arm without re-delivery', 'one readiness-gated `deliver --prompt`',
                       '`evidence: "screen"`', 'exception-path and follow-up only',
                       'role deadline counts from the persisted first arm'):
            self.assertIn(phrase, text)

    def test_sibling_guides_gate_staged_deltas_at_every_delivery_boundary(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        chain = normalized(REPOSITORY / "cmux-issue-chain" / "SKILL.md")
        grilling = normalized(REPOSITORY / "cmux-grilling" / "SKILL.md")
        for phrase in (
            'every role (implement, simplify, review, test, and triage)',
            'run_state.py snapshot --label "launched <role>-<pass>"` right before `start-agent`',
            'launch snapshot (`launched <role>-<pass>`) against the capture snapshot (`report-captured <role>-<pass>`)',
            '`staged_paths`', '`staged_diff_sha256`', 'gate `hitl` even with a clean report',
            "staged path lists in the gate reason", "never unstages on the worker's behalf",
            'index and head check applies to test',
        ):
            with self.subTest(guide="issue-chain", phrase=phrase):
                self.assertIn(phrase, chain)
        for phrase in (
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
            self.assertIn(phrase, normalized(INTEGRITY))

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
            "documented kept choices", "without that approval or an `ask-user` finding gates `stop`",
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
        self.assertIn("\n## Not Applied\n- None", documentation(guide))

    def test_issue_chain_protects_same_run_decisions_across_passes(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        for start, end, phrases in (
            ("## review self-fix policy", "## gate rule", (
                "including prior passes of the same run",
                "reports from unrelated runs are outside this same-run protection",
                "a triage-worker verdict that the orchestrator recorded in `decisions.md` after a passing triage gate counts as recorded approval while autonomous triage is not opted out; such entries carry the marker `[triage-worker verdict, run <run-id>, gate advance]`",
                "a later opted-out run still honors it",
                "until recorded human approval explicitly supersedes the earlier decision",
                "identify the decision and the authorized replacement or scope",
                "an agent proposal, a later report, or an unapproved recommendation alone",
                "unresolved scope or precedence ambiguity as `recommendation: ask-user`",
            )),
            ("### diff inspection at code-changing gates", "## canonical check commands", (
                "current pass and relevant prior passes of the same run",
                "include prior-pass `## not applied` lists in this comparison",
                "check any claimed supersession against recorded human approval",
                "without that approval or an `ask-user` finding gates `stop`",
                "record the reverted item in the `orchestrator.verified` event",
                "relay it to the human verbatim as a finding, not a recommendation",
            )),
        ):
            self.assertIn(start, text)
            self.assertIn(end, text)
            section = text.split(start, 1)[1].split(end, 1)[0]
            for phrase in phrases:
                with self.subTest(section=start, phrase=phrase):
                    self.assertIn(phrase, section)
        context = text.split("- context files:", 1)[1].split("send the visible cmux worker", 1)[0]
        for phrase in (
            "relevant prior-pass reports from the same run with `--context-file`",
            "recorded human approvals that supersede them",
            "`decisions.md` is embedded automatically",
            "verify the rendered review prompt includes",
        ):
            with self.subTest(context=phrase):
                self.assertIn(phrase, context)

    def test_issue_chain_ledger_distinguishes_approved_supersessions(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        self.assertIn("## recommendations triage", text)
        self.assertIn("## hitl issues", text)
        triage = text.split("## recommendations triage", 1)[1].split("## hitl issues", 1)[0]
        self.assertIn("approved, rejected, deferred, recorded, and open", triage)
        self.assertIn("explicit recorded supersession approvals", triage)
        self.assertIn("a marker-bearing triage-worker verdict satisfies the recorded approval rule", triage)
        self.assertIn("identify the earlier decision and the authorized replacement or scope", triage)

    def test_issue_chain_routes_quality_counter_proposals_to_triage(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        for start, end, phrases in (
            ("## review self-fix policy", "## gate rule", (
                "a quality-only reason (reuse, simplification, efficiency, altitude, style) is never a finding",
                "goes under `## recommendations` marked `counter-proposal`",
                "`scope: other` therefore never carries `ask-user`",
                "already queued for triage under `## recommendations`",
                "### resuming after a confirming hitl",
                "identical tree fingerprint, `head`, `staged_paths`, and `staged_diff_sha256`",
                "the only case in which the orchestrator records `advance` over a parsed `stop`",
            )),
            ("## gate rule", "### diff inspection at code-changing gates", (
                "`quality_only_findings: true`",
                "moves those entries to `## recommendations` unchanged",
                "a report mixing them with any other finding is a plain `stop`",
            )),
            ("### diff inspection at code-changing gates", "## canonical check commands", (
                "reported as a `counter-proposal` under `## recommendations` is not reverted in the diff",
                "any edit outside them gates `stop`",
            )),
        ):
            self.assertIn(start, text)
            self.assertIn(end, text)
            section = text.split(start, 1)[1].split(end, 1)[0]
            for phrase in phrases:
                with self.subTest(section=start, phrase=phrase):
                    self.assertIn(phrase, section)

    def test_issue_chain_follow_up_pass_runs_before_complete(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        triage = text.split("## recommendations triage", 1)[1].split("## follow-up pass", 1)[0]
        for phrase in (
            "after the final test report parses `advance` and before that gate event is recorded",
            "a follow-up pass exists only while the issue is uncommitted",
            "recommendations triage is autonomous by default",
            "`--human-triage` opts out",
            "the orchestrator never decides recommendation content",
            "must never ask the human or the orchestrator anything",
            "`for-the-human` never blocks",
            "no automatic relaunch is allowed",
            "`[human verdict, run <run-id>]`",
            "accept only when the proposal refutes the recorded reason with evidence",
        ):
            with self.subTest(section="triage", phrase=phrase):
                self.assertIn(phrase, triage)
        followup = text.split("## follow-up pass", 1)[1].split("## hitl issues", 1)[0]
        for phrase in (
            "needs no approval beyond the triage verdict",
            "the change is behavior-preserving", "it stays inside the files of the issue diff",
            "no acceptance criterion changes", "`--next-stage implement`", "`--followup-file`",
            "one follow-up pass per issue", "no simplify or review stage in it",
            "never start another pass", "the commit proposal covers the issue and the follow-up together",
        ):
            with self.subTest(section="follow-up", phrase=phrase):
                self.assertIn(phrase, followup)
        raw = documentation(guide)
        self.assertIn("--role implement --pass 2 --run-dir .scratch/orchestrator/runs/<run-id> --followup-file", raw)
        self.assertIn("\n## Recommendations\n- None, or refactorings that need a human decision.", raw)

    def test_issue_chain_autonomous_completion_and_summary(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        followup = text.split("## follow-up pass", 1)[1].split("## hitl issues", 1)[0]
        for phrase in (
            "after the follow-up test report parses `advance` and before that gate event is recorded",
            "collect_recommendations.py --run-dir <run-dir> --pass 2",
            "`advance --next-stage triage`", "`advance` with no next stage",
            "triage-2 never starts another follow-up pass",
            "accepted in triage-1, not applied in the follow-up pass: <reason verbatim> — open",
            "do not trigger `triage-2`",
        ):
            self.assertIn(phrase, followup)
        triage = text.split("## recommendations triage", 1)[1].split("## follow-up pass", 1)[0]
        for phrase in ("--pass 2", "reports/triage-1.md", "followup-items.md", "next_stage: null"):
            self.assertIn(phrase, triage)
        summary = text.split("## reporting to the human", 1)[1].split("## recommendations triage", 1)[0]
        for phrase in ("run recap", "every gate in order", "triage table",
                       "id, short title, verdict", "reason verbatim", "## not applied", "for-the-human",
                       "created by triage:", "commit.proposed", "wait"):
            self.assertIn(phrase, summary)
        commit = text.split("## branch and commit policy", 1)[1].split("## reporting to the human", 1)[0]
        self.assertIn("tracker changes published by triage (new issue files, `decisions.md`) with `--tracker-file`", commit)
        self.assertIn("test -> triage-1 -> (follow-up implement -> test -> triage-2) -> issue status -> complete -> commit proposal -> commit (commit mode) -> run recap + final summary -> wait", text)

    def test_issue_chain_relevant_prior_pass_context_and_example(self):
        guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        text = normalized(guide)
        self.assertIn("- context files:", text)
        self.assertIn("send the visible cmux worker", text)
        context = text.split("- context files:", 1)[1].split("send the visible cmux worker", 1)[0]
        self.assertIn(
            "relevant prior reports are those carrying protected decisions or explicit human supersession records",
            context,
        )
        self.assertIn("unrelated or decision-free historical reports are not required by default", context)
        lines = documentation(guide).splitlines()
        example = next(line for line in lines if line.startswith("python3 scripts/render_prompt.py ")
                       and "--role review --pass 2 " in line)
        for report in ("implement-1", "simplify-1", "review-1", "implement-2", "simplify-2"):
            with self.subTest(report=report):
                self.assertIn(
                    f"--context-file .scratch/orchestrator/runs/<run-id>/reports/{report}.md", example,
                )

    def test_vendored_run_helpers_are_byte_identical(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        helper_files = {
            "slugify": {guide: "orchestrator_lib.py" for guide in SIBLINGS},
            "run_identifier": {guide: "orchestrator_lib.py" for guide in SIBLINGS},
            **{name: {
                guide: "planning_state.py" if guide == PLANNING else "run_state.py"
                for guide in SIBLINGS
            } for name in ("ensure_runs_root_ignored", "refuse_runs_root_in_skill")},
        }
        for name, files in helper_files.items():
            sources = []
            for guide in SIBLINGS:
                filename = files[guide]
                source = (guide.parent / "scripts" / filename).read_text(encoding="utf-8")
                function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
                sources.append(ast.get_source_segment(source, function))
            self.assertEqual(sources, [sources[0]] * 3, name)

    def test_vendored_shared_files_are_byte_identical(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        for relative in ("scripts/run_briefing.py", "scripts/test_run_briefing.py", "scripts/run_commit.py",
                         "scripts/test_run_commit.py", "references/preparation-upgrades.md"):
            contents = [(guide.parent / relative).read_bytes() for guide in SIBLINGS]
            self.assertEqual(contents, [contents[0]] * 3, relative)

    def test_commit_transaction_is_documented_in_every_guide(self):
        for skill in ("cmux-issue-chain", "cmux-grilling", "cmux-planning"):
            text = documentation(REPOSITORY / skill / "SKILL.md").lower()
            vocabulary = text.split("## event vocabulary", 1)[1]
            for event in ("commit.attempted", "commit.created", "commit.skipped", "commit.failed"):
                self.assertIn(event, vocabulary, skill)
            for phrase in ("run_commit.py commit", "hitl always proposes", "commit.attempted",
                           "commit.created", "commit.skipped", "commit.failed", "never `--no-verify`",
                           "literal leaf `git add`", "git reset -q --", "git update-ref head <p> <c>",
                           "never re-propose a changed draft"):
                self.assertIn(phrase, text, skill)

    def test_every_guide_briefs_the_human_before_the_first_worker(self):
        for guide in SIBLINGS:
            text = normalized(guide)
            self.assertIn("## run briefing", text, guide)
            self.assertIn("run_briefing.py draft", text, guide)
            self.assertIn("run_briefing.py show", text, guide)

    def test_proposals_use_the_helper_and_literal_leaf_paths(self):
        for guide in SIBLINGS:
            text = normalized(guide)
            self.assertIn("run_commit.py propose", text)
            self.assertIn("literal leaf paths", text)
            for heading in ("## scripts", "## event vocabulary"):
                section = text.split(heading, 1)[1].split("## ", 1)[0]
                self.assertIn("run_commit.py propose", section)
                self.assertIn("commit.proposed", section)
            if guide.parent.name == "cmux-issue-chain":
                self.assertIn("commit.proposed", text.split("## reporting to the human", 1)[1].split("## run recap", 1)[0])
        text = normalized(PLANNING)
        self.assertLess(text.index("## ticket approval, staging, and publication"), text.index("## commit after"))
        self.assertLess(text.index("## commit after"), text.index("## run recap"))

    def test_every_guide_closes_the_run_with_a_recap(self):
        for guide in SIBLINGS:
            text = normalized(guide)
            self.assertIn("## run recap", text, guide)
            self.assertIn("run_briefing.py recap-draft", text, guide)
            self.assertIn("run_briefing.py recap-show", text, guide)

    def test_vendored_untracked_hashing_matches_without_chain_tokenizer(self):
        if len(SIBLINGS) != 3:
            self.skipTest("sibling skills are absent in this independent installation")
        sources = []
        parsers = []
        for guide in SIBLINGS:
            filename = "tree_integrity.py" if guide == PLANNING else "run_state.py"
            source = (guide.parent / "scripts" / filename).read_text(encoding="utf-8")
            nodes = ast.parse(source).body
            function = next(node for node in nodes if isinstance(node, ast.FunctionDef) and node.name == "untracked_content")
            limit = next(node for node in nodes if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "UNTRACKED_HASH_LIMIT_BYTES" for target in node.targets))
            function_source = ast.get_source_segment(source, function)
            # Issue-chain shares a stricter tokenizer; keep the other two parsers
            # identical and compare only the hashing tail in all three.
            if guide.parent.name != "cmux-issue-chain":
                parsers.append(function_source)
            hashing = function_source[function_source.index('        if code != "??":'):]
            sources.append((hashing, ast.get_source_segment(source, limit)))
        self.assertEqual(parsers, [parsers[0]] * 2)
        self.assertEqual(sources, [sources[0]] * 3)

    def test_shared_root_and_local_run_name_documentation(self):
        if not README.is_file():
            self.skipTest("repository README is absent")
        self.assertIn("YYYY-MM-DD-HHMM-<skill>-<key>", documentation(README))
        for skill, key in (("grilling", "grill"), ("planning", "plan"), ("issue-chain", "chain")):
            guide = REPOSITORY / f"cmux-{skill}" / "SKILL.md"
            text = documentation(guide)
            self.assertIn(f"YYYY-MM-DD-HHMM-{key}-", text)
            self.assertIn("local time", text)
            for path in (guide, *(guide.parent / "references").glob("*.md")):
                current = path.read_text()
                self.assertNotIn("planning-runs/", current, path)
                self.assertNotRegex(current, r"(?:plan|grill|chain)-[^`\n]*<YYYY-MM-DD>-<HHMM>", path)
                self.assertNotIn("layout_version: 1", current, path)
            self.assertNotIn("<ISSUE-ID>-<YYYY-MM-DD>-<HHMM>", text)

    def test_every_shipped_guide_requires_a_coordinated_schema_v3_upgrade(self):
        if not README.is_file():
            self.skipTest("repository README is not present in this independent installation")
        # The README line is the single source; asserting the copies equal it is what actually
        # matters, and it keeps the test from becoming one more copy that can drift.
        canonical = notice(README.read_text(encoding="utf-8"))
        for required in (
            "cmux-planning",
            "cmux-grilling",
            "cmux-issue-chain",
            "schema v3",
            "older separately installed sibling skills",
        ):
            self.assertIn(required, canonical.lower())

        for guide in GUIDES:
            with self.subTest(guide=guide.relative_to(REPOSITORY)):
                self.assertEqual(canonical, notice(documentation(guide)))

    def test_every_shipped_guide_documents_explicit_read_only_migration(self):
        # Detailed operator contracts belong in the standalone skill guides; the README
        # introduces the workflows and links to those references.
        for guide in GUIDES:
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
                    "claude-opus-high",
                    "profile name",
                    "harness",
                    "model",
                    "effort",
                    "without inferring relative quality",
                ):
                    self.assertIn(required, text)
                self.assertNotIn("migrates a schema-v1 file as a side effect", text)


class IssueChainEvidenceDocumentation(unittest.TestCase):
    def setUp(self):
        self.guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not self.guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")
        self.text = normalized(self.guide)
        self.references = self.guide.parent / "references"
        self.policy = normalized(self.references / "test-evidence.md")

    def section(self, start, end):
        return self.text.split(start, 1)[1].split(end, 1)[0]

    def test_default_chain_and_gate_require_evidence(self):
        chain = self.section("## default chain", "## review self-fix policy")
        for phrase in ("evidence check", "before every gate", "simplify after-run",
                       "review cites or runs"):
            self.assertIn(phrase, chain)
        gate = self.section("## gate rule", "### diff inspection at code-changing gates")
        for phrase in ("passing evidence check", "blocked` > `hitl` > `stop` > `advance",
                       "never downgrades a `blocked` or `hitl`", "latest `report-captured",
                       "newer `launched", "run_state.py event"):
            self.assertIn(phrase, gate)

    def test_check_commands_and_diff_inspection(self):
        commands = self.section("## canonical check commands", "## worker wait policy")
        self.assertNotIn("targeted check commands for implement, simplify, and review:", commands)
        for phrase in ("[test selection and evidence policy](references/test-evidence.md)",
                       "canonical declarations remain required",
                       "no runnable canonical check commands", "`hitl`"):
            self.assertIn(phrase, commands)
        diff = self.section("### diff inspection at code-changing gates", "## canonical check commands")
        self.assertIn("evidence check", diff)

    def test_selection_policy_has_one_authoritative_home(self):
        # Wording belongs to issue-chain's test_test_evidence_docs.py. Keep only
        # stable identity anchors here so policy edits do not require two suites.
        for anchor in ("# test selection and evidence policy", "authoritative policy"):
            self.assertIn(anchor, self.policy)
        chain = self.section("## default chain", "## review self-fix policy")
        self.assertIn("(references/test-evidence.md)", chain)
        for consumer in (self.text,
                         normalized(self.references / "worker-report-contract.md"),
                         normalized(self.references / "follow-up-pass.md")):
            self.assertNotIn("## test selection", consumer)

    def test_script_invocations_and_pane_guidance(self):
        self.assertNotIn("quick-check", self.text)
        scripts = self.text.split("## scripts", 1)[1]
        for phrase in ("run_check.py --artifact-dir", "--command",
                       "check_evidence.py --run-dir <run-dir> --stage <role> --pass <n> --report",
                       "evidence check passed"):
            self.assertIn(phrase, scripts)

    def test_references_describe_evidence_and_citations(self):
        followup = normalized(self.references / "follow-up-pass.md")
        for phrase in ("cite-before, run-after", "test-evidence.md#simplify-and-marked-follow-up-implement"):
            self.assertIn(phrase, followup)
        self.assertNotIn("baseline suite before and after", followup)
        events = documentation(self.references / "event-vocabulary.md").lower()
        row = next(line for line in events.splitlines() if "`orchestrator.verified`" in line)
        for phrase in ("test evidence", "check_evidence.py", "diff inspection"):
            self.assertIn(phrase, row)
        self.assertNotIn("quick-check", events)
        infrastructure = normalized(self.references / "infrastructure-blockers.md")
        for phrase in ("resume the same stage", "own evidence", "does not rerun checks"):
            self.assertIn(phrase, infrastructure)
        report = normalized(self.references / "worker-report-contract.md")
        for phrase in ("[test selection and evidence policy](test-evidence.md)",
                       "`evidence:`", "`cited:`", "`selection:`"):
            self.assertIn(phrase, report)
        scripts = normalized(self.references / "script-tests.md")
        for name in ("run_check", "check_evidence", "check_commands", "evidence_contract", "gate_evidence"):
            self.assertIn(f"test_{name}.py", scripts)

    @unittest.skipUnless(README.is_file(), "repository README absent in independent installation")
    def test_readme_chain_step_uses_evidence_check(self):
        step = next(line.lower() for line in documentation(README).splitlines()
                    if line.startswith("3. **Orchestrator"))
        self.assertIn("evidence check", step)
        self.assertIn("before every", step)
        self.assertNotIn("rerun", step)


class IssueChainEvidenceDocumentationRegression(unittest.TestCase):
    def setUp(self):
        self.guide = REPOSITORY / "cmux-issue-chain" / "SKILL.md"
        if not self.guide.is_file():
            self.skipTest("issue-chain skill is absent in this independent installation")

    def run_with_rewrite(self, relative_path, rewrite):
        target = self.guide.parent / relative_path
        read_text = Path.read_text

        # Rewrite at file level so on-demand references inlined into SKILL.md change too.
        def changed(path, *args, **kwargs):
            text = read_text(path, *args, **kwargs)
            return rewrite(text) if path == target else text

        def clear_caches():
            documentation.cache_clear()
            normalized.cache_clear()

        clear_caches()
        try:
            with patch.object(Path, "read_text", autospec=True, side_effect=changed):
                result = unittest.TestResult()
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    IssueChainEvidenceDocumentation).run(result)
        finally:
            clear_caches()
        self.assertFalse(result.errors, result.errors)
        return result

    def test_policy_rewording_preserving_anchors_passes(self):
        result = self.run_with_rewrite(
            "references/test-evidence.md",
            lambda _: "# Test selection and evidence policy\n\n"
                      "This is the authoritative policy. Its rules have been reworded.\n",
        )
        self.assertTrue(result.wasSuccessful(), result.failures)

    def test_missing_consumer_link_fails(self):
        baseline = self.run_with_rewrite("SKILL.md", lambda text: text)
        self.assertTrue(baseline.wasSuccessful(), baseline.failures)
        for path, link in (
            ("SKILL.md", "[test selection and evidence policy](references/test-evidence.md)"),
            ("references/worker-report-contract.md",
             "[Test selection and evidence policy](test-evidence.md)"),
            ("references/follow-up-pass.md",
             "[test selection and evidence policy](test-evidence.md#simplify-and-marked-follow-up-implement)"),
        ):
            with self.subTest(path=path):
                self.assertIn(link, documentation(self.guide.parent / path))
                result = self.run_with_rewrite(path, lambda text: text.replace(link, "test policy"))
                self.assertFalse(result.wasSuccessful(), "missing policy link must fail")


class CommitModeDocumentation(unittest.TestCase):
    def test_question_only_at_fresh_init(self):
        for guide in SIBLINGS:
            text = normalized(guide)
            for phrase in ("--commit-mode", "askuserquestion", "single-select", "fresh init",
                           "invocation does not already name", "never on resume", "re-init",
                           "exit-3", "smoke tests", "show proposal only", "nur vorschlag zeigen",
                           "commit automatically", "automatisch committen", "recommended"):
                self.assertIn(phrase, text, guide)



class ArtifactLanguageDocumentation(unittest.TestCase):
    def test_fresh_init_question_and_language_boundary(self):
        text = normalized(PLANNING)
        language = text.split("## artifact language at initialization", 1)[1].split("## ", 1)[0]
        for phrase in ("askuserquestion", "single-select", "english", "first and recommended",
                       "human's language", "other", "free text", "--artifact-language",
                       "never on resume", "re-init", "exit-3", "smoke tests"):
            self.assertIn(phrase, language)
        details = normalized(INITIALIZATION)
        for phrase in ("40 characters", "immutable", "legacy", "english language name"):
            self.assertIn(phrase, details)
        for path in (PLANNING, PLANNING.parent / "references" / "spec-contract.md"):
            content = normalized(path)
            for phrase in ("original language", "chosen language", "headings", "markers", "json keys",
                           "reports", "state", "events", "prompts", "technical_layers"):
                self.assertIn(phrase, content, path)
            self.assertNotIn("canonical persisted artifacts are english", content)
            self.assertNotIn("the specification is english", content)
            self.assertNotIn("one english frontmatter issue", content)


class ConversationBriefDocumentation(unittest.TestCase):
    def test_brief_is_confirmed_through_a_structured_question(self):
        initialize = normalized(PLANNING).split("## initialize", 1)[1].split("## ", 1)[0]
        self.assertIn("askuserquestion", initialize)
        self.assertIn(
            "only brief entries the human stated beat revalidated grilling decisions, which beat plan "
            "files; entries taken from files keep the rank of their source. "
            "other contradictions go to `open decisions`.", initialize)
        brief = normalized(PLANNING.parent / "references" / "conversation-brief.md")
        for phrase in ("complete brief as its own message", "askuserquestion", "single-select",
                       "human's language", "first and recommended", "did not state",
                       "do not copy content from plan files into the brief",
                       "an entry that comes from a file names its source in parentheses",
                       "show the revised brief in full and ask again",
                       "`--brief-confirmed` only after \"confirm\""):
            self.assertIn(phrase, brief)


class PlanningOperatorDocumentation(unittest.TestCase):
    def test_entrypoint_states_orchestrator_gate_rules(self):
        # Read the entry point itself: on-demand references cannot supply these rules.
        text = " ".join(PLANNING.read_text(encoding="utf-8").split()).lower()
        for rule in (
            "the orchestrator never changes a tracker after publication.",
            "every option offered at a gate, including the recommended one, stays within "
            "the planning contract and states its consequences for validation and digests.",
            "relaunch and revise reasons quote the chosen option verbatim as the human saw it, label "
            "and description, followed by the human's free text, with no orchestrator additions; "
            "reviewer findings arrive only as the attached review report.",
            "before asking about a `blocked` verdict, show the gate command's output in the chat, then ask. "
            "if your recommendation differs from the reviewer's, say so in one sentence; "
            "you are not obliged to follow the reviewer.",
            "only final spec and ticket approval questions carry no recommendation; "
            "blocker questions may carry a recommendation.",
            "label every option the orchestrator drafted itself, rather than taking it from a report or "
            "the human, as drafted by the orchestrator.",
            "an extension option states how the worker continues: only more time, or a new delivery of "
            "the full stage prompt.",
            "questions and walkthroughs use the user's language; inputs keep their original language.",
            "headings, markers, json keys, reports, state, events, and prompts stay english; "
            "preserve literal product copy.",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)
        self.assertEqual(text.count("relaunch and revise reasons quote"), 1)
        self.assertNotIn("quote only the chosen option's label", text)
        self.assertNotIn("never option descriptions", text)

    def test_recovery_reference_describes_verbatim_reasons_and_review_attachments(self):
        text = " ".join(STATUS_RECOVERY.read_text().split())
        for phrase in ("For relaunch and revise, `--reason` quotes the chosen option verbatim as the human "
                       "saw it, label and description, followed by the human's free text, with no "
                       "orchestrator additions.",
                       "Reviewer findings arrive only as the attached review report.",
                       "Both relaunch and revise attach",
                       "review report by its finalized manifest identity", "--scope spec",
                       "`approval --decision revise`", "`ticket-approval --decision revise`",
                       "a spec author gets every prior handoff", "only as path and sha256"):
            self.assertIn(phrase, text)
        self.assertNotIn("quotes only the chosen option's label", text)
        self.assertNotIn("never option descriptions", text)

    def test_ground_rules_keep_exact_approved_bullets(self):
        raw = PLANNING.read_text(encoding="utf-8")
        ground = raw.split("## Ground rules\n", 1)[1].split("\n## ", 1)[0]
        bullets = [" ".join(bullet.split()) for bullet in
                   re.findall(r"^- (.*(?:\n[ \t]+\S.*)*)", ground, re.MULTILINE)]
        expected = (
            (
                'The orchestrator never changes a tracker after publication.'
            ),
            (
                'Every option offered at a gate, including the recommended one, stays within the planning '
                'contract and states its consequences for validation and digests.'
            ),
            (
                'Relaunch and revise reasons quote the chosen option verbatim as the human saw it, label '
                "and description, followed by the human's free text, with no orchestrator additions; "
                'reviewer findings arrive only as the attached review report.'
            ),
            (
                "Before asking about a `blocked` verdict, show the gate command's output in the chat, then "
                "ask. If your recommendation differs from the reviewer's, say so in one sentence; you are "
                'not obliged to follow the reviewer.'
            ),
            (
                'Only final spec and ticket approval questions carry no recommendation; blocker questions '
                'may carry a recommendation.'
            ),
            (
                'Label every option the orchestrator drafted itself, rather than taking it from a report or '
                'the human, as drafted by the orchestrator.'
            ),
            (
                'An extension option states how the worker continues: only more time, or a new delivery of '
                'the full stage prompt.'
            ),
            (
                "Only after successful completion, the orchestrator's new Git writes through `run_commit.py "
                'commit` are literal leaf `git add`, `git commit`, path-limited `git reset -q --`, and '
                'compare-and-swap `git update-ref HEAD <P> <C>` to undo its proven commit. Workers must '
                'never change the Git index or HEAD.'
            ),
            (
                '`cmux-grilling` is optional. When supplied, import its JSON and the Markdown named by '
                '`markdownPath`, validate and copy their exact bytes, then explicitly revalidate them with '
                'the human before preparing a worker. Structural validation proves integrity, not '
                'freshness.'
            ),
            (
                'Workers synthesize supplied context and inspect the repository. They do not interview the '
                'user; they put missing information under `Open Decisions`.'
            ),
            (
                'The spec author may write only its draft and report. The tickets author may write only its '
                'JSON proposal, deterministic numbered summary, and report. A reviewer may write only its '
                'report and, for `pass_with_fixes`, its complete corrected candidate.'
            ),
            (
                "Questions and walkthroughs use the user's language; inputs keep their original language. "
                'Spec and ticket content follow the chosen language (`artifact_language`). Headings, '
                'markers, JSON keys, reports, state, events, and prompts stay English; preserve literal '
                'product copy. Field-level rules, including English `technical_layers` and fixed labels: '
                '[references/spec-contract.md](references/spec-contract.md).'
            ),
            (
                'Each ticket is a narrow but complete vertical slice. Never default to '
                'frontend/backend/database/test tickets, never persist token counts or estimates, and '
                'evaluate merge opportunities as explicitly as split points. Standalone prefactors '
                '(`slice_type: prefactor`) come first and block the slices they prepare. Blocking edges '
                'must be genuine and every blocker has a smaller ticket ID.'
            ),
            (
                'Only a passing reviewed ticket candidate may be staged. Publication is a collision-checked '
                'atomic directory move into the target repository and never invokes `cmux-issue-chain` or '
                '`adopt_tracker.py` at runtime.'
            ),
            (
                'Any unauthorized Git-visible delta gates HITL regardless of report; never silently revert '
                'it.'
            ),
        )
        for bullet in expected:
            with self.subTest(bullet=bullet):
                self.assertEqual(bullets.count(bullet), 1)

    def test_integrity_reference_route_and_entrypoint_exclusions(self):
        raw = PLANNING.read_text(encoding="utf-8")
        flat = " ".join(raw.split())
        routes = [route for route in ON_DEMAND.finditer(raw)
                  if route.group(1) == "integrity-boundaries.md"]
        self.assertEqual(len(routes), 1)
        for condition in ("integrity violation", "failed tree capture", "manifest question", "retry attempt",
                          "in-flight run after an upgrade", "what the integrity boundary covers"):
            self.assertIn(condition, routes[0].group())
        self.assertTrue(raw[:routes[0].start()].endswith("never silently revert it.\n\n"))
        headings = re.findall(r"^#+ (.+)$", documentation(INTEGRITY), re.MULTILINE)
        entry_headings = re.findall(r"^#+ (.+)$", raw, re.MULTILINE)
        self.assertTrue(headings)
        for heading in headings:
            self.assertNotIn(heading, entry_headings)
            self.assertFalse(heading.startswith("Commit"))
        self.assertIn(
            "Treat malformed reports, digest drift, dead panes, expired waits, blocked decisions, and "
            "integrity violations as evidence for human resolution. Never infer approval from prose, "
            "edit product code from the planning orchestrator, silently repair the working tree, or "
            "claim coverage beyond the Ground rules integrity boundary.", flat)

    def test_integrity_reference_preserves_moved_rules(self):
        expected = (
            'Two explicit integrity boundaries apply. The product-tree detector covers tracked changes, '
            'staged changes, untracked paths and their content (regular files up to the 8 MiB size cap '
            'and symlink target bytes), and HEAD movement. It does not cover ignored product files or '
            'skipped untracked content (files above the size cap or unsupported types), or contents of '
            'unreadable untracked directories omitted by Git with a warning. Separately, every trusted '
            "file in the Git-ignored run directory is finalized in `state.json`'s artifact manifest "
            'with its canonical run-relative path, kind, stage, pass, attempt, byte size, SHA-256, '
            'producer event, and immutable status. A baseline arms one pass and is never recaptured '
            'against different product-tree bytes, so a relaunch cannot adopt an unauthorized delta as '
            'its new "before". Before each launch, capture complete Git status, tracked and staged '
            'diffs; after the report, compare paths and diff content. `compare_tree` compares the whole '
            'before/after `staged_diff` independently of the allowed-write list. Any difference gates '
            '`integrity-violation`, including staging an allowed artifact in a non-ignored custom run '
            'root. Ordinary permitted artifact content writes and an unchanged pre-staged human '
            'baseline remain allowed. An unreadable or vanished untracked path fails capture with a '
            'diagnostic naming it instead of being skipped; restore access or remove the path and '
            'retry. Git only warns about an unreadable untracked directory, so its contents stay '
            'invisible rather than failing capture. Every worker emission has an immutable attempt '
            'identity. The first attempt retains the concise stage/pass filenames; every later '
            'same-pass attempt uses an `-attempt-N` suffix for its prompt, report, draft/proposal, '
            'optional corrected candidate, stage snapshot, and tree snapshots. Preparing a retry closes '
            'the earlier attempt and never reuses, deletes, or silently re-baselines its paths. '
            'In-flight runs with pre-change untracked baselines must restart after upgrading; never '
            'migrate those baselines or bypass seals.'
        )
        body = documentation(INTEGRITY).split("\n\n", 1)[1]
        self.assertEqual(" ".join(body.split()), expected)
        entry = " ".join(PLANNING.read_text(encoding="utf-8").split())
        for sentence in re.split(r"(?<=\.) ", expected):
            with self.subTest(sentence=sentence):
                self.assertNotIn(sentence, entry)

    def test_entrypoint_states_integrity_boundary_once(self):
        sources = [PLANNING, *sorted((PLANNING.parent / "references").glob("*.md"))]
        texts = {path: " ".join(path.read_text(encoding="utf-8").split()) for path in sources}
        for phrase in ("8 MiB", "artifact manifest",
                       "The product-tree detector covers tracked changes, staged changes",
                       "regular files up to the 8 MiB size cap and symlink target bytes",
                       "It does not cover ignored product files or skipped untracked content",
                       "contents of unreadable untracked directories omitted by Git with a warning",
                       "never recaptured against different product-tree bytes"):
            with self.subTest(phrase=phrase):
                self.assertEqual(texts[INTEGRITY].count(phrase), 1)
                self.assertEqual(sum(text.count(phrase) for text in texts.values()), 1)

    def test_planning_start_sequence_and_recovery_safety(self):
        text = normalized(PLANNING)
        stage_run = normalized(STAGE_RUN)
        procedure = stage_run.split("```bash", 1)[1].split("```", 1)[0]
        commands = ("render_prompt.py", "tree_integrity.py baseline", "pane_ctl.py launch",
                    "pane_ctl.py start-agent", "await_report.py")
        positions = [procedure.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("pane_ctl.py deliver", procedure)
        self.assertNotIn("pane_ctl.py observe", procedure)
        self.assertIn("| 9 | assignment not started; inspect the exception path below. |", stage_run)
        for phrase in ("after exit 9, take one `observe` and `assess`",
                       "then re-arm without re-delivery", "one readiness-gated `deliver --prompt`",
                       '`evidence: "screen"`', "exception-path and follow-up only",
                       "`--extension 0`", "interrupted launch or delivery input stops at hitl",
                       "report deadline counts from the persisted first arm", "never immutable manifest artifacts"):
            self.assertIn(phrase, text)

    def test_stage_run_route_and_moved_rules(self):
        raw = PLANNING.read_text(encoding="utf-8")
        entry = " ".join(raw.split())
        routes = [route for route in ON_DEMAND.finditer(raw)
                  if route.group(1) == "stage-run-details.md"]
        self.assertEqual(len(routes), 1)
        self.assertIn("running or watching a stage pass", routes[0].group())
        self.assertIn("judging its handoff", routes[0].group())
        self.assertIn("a board update fails at any transition", routes[0].group())
        self.assertTrue(raw[:routes[0].start()].endswith("## Run one stage\n\n"))
        reference = documentation(STAGE_RUN)
        flat = " ".join(reference.split())
        moved = (
            'For `spec`, `spec-review`, `tickets`, or `tickets-review`, use the current pass from `state.json`:',
            '| Exit | Meaning | | --- | --- | '
            '| 0 | Report captured; validate and gate it. | '
            '| 7 | Pane dead; stop at the existing HITL recovery boundary. | '
            '| 8 | Report deadline; use the existing human-approved extension rules. | '
            '| 9 | Assignment not started; inspect the exception path below. |',
            'Workers self-validate in `report-draft.md` beside their started marker and write the handoff report once, last.',
            'Read [references/spec-contract.md](spec-contract.md) when judging author or review handoffs.',
            'A failed board update is a stderr note and never a stop.',
        )
        for rule in moved:
            with self.subTest(rule=rule):
                self.assertIn(rule, flat)
                self.assertNotIn(rule, entry)
        self.assertNotIn('when judging author or review handoffs', entry)
        for row in reference.splitlines():
            if re.match(r'^\| [0789] \|', row):
                self.assertNotIn(row, entry)
        procedure = reference.split("```bash\n", 1)[1].split("```", 1)[0]
        self.assertEqual(procedure, (
            'python3 scripts/render_prompt.py --run-dir <run-dir> --stage <stage> --pass <n>\n'
            'python3 scripts/tree_integrity.py baseline --run-dir <run-dir> --stage <stage> --pass <n>\n'
            'python3 scripts/pane_ctl.py launch --run-dir <run-dir> --stage <stage> --pass <n> \\\n'
            '  --anchor <caller-surface>\n'
            'python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --stage <stage> --pass <n> \\\n'
            '  --surface <launch-surface-id>\n'
            'python3 scripts/await_report.py --run-dir <run-dir> --stage <stage> --pass <n> \\\n'
            '  --surface <launch-surface-id>\n'
        ))
        self.assertNotIn(procedure, raw)
        self.assertIn('startup-recovery', reference.split('| Exit |', 1)[0])
        for target in re.findall(r'\]\(([^)]+)\)', reference):
            self.assertTrue((STAGE_RUN.parent / target).is_file(), target)
        headings = re.findall(r"^#+ (.+)$", reference, re.MULTILINE)
        entry_headings = re.findall(r"^#+ (.+)$", raw, re.MULTILINE)
        self.assertTrue(headings)
        for heading in headings:
            self.assertNotIn(heading, entry_headings)
            self.assertFalse(heading.startswith("Commit"))
        for kept in (
            'Exits 7 and 8 publish `hitl` on the sidebar board. The recorded extension or relaunch decision returns the card to `running`.',
            'Read when the watcher exits 9 before confirming assignment start: [references/startup-recovery.md](references/startup-recovery.md).',
        ):
            self.assertIn(kept, raw)

    def test_ticket_stage_routes_and_moved_rules(self):
        raw = PLANNING.read_text(encoding="utf-8")
        entry = " ".join(raw.split())
        routes = [route for route in ON_DEMAND.finditer(raw)
                  if route.group(1) == "ticket-stage-details.md"]
        self.assertEqual(len(routes), 2)
        author = raw.split("## Ticket author and independent review\n", 1)[1].split("\n## ", 1)[0]
        approval = raw.split("## Ticket approval, staging, and publication\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(routes[0].group(), author)
        self.assertIn("gating the tickets author's report", routes[0].group())
        self.assertIn(routes[1].group(), approval)
        self.assertIn("publishing after ticket approval", routes[1].group())
        self.assertIn('Subject convention: [references/ticket-stage-details.md](references/ticket-stage-details.md).', entry)
        reference = documentation(TICKET_STAGE)
        flat = " ".join(reference.split())
        moved = (
            'Gate a clean report with `accept-author` as above. It validates approved-spec identity, '
            'proposal structure, summary equality, ticket count, ready frontier, genuine blockers, cycles, '
            'qualitative sizing, merge/split rationale, and wide-refactor sequences, then prepares a fresh '
            'immutable `tickets-review` snapshot. Run that stage in a new visible pane; '
            'gate its report with `accept-review` as above.',
            'The target must be absent or contain only a real `grilling/` directory (variant B); '
            'its basename must equal the dated feature name `YYYY-MM-DD-<slug>`; '
            '`tracker.slug` remains the pure slug.',
            'Publish on one filesystem; variant B moves `grilling/` first:',
            'python3 scripts/planning_state.py publish --run-dir <run-dir>',
            'Use an English one-line subject explaining what changed and why, an optional body, and no trailers.',
        )
        for rule in moved:
            with self.subTest(rule=rule):
                self.assertIn(rule, flat)
                self.assertNotIn(rule.rstrip('.:'), entry)
        self.assertIn('See the Gate the author and reviewer section in the entry point', reference)
        self.assertIn('## Gate the author and reviewer\n', raw)
        positions = [flat.index(rule) for rule in moved]
        self.assertEqual(positions, sorted(positions))
        headings = re.findall(r"^#+ (.+)$", reference, re.MULTILINE)
        entry_headings = re.findall(r"^#+ (.+)$", raw, re.MULTILINE)
        self.assertTrue(headings)
        for heading in headings:
            self.assertNotIn(heading, entry_headings)
            self.assertFalse(heading.startswith("Commit"))
        self.assertIn('Approve the reviewed tickets:\n\n```bash\n'
                      'python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \\\n'
                      '  --decision approve --reason <human-reason>\n```', approval)

    def test_initialization_routes_moved_rules_and_question_order(self):
        raw = PLANNING.read_text(encoding="utf-8")
        entry = " ".join(raw.split())
        details = " ".join(documentation(INITIALIZATION).split())
        moved = (
            "Copy plan files unchanged to `inputs/task-files/NN-<basename>` and the confirmed brief to "
            "`inputs/conversation-brief.md`; record `state.inputs`. "
            "Legacy `state.task` / `task.md` works; preserve each input's language.",
            "Pass `init --artifact-language <name>`: a non-empty English language name, at most 40 characters "
            "(e.g. `German`), default English. Stored as `artifact_language`, immutable; a different re-init "
            "value is refused. Legacy reads default to English. Briefing adds `Language: …` / `Sprache: …` "
            "only with the field, before Commit.",
            "Require a plan file or brief; grilling is additional.",
        )
        for rule in moved:
            with self.subTest(rule=rule):
                self.assertIn(rule, details)
                self.assertNotIn(rule, entry)
        routes = [route.group().strip() for route in ON_DEMAND.finditer(raw)
                  if route.group(1) == "initialization-details.md"]
        self.assertEqual(routes, [
            "Read when choosing init examples, relative paths, or retry behavior: "
            "[references/initialization-details.md](references/initialization-details.md).",
            "Read when handling init inputs, the language flag, installing planning, or setting it up for first use: "
            "[references/initialization-details.md](references/initialization-details.md).",
        ])
        installation = "Read when installing planning or setting it up for first use: "
        self.assertNotIn(installation, entry)
        self.assertIn(installation + "[references/installation.md](installation.md).", details)
        self.assertTrue((INITIALIZATION.parent / "installation.md").is_file())
        self.assertNotIn("as its second question", entry)
        language = entry.split("## Artifact language at initialization", 1)[1].split("## ", 1)[0]
        self.assertIn("In the same `AskUserQuestion` call as the commit mode, ask a single-select in the "
                      "human's language:", language)
        self.assertIn("Order the initialization questions as commit mode, feature name, language, assignments, "
                      "leaving out any skipped question.", language)
        defaults = normalized(PLANNING.parent / "references/default-assignments.md")
        self.assertIn("commit-mode, feature-name and language questions", defaults)
        self.assertIn("or alone when none of those is asked", defaults)
        self.assertNotIn("or alone when neither is asked", defaults)
        self.assertNotIn("`init` writes `*` plus newline", entry)
        self.assertNotIn("Config CLI never edits ignores.", entry)
        self.assertNotIn(".gitignore", details)
        self.assertIn("Read when init creates configuration or detects schema v1 or v2: "
                      "[references/configuration-migration.md](references/configuration-migration.md).", entry)

    def test_initialization_routes_to_authoritative_ticket_target(self):
        reference = documentation(INITIALIZATION)
        flat = " ".join(reference.split())
        self.assertNotIn('publication currently require the target to be absent', flat)
        self.assertNotIn('including refusing an empty folder', flat)
        self.assertIn('There is no `--slug` option. Init does not create the feature folder; a fresh '
                      'run refuses an existing folder unless it contains exactly the `grilling/` directory.', flat)
        self.assertIn('Re-init with a different feature folder is refused, while the same folder remains idempotent after '
                      'interrupted or completed publication, without changing target or staging.', flat)
        links = re.findall(r'\[references/ticket-stage-details\.md\]\(([^)]+)\)', reference)
        self.assertEqual(len(links), 1)
        self.assertEqual((INITIALIZATION.parent / links[0]).resolve(), TICKET_STAGE.resolve())
        self.assertTrue(TICKET_STAGE.is_file())

    def test_short_integrity_summary_preserves_coverage_and_exclusions(self):
        summary = " ".join(documentation(INTEGRITY).split())
        self.assertIn(
            "The product-tree detector covers tracked changes, staged changes, untracked paths "
            "and their content (regular files up to the 8 MiB size cap and symlink target bytes), "
            "and HEAD movement.",
            summary,
        )
        self.assertIn(
            "It does not cover ignored product files or skipped untracked content "
            "(files above the size cap or unsupported types), or contents of unreadable "
            "untracked directories omitted by Git with a warning.",
            summary,
        )

    def test_run_artifact_and_product_tree_integrity_boundaries_are_documented(self):
        text = normalized(INTEGRITY)
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
        ):
            self.assertIn(required, text)
        for required in (
            "unexpected files",
            "never attached implicitly",
        ):
            self.assertIn(required, normalized(PLANNING))
        for required in (
            "before run-state schema 3",
            "human decision to restart",
            "separately reviewed migration procedure",
        ):
            self.assertIn(required, normalized(CONFIGURATION_COMPATIBILITY))

    def test_status_commands_routes_to_configuration_compatibility(self):
        raw = PLANNING.read_text(encoding="utf-8")
        routes = [route for route in ON_DEMAND.finditer(raw)
                  if route.group(1) == "status-commands.md"]
        self.assertEqual(len(routes), 1)
        self.assertIn("resuming a run, recovering context, or inspecting status", routes[0].group())
        pointer = (
            "Read when inspecting configuration acceptance fields or opening a legacy run: "
            "[references/configuration-compatibility.md](configuration-compatibility.md)."
        )
        self.assertIn(pointer, documentation(STATUS_COMMANDS))
        links = re.findall(r'\[references/configuration-compatibility\.md\]\(([^)]+)\)', documentation(STATUS_COMMANDS))
        self.assertEqual(len(links), 1)
        self.assertEqual((STATUS_COMMANDS.parent / links[0]).resolve(), CONFIGURATION_COMPATIBILITY.resolve())
        self.assertTrue(CONFIGURATION_COMPATIBILITY.is_file())
        self.assertNotIn("configuration-compatibility.md", raw)
        self.assertNotIn("`configuration_created_and_accepted`", documentation(PLANNING))

    def test_recovery_references_own_extension_and_old_layout_rules(self):
        entry = " ".join(PLANNING.read_text(encoding="utf-8").split())
        recovery = " ".join(documentation(STATUS_RECOVERY).split())
        extension = (
            'For the one extension, pass `--deadline-minutes <additional-minutes> '
            '--deadline-reason "<recorded reason>"`; the watcher records the reason and grants '
            'that duration from the later of the existing deadline and extension arm.'
        )
        self.assertIn("`resume --decision extend` watcher extension. " + extension, recovery)
        self.assertNotIn("For the one extension,", entry)
        old_layout = (
            'Older layouts permit `status` only; continuation refuses “unsupported legacy layout”. '
            'Restart after inspection.'
        )
        self.assertIn(old_layout, " ".join(documentation(CONFIGURATION_COMPATIBILITY).split()))
        self.assertNotIn("Older layouts permit", entry)
        self.assertIn(
            'Both deadlines are persisted on first arm in a `worker.waiting` event, keyed to the '
            'current launch IDs and stage/pass or round. Every invocation computes the remaining time; '
            're-arming, including after a host timeout, never moves either deadline. Initial '
            '`--deadline-minutes` overrides the minimum for a bounded smoke run. '
            'Repeating the same extension is idempotent; a second extension is refused. '
            'The start window is not extended by this flag. A recorded exit-9 recovery '
            '(`respond` or screen-confirmed `mark-started`) or `deliver` creates a new first-arm window '
            'without spending the extension; merely observing, assessing, or re-arming does not. '
            'New launch IDs also start new windows. Never run two watchers for the same work concurrently.',
            entry,
        )

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

    def test_valid_schema_v3_configuration_needs_no_question(self):
        if README.is_file():
            for required in (
                "a schema-v3 file needs no migration question",
                "needs no start confirmation",
            ):
                self.assertIn(required, normalized(README))
        for guide in SIBLINGS:
            text = normalized(guide)
            for required in (
                "a schema-v3 file needs no migration question",
                "needs no start confirmation",
                "never offer profile overrides the human did not ask for",
            ):
                with self.subTest(guide=guide.relative_to(REPOSITORY), required=required):
                    self.assertIn(required, text)

    def test_frozen_slug_gates_and_optional_contract_flags_are_documented(self):
        frozen_slug = "`tracker.slug` must equal the frozen `tracker_slug`"
        for path in (PLANNING, PLANNING.parent / "references/spec-contract.md"):
            with self.subTest(path=path):
                paragraphs = [
                    paragraph
                    for paragraph in (
                        " ".join(raw.split()).lower()
                        for raw in path.read_text(encoding="utf-8").split("\n\n")
                    )
                    if frozen_slug in paragraph
                ]
                self.assertEqual(len(paragraphs), 1, "expected one frozen-slug paragraph")
                text = paragraphs[0]
                self.assertIn(frozen_slug, text)
                self.assertIn("at author, review, approval, and publication gates", text)
                for command in ("proposal", "author-report", "review-report"):
                    self.assertIn(f"`{command}`", text)
                self.assertIn("optional `--tracker-slug`", text)

    def test_untracked_upgrade_and_visibility_limits_are_documented(self):
        self.assertIn("pre-change untracked baselines must restart after upgrading", normalized(INTEGRITY))
        self.assertIn("git only warns about an unreadable untracked directory, so its contents stay invisible", normalized(INTEGRITY))

    def test_migration_guidance_output_stream_contract_is_documented(self):
        # Named siblings rather than the glob, so an independent installation alongside unrelated
        # cmux-* skills still checks every guide that ships this contract.
        for guide in SIBLINGS:
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
        guide = documentation(PLANNING)
        readme = README.read_text(encoding="utf-8")
        normalized_guide = " ".join(guide.split())
        for required in (
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
            "cmux-issue-chain",
        ):
            self.assertIn(required, normalized_guide)
        for required in (
            "`configuration_created_and_accepted`",
            "`configuration_created_or_migrated_and_accepted`",
            "without rewriting the run merely because it was read",
            "conflicting values are rejected",
        ):
            self.assertIn(required, normalized(CONFIGURATION_COMPATIBILITY))
        installation = " ".join(documentation(PLANNING.parent / "references/installation.md").split())
        for required in ("## Prerequisites and installation", "contact no model provider"):
            self.assertIn(required, installation)
        self.assertIn("They form an optional progression, not a mandatory pipeline", readme)
        self.assertIn("No workflow automatically invokes another", readme)
        self.assertNotIn("first vertical slice currently ends", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
