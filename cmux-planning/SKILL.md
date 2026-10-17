---
name: cmux-planning
description: Coordinate sequential visible CMUX planning workers that turn plan files or a confirmed conversation brief, with optional human-revalidated cmux-grilling input, into an approved repository-grounded specification and a reviewed native executable issue tracker. Use for cmux planning, task-to-spec workflows, vertical ticket decomposition, reviewed local specifications and trackers, optional grilling handoffs, planning run initialization, approval, revision, and collision-safe tracker publication. Do not use this skill to implement product code or to skip either approval boundary.
---

# CMUX Planning

Turn persisted planning inputs into an independently reviewed, explicitly approved specification and then
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


## Commit mode at initialization

Before a fresh init whose invocation does not already name `--commit-mode`, ask one `AskUserQuestion`
single-select in the human's language: "How should this run handle its commit?" /
"Wie soll dieser Lauf mit seinem Commit umgehen?" Offer `propose` first and recommended:
"Show proposal only" / "Nur Vorschlag zeigen"; then `commit`: "Commit automatically" /
"Automatisch committen". Pass `init --commit-mode commit|propose`; use an explicit mode without asking.
Never on resume, re-init, the exit-3 unfinished-run path, or smoke tests. Inspect unfinished runs
first; ask only after the human chooses a fresh run. Default and legacy mode: `propose`;
stored choices cannot change. Briefing ends with `Commit: automatic|proposal` (`automatisch|Vorschlag`).

## Artifact language at initialization

After commit mode, before default assignments, ask one `AskUserQuestion` single-select in the
human's language: "Which language should spec and ticket content use?" Offer English first
and recommended, then the human's language if not English; Other allows free text.
Use an explicit `--artifact-language` without asking. Same fresh-run checks; never on resume, re-init, exit-3, or smoke tests.

Pass `init --artifact-language <name>`: a non-empty English language name, at most 40 characters
(e.g. `German`), default English. Stored as `artifact_language`, immutable; a different re-init
value is refused. Legacy reads default to English. Briefing adds `Language: …` / `Sprache: …`
only with the field, before Commit.

## Default assignments at initialization

After both questions, with the same exceptions, run `python3 scripts/agents_config.py compare-defaults`
with the run's `--config` if valid schema v3 exists (including after migration).
Continue when `matches_defaults` is true.

Read when `compare-defaults` reports `matches_defaults: false`: [references/default-assignments.md](references/default-assignments.md).

## Ground rules

- Only after successful completion, the orchestrator's new Git writes through `run_commit.py commit`
  are literal leaf `git add`, `git commit`, path-limited `git reset -q --`, and compare-and-swap
  `git update-ref HEAD <P> <C>` to undo its proven commit. Never `--no-verify`; workers retain their
  index and HEAD prohibition. A HITL issue run always proposes.

- Copy plan files unchanged to `inputs/task-files/NN-<basename>` and the confirmed brief to
  `inputs/conversation-brief.md`; record `state.inputs`.
  Legacy `state.task` / `task.md` works; preserve each input's language.
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
- Questions and walkthroughs use the user's language; inputs keep their original language. Spec and ticket
  content follow the chosen language (`artifact_language`). Headings, markers, JSON keys, reports,
  state, events, and prompts stay English; preserve literal product copy. Field-level rules,
  including English `technical_layers` and fixed labels: [references/spec-contract.md](references/spec-contract.md).
- Each ticket is a narrow but complete vertical slice. Never default to frontend/backend/database/test
  tickets, never persist token counts or estimates, and evaluate merge opportunities as explicitly as
  split points. Standalone prefactors (`slice_type: prefactor`) come first and block the slices they
  prepare. Blocking edges must be genuine and every blocker has a smaller ticket ID.
- Only a passing reviewed ticket candidate may be staged. Publication is a collision-checked atomic
  directory move into the target repository and never invokes `cmux-issue-chain` or
  `adopt_tracker.py` at runtime.

Read [references/spec-contract.md](references/spec-contract.md) when judging author or review
handoffs.

## First-use configuration checkpoint

Read when preparing workers for the first time, upgrading harnesses or snapshots, or diagnosing trust preflight refusal: [references/preparation-upgrades.md](references/preparation-upgrades.md).

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v3. Older separately installed sibling skills cannot read the migrated schema-v3 shared configuration.

Codex workers use `-c tui.animations=false` to disable decorative motion on the welcome screen,
shimmer, and spinner, so the screen that readiness checks read stays stable. They also use
`-c tui.disable_paste_burst=true` to disable Enter suppression after a typed burst, so
exception-path `deliver` submits text with a single Enter.

All three independently shipped skills vendor the same `scripts/agents_config.py` schema-v3 CLI.
It requires `planning.spec`, `planning.tickets`, and `planning.reviewer`. Authors default to
`claude-fable-high` and the reviewer to `codex-astra-high`. Every role accepts Claude Code, Codex
or Pi; the reviewer carries no fixed harness, and its independence from the authors is enforced by
the model-diversity gate below instead. A Pi model must name its provider (`provider/id`, such as
`openrouter/z-ai/glm-5.3`), because Pi has no provider-wide auth status and its preflight check is
scoped to the model it is given.
`validate` and `show-resolved` are read-only and never migrate schema v1 or v2; all planning preparation
commands likewise stop before launchable state and display the exact preview and acceptance commands.

A schema-v3 file needs no migration question.
An existing valid schema-v3 file needs no start confirmation either; the start question belongs only to a newly created default (accepted with `--accept-config`). Never offer profile overrides the human did not ask for.

Read when init creates configuration or detects schema v1 or v2: [references/configuration-migration.md](references/configuration-migration.md).

Read when installing planning or setting it up for first use: [references/installation.md](references/installation.md).

## Initialize

Before a fresh init: unfinished-run check (exit 3), commit mode, language, draft and confirm the
conversation brief, then init. Use [references/conversation-brief.md](references/conversation-brief.md)
for its six English headings, human-language content and verbatim quotes; show it fully for confirmation.
Require a plan file or brief; grilling is additional. Explicit brief decisions beat revalidated grilling
decisions, which beat plans; other contradictions go to `Open Decisions`.

Repeat `--task-file` for multiple plans:

```bash
python3 scripts/planning_state.py init --task-file <path> --repo <repo> \
  --workspace-id <workspace> [--artifact-language <name>] [--config <agents.json>] [--accept-config]
```

For conversation input, pass `--conversation-brief <path> --brief-confirmed`, optionally alongside
plan files. For grilling input,
also pass `--grilling-json <result.json>` and optionally the exact `--grilling-markdown <result.md>`.
The JSON's `markdownPath` remains authoritative. Missing, malformed, path-inconsistent,
repository-mismatched, or ambiguous pairs fail before any launchable state or pane exists.

Direct input starts at `spec` with an immutable prepared snapshot, unless the resolved author and
reviewer share a harness and model: that start prints one extra warning object with `prepared: null`
before the run directory, exits with code 2, and leaves `spec` waiting on the confirmation described
below with no snapshot. Grilling input starts at `awaiting-grilling-revalidation` with no
snapshot.

Read when inspecting configuration acceptance fields or opening a legacy run: [references/configuration-compatibility.md](references/configuration-compatibility.md).

Read when choosing init examples, relative paths, or retry behavior: [references/initialization-details.md](references/initialization-details.md).

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
- Fill placeholders from input copies (legacy `task.md`) and the optional grilling pair:
  `{{task}}` is what will be planned in two or three sentences; `{{constraints}}` lists the fixed
  constraints and non-goals. Neutral wording; keep the fixed lines and their order unchanged.
- `show` refuses while a placeholder remains, prints the briefing, records `run.briefing`, and sets
  the sidebar pill `cmux-planning-run` (`Planning · <slug>`) in the pinned workspace. A failed pill is
  a stderr note, not a stop. Relay the printed briefing verbatim as its own message, without preamble.
- The scripts publish the board automatically at transitions in the pinned workspace. A failed board
  update is a stderr note and never a stop. `--no-status` suppresses pill and board on
  `run_briefing.py`; `planning_state.py` publishes whenever a workspace is pinned (`--no-workspace` avoids it).
- On resume, run `show` again after `context` and status. `briefing.md` is orchestrator text, not a
  worker artifact: the artifact audit skips it and no prompt attaches it.

Read when initialization supplied a grilling input pair: [references/grilling-revalidation.md](references/grilling-revalidation.md).

Read when preparation reports a same-harness-and-model diversity warning or a pending diversity decision: [references/model-diversity.md](references/model-diversity.md).

## Worker input readiness

The normal start attaches the baseline-verified assignment to `start-agent`; the armed watcher
confirms its first-step marker without a screen judgment. For exception-path input and follow-ups,
use [Interactive worker readiness](references/worker-readiness.md): `observe`, explicitly `assess`,
resolve pending dialogs, then use one readiness-gated delivery. Read each result before the next
input. The gate applies to Codex, Claude Code and Pi. `worker.ready` permits one delivery and is
distinct from `worker.started`; observe again before recovery input.

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
# Watcher exits: 0 report, 7 pane dead, 8 deadline, 9 assignment not started.
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

`start-agent` emits one JSON line with the launch and marker identity; its default
`--settle-seconds 0` performs no screen read. The watcher has a five-minute `--start-minutes`
window for the current attempt's `started` marker, whose nanosecond modification time must be at
least the launch's `start_time_ns`. A non-empty report arriving first also confirms the start only when its
`st_mtime_ns >= start_time_ns`; stale reports remain pending. Markers are
mutable declared writes, never immutable manifest artifacts. The report deadline counts from the persisted first arm.

For a local interactive Claude Code orchestrator (2.1.288 or later), use Bash
`run_in_background`: background tasks have no time limit and produce one wake-up at exit.
For other hosts and unattended sessions, use Monitor with re-arm (30 minutes by default,
up to 2 hours). If Monitor expires before the watcher exits, re-arm the same command;
this resumes the persisted deadline and does not grant more time.

```
Bash(
  command: "python3 scripts/await_report.py --run-dir <run-dir> --stage <stage> --pass <n> --surface <launch-surface-id>",
  run_in_background: true
)
```

Both deadlines are persisted on first arm in a `worker.waiting` event, keyed to the
current launch IDs and stage/pass or round. Every invocation computes the remaining time;
re-arming, including after a host timeout, never moves either deadline. Initial
`--deadline-minutes` overrides the minimum for a bounded smoke run. For the one extension,
pass `--deadline-minutes <additional-minutes> --deadline-reason "<recorded reason>"`;
the watcher records the reason and grants that duration from the later of the existing
deadline and extension arm. Repeating the same extension is idempotent; a second extension
is refused. The start window is not extended by this flag. A recorded exit-9 recovery
(`respond` or screen-confirmed `mark-started`) or `deliver` creates a new first-arm window
without spending the extension; merely observing, assessing, or re-arming does not.
New launch IDs also start new windows. Never run two watchers for the same work concurrently.

Planning keeps its human-approved `resume --decision extend --reason "<reason>"` boundary.
An explicit `--deadline-reason` requires that recorded approval and must match its reason.
The recommended `--extension 1` consumes that recorded approval and persists one extension
using `--deadline-minutes` (or the stage minimum when omitted); rejoining it cannot renew it.

| Exit | Meaning |
| --- | --- |
| 0 | Report captured; validate and gate it. |
| 7 | Pane dead; stop at the existing HITL recovery boundary. |
| 8 | Report deadline; use the existing human-approved extension rules. |
| 9 | Assignment not started; inspect the exception path below. |

Exits 7 and 8 publish `hitl` on the sidebar board. The recorded extension or relaunch decision returns the card to `running`.

Read when the watcher exits 9 before confirming assignment start: [references/startup-recovery.md](references/startup-recovery.md).

Event vocabulary: `worker.starting` and `worker.launch_sent` bind launch time and assignment identity;
`worker.started` confirms assignment execution with marker, report, or exception-path
`evidence: "screen"`. Readiness events are exception-path and follow-up only.
`worker.waiting` includes `not_started` (exit 9) as well as report, pending, pane_dead, and deadline.

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

Read when resuming a run, recovering context, or inspecting status: [references/status-commands.md](references/status-commands.md).

Workers must never change the Git index or HEAD. After the run, the orchestrator commits in commit
mode and the human commits otherwise; push, PR, and CI stay with the human. `compare_tree` compares the whole before/after `staged_diff` independently of
the allowed-write list. Any difference gates `integrity-violation`, including staging an
allowed report or candidate path in a non-ignored custom run root. Ordinary permitted artifact
content writes and an unchanged pre-staged human baseline remain allowed.

The product-tree integrity boundary includes untracked content (regular files up to 8 MiB and
symlink target bytes); ignored files and skipped untracked content remain outside coverage.

Read when resuming a run, recovering context, or following a status recovery recommendation: [references/status-recovery.md](references/status-recovery.md).

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

- proposed test seams as a separate block before the specification;
- the complete reviewed specification and reviewer verdict;
- the correction summary and human-visible draft/candidate diff;
- assumptions and decided/deferred items;
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

Run the prepared `tickets` stage with the same render → baseline → `launch` → `start-agent` → `await_report.py` sequence.
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

## Commit

After successful `publish`, record a proposal with `run_commit.py propose` for the published
`README.md`, `spec.md`, `map.md`, `decisions.md`, and `issues/<file>` leaf files. Build the file list as
repository-relative literal leaf paths from `git status --porcelain=v1 -z --untracked-files=all` under
`published_tracker.path`, never a directory or an expanded glob. Pass each leaf with `--file`, and
exclude unrelated changes from the proposal while listing them with `--ride-along`. Use an English
one-line subject explaining what changed and why, an optional body, and no trailers.

```bash
python3 scripts/run_commit.py propose --run-dir <run-dir> --subject "Publish approved implementation tracker" --file <tracker>/README.md --file <tracker>/spec.md --file <tracker>/map.md --file <tracker>/decisions.md --file <tracker>/issues/<file>
```

The helper records the replay-safe proposal, including ignored and pre-run dirty classifications.

In commit mode, next run `python3 scripts/run_commit.py commit --run-dir <run-dir>` before the recap.
Use a background or long-timeout invocation with enough time for the repository's commit hooks;
a killed call leaves a `commit.attempted` without an outcome.
Never commit for a HITL issue run (`chain: []`): HITL always proposes, regardless of the stored mode.
Never commit after `hitl`, `blocked`, or `stop`. In propose mode, show the recorded proposal.
The orchestrator commits in commit mode; the human commits otherwise. Push, PR, and CI stay with the
human. Never run `git push` and never `--no-verify`.

On resume, if `commit.attempted` has no outcome, run `run_commit.py commit` once before the recap;
never re-propose a changed draft. Recovery accepts only a matching parent and tree. The helper never
retries a commit: `commit.created` replays, and `commit.failed` or `commit.skipped` refuses another
attempt. A hook may fix planned files; the recap reports its changes and side effects. Foreign paths
in a proven commit cause a compare-and-swap undo unless a remote-tracking ref contains that commit.
An unverified outcome leaves Git untouched and names HEAD for human inspection.

## Run recap

The counterpart to the Run briefing. After the Commit step following successful `publish`, or after a halting gate that ends
the run (`hitl`, `blocked`, or `stop`):

```bash
python3 scripts/run_briefing.py recap-draft --run-dir <run-dir> --lang <de|en>
# Replace {{outcome}} in <run-dir>/recap.md, then:
python3 scripts/run_briefing.py recap-show --run-dir <run-dir> --lang <de|en>
```

Read when drafting the run recap or selecting its next issue: [references/recap-draft.md](references/recap-draft.md).

- Fill only `{{outcome}}`: one or two sentences on what the approved plan delivers, or for a halted
  run what stopped it and what the human has to decide. Neutral wording.
- `recap-show` refuses while the placeholder remains, prints the recap, records `run.recap`, and
  turns the sidebar pill into `✓ Planning · <slug>` (green) or `<decision> · Planning · <slug>` (red).
  `--clear-status` clears both pill and board, only when the human asks for it. Relay the printed recap
  verbatim as its own message. Like `briefing.md`, `recap.md` is skipped by the artifact audit.

## Artifact locations and failure policy

Each run records `workflow: planning`, `layout_version: 1`, and an initially empty `deliverables` object.
`tracker.slug` must equal the frozen `tracker_slug` at author, review, approval, and publication
gates. The `tracker_contract.py` commands `proposal`, `author-report`, and `review-report` accept
optional `--tracker-slug` to check this equality outside the run; the orchestrator supplies the frozen
value at its gates. This does not authorize ticket revision after approval.

Publication records `deliverables.tracker` alongside `published_tracker`. The frozen `tracker_slug`
uses the brief's Goal when present, otherwise the first plan's first heading (or first line, at most 30 characters); `init --slug <value>` overrides it with lowercase
words separated by hyphens. Default ids are `plan-<tracker_slug>-<YYYY-MM-DD>-<HHMM>` (UTC).
Legacy runs under `.scratch/orchestrator/planning-runs/` cannot continue; inspect read-only and obtain
a human decision to restart or use a separately reviewed migration procedure.

Runs live under `.scratch/orchestrator/runs/<run-id>/` by default. `inputs/` (legacy `task.md`),
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
contents stay invisible rather than failing capture. The Ground rules language split applies.

Upgrade note: affected in-flight planning runs with pre-change untracked baselines must restart after
upgrading. Do not migrate those baselines or bypass their seals.

## Scripts

`run_commit.py propose` validates published literal leaf paths and is the only writer of
`commit.proposed`. Use `planning_state.py` for the planning lifecycle and `run_briefing.py` for briefing
and recap generation. The scripts publish the board automatically at transitions; a failed board
update is a stderr note and never a stop.

## Event Vocabulary

`commit.attempted`, `commit.created`, `commit.skipped`, and `commit.failed` are written only by
`run_commit.py commit`: attempt before Git, proven success, nothing to commit, or proposal fallback.

`commit.proposed` is written only by `run_commit.py propose` after publication and carries the exact
file list, message draft, proposal ID, and ignored/preexisting classifications.

Read when changing planning or preparing an offline smoke run: [references/verification.md](references/verification.md).
