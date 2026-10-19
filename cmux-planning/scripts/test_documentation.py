#!/usr/bin/env python3

from __future__ import annotations

import unittest
import ast
import re
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
                for phrase in (" init ", "## run briefing", "## run recap", "run_commit.py propose",
                               "run_commit.py commit", "run_in_background: true", "persisted on first arm"):
                    self.assertIn(phrase, text)
                for heading in self.NORMAL_HEADINGS[guide.parent.name]:
                    self.assertIn(heading, text)


def notice(text: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith(NOTICE_MARKER)]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one coordinated-upgrade notice, found {len(lines)}")
    return lines[0]


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

    def test_quiz_answers_route_to_approval_ticket_revision_or_spec_revision(self):
        for phrase in (
            "only when all three answers are positive (fits, correct, no change), ask for the target path",
            "--decision approve --reason <human-reason> --target <repo-relative-or-absolute-target>",
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

    def test_shared_root_and_legacy_documentation(self):
        if not README.is_file():
            self.skipTest("repository README is absent")
        for guide in (README, PLANNING):
            text = documentation(guide)
            self.assertIn(".scratch/orchestrator/runs/<run-id>/", text)
            self.assertIn("deliverables", text)
            for line in text.splitlines():
                if "planning-runs" in line:
                    self.assertIn("legacy", line.lower())

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
                    "claude-fable-high",
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
        for phrase in ("targeted check commands for implement, simplify, and review:",
                       "test worker always runs the full canonical suite", "one after another",
                       "run_check.py", "byte-for-byte"):
            self.assertIn(phrase, commands)
        diff = self.section("### diff inspection at code-changing gates", "## canonical check commands")
        self.assertIn("evidence check", diff)

    def test_script_invocations_and_pane_guidance(self):
        self.assertNotIn("quick-check", self.text)
        scripts = self.text.split("## scripts", 1)[1]
        for phrase in ("run_check.py --artifact-dir", "--command",
                       "check_evidence.py --run-dir <run-dir> --stage <role> --pass <n> --report",
                       "evidence check passed"):
            self.assertIn(phrase, scripts)

    def test_references_describe_evidence_and_citations(self):
        followup = normalized(self.references / "follow-up-pass.md")
        for phrase in ("cite-before, run-after", "most recent stage with green evidence",
                       "same starting tree", "normally test", "own after-run"):
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
        for phrase in ("- cited: artifacts/", "run_check.py", "byte-for-byte",
                       "relative to the run directory"):
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
                       "never on resume", "re-init", "exit-3", "smoke tests", "40 characters",
                       "immutable", "legacy", "english language name"):
            self.assertIn(phrase, language)
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
        brief = normalized(PLANNING.parent / "references" / "conversation-brief.md")
        for phrase in ("complete brief as its own message", "askuserquestion", "single-select",
                       "human's language", "first and recommended", "did not state",
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
            "a relaunch reason consists of the human's answer plus the reviewer findings, "
            "without additions by the orchestrator.",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_entrypoint_states_integrity_boundary_once(self):
        text = " ".join(PLANNING.read_text(encoding="utf-8").split())
        for phrase in ("skipped untracked content", "8 MiB", "artifact manifest",
                       "never recaptured against different product-tree bytes"):
            self.assertEqual(text.count(phrase), 1, phrase)

    def test_planning_start_sequence_and_recovery_safety(self):
        text = normalized(PLANNING)
        procedure = text.split("## run one stage", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
        commands = ("render_prompt.py", "tree_integrity.py baseline", "pane_ctl.py launch",
                    "pane_ctl.py start-agent", "await_report.py")
        positions = [procedure.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("pane_ctl.py deliver", procedure)
        self.assertNotIn("pane_ctl.py observe", procedure)
        for phrase in ("| 9 | assignment not started", "after exit 9, take one `observe` and `assess`",
                       "then re-arm without re-delivery", "one readiness-gated `deliver --prompt`",
                       '`evidence: "screen"`', "exception-path and follow-up only",
                       "`--extension 0`", "interrupted launch or delivery input stops at hitl",
                       "report deadline counts from the persisted first arm", "never immutable manifest artifacts"):
            self.assertIn(phrase, text)

    def test_short_integrity_summary_preserves_coverage_and_exclusions(self):
        text = documentation(PLANNING)
        start = "- Two explicit integrity boundaries apply."
        end = "\n- Every worker emission"
        self.assertIn(start, text)
        self.assertIn(end, text)
        summary = " ".join(text.split(start, 1)[1].split(end, 1)[0].split())
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
        self.assertIn("pre-change untracked baselines must restart after upgrading", normalized(PLANNING))
        self.assertIn("git only warns about an unreadable untracked directory, so its contents stay invisible", normalized(PLANNING))

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
