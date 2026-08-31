---
name: cmux-planning
description: Coordinate sequential visible CMUX planning workers that turn a task or explicitly human-revalidated cmux-grilling JSON/Markdown pair into an approved repository-grounded specification and a reviewed native executable issue tracker. Use for cmux planning, task-to-spec workflows, vertical ticket decomposition, reviewed local specifications and trackers, optional grilling handoffs, planning run initialization, approval, revision, and collision-safe tracker publication. Do not use this skill to implement product code or to skip either approval boundary.
---

# CMUX Planning

Turn one persisted task into an independently reviewed, explicitly approved specification and then
an independently reviewed native issue tracker. The orchestrator coordinates; it does not author the
planning artifacts or edit product code. Every author and reviewer runs as a fresh, visibly labeled
CMUX pane.

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

`planning_state.py init` creates a missing config or detects a valid schema-v1 file, then displays
every resolved workflow. For schema v1 it strictly validates and previews the complete schema-v2
candidate without changing the original bytes, emits the compatibility warning above, and exits
before a run exists. Let the human confirm that every installed sibling was upgraded, review the
assignments, and rerun with `--accept-config`; that explicit rerun atomically migrates the file and
starts initialization. Migration preserves existing profiles and assignments and leaves original
bytes untouched on failure. `atomic_initialize` remains create-only.

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
`{"accepted": false}` and remains at the same state with no prepared worker. Interruption also leaves
the copied pair and state untouched.

```bash
python3 scripts/planning_state.py revalidate --run-dir <run-dir> --outcomes <outcomes.json>
```

Workers consume only the resulting complete `grilling-input.json`, never the incomplete source pair.

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
python3 scripts/await_report.py --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <new-surface>
```

The baseline makes the prepared snapshot launchable. `pane_ctl.py` always uses the pinned workspace
and stable surface identity, starts a fresh configured process, labels the pane, and records lifecycle
events. The armed watcher treats missing reports as pending, emits heartbeats, detects pane death, and
does not treat a transient health-command failure as worker failure.

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

## Verification

Run the planning suite and both sibling regression suites:

```bash
python3 -m unittest discover -s cmux-planning/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-issue-chain/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-grilling/scripts -p 'test_*.py'
```
