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
- Two explicit integrity boundaries apply. The product-tree detector covers tracked changes, staged
  changes, untracked paths and their content (regular files up to the 8 MiB size cap and symlink
  target bytes), and HEAD movement. It does not cover ignored product files or skipped untracked
  content (files above the size cap or unsupported types), or contents of unreadable untracked
  directories omitted by Git with a warning. Separately, every trusted file in the Git-ignored run
  directory is finalized in `state.json`'s artifact manifest with its canonical run-relative path,
  kind, stage, pass, attempt, byte size, SHA-256, producer event, and immutable status. A baseline
  arms one pass and is never recaptured against different product-tree bytes, so a relaunch cannot
  adopt an unauthorized delta as its new "before".
- Every worker emission has an immutable attempt identity. The first attempt retains the concise
  stage/pass filenames; every later same-pass attempt uses an `-attempt-N` suffix for its prompt,
  report, draft/proposal, optional corrected candidate, stage snapshot, and tree snapshots. Preparing
  a retry closes the earlier attempt and never reuses, deletes, or silently re-baselines its paths.
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
`claude-fable-high` and the reviewer to `codex-astra-high`. Every role accepts Claude Code, Codex
or Pi; the reviewer carries no fixed harness, and its independence from the authors is enforced by
the model-diversity gate below instead. A Pi model must name its provider (`provider/id`, such as
`openrouter/z-ai/glm-5.3`), because Pi has no provider-wide auth status and its preflight check is
scoped to the model it is given.
`validate` and `show-resolved` are read-only and never migrate schema v1; all planning preparation
commands likewise stop before launchable state and display the exact preview and acceptance commands.

A schema-v2 file needs no migration question.
An existing valid schema-v2 file needs no start confirmation either; the start question belongs only to a newly created default (accepted with `--accept-config`). Never offer profile overrides the human did not ask for.

`planning_state.py init` creates a missing config or detects a valid schema-v1 file, then displays
every resolved workflow. For schema v1 it strictly validates and previews the complete schema-v2
candidate without changing the original bytes, emits the compatibility warning above, and exits
before a run exists. The shared `agents_config.py migrate` command is the read-only preview interface.
Present its complete preview in the human's language and ask the human to accept exactly that proposal.
Its stable output contract writes the complete migration guidance once on stdout; stderr contains only
the short read-only refusal and does not repeat either command. A schema-v1 planning initialization leaves
stdout empty and emits one complete actionable guidance block on stderr, including the candidate digest
and exact preview and acceptance commands once each.
On confirmation, invoke its displayed `agents_config.py migrate --accept` command including its digest
argument, then rerun planning
initialization; `--accept-config` never authorizes schema migration. When `claude-fable-high` is absent,
the preview identifies it as unavailable and displays the lexicographically first compatible fallback's
profile name, harness, model, and effort without inferring relative quality. Migration preserves existing
profiles and assignments and leaves original bytes untouched on failure. It refuses targets with no
write bit or more than one hard link, preserves a symlink path, and applies both guards to its resolved
target. `atomic_initialize` remains create-only.

## Prerequisites and installation

Install the skill into an agent that can run Python 3 and Git in the target repository. Visible worker
operation additionally requires cmux, Claude Code for the default author profiles, and Codex CLI
for the default reviewer profile. Offline tests use fake harnesses and fake CMUX and contact no
model provider.

Use the skills CLI from this repository or copy the complete `cmux-planning` directory into the agent's
skills directory. Upgrade installed siblings together before accepting schema-v1 migration. Runtime is
standalone: a direct task needs neither sibling, and vendored contracts validate optional grilling input
and the native tracker without locating another skill installation.

On first use, let `planning_state.py init` create or preview the shared configuration. For a newly
created schema-v2 default, inspect `planning.spec`, `planning.tickets`, and `planning.reviewer`,
then rerun with `--accept-config`. For schema v1, run the shared read-only preview, obtain explicit
confirmation, run `agents_config.py migrate --accept`, and only then rerun
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

Direct input starts at `spec` with an immutable prepared snapshot, unless the resolved author and
reviewer share a harness and model: that start prints one extra warning object with `prepared: null`
before the run directory, exits with code 2, and leaves `spec` waiting on the confirmation described
below with no snapshot. Grilling input starts at `awaiting-grilling-revalidation` with no
snapshot.

Every newly initialized run records the creation-only boolean
`configuration_created_and_accepted` in `state.json`. It is true only when that invocation created a
missing shared configuration and the operator accepted the new default with `--accept-config`; it is
false when initialization used an existing configuration. It does not mean that planning initialization
migrated a shared configuration—migration remains the separate, explicit `agents_config.py migrate
--accept` operation described above. New runs never write the former
`configuration_created_or_migrated_and_accepted` key.

Durable runs that contain only the legacy key remain readable and resumable. Its recorded boolean is
used as the compatibility value without rewriting the run merely because it was read. A state containing
both names is accepted only when their boolean values match; conflicting values are rejected with an
error that requires the operator to make them agree before the run can continue.

That configuration-field compatibility does not authorize legacy run-artifact trust. A run created
before run-state schema 3 / artifact-manifest version 1 remains inspectable through `status` and
`context`, but every state-changing command and worker launch refuses it with guidance to obtain a
human decision to restart or to use a separately reviewed migration procedure. No automatic migration
or digest baseline is inferred from files already present in such a run.

Concrete direct-task and optional grilling-pair starts are:

```bash
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --grilling-json ./grilling-result.json --grilling-markdown ./grilling-result.md \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
```

Relative `--runs-root` and `--run-dir` paths are interpreted from the command's working directory,
as in grilling and issue-chain. Stored artifact pointers are canonical run-relative paths; readers
join them to the run directory exactly once. Absolute worker handoff paths remain supported.

Initialization is idempotent for the same run ID when `state.json` already exists: it prints the
existing run directory and exits successfully without replacing input, preparing workers, or advancing
the run. Inspect `status` and use `resume` to continue, including any pending human gates. Configuration,
typed overrides, live probes, and `--accept-config` are refused on re-initialization rather than silently
ignored; use stage preparation for fresh configuration. A directory without `state.json` does not by
itself block initialization, so a failed start that only wrote `task.md` can be retried.

For a different run ID, initialization looks for the newest unfinished run recorded for the same
repository. It prints that run and its exact `resume` command and exits before creating another.
Completed runs never block a later session. Use `--new-run` only after the human deliberately chooses
a separate planning session beside an unfinished one; it never resets an existing run.

## Run briefing

A fresh run opens with a compact briefing so the human sees what is being planned without opening a
file. After `planning_state.py init` (including a diversity-gated exit 2 or grilling input awaiting
revalidation) and before the first `pane_ctl.py launch`:

```bash
python3 scripts/run_briefing.py draft --run-dir <run-dir> --lang <de|en>
# Replace {{task}} and {{constraints}} in <run-dir>/briefing.md, then:
python3 scripts/run_briefing.py show --run-dir <run-dir> --lang <de|en>
```

- `draft` writes `briefing.md` with the facts filled in (task source, stage flow, tracker slug) and
  never overwrites an existing briefing. Pick `--lang` by the human's language.
- Fill only the placeholders, from `task.md` and, for grilling input, the copied pair:
  `{{task}}` is what will be planned in two or three sentences; `{{constraints}}` lists the fixed
  constraints and non-goals. Neutral wording; keep the fixed lines and their order unchanged.
- `show` refuses while a placeholder remains, prints the briefing, records `run.briefing`, and sets
  the sidebar pill `cmux-planning-run` (`Planning · <slug>`) in the pinned workspace. A failed pill is
  a stderr note, not a stop. Relay the printed briefing verbatim as its own message, without preamble.
- On resume, run `show` again after `context` and status. `briefing.md` is orchestrator text, not a
  worker artifact: the artifact audit skips it and no prompt attaches it.

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

## Confirm author/reviewer model diversity

No role is pinned to a harness, so independent review rests on this gate alone. Before preparing any
stage, planning compares the resolved `planning.spec` or `planning.tickets` profile with the resolved
`planning.reviewer`. A reviewer stage is compared against the author it is about to check, so a
configuration change or typed override between author and review is caught instead of launched. When
both resolve to the same harness and model, preparation stops before a launchable snapshot exists and
prints a warning naming both roles, profile names, harnesses, and models. Present that warning and ask
the confirmation question in the user's language. Never substitute or fall back to another profile
automatically. One decision covers one harness-and-model combination: an author stage and the reviewer
stage that checks it share it, so a confirmed combination is never asked twice.
This expected gate is not a crash: every public command that reaches the blocked preparation
prints structured JSON with `prepared: null`, the warning, and the exact confirmation command, exits
with exit code 2, and writes no traceback to stderr. A diverse or already-confirmed resolution remains
successful and exits 0 with its launchable snapshot and no extra warning.

Exit code 2 is not unique to the diversity gate: argument-usage errors and other precondition
refusals also use it. Wrappers must inspect stdout and stderr, identifying a gated preparation by
`prepared: null` and `diversity_warning` in its structured stdout response, rather than treating the
exit code alone as a request for diversity confirmation.

A non-zero preparation result does not roll back an earlier state transition. For example,
`approval --decision approve` can persist spec approval and move to `tickets` before ticket author
preparation exits 2. Revision, revalidation, and relaunch commands can likewise persist progress before
reaching the gate. A wrapper using `set -e` must handle this outcome explicitly: read `status` and
`context` for the same run, then follow the recommended next command. Do not blindly retry the original
transition command; its approval or revision may already be recorded and its original stage guard may
no longer apply.

If the human knowingly accepts same-harness-and-model operation, translate the recorded decision and
their human-authored reason into English and run the exact command reported by `status`:

```bash
python3 scripts/planning_state.py diversity-confirmation --run-dir <run-dir> \
  --decision confirm --reason <human-reason-in-English>
```

That decision is persisted in state and events and prepares the waiting author stage. It covers later
passes and the other author stage only while the resolved author/reviewer harness-and-model combination
is unchanged. A changed combination invalidates the decision; another collision asks again. Profile
names or effort may change without invalidation when the resolved harnesses and models remain the same.

Refusal is also explicit and reasoned:

```bash
python3 scripts/planning_state.py diversity-confirmation --run-dir <run-dir> \
  --decision refuse --reason <human-reason-in-English>
```

Refusal leaves the run at its current `spec` or `tickets` stage with no launchable snapshot. Follow the
printed guidance naming the shared configuration file and the exact
`workflows.planning.spec` or `workflows.planning.tickets` assignment to change. Refusal never prepares
a snapshot even when the resolved combination changed meanwhile and is now diverse: the refusal and its
reason are recorded, the guidance is printed, and launching that stage takes a later explicit `prepare`.
A genuinely diverse resolution prepares normally with no warning or extra prompt.

## Worker input readiness

Before starting or messaging any worker, follow [Interactive worker readiness](references/worker-readiness.md).
After `start-agent`, inspect with `observe`, explicitly `assess` the current screen, resolve pending
startup dialogs, and only then `deliver`. Read each tool result before the next input; never batch
start and task delivery. The gate applies to Codex, Claude Code and Pi, all roles/lanes, and follow-ups.
`worker.ready` permits one delivery and is distinct from `worker.started`. On recovery, observe again.

## Run one stage

For `spec`, `spec-review`, `tickets`, or `tickets-review`, use the corresponding current pass number
from `state.json`:

```bash
python3 scripts/render_prompt.py --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/tree_integrity.py baseline --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --stage <stage> --pass <n> \
  --anchor <caller-surface>
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
# Read the start output; run observe and assess separately before delivery.
python3 scripts/pane_ctl.py observe --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
python3 scripts/pane_ctl.py assess --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id> --observation <observation-id> --state ready \
  --reason "<evidence that the expected agent is fully loaded and idle>"
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id> --prompt <rendered-prompt>
python3 scripts/pane_ctl.py mark-started --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
python3 scripts/await_report.py --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
```

The baseline makes the prepared snapshot launchable. `pane_ctl.py launch` prints JSON whose
`surface_id` is the new pane's stable UUID; copy that exact value into every later pane command for
the stage pass, including the watcher and `close`. The auxiliary `surface_ref` is only a human-readable
launch-time position such as `surface:107`; positional refs shift when panes close and must never be
used as a planning worker's post-launch identity. `start-agent`, `deliver`, `mark-started`, and the
watcher validate their supplied identity against the latest recorded launch UUID before calling CMUX,
and a mismatch stops with the recorded UUID in the error. `close` is the one recovery exception: it
accepts any stable UUID this stage pass recorded, so a pane orphaned by a failed or retried launch
stays closable; an unknown UUID or a positional ref still fails before any CMUX call.
`pane_ctl.py` always uses the pinned workspace, starts a fresh configured process,
labels the pane, and records lifecycle events under that UUID. Every interactive Claude author starts
in `auto` permission mode; the safe, tool-disabled live provider probe remains in `plan` mode. The
armed watcher treats missing reports as pending, emits heartbeats, detects pane death, and does not
treat a transient health-command failure as worker failure.

Use the prompt and handoff paths recorded under the current attempt in `state.json`; do not construct
them from stage/pass alone. The watcher accepts a report only after observing identical non-empty bytes
twice, records that exact identity in the manifest before emitting its captured-report event, and the
gate repeats a stable capture when invoked directly. A missing, truncated, replaced, or changed
finalized artifact records `artifact.integrity_violation`, closes the attempt, and gates HITL before
the artifact can be parsed or launched.

After `accept-author` or `accept-review` records its gate decision for the captured report, close
that worker's pane:

```bash
python3 scripts/pane_ctl.py close --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
```

`close` closes the surface and records `pane.closed`. A repeated `mark-started` for an already
confirmed stage pass writes no second event and reports `"already_recorded": true`, so the recovery
sequence is safe to re-run. Never close a pane whose report is still pending. Keep at most the orchestrator pane and the current active worker pane open; at an approval
boundary, HITL stop, revision, or completion, close every completed worker pane whose report and
gate decision are already recorded.

## Status and context recovery

Status is read-only and derives progress from `state.json`, digest-bound files, structured lifecycle
events, and optional CMUX surface health. It never treats pane text or a worker narrative as success:

```bash
python3 scripts/planning_state.py status --run-dir <run-dir>
python3 scripts/planning_state.py resume --run-dir <run-dir>
python3 scripts/planning_state.py context --run-dir <run-dir>
```

Workers must never change the Git index or HEAD; staging and committing belong to the human
after the run. `compare_tree` compares the whole before/after `staged_diff` independently of
the allowed-write list. Any difference gates `integrity-violation`, including staging an
allowed report or candidate path in a non-ignored custom run root. Ordinary permitted artifact
content writes and an unchanged pre-staged human baseline remain allowed.

The product-tree integrity boundary includes untracked content (regular files up to 8 MiB and
symlink target bytes); ignored files and skipped untracked content remain outside coverage.

The status JSON reports the run and repository, task/source digest, copied and normalized grilling
identities, revalidation progress, exact stage/mode/pass, prepared snapshot validity, live or last-known
pane, pending report, latest review verdict and candidate digest, both digest-bound approvals, staging
and publication phase, consistency errors, and one recommended next command. Its classifications
distinguish awaiting or interrupted grilling revalidation, spec authoring/review, ticket authoring/review,
pending model-diversity confirmation, pending report, both approval boundaries, requested revision,
review-blocked, HITL, completed, and inconsistent state. A `pending-diversity-confirmation`
classification includes the warning, but its decision status controls the recovery guidance. A
`pending` decision means awaiting confirmation and recommends the exact
`diversity-confirmation --decision confirm` command. A `refused` decision is a recorded refusal and
recommends human inspection and configuration recovery through `context`; it never recommends
confirmation. The short action text refers to a diverse profile in the shared configuration.
For the exact file and assignment, inspect `shared_configuration_path` and `assignment_path` in the
`diversity_confirmation` payload returned by `status`; it names the role of the stage that is
blocked (`workflows.planning.spec`, `workflows.planning.tickets`, or `workflows.planning.reviewer`).
Initialization persists a validated `input` checkpoint before activating the first
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
  readiness protocol and the same baseline-bound prompt. Always observe again on recovery before input.
  After delivery, inspect the visible screen:
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

The recovery prompt includes the reason plus prior candidates, reports, reviews, and feedback only by
their finalized manifest identities; failed panes, snapshots, events, and handoffs remain in history.
Unexpected files are listed as audit information and are never attached implicitly. A dead author gets
a new author pass. A dead reviewer gets a new reviewer pass over the unchanged author identity. A
blocked review routes back to an author and cannot be relabeled as another reviewer pass. If ticket
review found an approved-spec defect, use `ticket-approval --decision revise --scope spec` so the full
spec author/review/approval sequence repeats.

## Gate the author and reviewer

After author completion:

```bash
python3 scripts/planning_state.py accept-author --run-dir <run-dir>
```

This verifies the after-tree, validates grounding, report structure, exact draft path, specification
sections, and test seams, then advances only to `spec-review` and prepares a fresh reviewer snapshot.

After independent review:

```bash
python3 scripts/planning_state.py accept-review --run-dir <run-dir>
```

`pass` binds the unchanged draft's manifest identity. `pass_with_fixes` requires a complete corrected candidate and
structured correction summary; deterministic validation leads directly to human approval without
another automatic model review. `blocked` preserves evidence and requires human input plus a new author
pass. A malformed, ungrounded, drifting, digest-mismatched, or open-decision candidate never reaches
approval. A malformed attempt is closed with all captured files preserved; a later `prepare` arms a
new attempt-specific path set. A candidate left by an older attempt is stale audit evidence: it neither
blocks a legitimate current `pass`/`blocked` verdict nor becomes the current approval candidate.

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
pane. Gate its report with:

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

Each run records `workflow: planning`, `layout_version: 1`, and an initially empty `deliverables` object.
`tracker.slug` must equal the frozen `tracker_slug` at author, review, approval, and publication
gates. The `tracker_contract.py` commands `proposal`, `author-report`, and `review-report` accept
optional `--tracker-slug` to check this equality outside the run; the orchestrator supplies the frozen
value at its gates. This does not authorize ticket revision after approval.

Publication records `deliverables.tracker` alongside `published_tracker`. The frozen `tracker_slug`
is derived from the task (at most 30 characters); `init --slug <value>` overrides it with lowercase
words separated by hyphens. Default ids are `plan-<tracker_slug>-<YYYY-MM-DD>-<HHMM>` (UTC).
Legacy runs under `.scratch/orchestrator/planning-runs/` cannot continue; inspect read-only and obtain
a human decision to restart or use a separately reviewed migration procedure.

Runs live under `.scratch/orchestrator/runs/<run-id>/` by default. `task.md`, optional `inputs/`,
`grilling-input.json`, `artifacts/`, `reports/`, `prompts/`, `stage-snapshots/`, `tree-snapshots/`,
`state.json`, and `events.jsonl` are the recovery record. Approved native trackers contain `README.md`,
`spec.md`, `map.md`, `decisions.md`, and `issues/` at the explicit target. That target is immediately
consumable by `cmux-issue-chain`: inspect its first ready issue, then initialize issue execution as a
separate workflow.

`artifact_manifest` is the trust list for run files; `current_attempt` declares only the writable paths
for the armed worker, `attempt_history` closes earlier emissions without deleting them, and
`artifact_audit` lists stale finalized identities and unexpected files. Unexpected files do not become
trusted merely because their names resemble a draft, report, or reviewed candidate. Absolute paths,
traversal, symlink escape, role-location substitution, kind substitution, and digest or byte-size drift
all fail before consumption. Finalized identities are never rewritten or adopted as a fresh baseline.

Treat malformed reports, digest drift, dead panes, expired waits, blocked decisions, and integrity
violations as evidence for human resolution. Never infer approval from prose, edit product code from
the planning orchestrator, silently repair the working tree, or claim detection coverage for ignored
files or skipped untracked content (files above the 8 MiB size cap or unsupported types). An unreadable
or vanished untracked path fails capture with a diagnostic naming it instead of being skipped; restore
access or remove the path and retry. Git only warns about an unreadable untracked directory, so its
contents stay invisible rather than failing capture. Canonical persisted artifacts are English, literal
product copy keeps its actual language, and human questions and walkthroughs use the user's language.

Upgrade note: affected in-flight planning runs with pre-change untracked baselines must restart after
upgrading. Do not migrate those baselines or bypass their seals.

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
python3 scripts/test_worker_readiness.py
```

It uses fake workers and fake CMUX to cover a direct task, both author/reviewer stages, a safe
`pass_with_fixes`, both human approvals, publication, and initialization of the first ready issue
through the sibling issue-chain source when this development repository contains it.
