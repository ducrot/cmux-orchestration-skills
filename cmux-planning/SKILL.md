---
name: cmux-planning
description: Coordinate sequential visible CMUX planning workers that turn a task or explicitly human-revalidated cmux-grilling JSON/Markdown pair into a repository-grounded English specification, obtain a fresh independent Codex review, enforce exact run-scoped handoffs with Git-visible integrity gates, and pause for explicit human specification approval. Use for cmux planning, task-to-spec workflows, reviewed local specifications, optional grilling handoffs, planning run initialization, spec revision, and the planning stage before local issue decomposition. Do not use this skill to implement product code or to skip specification approval and jump directly from grilling to tickets.
---

# CMUX Planning

Turn one persisted task into an independently reviewed, explicitly approved specification. The
orchestrator coordinates; it does not author the specification or edit product code. Every author
and reviewer runs as a fresh, visibly labeled CMUX pane.

This release implements the specification slice through the `tickets` boundary:

```text
input -> awaiting-grilling-revalidation (optional) -> spec -> spec-review
      -> awaiting-spec-approval -> tickets
```

Ticket decomposition and tracker publication belong to the next planning slice. Never improvise
them from this stage.

## Ground rules

- Persist exactly one run-scoped `task.md`. Preserve explicit task text or file content in its
  original language; a conversation start persists the orchestrator's summary.
- `cmux-grilling` is optional. When supplied, import its JSON and the Markdown named by
  `markdownPath`, validate and copy their exact bytes, then explicitly revalidate them with the
  human before preparing a worker. Structural validation proves integrity, not freshness.
- Workers synthesize supplied context and inspect the repository. They do not interview the user;
  they put missing information under `Open Decisions`.
- The author may write only its draft and report. The reviewer may write only its report and, for
  `pass_with_fixes`, its complete corrected candidate.
- Before each launch, capture the complete Git status, tracked diff, and staged diff. After the
  report, compare path and diff content. Any unauthorized Git-visible delta gates HITL regardless
  of report content; never silently revert it.
- The detector covers tracked changes and newly listed untracked paths. It does not cover ignored
  files, content changes to files already untracked in the baseline, or the Git-ignored run
  directory; run-directory handoffs are gated by digest instead. A baseline arms one pass and is
  never recaptured, so a relaunch cannot adopt an unauthorized delta as its new "before".
- Ask human revalidation and approval questions in the user's language. Persist task inputs,
  specifications, reports, state, and events in English; preserve literal product copy.

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

For `spec` or `spec-review`, use its current pass number from `state.json`:

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

Approval freezes the exact candidate digest and advances to `tickets` without preparing a tickets
worker. Revision preserves rejected artifacts, increments the spec pass, prepares a fresh author, and
requires a new independent review. A decision is deferrable only after moving it outside current scope.

## Verification

Run the planning suite and both sibling regression suites:

```bash
python3 -m unittest discover -s cmux-planning/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-issue-chain/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-grilling/scripts -p 'test_*.py'
```
