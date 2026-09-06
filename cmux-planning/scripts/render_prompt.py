#!/usr/bin/env python3
"""Render deterministic spec-author and independent-reviewer work orders."""

from __future__ import annotations

import argparse
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
from spec_contract import SPEC_SECTIONS
from stage_snapshot import SnapshotError, approved_spec_from_state, load_prepared_snapshot
from tracker_contract import validate_proposal


# Named from the enforced list, so a prompt can never instruct a section set the gate rejects.
SPEC_CONTRACT = f"""The draft must be English and contain substantive `##` sections named exactly:
{", ".join(SPEC_SECTIONS[:-1])}, and {SPEC_SECTIONS[-1]}. Preserve literal product copy and
domain terms in their actual language. Under Testing Decisions include bullet entries prefixed
`Existing seam:`, `Prior-art test:`, and `Verification:`. If proposing a `New seam:`, also include
`Justification:`. An open decision states the question, context, options, recommendation when evidence
supports one, and why it remains open. Use exactly `- None` when there are no open decisions."""


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
        expected_path=path,
    )
    payload = path.read_bytes()
    if sha256_bytes(payload) != pointer["sha256"]:
        raise SnapshotError("normalized grilling input changed after revalidation")
    return (
        "Consume only this complete human-revalidated handoff; do not use or recover the copied "
        f"source pair: `{path}`\n\n```json\n{payload.decode('utf-8').rstrip()}\n```"
    )


def resumed_context(run_dir: Path, state: dict) -> str:
    recovery = state.get("resume_context")
    if not isinstance(recovery, dict):
        return "No interrupted prior pass is attached to this assignment."
    blocks = [
        f"Human resume reason: {recovery.get('reason', '')}",
        (
            f"Recovery route: {recovery.get('from_stage')}-{recovery.get('from_pass')} -> "
            f"{recovery.get('to_stage')}-{recovery.get('to_pass')}"
        ),
    ]
    for item in recovery.get("prior_handoffs", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise SnapshotError("resume context contains a malformed prior handoff")
        path = Path(item["path"]).resolve()
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as error:
            raise SnapshotError("resume context points outside this planning run") from error
        if not isinstance(item.get("manifest_id"), str):
            raise SnapshotError("resume context handoff has no immutable manifest identity")
        verify_entry(
            state,
            run_dir,
            item["manifest_id"],
            expected_path=path,
        )
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise SnapshotError(f"resume context handoff is missing or changed: {path}")
        try:
            content = path.read_text(encoding="utf-8").rstrip()
        except UnicodeError as error:
            raise SnapshotError(f"resume context handoff is not UTF-8: {path}") from error
        blocks.append(
            f"### {item.get('label', 'Prior handoff')}\n\n"
            f"`{path}` (sha256 `{item['sha256']}`)\n\n```text\n{content}\n```"
        )
    return "\n\n".join(blocks)


def author_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    task_path = (run_dir / state["task"]["path"]).resolve()
    verify_entry(
        state,
        run_dir,
        state["task"].get("manifest_id", ""),
        expected_kind="task",
        expected_path=task_path,
    )
    task = task_path.read_text(encoding="utf-8")
    paths = snapshot["allowed_worker_writes"]
    feedback = state.get("spec_revision_feedback") or "None recorded for this specification pass."
    return f"""# Planning Worker Prompt: specification author (pass {pass_num})

Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']}

Synthesize the supplied context into a repository-grounded specification. Do not interview the user.
Inspect repository source, local documentation, ADRs, terminology, history, and existing tests as needed.
When information is genuinely missing, record it under `Open Decisions` instead of guessing.

## Persisted Task

Source: `{task_path}` (sha256 `{state['task']['sha256']}`)

```text
{task.rstrip()}
```

## Optional Revalidated Grilling Context

{normalized_context(run_dir, state)}

## Human Specification Revision Feedback

{feedback}

## Interrupted-Pass Recovery Context

{resumed_context(run_dir, state)}

## Specification Contract

{SPEC_CONTRACT}

Testing decisions must choose the highest useful existing test seam, cite relevant prior-art tests,
prefer observable behavior over implementation details, and justify any new seam.

## Write Boundary

You may inspect the repository read-only. Physically write only these exact files:

- Complete draft: `{paths['draft']}`
- Structured report: `{paths['report']}`

Do not edit product code, configuration, lifecycle state, prompts, snapshots, or any other path. The
orchestrator compares complete Git status plus tracked and staged diffs before and after your stage.
That detector covers tracked changes and newly listed untracked paths; it does not claim coverage for
ignored files, for content changes to files already untracked in the baseline, or for the Git-ignored
run directory, whose handoff artifacts are gated by digest instead.

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

Self-validate before handoff (skip the first command for `BLOCKED`, which has no complete draft):

```bash
python3 {contract_path()} spec {paths['draft']}
python3 {contract_path()} author-report {paths['report']} --draft {paths['draft']}
```
"""


def review_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    author = state.get("author_spec")
    if not isinstance(author, dict):
        raise SnapshotError("review prompt requires the validated author handoff")
    task_path = (run_dir / state["task"]["path"]).resolve()
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
    return f"""# Planning Worker Prompt: independent specification review (pass {pass_num})

Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']} (Codex is mandatory)

Review independently in this fresh pane. Do not trust the author's summary: inspect the target repository
read-only where useful. Check the persisted task, optional normalized grilling decisions, repository evidence,
the complete draft, and the contract below.

## Inputs and Identity

- Task: `{task_path}` (sha256 `{state['task']['sha256']}`)
- Author report: `{author_report}`
- Draft: `{draft}` (sha256 `{author['draft_sha256']}`)

### Persisted Task

```text
{task_path.read_text(encoding='utf-8').rstrip()}
```

### Optional Revalidated Grilling Context

{normalized_context(run_dir, state)}

### Author Report

```markdown
{author_report.read_text(encoding='utf-8').rstrip()}
```

## Interrupted-Pass Recovery Context

{resumed_context(run_dir, state)}

## Specification Contract

{SPEC_CONTRACT}

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

You may physically write only:

- Review report: `{paths['report']}`
- Complete corrected candidate only for `pass_with_fixes`: `{paths['candidate']}`

Do not edit the author draft, product code, lifecycle state, or any other path. The author draft is
digest-bound to its own gate, so rewriting it in place fails the review outright, and the mandatory
Git-visible before/after inspection gates every delta outside the run directory.

## Review Report Contract

```markdown
## Verdict
pass

## Findings
- None

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
python3 {contract_path()} review-report {paths['report']} \\
  --input {draft} --candidate {paths['candidate']}
```
"""


VERTICAL_SLICE_POLICY = """Prefer a small number of cohesive tracer-bullet vertical slices. Each
ticket must state one complete user-observable delivered behavior, include stable acceptance criteria,
and be independently demonstrable or verifiable. A slice may cross every technical layer needed for
that behavior. Never decompose by frontend, backend, database, tests, directories, file types, or worker
specialties by default. Use suitability for one fresh worker context only as a qualitative boundary;
never write token counts or estimates into the proposal. Evaluate merge opportunities as explicitly as
split points: merge work sharing one outcome, verification story, and substantially the same context;
split independent outcomes, decision boundaries, rollout requirements, or excessive context. Add only
blocking edges whose prerequisite genuinely prevents the blocked ticket from starting, leaving every
initially ready ticket visible in the frontier. A wide mechanical refactor that cannot remain green as
ordinary slices must use explicit expand, bounded migrate, and contract tickets; add a final integration
exception only when intermediate migration batches cannot remain green independently."""


NATIVE_TRACKER_POLICY = """The machine proposal uses schema version 1 with exactly four top-level keys:
`schema_version`, `source_spec`, `tracker`, and `tickets`. `source_spec` contains exact `path` and
`sha256`. `tracker` contains lowercase kebab-case `slug`, non-empty `title`, `working_branch`, and a
non-empty list of exact runnable `canonical_check_commands`. Every ticket contains exactly `id` in
ISSUE-NNN form, `title`, `delivered_behavior`, non-empty `acceptance_criteria`, `blocked_by`,
`merge_split_rationale`, `slice_type`, non-empty `technical_layers`, and `wide_refactor`. A normal ticket
uses `slice_type: vertical` and `wide_refactor: null`. A wide-refactor ticket uses
`slice_type: wide-refactor` and an object with `phase`, `sequence: expand-migrate-contract`, and
`integration_reason` (null except for a justified integration exception). IDs are unique, blockers must
exist, and dependencies must be acyclic. All approved work is fully specified AFK work with the
ready-for-agent label when published; no adoption conversion is used."""


def tickets_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    approved_spec, spec_digest = approved_spec_from_state(state, run_dir=run_dir)
    task_path = (run_dir / state["task"]["path"]).resolve()
    paths = snapshot["allowed_worker_writes"]
    feedback = state.get("ticket_revision_feedback") or "None recorded for this tickets pass."
    return f"""# Planning Worker Prompt: tickets author (pass {pass_num})

Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']}

Turn the immutable approved specification into a native executable tracker proposal. Work in this fresh
pane without recovering or inheriting either specification worker session. Inspect the target repository
read-only for current branch, exact runnable checks, implementation context, terminology, and prior-art
tests. Do not make product or scope decisions that the approved specification did not make.

## Inputs and Identity

- Persisted task: `{task_path}` (sha256 `{state['task']['sha256']}`)
- Approved specification: `{approved_spec}` (sha256 `{spec_digest}`)
- Repository: `{state['repository']}`

### Approved Specification

```markdown
{approved_spec.read_text(encoding='utf-8').rstrip()}
```

### Human Ticket Revision Feedback

{feedback}

## Interrupted-Pass Recovery Context

{resumed_context(run_dir, state)}

## Tracker Ground Rules

- Canonical artifacts, headings, frontmatter values, reports, and proposal text are English; preserve
  literal product copy in its real language.
- Record the target repository's current working branch and exact runnable baseline check commands.
- Only fully specified approved work may be AFK and ready-for-agent.
- The published tracker must contain README.md, spec.md, map.md, decisions.md, and one native issue file
  per complete proposed ticket under issues/.

## Vertical-Slice Policy

{VERTICAL_SLICE_POLICY}

## Native Proposal Contract

{NATIVE_TRACKER_POLICY}

Write the complete machine proposal first, then generate the exact numbered human summary with the
vendored contract command. The summary contains every ticket's title, delivered behavior, acceptance
criteria, blockers, and merge/split rationale.

## Write Boundary

You may physically write only these exact files:

- Machine-readable proposal: `{paths['proposal']}`
- Human-readable numbered summary: `{paths['summary']}`
- Structured report: `{paths['report']}`

Do not edit the approved spec, product code, configuration, lifecycle state, or any other path. Mandatory
before/after Git-visible inspection gates every other tracked delta or newly listed untracked path within
the documented detector boundary.

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

Use `BLOCKED` only for a real blocker, and then state it under Blockers. Self-validate a passing handoff:

```bash
python3 {tracker_contract_path()} proposal {paths['proposal']} \\
  --spec {approved_spec} --spec-sha256 {spec_digest}
python3 {tracker_contract_path()} render-summary \\
  --proposal {paths['proposal']} --out {paths['summary']}
python3 {tracker_contract_path()} author-report {paths['report']} \\
  --proposal {paths['proposal']} --summary {paths['summary']} \\
  --spec {approved_spec} --spec-sha256 {spec_digest}
```
"""


def tickets_review_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    approved_spec, spec_digest = approved_spec_from_state(state, run_dir=run_dir)
    author = state.get("author_tickets")
    if not isinstance(author, dict) or not author.get("proposal_sha256"):
        raise SnapshotError("tickets review prompt requires the validated tickets author handoff")
    task_path = (run_dir / state["task"]["path"]).resolve()
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
    validate_proposal(
        proposal, expected_spec=approved_spec, expected_spec_sha256=spec_digest
    )
    return f"""# Planning Worker Prompt: independent ticket review (pass {pass_num})

Prepared: {snapshot['resolved_at']}
Stage snapshot: {snapshot['snapshot_id']}
Harness: {snapshot['selected_worker']['harness']} (Codex is mandatory)

Review independently in this fresh pane without either author session. Inspect the repository read-only
where useful. Check the task, immutable approved specification and its decisions, exact author proposal
and report identities, tracker ground rules, vertical-slice policy, and native tracker contract.

## Inputs and Identity

- Task: `{task_path}` (sha256 `{state['task']['sha256']}`)
- Approved specification: `{approved_spec}` (sha256 `{spec_digest}`)
- Machine proposal: `{proposal}` (sha256 `{author['proposal_sha256']}`)
- Human summary: `{summary}` (sha256 `{author['summary_sha256']}`)
- Author report: `{report}` (sha256 `{sha256_file(report)}`)

### Persisted Task

```text
{task_path.read_text(encoding='utf-8').rstrip()}
```

### Approved Specification and Decisions

```markdown
{approved_spec.read_text(encoding='utf-8').rstrip()}
```

### Author Report

```markdown
{report.read_text(encoding='utf-8').rstrip()}
```

## Interrupted-Pass Recovery Context

{resumed_context(run_dir, state)}

## Vertical-Slice Policy

{VERTICAL_SLICE_POLICY}

## Native Tracker Contract

{NATIVE_TRACKER_POLICY}

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

You may physically write only:

- Review report: `{paths['report']}`
- Complete corrected machine proposal only for `pass_with_fixes`: `{paths['candidate']}`

Mandatory before/after Git-visible inspection gates every other delta. Never edit the author proposal,
approved spec, product code, lifecycle state, or human summary.

## Review Report Contract

```markdown
## Verdict
pass

## Findings
- None

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
python3 {tracker_contract_path()} review-report {paths['report']} \\
  --input {proposal} --candidate {paths['candidate']} \\
  --input-sha256 {author['proposal_sha256']} \\
  --spec {approved_spec} --spec-sha256 {spec_digest}
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
