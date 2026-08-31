#!/usr/bin/env python3
"""Render deterministic spec-author and independent-reviewer work orders."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator_lib import STAGES, atomic_write, read_json, sha256_bytes
from spec_contract import SPEC_SECTIONS
from stage_snapshot import SnapshotError, load_prepared_snapshot


# Named from the enforced list, so a prompt can never instruct a section set the gate rejects.
SPEC_CONTRACT = f"""The draft must be English and contain substantive `##` sections named exactly:
{", ".join(SPEC_SECTIONS[:-1])}, and {SPEC_SECTIONS[-1]}. Preserve literal product copy and
domain terms in their actual language. Under Testing Decisions include bullet entries prefixed
`Existing seam:`, `Prior-art test:`, and `Verification:`. If proposing a `New seam:`, also include
`Justification:`. An open decision states the question, context, options, recommendation when evidence
supports one, and why it remains open. Use exactly `- None` when there are no open decisions."""


def contract_path() -> str:
    """Absolute: the worker's cwd is the target repository, not the orchestrator's, and a
    cwd-relative path would also make the deterministic prompt bytes depend on where the
    orchestrator happened to stand."""
    return str(Path(__file__).resolve().parent / "spec_contract.py")


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
    payload = path.read_bytes()
    if sha256_bytes(payload) != pointer["sha256"]:
        raise SnapshotError("normalized grilling input changed after revalidation")
    return (
        "Consume only this complete human-revalidated handoff; do not use or recover the copied "
        f"source pair: `{path}`\n\n```json\n{payload.decode('utf-8').rstrip()}\n```"
    )


def author_prompt(run_dir: Path, pass_num: int, snapshot: dict, state: dict) -> str:
    task_path = (run_dir / state["task"]["path"]).resolve()
    task = task_path.read_text(encoding="utf-8")
    paths = snapshot["allowed_worker_writes"]
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
    author_report = (run_dir / "reports" / f"spec-{pass_num}.md").resolve()
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


def render(run_dir: Path, stage: str, pass_num: int) -> str:
    snapshot = load_prepared_snapshot(run_dir, stage, pass_num, require_baseline=False)
    state = read_json(run_dir / "state.json")
    return (
        author_prompt(run_dir, pass_num, snapshot, state)
        if stage == "spec"
        else review_prompt(run_dir, pass_num, snapshot, state)
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        run_dir = Path(args.run_dir)
        output = Path(args.out) if args.out else run_dir / "prompts" / f"{args.stage}-{args.pass_num}.md"
        atomic_write(output, render(run_dir, args.stage, args.pass_num).encode("utf-8"))
        print(output)
        return 0
    except (SnapshotError, OSError, KeyError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
