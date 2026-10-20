#!/usr/bin/env python3
"""Render deterministic spec-author and independent-reviewer work orders."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from artifact_manifest import (
    ArtifactIntegrityError,
    current_attempt,
    find_attempt_entry,
    record_artifact,
    verify_entry,
    verify_or_gate,
)
from orchestrator_lib import (
    STAGES,
    atomic_write,
    read_planning_state,
    sha256_bytes,
    sha256_file,
    write_json,
)
from planning_inputs import INLINE_SOURCES, manifest_kind, original_display, planning_inputs
from planning_recovery import DEFAULT_ARTIFACT_LANGUAGE
from spec_contract import SPEC_SECTIONS
from stage_snapshot import SnapshotError, approved_spec_from_state, load_prepared_snapshot
from tracker_contract import EXECUTION_LABELS, validate_proposal

DETECTOR_BOUNDARY = """The detector covers tracked changes, staged changes, untracked paths and their content (regular files
up to the 8 MiB size cap and symlink target bytes), and commits (HEAD movement). It excludes ignored
files and skipped untracked content (files above the size cap or unsupported types). It also excludes
contents of unreadable untracked directories that Git omits with a warning. Git-ignored run
handoff artifacts are gated by digest instead."""

INDEX_HEAD_PROHIBITION = 'Never run `git add`, `git rm --cached`, `git stash`, `git commit`, `git reset`, or any other command that changes the index or HEAD; staging and committing happen after the run, outside the worker.'


REPORT_HANDOFF_STEP = """Write the report to the report handoff path only once, as your final action,
with exactly the validated bytes of the report draft, after every other file is complete. Never
write a provisional report there and never touch it again: the orchestrator may capture it at any
moment, and a report changed after capture fails the handoff. If validation cannot complete,
report the failure honestly in that single write instead of claiming a validated handoff."""


REVIEW_HANDOFF_CONTRACT = f"""Empty sections are machine-readable sentinels: their entire body must be
exactly `- None`, with no period, explanation, second bullet, or trailing paragraph. For `pass`,
this applies to Findings, Corrections, Blockers, and Plan Drift; for `pass_with_fixes`, Blockers and
Plan Drift must remain exactly `- None`. Put explanatory context in Methods, not after a sentinel.
For example, `- None. The proposal remains unchanged.` is invalid.

Write the report to the report draft first and run the self-validation command below on it.
Inspect its exit code and output.
Exit 0 validates `pass` or `pass_with_fixes`; exit 2 with `"gate": "blocked"` validates `blocked` and
is a complete handoff, not a failure. Exit 1 means the report draft or candidate is malformed: fix it
within your write boundary and rerun until it validates. Never remove a real finding, blocker, or drift
merely to pass validation; use the appropriate verdict. Any subsequent report draft or candidate edit
invalidates that check and requires another run. Claim successful self-validation only for the
exact bytes handed off.

{REPORT_HANDOFF_STEP}"""


# Named from the enforced list, so a prompt can never instruct a section set the gate rejects.
SPEC_CONTRACT = f"""The draft must contain non-empty `##` sections named exactly:
{", ".join(SPEC_SECTIONS[:-1])}, and {SPEC_SECTIONS[-1]}. User Stories must contain at least one
list item. Under Testing Decisions include entries containing
`Existing seam:`, `Prior-art test:`, and `Verification:`. If proposing a `New seam:`, also include
`Justification:`. Use exactly `- None` when there are no open decisions; a reviewed candidate must
have no open decisions."""


PATH_FREEDOM_EXCEPTION = (
    "Handover locations may be named by path: artifacts one ticket produces and another reads, "
    "and the tracker's documentation folder. Prescribed commands whose flags carry the safety "
    "of a step may be stated verbatim."
)

PATH_REVIEW_PRESERVATION = (
    "When removing ordinary file paths, keep exempt handover locations and "
    "safety-carrying commands verbatim."
)


# Adapted from mattpocock/skills to-spec, pinned in the planning-to-spec design document.
SPEC_TEMPLATE = f"""<spec-template>
## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A LONG, numbered list of user stories. Each user story should be in the format of:

1. As an <actor>, I want a <feature>, so that <benefit>

<user-story-example>
1. As a mobile bank customer, I want to see balance on my accounts, so that I can make better informed decisions about my spending
</user-story-example>

This list of user stories should be extremely extensive and cover all aspects of the feature.
Translate the actor, want, benefit pattern into the artifact language; for German:
"Als <Rolle> möchte ich <Funktion>, damit <Nutzen>". The reviewer checks structure and coverage;
the validator only requires a list item, not a language-specific story form.

## Implementation Decisions

A list of implementation decisions that were made. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Include only decisions established by plan files, the confirmed brief, revalidated grilling input,
or necessarily imposed by the repository's current behavior. Put your own inferences in Assumptions,
with their basis, and unresolved choices in Open Decisions. Do not present an inference as a decision.

Do NOT include ordinary file paths or code snippets. They may end up being outdated very quickly.
{PATH_FREEDOM_EXCEPTION}
Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can
(state machine, reducer, schema, type shape), inline it within the relevant decision and note briefly
that it came from a prototype. Trim to the decision-rich parts, not a working demo, just the important bits.

## Testing Decisions

A list of testing decisions that were made. Include:

- A description of what makes a good test (only test external behavior, not implementation details)
- Which modules will be tested
- Prior art for the tests (i.e. similar types of tests in the codebase)

Use `Existing seam:`, `Prior-art test:`, and `Verification:` entries. Name seams, modules, and tests
by name and behavior, never by file path. For `New seam:`, add `Justification:` explaining why
existing seams cannot cover the behavior and why this is the highest useful new seam.

## Assumptions

[AFK addition] Your own conclusions, each with its evidence or basis. Keep these distinct from
established Implementation Decisions. Use `- None` if there are no assumptions.

## Open Decisions

[AFK addition] For each unresolved choice, state the question, context, options, recommendation
when supported by evidence, and why it remains open. Do not interview the user or invent a decision.
Use exactly `- None` if there are no open decisions.

## Out of Scope

A description of the things that are out of scope for this spec.

## Further Notes

Any further notes about the feature. Preserve literal product copy and domain terms in their actual
language throughout the specification.
</spec-template>"""


STATE_AND_RECOVERY_CHECK = """## State and Recovery Check

<state-and-recovery-check>
Require a recovery point before every state-changing operation the spec prescribes, such as migrations, data changes, deployments, and cleanups; the delivered feature's runtime writes are not such operations.
Check that the spec identifies
the recoverable state and how to restore it before the operation begins.
Check the ordering of snapshots relative to baselines and references: capture recoverable state
before mutations and establish each baseline or reference before the steps that depend on it.
Account for side effects of prescribed commands, including hooks, scripts, and providers;
include their state changes in the recovery and ordering checks.
Check that gates stay consistent with the steps they guard, including prerequisites, approval
conditions, and recovery steps. Record these checks within the existing spec sections and review;
do not add a spec section or an extra review round.
</state-and-recovery-check>"""


def spec_language(state: dict) -> str:
    return f"""Artifact language: {state.get('artifact_language', DEFAULT_ARTIFACT_LANGUAGE)}
Write specification content in this language, including the actor, want, benefit story pattern.
Machine-readable section headings, testing markers, and the `- None` sentinel stay exactly as
written in the template.
Reports retain their prescribed English headings and sentinel values."""


def spec_template_section(state: dict) -> str:
    return f"""## Specification Template and Language

{spec_language(state)}

{SPEC_TEMPLATE}"""


def script_path(name: str) -> str:
    """Absolute: the worker's cwd is the target repository, not the orchestrator's, and a
    cwd-relative path would also make the deterministic prompt bytes depend on where the
    orchestrator happened to stand."""
    return str(Path(__file__).resolve().parent / name)


def contract_path() -> str:
    return script_path("spec_contract.py")


def tracker_contract_path() -> str:
    return script_path("tracker_contract.py")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--pass", dest="pass_num", type=int, required=True)
    parser.add_argument("--out")
    return parser


def fenced_content(content: str, language: str) -> str:
    """Use a fence longer than any backtick run so embedded fences cannot close it."""
    longest = max(map(len, re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{content.rstrip()}\n{fence}"


def normalized_context(run_dir: Path, state: dict) -> str:
    pointer = state.get("normalized_grilling_input")
    if not pointer:
        return "No normalized grilling input was supplied."
    path = run_dir / pointer["path"]
    verify_entry(
        state,
        run_dir,
        pointer.get("manifest_id", ""),
        expected_kind="normalized-grilling-input",
        expected_path=pointer["path"],
    )
    payload = path.read_bytes()
    if sha256_bytes(payload) != pointer["sha256"]:
        raise SnapshotError("normalized grilling input changed after revalidation")
    return (
        "Consume only this complete human-revalidated handoff; do not use or recover the copied "
        f"source pair: `{path}`\n\n{fenced_content(payload.decode('utf-8'), 'json')}"
    )


def resumed_context(run_dir: Path, state: dict, stage: str, pass_num: int) -> str:
    recovery = state.get("resume_context")
    revision = not isinstance(recovery, dict)
    if revision:
        recovery = state.get("revision_context")
    if not isinstance(recovery, dict):
        return ""
    target = recovery.get("to_stage")
    if not isinstance(target, str):
        return ""
    review_stage = target if target.endswith("-review") else f"{target}-review"
    if (stage, pass_num) not in {
        (target, recovery.get("to_pass")),
        (review_stage, recovery.get("to_review_pass")),
    }:
        return ""
    reviewer = stage.endswith("-review")
    context_name = "revision context" if revision else "resume context"
    blocks = ["## Revision Review Context"] if revision else [
        "## Interrupted-Pass Recovery Context",
        f"Human resume reason: {recovery.get('reason', '')}",
        (
            f"Recovery route: {recovery.get('from_stage')}-{recovery.get('from_pass')} -> "
            f"{recovery.get('to_stage')}-{recovery.get('to_pass')}"
        ),
    ]
    for item in recovery.get("prior_handoffs", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise SnapshotError(f"{context_name} contains a malformed prior handoff")
        path = Path(item["path"]).resolve()
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as error:
            raise SnapshotError(f"{context_name} points outside this planning run") from error
        if not isinstance(item.get("manifest_id"), str):
            raise SnapshotError(f"{context_name} handoff has no immutable manifest identity")
        entry = verify_entry(
            state,
            run_dir,
            item["manifest_id"],
            expected_path=path,
        )
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise SnapshotError(f"{context_name} handoff is missing or changed: {path}")
        block = f"### {item.get('label', 'Prior handoff')}\n\n`{path}` (sha256 `{item['sha256']}`)"
        if revision:
            block += f" (manifest `{item['manifest_id']}`)"
        if not reviewer and stage != "spec" and not (stage == "tickets" and entry["kind"] == "tickets-summary"):
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeError as error:
                raise SnapshotError(f"{context_name} handoff is not UTF-8: {path}") from error
            block += f"\n\n{fenced_content(content, 'text')}"
        blocks.append(block)
    if stage == "spec" and recovery.get("prior_handoffs"):
        blocks.append("Read each prior handoff from its path and verify its sha256 before revising.")
    return "\n\n".join(blocks)


def report_draft_path(paths: dict) -> str:
    return str(Path(paths["started"]).parent / "report-draft.md")


def first_step(marker: str) -> str:
    return f"""## First Step

Before anything else, use the harness's file-writing tool to create or overwrite
`{marker}` (create its parent directory if necessary). Rewrite an existing marker
so its modification time is refreshed, then execute this assignment.
"""


def verified_inputs(run_dir: Path, state: dict) -> list[tuple[dict, Path]]:
    verified = []
    for item in planning_inputs(state):
        path = run_dir / item["path"]
        entry = verify_entry(state, run_dir, item.get("manifest_id", ""),
                             expected_kind=manifest_kind(state, item), expected_path=path)
        if entry["sha256"] != item["sha256"]:
            raise SnapshotError(f"planning input pointer digest changed: {path}")
        verified.append((item, path))
    return verified


def input_context(state: dict, inputs: list[tuple[dict, Path]], *, inline: bool) -> str:
    blocks = []
    for item, path in inputs:
        block = (f"- {item['kind']}: `{original_display(state, item)}`; "
                 f"run copy: `{path.resolve()}` (sha256 `{item['sha256']}`)")
        if inline:
            block += f"\n\n{fenced_content(path.read_text(encoding='utf-8'), 'text')}"
        blocks.append(block)
    if inline and any(item["original_path"] not in INLINE_SOURCES and item["kind"] != "conversation-brief"
                      for item, _ in inputs):
        blocks.append("You may read neighboring files at the original paths as unpinned context.")
    return "\n\n".join(blocks)


INPUT_PRECEDENCE = (
    "An explicit decision in the brief takes precedence over revalidated grilling decisions, "
    "which take precedence over plan files. Contradictions between plan files or without an "
    "explicit decision belong under `Open Decisions`."
)


def author_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    paths = snapshot["allowed_worker_writes"]
    feedback = state.get("spec_revision_feedback") or "None recorded for this specification pass."
    return f"""# Planning Worker Prompt: specification author (pass {pass_num})

{first_step(paths['started'])}
Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']}

Synthesize the supplied context into a repository-grounded specification. Do not interview the user.
When information is genuinely missing, record it under `Open Decisions` instead of guessing.

## Process

1. Explore the repo to understand the current state of the codebase. Use the project's domain glossary vocabulary
   throughout the spec, and respect any ADRs in the area you're touching. Inspect source, local docs,
   history, and existing tests as needed.
2. Sketch out the seams at which you're going to test the feature. Prefer existing seams to new ones.
   Use the highest useful seam possible. If new seams are needed, propose them at the highest point
   you can. The fewer seams across the codebase, the better; the ideal number is one. Record the
   proposed seams in your report for the human approval walkthrough; do not create a separate seam gate.
3. Write the spec using the template below and the supplied inputs. Do not publish it yourself.
   No file paths or code snippets in the spec, except the handover locations, safety-carrying commands,
   and narrowly defined prototype snippet allowed by the template below.
   Name modules, tests, and seams by name and behavior. Paths and line references belong in the
   author report under `Repository Sources / Methods`.

## Persisted Task

{input_context(state, verified_inputs(run_dir, state), inline=True)}

## Optional Revalidated Grilling Context

{normalized_context(run_dir, state)}

{INPUT_PRECEDENCE}

## Human Specification Revision Feedback

{feedback}

{resumed_context(run_dir, state, "spec", pass_num)}

## Specification Contract

{SPEC_CONTRACT}

{spec_template_section(state)}

{STATE_AND_RECOVERY_CHECK}

## Write Boundary

{INDEX_HEAD_PROHIBITION}

You may inspect the repository read-only. Physically write only these exact files:

- Complete draft: `{paths['draft']}`
- Started marker: `{paths['started']}`
- Report draft for self-validation: `{report_draft_path(paths)}`
- Structured report: `{paths['report']}`

Do not edit product code, configuration, lifecycle state, prompts, snapshots, or any other path. The
orchestrator compares complete Git status plus tracked and staged diffs before and after your stage.
{DETECTOR_BOUNDARY}

## Report Contract

Write all sections exactly once. A clean result is `PASS`; use `BLOCKED` only for a real blocker.

```markdown
## Result
PASS

## Repository Sources / Methods
- `path or git method`: concrete relevance

## Proposed Test Seams
- seam, prior-art test, and external behavior

## Blockers
- None

## Plan Drift
- None

## Draft Path
`{paths['draft']}`
```

Write the report to the report draft first and self-validate it (skip the first command for
`BLOCKED`, which has no complete draft). Fix the report draft and rerun until both pass:

```bash
python3 {contract_path()} spec {paths['draft']}
python3 {contract_path()} author-report {report_draft_path(paths)} --draft {paths['draft']}
```

{REPORT_HANDOFF_STEP}
"""


def review_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    author = state.get("author_spec")
    if not isinstance(author, dict):
        raise SnapshotError("review prompt requires the validated author handoff")
    draft = Path(author["draft"]).resolve()
    verify_entry(
        state,
        run_dir,
        author.get("draft_manifest_id", ""),
        expected_kind="spec-draft",
        expected_path=draft,
    )
    author_report = Path(author["report"]).resolve()
    verify_entry(
        state,
        run_dir,
        author.get("report_manifest_id", ""),
        expected_kind="worker-report",
        expected_path=author_report,
    )
    paths = snapshot["allowed_worker_writes"]
    inputs = verified_inputs(run_dir, state)
    return f"""# Planning Worker Prompt: independent specification review (pass {pass_num})

{first_step(paths['started'])}
Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']}

Review independently in this fresh pane. Do not trust the author's summary: inspect the target repository
read-only where useful. Check the persisted task, optional normalized grilling decisions, repository evidence,
the complete draft, and the contract below.

## Inputs and Identity

{input_context(state, inputs, inline=False)}
- Author report: `{author_report}`
- Draft: `{draft}` (sha256 `{author['draft_sha256']}`)

### Persisted Task

{input_context(state, inputs, inline=True)}

### Optional Revalidated Grilling Context

{normalized_context(run_dir, state)}

{INPUT_PRECEDENCE}

### Author Report

{fenced_content(author_report.read_text(encoding='utf-8'), 'markdown')}

{resumed_context(run_dir, state, "spec-review", pass_num)}

## Specification Contract

{SPEC_CONTRACT}

{spec_template_section(state)}

{STATE_AND_RECOVERY_CHECK}

Check Problem Statement and Solution from the user's perspective, story structure and coverage in
the artifact language, no file paths or code snippets (except the documented handover-location,
safety-carrying-command, and prototype exceptions),
seam minimalism (prefer existing seams, the highest useful seam, as few as possible, ideally one;
new seams at the highest useful point), and decision/assumption separation. Check that every
Implementation Decision comes from the inputs or is necessarily imposed by the repository;
the author's own conclusions must be Assumptions with their basis.
{PATH_REVIEW_PRESERVATION}
Removing file paths outside those exceptions or moving an author inference into Assumptions while
retaining established intent is `pass_with_fixes`. If an inference presented as a decision
requires a real product, scope, behavior, priority, or architecture decision, return `blocked`.

A missing recovery point before a production mutation the spec prescribes is a `blocked` finding.
Do not silently patch this gap with `pass_with_fixes` or overlook it; report it for the human.

No unresolved current-scope Open Decision may pass. A deferred decision passes only after the candidate
explicitly moves it to Out of Scope or a follow-up area.

Return exactly one verdict:

- `pass`: no change; reference the unchanged draft digest and do not write the candidate path.
- `pass_with_fixes`: correct only established-intent defects (contradictions, stale wording,
  cross-references, clearly implied traceability, structure, or acceptance-criterion clarity). Write the
  complete corrected candidate and a structured correction summary. No automatic model re-review follows.
- `blocked`: any correction needs a new or changed product, scope, behavior, priority, or architecture
  decision. State the decision needed and do not fabricate or write a candidate.

## Write Boundary

{INDEX_HEAD_PROHIBITION}

You may physically write only:

- Started marker: `{paths['started']}`
- Report draft for self-validation: `{report_draft_path(paths)}`
- Review report: `{paths['report']}`
- Complete corrected candidate only for `pass_with_fixes`: `{paths['candidate']}`

Do not edit the author draft, product code, lifecycle state, or any other path. The author draft is
digest-bound to its own gate, so rewriting it in place fails the review outright, and the mandatory
Git-visible before/after inspection gates unauthorized deltas outside the run directory.
{DETECTOR_BOUNDARY}

## Review Report Contract

{REVIEW_HANDOFF_CONTRACT}

`## Checked` must cover all input sections by their exact section names, with backtick-quoted
references and a stated check and outcome in every bullet. Missing or empty evidence is malformed.
`Checked` cannot be `- None`, including for `blocked`.
A quoted reference may contain colons, so `src/cli.py:42` is one reference. A `blocked` verdict is
the only exception to coverage: it still needs at least one structurally valid evidence bullet and
a substantive blocker, but only for what the review actually reached.

```markdown
## Verdict
pass

## Findings
- None

## Checked
- `<reference>`: <what was checked>: <outcome>

## Methods
- repository source/test/history checked independently

## Input Identity
sha256 {author['draft_sha256']}

## Resulting Candidate Identity
sha256 {author['draft_sha256']}

## Corrections
- None

## Blockers
- None

## Plan Drift
- None
```

Self-validate before handoff (the candidate path may be absent for `pass` or `blocked`):

```bash
python3 {contract_path()} review-report {report_draft_path(paths)} \\
  --input {draft} --candidate {paths['candidate']}
```
"""


VERTICAL_SLICE_POLICY = """Each slice cuts a narrow but COMPLETE path through every layer needed for
its behavior (schema, API, UI, tests). Each ticket must state one complete user-observable delivered
behavior, include stable acceptance criteria, and be independently demonstrable or verifiable.
For normal vertical slices only: Never decompose by frontend, backend, database, tests,
directories, file types, or worker specialties. Use suitability for one fresh worker context only as
a qualitative boundary; never write token counts or estimates into the proposal. Evaluate merge
opportunities as explicitly as split points: merge only work sharing one outcome, verification story,
and substantially the same context; split independent outcomes, decision boundaries, rollout
requirements, or excessive context. More than six acceptance criteria is a soft size limit: split such
a ticket, or justify in `merge_split_rationale` why its one outcome stays whole. Add only blocking edges whose prerequisite genuinely prevents
the blocked ticket from starting, leaving every initially ready ticket visible in the frontier.

A ticket of any slice type creating rules, conventions, or configuration for agents blocks every
AFK ticket that works under those rules.

Look for prefactoring: "make the change easy, then make the easy change." Create a standalone ticket
when it prepares several slices or is substantial; otherwise make it the first step of its slice.
A standalone prefactor uses `slice_type: prefactor` and `wide_refactor: null`, comes before and blocks
the benefiting slices. Its `delivered_behavior` describes preserved behavior and what it simplifies
for the following slices. Verify it with existing tests. This is the only exception to describing delivered behavior from the user's perspective, apart from
the mechanical tickets of a wide refactor.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change (rename a column, retype a shared symbol) whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a ticket blocked by every migrate batch. When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify ticket; green is promised only there."""


PUBLICATION_LABEL_RULE = (
    f"Only fully specified approved work is published: AFK tickets with {EXECUTION_LABELS['AFK']} "
    f"and HITL tickets with {EXECUTION_LABELS['HITL']}"
)


def ticket_ground_rules(state: dict) -> str:
    return f"""- Artifact language: {state.get('artifact_language', DEFAULT_ARTIFACT_LANGUAGE)}. Write ticket content in this language:
  `title`, `delivered_behavior`, `acceptance_criteria`, `merge_split_rationale`, and `tracker.title`.
  Preserve literal product copy and domain terms in their original language.
- Keep headings, markers, JSON keys, `technical_layers`, fixed labels, frontmatter values, and worker
  reports in English; preserve the native contract's exact structure and machine-readable values.
- Ticket titles, `delivered_behavior` (What to build), and acceptance criteria contain no file paths or code snippets.
  {PATH_FREEDOM_EXCEPTION}
  A prototype snippet is also allowed when it encodes a decision more precisely than prose:
  note its prototype origin and trim it to the decision-rich parts, rather than a working demo.
  `canonical_check_commands` may contain paths.
- Describe end-to-end behavior from the user's perspective, not a layer-by-layer implementation list,
  except for the standalone prefactor and wide-refactor tickets described in the vertical-slice policy.
- Number tickets in dependency order: every blocker must have a smaller numeric ID than its dependent.
- Record the target repository's current working branch and exact runnable baseline check commands.
- {PUBLICATION_LABEL_RULE}.
- The published tracker must contain README.md, spec.md, map.md, decisions.md, and one native issue file
  per complete proposed ticket under issues/."""


HUMAN_TICKET_POLICY = """Choose execution_mode deliberately for every ticket. Cut human steps such as
production pulls, deployments, and approvals as their own HITL tickets, with genuine blocking edges
to the work they enable or depend on; do not bury human steps in prose inside AFK tickets.
Check every ticket for over-HITL (a human ticket an agent could complete) and under-HITL (an AFK
ticket containing a human step). Keep work an agent can complete AFK; reserve HITL for work requiring
human action or authority. A HITL ticket contains only human steps; agent work it needs becomes its
own AFK ticket that blocks it. An AFK ticket that mutates a database states that the mutation runs
only in its implement pass, never in simplify, test, or review passes."""


NATIVE_TRACKER_POLICY = f"""The machine proposal uses schema version 2 with exactly four top-level keys:
`schema_version`, `source_spec`, `tracker`, and `tickets`. `source_spec` contains exact `path` and
`sha256`. `tracker` contains lowercase kebab-case `slug`, non-empty `title`, `working_branch`, and a
non-empty list of exact runnable `canonical_check_commands`. `tracker.slug` must equal the
Tracker slug (fixed) value under Inputs and Identity. Every ticket contains exactly `id` in
ISSUE-NNN form, `title`, `delivered_behavior`, non-empty `acceptance_criteria`, `blocked_by`,
`merge_split_rationale`, `slice_type`, non-empty `technical_layers`, `wide_refactor`, and required
`execution_mode`, whose value is `AFK` or `HITL`. A normal ticket
uses `slice_type: vertical` and `wide_refactor: null`. A standalone prefactor uses
`slice_type: prefactor` and `wide_refactor: null`. A wide-refactor ticket uses
`slice_type: wide-refactor` and an object with `phase`, `sequence: expand-migrate-contract`, and
`integration_reason` (null except for a justified integration exception). `phase` is `expand`, `migrate`,
`contract`, or `integration`: every migrate ticket is blocked by an expand ticket, every contract ticket by
every migrate ticket, and the integrate-and-verify ticket uses phase `integration` and is blocked by a
contract ticket. IDs are unique, blockers must
exist, every blocker must have a smaller numeric ID than its dependent, and dependencies must be
acyclic. {PUBLICATION_LABEL_RULE}; no adoption conversion is used."""


def tickets_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    approved_spec, spec_digest = approved_spec_from_state(state, run_dir=run_dir)
    paths = snapshot["allowed_worker_writes"]
    tracker_slug = state["tracker_slug"]
    feedback = state.get("ticket_revision_feedback") or "None recorded for this tickets pass."
    return f"""# Planning Worker Prompt: tickets author (pass {pass_num})

{first_step(paths['started'])}
Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']}

Turn the immutable approved specification into a native executable tracker proposal. Work in this fresh
pane without recovering or inheriting either specification worker session. Inspect the target repository
read-only for current branch, exact runnable checks, implementation context, terminology, and prior-art
tests. Do not make product or scope decisions that the approved specification did not make.

## Process

1. Read the approved specification in full, including its decisions and scope boundaries.
2. Explore the repository read-only: use domain glossary vocabulary, ADRs, existing tests, and
   prefactoring opportunities to ground the breakdown (make the change easy, then make the easy change).
3. Draft slices: apply the vertical-slice policy below, look for merge and split opportunities, and
   describe each delivered behavior from the user's perspective.
4. Set blocking edges: include only genuine prerequisites, put prefactoring first, and assign IDs in
   dependency order so every blocker has a smaller number. Expose all initially ready tickets.

## Inputs and Identity

{input_context(state, verified_inputs(run_dir, state), inline=False)}
- Approved specification: `{approved_spec}` (sha256 `{spec_digest}`)
- Tracker slug (fixed): `{tracker_slug}`
- Repository: `{state['repository']}`

### Approved Specification

{fenced_content(approved_spec.read_text(encoding='utf-8'), 'markdown')}

### Human Ticket Revision Feedback

{feedback}

{resumed_context(run_dir, state, "tickets", pass_num)}

## Tracker Ground Rules

{ticket_ground_rules(state)}

## Vertical-Slice Policy

{VERTICAL_SLICE_POLICY}

## Human Work Boundaries

{HUMAN_TICKET_POLICY}

## Native Proposal Contract

{NATIVE_TRACKER_POLICY}

Write the complete machine proposal first, then generate the exact numbered human summary with the
vendored contract command. The summary contains every ticket's title, delivered behavior, acceptance
criteria, blockers, and merge/split rationale.

## Write Boundary

{INDEX_HEAD_PROHIBITION}

You may physically write only these exact files:

- Machine-readable proposal: `{paths['proposal']}`
- Human-readable numbered summary: `{paths['summary']}`
- Started marker: `{paths['started']}`
- Report draft for self-validation: `{report_draft_path(paths)}`
- Structured report: `{paths['report']}`

Do not edit the approved spec, product code, configuration, lifecycle state, or any other path. Mandatory
before/after Git-visible inspection gates every other delta within the documented detector boundary.
{DETECTOR_BOUNDARY}

## Report Contract

```markdown
## Result
PASS

## Repository Sources / Methods
- `path or git method`: concrete relevance

## Source Spec Identity
sha256 {spec_digest}

## Ticket Count
1

## Ready Frontier
- ISSUE-001

## Blockers
- None

## Plan Drift
- None

## Proposal Paths
- `{paths['proposal']}`
- `{paths['summary']}`
```

Use `BLOCKED` only for a real blocker, and then state it under Blockers. Write the report to the report
draft first and self-validate a passing handoff, fixing the report draft and rerunning until it passes:

```bash
python3 {tracker_contract_path()} proposal {paths['proposal']} \\
  --spec {approved_spec} --spec-sha256 {spec_digest} --tracker-slug {tracker_slug}
python3 {tracker_contract_path()} render-summary \\
  --proposal {paths['proposal']} --out {paths['summary']}
python3 {tracker_contract_path()} author-report {report_draft_path(paths)} \\
  --proposal {paths['proposal']} --summary {paths['summary']} \\
  --spec {approved_spec} --spec-sha256 {spec_digest} --tracker-slug {tracker_slug}
```

{REPORT_HANDOFF_STEP}
"""


def tickets_review_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    approved_spec, spec_digest = approved_spec_from_state(state, run_dir=run_dir)
    author = state.get("author_tickets")
    if not isinstance(author, dict) or not author.get("proposal_sha256"):
        raise SnapshotError("tickets review prompt requires the validated tickets author handoff")
    proposal = Path(author["proposal"]).resolve()
    summary = Path(author["summary"]).resolve()
    verify_entry(
        state,
        run_dir,
        author.get("proposal_manifest_id", ""),
        expected_kind="tickets-proposal",
        expected_path=proposal,
    )
    verify_entry(
        state,
        run_dir,
        author.get("summary_manifest_id", ""),
        expected_kind="tickets-summary",
        expected_path=summary,
    )
    report = Path(author["report"]).resolve()
    verify_entry(
        state,
        run_dir,
        author.get("report_manifest_id", ""),
        expected_kind="worker-report",
        expected_path=report,
    )
    paths = snapshot["allowed_worker_writes"]
    tracker_slug = state["tracker_slug"]
    validate_proposal(
        proposal,
        expected_spec=approved_spec,
        expected_spec_sha256=spec_digest,
        expected_tracker_slug=tracker_slug,
    )
    return f"""# Planning Worker Prompt: independent ticket review (pass {pass_num})

{first_step(paths['started'])}
Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']}

Review independently in this fresh pane without either author session. Inspect the repository read-only
where useful. Check the task, immutable approved specification and its decisions, exact author proposal
and report identities, tracker ground rules, vertical-slice policy, human work boundaries, and native
tracker contract.

## Inputs and Identity

{input_context(state, verified_inputs(run_dir, state), inline=False)}
- Approved specification: `{approved_spec}` (sha256 `{spec_digest}`)
- Tracker slug (fixed): `{tracker_slug}`
- Machine proposal: `{proposal}` (sha256 `{author['proposal_sha256']}`)
- Human summary: `{summary}` (sha256 `{author['summary_sha256']}`)
- Author report: `{report}` (sha256 `{sha256_file(report)}`)

### Approved Specification and Decisions

{fenced_content(approved_spec.read_text(encoding='utf-8'), 'markdown')}

### Author Report

{fenced_content(report.read_text(encoding='utf-8'), 'markdown')}

{resumed_context(run_dir, state, "tickets-review", pass_num)}

## Tracker Ground Rules

{ticket_ground_rules(state)}

## Vertical-Slice Policy

{VERTICAL_SLICE_POLICY}

## Human Work Boundaries

{HUMAN_TICKET_POLICY}

## Native Tracker Contract

{NATIVE_TRACKER_POLICY}

Check each ticket for user perspective (with the standalone prefactor and wide-refactor exceptions),
no file paths or code snippets (except the documented handover-location, safety-carrying-command,
and prototype exceptions), prefactoring first, no horizontal slices, dependency-ordered IDs, and a deliberate
`execution_mode` without over-HITL or under-HITL. Verify the chosen
artifact language, glossary and ADR alignment, narrow but complete behavior, justified merges and splits,
existing-test verification for preserved prefactor behavior, and any wide-refactor sequence or integration
exception against these rules and repository evidence. Prefactors must precede and block benefiting slices.
Check that every ticket creating rules, conventions, or configuration for agents blocks all affected
AFK tickets.
For a ticket above the soft size limit whose `merge_split_rationale` does not justify keeping it whole,
return `blocked` with a concrete, reasoned split.
{PATH_REVIEW_PRESERVATION}

Return exactly one verdict:

- `pass`: no change; bind the unchanged proposal digest and do not write the candidate.
- `pass_with_fixes`: write one complete corrected machine proposal and a structured diff summary. You
  may repair contradictions, stale references, native structure, clearly implied acceptance-criterion
  traceability, wording clarity, or an unambiguous blocker representation only. Do not invent scope,
  behavior, priority, architecture, ticket boundaries, or dependencies.
- `blocked`: state the substantive ambiguity, dependency/ticket-boundary decision, or approved-spec
  defect. Do not write a candidate. Correcting an approved-spec defect requires the full spec author,
  spec review, spec approval, ticket author, and ticket review sequence again.

## Write Boundary

{INDEX_HEAD_PROHIBITION}

You may physically write only:

- Started marker: `{paths['started']}`
- Report draft for self-validation: `{report_draft_path(paths)}`
- Review report: `{paths['report']}`
- Complete corrected machine proposal only for `pass_with_fixes`: `{paths['candidate']}`

Mandatory before/after Git-visible inspection gates every other covered delta.
{DETECTOR_BOUNDARY}
Never edit the author proposal,
approved spec, product code, lifecycle state, or human summary.

## Review Report Contract

{REVIEW_HANDOFF_CONTRACT}

`## Checked` must cover all input ticket ids from the author proposal, with backtick-quoted
references and a stated check and outcome in every bullet. Missing or empty evidence is malformed.
`Checked` cannot be `- None`, including for `blocked`.
A quoted reference may contain colons, so `src/cli.py:42` is one reference. A `blocked` verdict is
the only exception to coverage: it still needs at least one structurally valid evidence bullet and
a substantive blocker, but only for the ticket ids the review actually reached.

```markdown
## Verdict
pass

## Findings
- None

## Checked
- `<reference>`: <what was checked>: <outcome>

## Methods
- repository source/test/history checked independently

## Input Identity
sha256 {author['proposal_sha256']}

## Resulting Candidate Identity
sha256 {author['proposal_sha256']}

## Corrections
- None

## Blockers
- None

## Plan Drift
- None
```

Self-validate before handoff (the candidate may be absent for `pass` or `blocked`):

```bash
python3 {tracker_contract_path()} review-report {report_draft_path(paths)} \\
  --input {proposal} --candidate {paths['candidate']} \\
  --input-sha256 {author['proposal_sha256']} \\
  --spec {approved_spec} --spec-sha256 {spec_digest} --tracker-slug {tracker_slug}
```
"""


def render(run_dir: Path, stage: str, pass_num: int) -> str:
    snapshot = load_prepared_snapshot(run_dir, stage, pass_num, require_baseline=False)
    state = read_planning_state(run_dir / "state.json")
    renderers = {
        "spec": author_prompt,
        "spec-review": review_prompt,
        "tickets": tickets_prompt,
        "tickets-review": tickets_review_prompt,
    }
    if stage not in renderers:
        raise SnapshotError(f"unknown planning stage: {stage}")
    return renderers[stage](run_dir, pass_num, snapshot, state)


def main() -> int:
    args = build_parser().parse_args()
    try:
        run_dir = Path(args.run_dir).resolve()
        state = verify_or_gate(run_dir, stage=args.stage)
        attempt = current_attempt(state, args.stage, args.pass_num)
        expected = Path(attempt["paths"]["prompt"])
        output = Path(args.out).resolve() if args.out else expected
        if output != expected:
            raise SnapshotError(f"prompt path substitution: expected {expected}, got {output}")
        payload = render(run_dir, args.stage, args.pass_num).encode("utf-8")
        existing = find_attempt_entry(state, "prompt", attempt["attempt_id"])
        if existing is not None:
            verified = verify_entry(
                state,
                run_dir,
                existing["id"],
                expected_kind="prompt",
                expected_path=output,
            )
            if verified["sha256"] != sha256_bytes(payload) or verified["byte_size"] != len(payload):
                raise SnapshotError("finalized prompt cannot be re-rendered with different bytes")
        else:
            if output.exists():
                raise SnapshotError("unexpected prompt already occupies the armed attempt path")
            atomic_write(output, payload)
            entry = record_artifact(
                state,
                run_dir,
                output,
                kind="prompt",
                stage=args.stage,
                pass_num=args.pass_num,
                attempt=attempt["attempt"],
                producer="prompt.rendered",
                expected_path=expected,
            )
            state["current_attempt"]["prompt_manifest_id"] = entry["id"]
            write_json(run_dir / "state.json", state)
        print(output)
        return 0
    except (ArtifactIntegrityError, SnapshotError, OSError, KeyError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
