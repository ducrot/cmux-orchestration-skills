---
name: cmux-planning
description: Coordinate sequential visible CMUX planning workers that turn plan files or a confirmed conversation brief, with optional human-revalidated cmux-grilling input, into an approved repository-grounded specification and a reviewed native executable issue tracker. Use for cmux planning, task-to-spec workflows, vertical ticket decomposition, reviewed local specifications and trackers, optional grilling handoffs, planning run initialization, approval, revision, and collision-safe tracker publication. Do not use this skill to implement product code or to skip either approval boundary.
---

# CMUX Planning

Turn persisted inputs into a specification, then a native issue tracker, each independently reviewed
and explicitly approved. The orchestrator coordinates without authoring artifacts or editing product code;
each author and reviewer gets a fresh, visibly labeled CMUX pane.
Optional upstream `cmux-grilling` stress-tests uncertain decisions; downstream `cmux-issue-chain`
executes published trackers. Neither is invoked here; all three workflows work independently.

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
  `git update-ref HEAD <P> <C>` to undo its proven commit. Workers must never change the Git index or
  HEAD.

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
- Two explicit integrity boundaries apply. The product-tree detector covers tracked changes, staged
  changes, untracked paths and their content (regular files up to the 8 MiB size cap and symlink
  target bytes), and HEAD movement. It does not cover ignored product files or skipped untracked
  content (files above the size cap or unsupported types), or contents of unreadable untracked
  directories omitted by Git with a warning. Separately, every trusted file in the Git-ignored run
  directory is finalized in `state.json`'s artifact manifest with its canonical run-relative path,
  kind, stage, pass, attempt, byte size, SHA-256, producer event, and immutable status. A baseline
  arms one pass and is never recaptured against different product-tree bytes, so a relaunch cannot
  adopt an unauthorized delta as its new "before".
  Before each launch, capture complete Git status, tracked and staged diffs; after the report,
  compare paths and diff content. Any unauthorized Git-visible delta gates HITL regardless of report;
  never silently revert it. `compare_tree` compares the whole before/after `staged_diff` independently
  of the allowed-write list. Any difference gates `integrity-violation`, including staging an allowed
  artifact in a non-ignored custom run root. Ordinary permitted artifact content writes and an
  unchanged pre-staged human baseline remain allowed.
  An unreadable or vanished untracked path fails capture with a diagnostic naming it instead of
  being skipped; restore access or remove the path and retry. Git only warns about an unreadable
  untracked directory, so its contents stay invisible rather than failing capture.
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

All three skills vendor `scripts/agents_config.py` schema-v3 CLI, requiring `planning.spec`,
`planning.tickets`, and `planning.reviewer`. Authors default to `claude-fable-high`, reviewer to
`codex-astra-high`. All roles accept Claude Code, Codex or Pi; model diversity, not a fixed reviewer
harness, enforces independence. Pi requires a provider-qualified model (`provider/id`, e.g.
`openrouter/z-ai/glm-5.3`): preflight is model-scoped because Pi lacks provider-wide auth status.
`validate` and `show-resolved` are read-only and never migrate schema v1 or v2; all planning preparation
commands likewise stop before launchable state and display the exact preview and acceptance commands.

A schema-v3 file needs no migration question; an existing valid file needs no start confirmation.
Ask about starting only for a newly created default (`--accept-config`). Never offer profile overrides the human did not ask for.

Read when init creates configuration or detects schema v1 or v2: [references/configuration-migration.md](references/configuration-migration.md).

Read when installing planning or setting it up for first use: [references/installation.md](references/installation.md).

## Initialize

Before a fresh init: unfinished-run check (exit 3), commit mode, language, draft and confirm the
conversation brief, then init. Use [references/conversation-brief.md](references/conversation-brief.md)
for its six English headings, human-language content and verbatim quotes; show it fully as its own message,
then confirm it with one `AskUserQuestion` single-select as described there.
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

Direct input starts at `spec` with an immutable prepared snapshot. If author and reviewer share a
harness and model, init instead prints an extra warning object (`prepared: null`) before the run
directory, exits with code 2, and awaits confirmation at `spec` without a snapshot. Grilling starts at
`awaiting-grilling-revalidation` without a snapshot.

Read when inspecting configuration acceptance fields or opening a legacy run: [references/configuration-compatibility.md](references/configuration-compatibility.md).

Read when choosing init examples, relative paths, or retry behavior: [references/initialization-details.md](references/initialization-details.md).

## Run briefing

After `planning_state.py init` (including diversity-gated exit 2 or grilling awaiting revalidation),
show a compact briefing before the first `pane_ctl.py launch`:

```bash
python3 scripts/run_briefing.py draft --run-dir <run-dir> --lang <de|en>
# Replace {{task}} and {{constraints}} in <run-dir>/briefing.md, then:
python3 scripts/run_briefing.py show --run-dir <run-dir> --lang <de|en>
```

- `draft` fills task source, stage flow and tracker slug in `briefing.md` and never overwrites an existing one.
  Pick `--lang` by the human's language. From input copies (legacy `task.md`) and optional grilling,
  fill `{{task}}` with two or three sentences on the plan and `{{constraints}}` with fixed constraints
  and non-goals. Use neutral wording; preserve fixed lines and order.
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

For `spec`, `spec-review`, `tickets`, or `tickets-review`, use the current pass from `state.json`:

```bash
python3 scripts/render_prompt.py --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/tree_integrity.py baseline --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --stage <stage> --pass <n> \
  --anchor <caller-surface>
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --stage <stage> --pass <n> \
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

`start-agent` emits one JSON line with the launch and marker identity; its default
`--settle-seconds 0` performs no screen read. The watcher has a five-minute `--start-minutes`
window for the current attempt's `started` marker, whose nanosecond modification time must be at
least the launch's `start_time_ns`. A non-empty report arriving first also confirms the start only when its
`st_mtime_ns >= start_time_ns`; stale reports remain pending. Markers are
mutable declared writes, never immutable manifest artifacts. The report deadline counts from the persisted first arm.

For a local interactive Claude Code orchestrator (2.1.288 or later), use Bash
`run_in_background`: background tasks have no time limit and produce one wake-up at exit.
For other hosts and unattended sessions, use Monitor with re-arm (30 minutes by default,
up to 2 hours). If Monitor expires before the watcher exits, re-arm the same command.

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

After `accept-author` or `accept-review` records the captured report's gate decision, close its pane:

```bash
python3 scripts/pane_ctl.py close --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id> --force
```

`close` records `pane.closed`. Repeated `mark-started` for a confirmed stage pass writes no second
event and reports `"already_recorded": true`, making recovery replay safe. Never close a pane with a
pending report. Keep only the orchestrator and current worker panes; at approval, HITL, revision, or
completion, close completed workers with recorded reports and gate decisions.

## Status and context recovery

Read when resuming a run, recovering context, or inspecting status: [references/status-commands.md](references/status-commands.md).

Read when resuming a run, recovering context, or following a status recovery recommendation: [references/status-recovery.md](references/status-recovery.md).

## Gate the author and reviewer

After author completion:

```bash
python3 scripts/planning_state.py accept-author --run-dir <run-dir>
```

This checks after-tree, grounding, report structure, exact draft path, spec sections and test seams,
then advances only to `spec-review` with a fresh reviewer snapshot.

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

Repeated approval is idempotent only with an unchanged candidate digest. A changed draft or candidate
stales approval and blocks continuation.

## Ticket author and independent review

Run `tickets` as in Run one stage.
Authors receive only the immutable approved spec, task, repository identity, tracker ground rules,
vertical-slice policy, native proposal schema, revision feedback, and exact handoff paths. Its JSON
proposal is authoritative; `tracker_contract.py render-summary` renders its exact numbered summary.

Gate a clean report with `accept-author` as above. It validates approved-spec identity, proposal structure, summary equality, ticket count, ready
frontier, genuine blockers, cycles, qualitative sizing, merge/split rationale, and wide-refactor
sequences, then prepares a fresh immutable `tickets-review` snapshot. Run that stage in a new visible
pane; gate its report with `accept-review` as above.

The tickets reviewer returns `pass`, `pass_with_fixes`, or `blocked`. Safe fixes may correct only
established intent and lead directly to human approval after deterministic validation. A substantive
ticket boundary, dependency, product, scope, behavior, priority, architecture, or approved-spec defect
blocks. An approved-spec correction invalidates the proposal and restarts spec author, spec review, spec
approval, ticket author, and ticket review.

## Ticket approval, staging, and publication

At `awaiting-ticket-approval`, load the deterministic walkthrough before asking the human:

```bash
python3 scripts/planning_state.py ticket-approval-view --run-dir <run-dir>
```

Show a compact numbered list: title, blocked by, and what to build (`delivered_behavior`) per ticket.
Below it, state the review verdict, its correction summary, and any wide-refactor exceptions, because
safe reviewer fixes reach this gate without another author pass. Provide full acceptance criteria and
merge/split rationale on request. The view also includes the ready frontier, blocking edges, and
author/candidate diff.

Ask one `AskUserQuestion` with three single-select questions in the human's language (translate these
questions and options):

- Granularity: fits / too coarse / too fine
- Edges: correct / needs correction
- Merge/Split: no change / change

If any answer differs, ask a concrete follow-up to identify the affected tickets and requested change.
Record that reason below; require a fresh ticket pass, a new review, and a new quiz. If the follow-up
reveals an approved-spec defect, use `--scope spec` to restart the complete spec sequence instead:

```bash
python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \
  --decision revise --reason <concrete-change>
python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \
  --decision revise --scope spec --reason <approved-spec-defect>
```

Only when all three answers are positive (fits, correct, no change), ask for the target path and approve.
Spec approval keeps its existing flow without a fixed quiz.

Approval freezes the exact reviewed proposal digest, stages `README.md`, `spec.md`, `map.md`,
`decisions.md`, and every native issue file under the run directory, and validates the complete staged
tracker with this skill's standalone native contract. The target must remain absent and its basename must
equal the approved lowercase kebab-case tracker slug:

```bash
python3 scripts/planning_state.py ticket-approval --run-dir <run-dir> \
  --decision approve --reason <human-reason> --target <repo-relative-or-absolute-target>
```

After approval and successful staging, publish in one same-filesystem directory move:

```bash
python3 scripts/planning_state.py publish --run-dir <run-dir>
```

Publication refuses path escape, collisions, changed approved identities, malformed or partial issue
sets, duplicate IDs, unknown blockers, cycles, changed staging, and second publication. Staging or
validation failure leaves the target unchanged and records diagnostics for human resolution.

Read when recovering interrupted ticket staging or publication: [references/ticket-publication-recovery.md](references/ticket-publication-recovery.md).

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

After Commit following successful `publish`, or a halting gate (`hitl`, `blocked`, or `stop`):

```bash
python3 scripts/run_briefing.py recap-draft --run-dir <run-dir> --lang <de|en>
# Replace {{outcome}} in <run-dir>/recap.md, then:
python3 scripts/run_briefing.py recap-show --run-dir <run-dir> --lang <de|en>
```

Read when drafting the run recap or selecting its next issue: [references/recap-draft.md](references/recap-draft.md).

- Fill only `{{outcome}}`: one or two neutral sentences on the approved plan's delivery, or the halt
  reason and required human decision.
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

`artifact_manifest` trusts run files; `current_attempt` declares armed-worker writable paths;
`attempt_history` closes earlier emissions without deletion; `artifact_audit` lists stale identities
and unexpected files. Draft/report/candidate-like names confer no trust. Absolute paths, traversal,
symlink escape, role-location or kind substitution, digest or byte-size drift fail before consumption.
Finalized identities are never rewritten or adopted as a fresh baseline.

Treat malformed reports, digest drift, dead panes, expired waits, blocked decisions, and integrity
violations as evidence for human resolution. Never infer approval from prose, edit product code from
the planning orchestrator, silently repair the working tree, or claim coverage beyond the Ground rules
integrity boundary.

In-flight runs with pre-change untracked baselines must restart after upgrading; never migrate
those baselines or bypass seals.

## Scripts

Use `planning_state.py` for the planning lifecycle and `run_briefing.py` for briefing and recap generation.
`run_commit.py propose` owns `commit.proposed` (see Event Vocabulary).

## Event Vocabulary

`commit.attempted`, `commit.created`, `commit.skipped`, and `commit.failed` are written only by
`run_commit.py commit`: attempt before Git, proven success, nothing to commit, or proposal fallback.

`run_commit.py propose` validates published literal leaf paths and alone writes `commit.proposed`
after publication: exact file list, message draft, proposal ID, and ignored/preexisting classifications.

Read when changing planning or preparing an offline smoke run: [references/verification.md](references/verification.md).
