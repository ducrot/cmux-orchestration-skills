---
name: cmux-planning
description: Coordinate sequential visible CMUX planning workers that turn a task or explicitly human-revalidated cmux-grilling JSON/Markdown pair into an approved repository-grounded specification and a reviewed native executable issue tracker. Use for cmux planning, task-to-spec workflows, vertical ticket decomposition, reviewed local specifications and trackers, optional grilling handoffs, planning run initialization, approval, revision, and collision-safe tracker publication. Do not use this skill to implement product code or to skip either approval boundary.
---

# CMUX Planning

Turn one persisted task into an independently reviewed, explicitly approved specification and then
an independently reviewed native issue tracker. The orchestrator coordinates; it does not author the
planning artifacts or edit product code. Every author and reviewer runs as a fresh, visibly labeled
CMUX pane.

`cmux-planning` performs synthesis and independent review. Optional `cmux-grilling` is a separate
upstream workflow for stress-testing uncertain decisions; it is neither required nor invoked here.
`cmux-issue-chain` is a separate downstream workflow that may execute the published native tracker,
but planning never starts it automatically. Each workflow can be used on its own.

```text
input -> awaiting-grilling-revalidation (optional) -> spec -> spec-review
      -> awaiting-spec-approval -> tickets -> tickets-review
      -> awaiting-ticket-approval -> ready-to-publish -> complete
```

## Ground rules

- Persist exactly one run-scoped `task.md`. Preserve explicit task text or file content in its
  original language; a conversation start persists the orchestrator's summary.
- `cmux-grilling` is optional. When supplied, import its JSON and the Markdown named by
  `markdownPath`, validate and copy their exact bytes, then explicitly revalidate them with the
  human before preparing a worker. Structural validation proves integrity, not freshness.
- Workers synthesize supplied context and inspect the repository. They do not interview the user;
  they put missing information under `Open Decisions`.
- The spec author may write only its draft and report. The tickets author may write only its JSON
  proposal, deterministic numbered summary, and report. A reviewer may write only its report and,
  for `pass_with_fixes`, its complete corrected candidate.
- Before each launch, capture the complete Git status, tracked diff, and staged diff. After the
  report, compare path and diff content. Any unauthorized Git-visible delta gates HITL regardless
  of report content; never silently revert it.
- The detector covers tracked changes and newly listed untracked paths. It does not cover ignored
  files, content changes to files already untracked in the baseline, or the Git-ignored run
  directory; run-directory handoffs are gated by digest instead. A baseline arms one pass and is
  never recaptured, so a relaunch cannot adopt an unauthorized delta as its new "before".
- Ask human revalidation and approval questions in the user's language. Persist task inputs,
  specifications, reports, state, and events in English; preserve literal product copy.
- Ticket decomposition prefers a small number of cohesive tracer-bullet vertical slices. Never
  default to frontend/backend/database/test tickets, never persist token counts or estimates, and
  evaluate merge opportunities as explicitly as split points. Blocking edges must be genuine.
- Only a passing reviewed ticket candidate may be staged. Publication is a collision-checked atomic
  directory move into the target repository and never invokes `cmux-issue-chain` or
  `adopt_tracker.py` at runtime.

Read [references/spec-contract.md](references/spec-contract.md) when judging author or review
handoffs.

## First-use configuration checkpoint

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v2. Older separately installed sibling skills cannot read the migrated schema-v2 shared configuration.

All three independently shipped skills vendor the same `scripts/agents_config.py` schema-v2 CLI.
It requires `planning.spec`, `planning.tickets`, and `planning.reviewer`. Authors default to
`claude-opus-xhigh`; the reviewer defaults to `codex-sol-xhigh` and must resolve to Codex.
`validate` and `show-resolved` are read-only and never migrate schema v1; all planning preparation
commands likewise stop before launchable state and display the exact preview and acceptance commands.

`planning_state.py init` creates a missing config or detects a valid schema-v1 file, then displays
every resolved workflow. For schema v1 it strictly validates and previews the complete schema-v2
candidate without changing the original bytes, emits the compatibility warning above, and exits
before a run exists. The shared `agents_config.py migrate` command is the read-only preview interface.
Present its complete preview in the human's language and ask the human to accept exactly that proposal.
On confirmation, invoke its displayed `agents_config.py migrate --accept` command including its digest
argument, then rerun planning
initialization; `--accept-config` never authorizes schema migration. When `claude-opus-xhigh` is absent,
the preview identifies it as unavailable and displays the lexicographically first compatible fallback's
profile name, harness, model, and effort without inferring relative quality. Migration preserves existing
profiles and assignments and leaves original bytes untouched on failure. It refuses targets with no
write bit or more than one hard link, preserves a symlink path, and applies both guards to its resolved
target. `atomic_initialize` remains create-only.

## Prerequisites and installation

Install the skill into an agent that can run Python 3 and Git in the target repository. Visible worker
operation additionally requires cmux, Claude Code for the default author profiles, and Codex CLI for
the mandatory independent reviewer. Offline tests use fake harnesses and fake CMUX and contact no model
provider.

Use the skills CLI from this repository or copy the complete `cmux-planning` directory into the agent's
skills directory. Upgrade installed siblings together before accepting schema-v1 migration. Runtime is
standalone: a direct task needs neither sibling, and vendored contracts validate optional grilling input
and the native tracker without locating another skill installation.

On first use, let `planning_state.py init` create or preview the shared configuration. For a newly
created schema-v2 default, inspect `planning.spec`, `planning.tickets`, and the mandatory Codex
`planning.reviewer`, then rerun with `--accept-config`. For schema v1, run the shared read-only preview,
obtain explicit confirmation, run `agents_config.py migrate --accept`, and only then rerun
`planning_state.py init`.

## Initialize

Use one task source:

```bash
python3 scripts/planning_state.py init --task-file <path> --repo <repo> \
  --workspace-id <workspace> [--config <agents.json>] [--accept-config]
```

For conversation input, render a faithful summary into `--conversation-summary`. For grilling input,
also pass `--grilling-json <result.json>` and optionally the exact `--grilling-markdown <result.md>`.
The JSON's `markdownPath` remains authoritative. Missing, malformed, path-inconsistent,
repository-mismatched, or ambiguous pairs fail before any launchable state or pane exists.

Direct input starts at `spec` with an immutable prepared snapshot. Grilling input starts at
`awaiting-grilling-revalidation` with no snapshot.

Concrete direct-task and optional grilling-pair starts are:

```bash
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --grilling-json ./grilling-result.json --grilling-markdown ./grilling-result.md \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
```

Initialization first looks for the newest unfinished run recorded for the same repository. It prints
that run and its exact `resume` command and exits before creating another. Completed runs never block a
later session. Use `--new-run` only after the human deliberately chooses a separate planning session
beside an unfinished one.

## Revalidate optional grilling input

Show every item that the human must consider:

```bash
python3 scripts/planning_state.py show-revalidation --run-dir <run-dir>
```

Explain that freshness is a human judgment. Show the artifact task and repository, current HEAD and
status identity, Markdown premise corrections, every assumption, and every open, decided, or deferred
decision. Record a JSON outcomes file with this shape:

```json
{
  "accepted": true,
  "premise_corrections": [
    {"index": 1, "outcome": "confirmed", "reason": ""}
  ],
  "assumptions": [
    {"index": 1, "outcome": "corrected", "value": "Corrected statement", "reason": "Why"}
  ],
  "decisions": [
    {"id": "D1", "status": "decided", "decision": "Chosen option", "reason": "Why"}
  ]
}
```

Each premise correction and assumption is `confirmed`, `corrected`, or `discarded`; corrected and
discarded entries need reasons, and corrected entries need replacement text. Cover every source
decision with `open`, `decided`, or `deferred`; resolved entries need outcome text. Refusal uses
`{"accepted": false}` and remains at the same stage with no prepared worker. Interruption preserves
the copied pair plus the latest partial outcomes without creating launchable state.

```bash
python3 scripts/planning_state.py revalidate --run-dir <run-dir> --outcomes <outcomes.json>
```

Workers consume only the resulting complete `grilling-input.json`, never the incomplete source pair.
Every supplied outcomes checkpoint is atomically preserved before normalization, so an interrupted
walkthrough can resume the same copied pair and recorded partial outcomes. Only a complete normalized
handoff prepares `spec-1`; partial or refused outcomes never make a worker launchable.

## Run one stage

For `spec`, `spec-review`, `tickets`, or `tickets-review`, use the corresponding current pass number
from `state.json`:

```bash
python3 scripts/render_prompt.py --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/tree_integrity.py baseline --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --stage <stage> --pass <n> \
  --anchor <caller-surface>
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <new-surface>
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <new-surface> --prompt <rendered-prompt>
python3 scripts/pane_ctl.py mark-started --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <new-surface>
python3 scripts/await_report.py --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <new-surface>
```

The baseline makes the prepared snapshot launchable. `pane_ctl.py` always uses the pinned workspace
and stable surface identity, starts a fresh configured process, labels the pane, and records lifecycle
events. The armed watcher treats missing reports as pending, emits heartbeats, detects pane death, and
does not treat a transient health-command failure as worker failure.

## Status and context recovery

Status is read-only and derives progress from `state.json`, digest-bound files, structured lifecycle
events, and optional CMUX surface health. It never treats pane text or a worker narrative as success:

```bash
python3 scripts/planning_state.py status --run-dir <run-dir>
python3 scripts/planning_state.py resume --run-dir <run-dir>
python3 scripts/planning_state.py context --run-dir <run-dir>
```

The status JSON reports the run and repository, task/source digest, copied and normalized grilling
identities, revalidation progress, exact stage/mode/pass, prepared snapshot validity, live or last-known
pane, pending report, latest review verdict and candidate digest, both digest-bound approvals, staging
and publication phase, consistency errors, and one recommended next command. Its classifications
distinguish awaiting or interrupted grilling revalidation, spec authoring/review, ticket authoring/review,
pending report, both approval boundaries, requested revision, review-blocked, HITL, completed, and
inconsistent state. Initialization persists a validated `input` checkpoint before activating the first
stage, so an interruption there reports `input-validation` and resumes that same prepared identity. A
pre-run input or configuration failure has no run state and remains an initialization error rather than
being inferred as a worker stage.

After context compaction, run `context` and status before acting. The context manifest enumerates the
persisted task, copied grilling pair, normalized handoff, latest author and review artifacts, approved
spec, latest ticket proposal, state, events, immutable stage and tree snapshots, reports, and digests.
Read the applicable artifacts and human diff (`approval-view` or `ticket-approval-view`) plus reported
pane health; do not reconstruct progress from conversation memory.

Follow the status command exactly for active work:

- A live pane whose deterministic prompt was sent and whose report is pending is rejoined with the
  armed `await_report.py` command. Never launch a duplicate worker.
- A recorded pane in which the worker or prompt was never started uses the reported `start-agent` or
  `deliver` command and the same baseline-bound prompt. After delivery, inspect the visible screen:
  re-deliver only for the known summarized-and-waiting case, otherwise record `mark-started` before
  arming the watcher. A stage with no pane uses the launch command.
- A non-empty handoff is gated or inspected and never overwritten as an uncertain retry.
- A first live-pane deadline may receive the run's one human-reasoned `resume --decision extend`
  watcher extension. Pane death, expiry of that extension, snapshot tampering, an integrity violation,
  an unknown state shape, or an uncertain handoff stops at HITL. None automatically advances or
  relaunches.
- At either approval boundary, rerun the corresponding view. It reopens the same reviewed,
  digest-bound candidate and never invokes a worker.

An explicit human decision may replace a dead or expired worker with one fresh numbered pass:

```bash
python3 scripts/planning_state.py resume --run-dir <run-dir> \
  --decision relaunch --reason <human-authored-reason>
```

The recovery prompt includes the reason plus prior candidates, reports, reviews, and feedback by their
recorded digests; failed panes, snapshots, events, and handoffs remain in history. A dead author gets a
new author pass. A dead reviewer gets a new reviewer pass over the unchanged author identity. A blocked
review routes back to an author and cannot be relabeled as another reviewer pass. If ticket review found
an approved-spec defect, use `ticket-approval --decision revise --scope spec` so the full spec
author/review/approval sequence repeats.

## Gate the author and reviewer

After author completion:

```bash
python3 scripts/planning_state.py accept-author --run-dir <run-dir>
```

This verifies the after-tree, validates grounding, report structure, exact draft path, specification
sections, and test seams, then advances only to `spec-review` and prepares a fresh Codex snapshot.

After independent review:

```bash
python3 scripts/planning_state.py accept-review --run-dir <run-dir>
```

`pass` binds the unchanged draft digest. `pass_with_fixes` requires a complete corrected candidate and
structured correction summary; deterministic validation leads directly to human approval without
another automatic model review. `blocked` preserves evidence and requires human input plus a new author
pass. A malformed, ungrounded, drifting, digest-mismatched, or open-decision candidate never reaches
approval.

## Human approval or revision

At `awaiting-spec-approval`, present in the user's language:

- the complete reviewed specification and reviewer verdict;
- the correction summary and human-visible draft/candidate diff;
- assumptions and decided/deferred items;
- proposed test seams;
- explicit confirmation that no decision remains open.

Load the complete deterministic walkthrough payload first; it includes the reviewed specification,
review verdict and corrections, author-proposed test seams, assumptions and decisions, out-of-scope
items, the no-open-decision check, and a unified author/candidate diff:

```bash
python3 scripts/planning_state.py approval-view --run-dir <run-dir>
```

Then record exactly one outcome:

```bash
python3 scripts/planning_state.py approval --run-dir <run-dir> \
  --decision approve --reason <human-reason>
python3 scripts/planning_state.py approval --run-dir <run-dir> \
  --decision revise --reason <requested-change>
```

Approval freezes the exact candidate digest, advances to `tickets`, and prepares a new immutable stage
snapshot without reusing either spec worker session. Revision preserves rejected artifacts, increments
the spec pass, prepares a fresh author, and requires a new independent review. A decision is deferrable
only after moving it outside current scope.

Repeating the same recorded approval is idempotent only while its candidate digest is unchanged. A
changed draft or candidate makes the approval stale and blocks continuation; it never inherits the old
approval.

## Ticket author and independent review

Run the prepared `tickets` stage with the same render, baseline, pane, delivery, and watcher commands.
The author receives only the immutable approved spec, task, repository identity, tracker ground rules,
vertical-slice policy, native proposal schema, revision feedback, and exact handoff paths. Its JSON
proposal is the source of truth; `tracker_contract.py render-summary` creates the exact human-readable
numbered representation.

Gate a clean author report:

```bash
python3 scripts/planning_state.py accept-author --run-dir <run-dir>
```

This validates approved-spec identity, proposal structure, summary equality, ticket count, ready
frontier, genuine blockers, cycles, qualitative sizing, merge/split rationale, and wide-refactor
sequences, then prepares a fresh immutable `tickets-review` snapshot. Run that stage in a new visible
pane; its selected harness must be Codex. Gate its report with:

```bash
python3 scripts/planning_state.py accept-review --run-dir <run-dir>
```

The tickets reviewer returns `pass`, `pass_with_fixes`, or `blocked`. Safe fixes may correct only
established intent and lead directly to human approval after deterministic validation. A substantive
ticket boundary, dependency, product, scope, behavior, priority, architecture, or approved-spec defect
blocks. An approved-spec correction invalidates the proposal and restarts spec author, spec review, spec
approval, ticket author, and ticket review.

## Ticket approval, staging, and publication

Load the deterministic walkthrough before asking the human. It includes verdict and corrections, every
ticket's delivered behavior and criteria, the ready frontier, blocking edges, wide-refactor exceptions,
merge/split rationale, and author/candidate diff:

```bash
python3 scripts/planning_state.py ticket-approval-view --run-dir <run-dir>
```

Record revision feedback with a fresh tickets pass, or route an approved-spec defect back through the
complete spec sequence:

```bash
python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \
  --decision revise --reason <granularity-change>
python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \
  --decision revise --scope spec --reason <approved-spec-defect>
```

Approval requires the explicit target path. It freezes the exact reviewed proposal digest, stages
`README.md`, `spec.md`, `map.md`, `decisions.md`, and every native issue file under the run directory,
and validates the complete staged tracker with this skill's standalone native contract. The target must
remain absent and its basename must equal the approved lowercase kebab-case tracker slug:

```bash
python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \
  --decision approve --reason <human-reason> --target <repo-relative-or-absolute-target>
```

Only after approval and successful staging, publish the complete directory in one same-filesystem move:

```bash
python3 scripts/planning_state.py publish --run-dir <run-dir>
```

Publication refuses path escape, collisions, changed approved identities, malformed or partial issue
sets, duplicate IDs, unknown blockers, cycles, changed staging, and second publication. Staging or
validation failure leaves the target unchanged and records diagnostics for human resolution.

Status distinguishes publication not started, fully staged but not yet recorded, recorded and validated,
already moved but not recorded, and completed. Repeating explicit ticket approval adopts complete
unrecorded staging only after it validates against the reviewed proposal and approved spec; partial or
changed staging stops for inspection. If interruption happens after the atomic move but before the final
state write, rerunning `publish` validates the existing target against the approved spec, proposal,
ticket set, and staged artifact identities before completing state. If both staging and target exist,
identities differ, or the run is already complete, publication refuses to duplicate or partially
overwrite anything.

## Artifact locations and failure policy

Runs live under `.scratch/orchestrator/planning-runs/<run-id>/` by default. `task.md`, optional `inputs/`,
`grilling-input.json`, `artifacts/`, `reports/`, `prompts/`, `stage-snapshots/`, `tree-snapshots/`,
`state.json`, and `events.jsonl` are the recovery record. Approved native trackers contain `README.md`,
`spec.md`, `map.md`, `decisions.md`, and `issues/` at the explicit target. That target is immediately
consumable by `cmux-issue-chain`: inspect its first ready issue, then initialize issue execution as a
separate workflow.

Treat malformed reports, digest drift, dead panes, expired waits, blocked decisions, and integrity
violations as evidence for human resolution. Never infer approval from prose, edit product code from
the planning orchestrator, silently repair the working tree, or claim detection coverage for ignored
files or contents of baseline-untracked files. Canonical persisted artifacts are English, literal
product copy keeps its actual language, and human questions and walkthroughs use the user's language.

## Verification

Run the planning suite and both sibling regression suites:

```bash
python3 -m unittest discover -s cmux-planning/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-issue-chain/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-grilling/scripts -p 'test_*.py'
```

The dependency-free end-to-end smoke path is:

```bash
python3 scripts/test_planning_flow.py -v -k offline_smoke
```

It uses fake workers and fake CMUX to cover a direct task, both author/reviewer stages, a safe
`pass_with_fixes`, both human approvals, publication, and initialization of the first ready issue
through the sibling issue-chain source when this development repository contains it.
