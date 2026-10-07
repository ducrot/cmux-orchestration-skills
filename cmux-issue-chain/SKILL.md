---
name: cmux-issue-chain
description: Coordinate gated visible CMUX worker chains for local Markdown issue trackers. Use when an orchestrating agent needs to run AFK issues through implement, simplify/refactor, test, harness-aware code review (Claude Code /code-review --fix or an inline review pass on other harnesses), reviewer self-fix handling, blocker handling, plan-drift handling, run-state logging, prompt rendering, worker report parsing, or cmux worker-pane workflows without directly editing product code.
---

# CMUX Orchestrator

Use this skill to run a local issue through a gated multi-agent workflow. The orchestrator is a coordinator only: it may update lifecycle state, run logs, snapshots, issue status/progress, gate decisions, and documented plan changes, but it must not edit product code.

All `scripts/…` and `references/…` paths in this skill are relative to the skill's own
base directory (the directory containing this SKILL.md); resolve them against that
directory, not the working directory.


## Commit mode at initialization

Before a fresh init whose invocation does not already name `--commit-mode`, ask one
`AskUserQuestion` single-select question in the human's language: "How should this run
handle its commit?" / "Wie soll dieser Lauf mit seinem Commit umgehen?"
Offer `propose` first and recommended: "Show proposal only" / "Nur Vorschlag zeigen";
offer `commit` second: "Commit automatically" / "Automatisch committen".
Pass the chosen mode to `init --commit-mode commit|propose`. When the invocation already
names the mode, use it without asking. Never on resume, on re-init, in planning's exit-3
unfinished-run path, or in smoke tests: reuse the stored choice. For planning, inspect
existing unfinished runs before asking; ask only after the human chooses a fresh run.
Omitting the flag at fresh init (including smoke tests) records `commit_mode: propose`.
Legacy runs without the field read as `propose`; an existing run's mode cannot change.
The briefing's final fixed line shows `Commit: automatic|proposal` (`automatisch|Vorschlag`).

Append an asked answer to `--invocation` as ` --commit-mode <mode>` so the next-run
prompt carries it. A prompt already naming the mode is recorded unchanged. The question
is still asked for a HITL issue even though it has no worker chain. Init derives the mode
from `--invocation` when the direct flag is omitted and refuses contradictory values.

## Default assignments at initialization

At the same point as the commit-mode question, with the same exceptions, run
`python3 scripts/agents_config.py compare-defaults` with the run's `--config` when that file
already exists as valid schema v3, including one just migrated. Continue when `matches_defaults`
is true.

Read when `compare-defaults` reports `matches_defaults: false`: [references/default-assignments.md](references/default-assignments.md).

## Worker Profile Configuration

Read when preparing workers for the first time, upgrading harnesses or snapshots, or diagnosing trust preflight refusal: [references/preparation-upgrades.md](references/preparation-upgrades.md).

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v3. Older separately installed sibling skills cannot read the migrated schema-v3 shared configuration.

Read when resolving the configuration path before init, creating or migrating configuration, or inspecting profiles: [references/configuration.md](references/configuration.md).

`run_state.py init` requires an existing configuration at that default or explicit path; it never
creates one. After the first-use checkpoint, it validates and preflights all four issue-chain roles
and prepares the `implement-1` stage snapshot before it publishes a launchable run. Pass
`--config <path>` to pin an explicit configuration source. After an advance gate, prepare the next
stage from the latest bytes at that pinned source before creating its pane:

```bash
python3 scripts/run_state.py prepare --run-dir <run-dir> --stage simplify --pass 1
```

Preparation accepts repeatable typed overrides in `WORKER=VALUE` form: `--profile`,
`--harness`, `--model`, `--effort`, and `--executable`. File assignment resolves first, then
profile selection, then direct field overrides. The same field may be overridden only once
per worker. Overrides live only in that stage snapshot; the next preparation reloads the file.
Every preparation validates every role, resolves each executable, captures `--version`, checks
required flags and authentication-status support through help output, and verifies local auth.
That local preflight is mandatory and detects capabilities rather than enforcing minimum CLI
versions. Provider entitlement stays `unverified` by default.

Opt into live entitlement checks on initialization or any later stage preparation with
`--probe-profiles`; use `--probe-timeout <seconds>` with it to change the CLI-only 120-second
default. The option makes one real request per unique named and fully resolved assigned profile,
after the whole workflow has passed validation and local preflight. Duplicate assignments share a
request and unused profiles are not contacted. Claude runs in safe, non-persistent print mode with
all tools disabled; Codex runs ephemerally in a read-only sandbox with approvals disabled. Each
probe's own options are checked against the CLI's help before its request goes out, so an
installation that cannot be probed reports a missing capability instead of a failed entitlement.
Both must exit zero and print exactly `CMUX_PROFILE_PROBE_OK_V1`. A nonzero exit, timeout,
malformed output, or missing sentinel fails preparation before pane creation. Success changes the matching
entitlement to `verified`; no probe leaves it `unverified`. The immutable snapshot audits the
configuration source and hash, overrides, resolved profiles, executable/version/preflight data,
final worker argv, probe enablement and timeout, and each probe's status and timing without saving
provider output, credentials, or ambient environment values. The launch command keeps the
configured executable as its program name; the resolved absolute path is audit data only.

Harness safety remains code-owned: JSON and typed overrides cannot supply free-form arguments,
environment values, capabilities, sandbox or approval policy, network access, writable roots,
prompt delivery, or other runtime safety overrides.

## Boundaries

- Only after successful completion, the orchestrator's new Git writes through `run_commit.py commit`
  are literal leaf `git add`, `git commit`, path-limited `git reset -q --`, and compare-and-swap
  `git update-ref HEAD <P> <C>` to undo its proven commit. Never `--no-verify`; workers retain their
  index and HEAD prohibition. A HITL issue run always proposes.

- Treat product code as worker-owned. Do not modify application, extension, frontend, deployment, or test implementation files from the orchestrator role.
- Write lifecycle state only: `.scratch/orchestrator/runs/<run-id>/`, local issue frontmatter/checklists, run logs, prompt files, worker reports, gate decisions, snapshots, documented plan changes, the tracker `decisions.md` triage ledger, and issue files from human acceptance or gated triage-worker acceptance in recommendations triage.
- Require workers to write structured reports to their exact rendered report handoff paths and return the
  same report body in the console. That exact report file is the only orchestration lifecycle state a worker
  may write; all other run state remains orchestrator-owned.
- Workers may also write task-specific artifacts in their rendered
  `.scratch/orchestrator/runs/<run-id>/artifacts/<role>-<pass>/` directory. Create it as needed for
  helper scripts, report drafts, logs, snapshots, and raw evidence; do not create ad-hoc
  `.scratch/issue-*` directories. Workers may read earlier workers' artifacts but write artifacts only
  in their own directory, and reference relevant files in their reports. Reusable tests belong in the
  repository's normal test locations, subject to role permissions. Keep artifacts after completion;
  the human deletes run directories manually. There is no automatic cleanup or retention deadline.
- Allow code-writing worker roles only for implementation, simplify/refactor, and code review in its self-fix pass. Test workers must inspect, run checks, and report findings without product-code edits.
- Allow simplify/refactor workers to apply behavior-preserving refactorings from their simplify pass themselves. They must not implement missing feature scope, change acceptance behavior, or perform broad hardening outside the issue.
- Allow review workers to apply the safe fixes from their review pass themselves. They must not broaden scope, implement unrelated features, or hand unresolved findings back to the implementer for another automatic loop.
- Stop the affected chain when an issue is `HITL`, blocked by unfinished prerequisites, or has an unresolved blocker.
- Start workers visibly in CMUX panes. Do not substitute hidden subagents, background shells, or non-CMUX subprocess workers for live orchestration.

## Default Chain

For an AFK issue, use this lifecycle unless the user requests a narrower run:

1. Implement with Codex. Testing is anchored here: the implementer proves the change with regression tests
   that fail without it and an end-to-end execution of the changed path.
2. Simplify/refactor, applying behavior-preserving refactorings when appropriate. On Claude Code the
   worker runs `/simplify`; on any other harness the rendered prompt spells out the same pass inline.
3. Orchestrator quick-check — an orchestrator step, not a worker pane: before recording the simplify gate,
   re-run the tracker's canonical check commands yourself (see Canonical Check Commands) and record an
   `orchestrator.verified` event with commands and outcomes. A red suite makes the simplify gate `stop`
   regardless of what the report claims.
4. Code review, applying review fixes when appropriate. On Claude Code the worker runs
   `/code-review medium --fix`; on any other harness the rendered prompt spells out a three-axis review pass
   (standards with a smell baseline, spec, correctness) inline.
5. Final test with Codex.
6. Recommendations triage is autonomous by default: a fresh visible `Triager 1 - <issue-id>` worker
   decides the collected items, then at most one follow-up pass applies accepted eligible items (see
   Follow-up Pass in `references/follow-up-pass.md`). Full flow:
   `test -> triage-1 -> (follow-up implement -> test -> triage-2) -> issue status -> complete -> commit proposal -> commit (commit mode) -> run recap + final summary -> wait`.
   Triage-2 runs only for new follow-up recommendations. Opt out at init with `--human-triage`.
   A run with nothing to triage completes directly from `test`, although its chain lists `triage`.

Run simplify/refactor after every implementation pass. Start the simplify, reviewer, and final tester workers fresh for each pass.

There is deliberately no test worker between simplify and review: it would re-run the suite the simplifier
already ran before and after its changes, and the review pass covers the full working diff, simplify
changes included — in the pilot runs a post-simplify tester found nothing three times while the one real
gap sailed past it and was caught by review. The final test after review is the one that stays: it is the
only check after the last code-changing stage, and reviewers must not accept their own fixes.

Simplify is an editing role, not a passive reviewer. If the simplify pass proposes behavior-preserving cleanup within the current issue scope, the simplify worker may apply it and must report changed files plus the checks used to confirm behavior preservation.

Review is an editing role, not a passive reviewer. If the review pass finds fixable review findings within the current issue scope, the review worker may apply those fixes and must report changed files plus the checks used to validate them.

## Review Self-Fix Policy

Run review as a self-fix pass (`/code-review medium --fix` on Claude Code, the inline three-axis pass elsewhere). The review worker fixes must-fix findings itself when they are safely fixable inside the issue scope.

Self-fix has an intent boundary. A finding that challenges a documented issue decision — the issue's
"What to build", its acceptance criteria, or a recorded plan change — is `Recommendation: ask-user`, not
must-fix: the review worker must not fix it even when a safe mechanical fix exists, because the fix would
silently undo a deliberate decision. It stays in `## Findings` and the orchestrator relays it to the human
verbatim — file and description unparaphrased, never pre-judged. Routine correctness, reliability, and
security fixes stay self-fixable even when the smallest fix re-adds a little previously deleted logic,
provided they preserve documented decisions.

An earlier-stage decision recorded in this run, including prior passes of the same run, is protected the
same way. Earlier-stage decisions include every item under `## Not Applied` and every behavior-preserving
kept choice explained under `## Change Summary` or `## Notes`. Unless explicitly superseded by recorded
human approval, the review worker never reverts one. If the fix pass reverted such an item without that
approval — `/code-review --fix` briefs its internal agents from the diff alone and does not see the
`## Not Applied` list — the worker restores it before running the baseline suite.

How the proposal is reported depends on its reason. A quality-only reason (reuse, simplification,
efficiency, altitude, style) is never a finding: the earlier decision stands, and the proposal goes under
`## Recommendations` marked `Counter-proposal`, naming the earlier decision and its report and linking any
proposal artifact. The chain advances and the human sees the proposal in triage. Only a correctness,
regression, acceptance, security, or data-safety reason makes it an ask-user finding. `Scope: other`
therefore never carries `ask-user`. The review worker does not re-report as a finding an item that an
earlier report of the run already queued for triage under `## Recommendations`.

Reports from unrelated runs are outside this same-run protection. Protection of Not Applied items and
documented intended behavior persists until recorded human approval explicitly supersedes the earlier
decision. The approval must identify the decision and the authorized replacement or scope. An agent
proposal, a later report, or an unapproved recommendation alone does not supersede it. Report unresolved
scope or precedence ambiguity as `Recommendation: ask-user`; do not apply the disputed change. A triage-worker verdict that the orchestrator recorded in
`decisions.md` after a passing triage gate counts as recorded approval while autonomous triage is
not opted out; such entries carry the marker `[triage-worker verdict, run <run-id>, gate advance]`.
Only non-opted-out runs produce the marker; a later opted-out run still honors it.

Correcting a regression introduced by an earlier refactoring remains a must-fix when the correction
preserves the documented intended behavior; changing that intended behavior still requires ask-user.

Do not route code-review findings back to the implementer for an automatic fix loop. The old review-driven `Implement -> Simplify -> Test -> Review` loop is disabled.

After review self-fix:

1. If the review report has no remaining must-fix findings, continue to the final Codex test.
2. If the review report has remaining must-fix or ask-user findings, a blocker, or unsafe fix uncertainty, record a `hitl` gate and stop.
3. If the final Codex test after review changes reports findings, record a `hitl` gate and stop unless the user explicitly authorizes another worker pass.
4. Review reports that contain only non-blocking recommendations may advance when `## Findings` is `None`.

Read when resuming after a confirming HITL: [references/resume-hitl.md](references/resume-hitl.md).

## Gate Rule

Advance only when the latest relevant worker report contains:

- `NO FINDINGS`
- Concrete tests/checks run
- No `BLOCKER`
- No unresolved `PLAN DRIFT`
- Every required section present and non-empty

`parse_report.py` decides this and emits one of five gate values. `run_state.py gate --decision` accepts the
same five. Never invent a sixth.

| Gate      | Meaning                                         | Exit code | Orchestrator action                |
|-----------|-------------------------------------------------|-----------|------------------------------------|
| `advance` | Clean report, tests run                         | 0         | Launch the next stage              |
| `stop`    | Findings, missing tests, or unclear `## Result` | 3         | Do not advance; triage             |
| `blocked` | Worker reported a `BLOCKER`                     | 4         | Stop the chain, record the blocker |
| `hitl`    | Plan drift, or a malformed report               | 5         | Stop; a human decides              |
| `pending` | Report not written yet                          | 6         | Keep waiting per the wait policy   |

The gate is the **most severe** triggered condition, not the last one evaluated: `blocked` > `hitl` > `stop` >
`advance`. A report carrying both a blocker and plan drift is `blocked`.

A required section (`## Result`, `## Blockers`, `## Plan Drift`) that is absent or empty makes the report
malformed and yields `hitl`. An omitted section never reads as `None`.

Review reports must separate blocking findings from non-blocking recommendations. Only `Recommendation: must-fix` and `Recommendation: ask-user` items belong in `## Findings`. Low-risk cleanup, broader hardening, speculative edge cases, nice-to-have improvements, and quality-only counter-proposals to earlier-stage decisions belong in `## Recommendations` and must not block the gate by themselves.

Unresolved must-fix or ask-user findings after the review worker's own self-fix pass become HITL. Do not launch another implementer or second reviewer automatically. Any blocker stops the issue chain and must be recorded in the issue and run log. Any major plan drift becomes a HITL blocker.

Read when a report fails formatting or contains quality-only findings: [references/report-recovery.md](references/report-recovery.md).

### Diff inspection at code-changing gates

Before recording the gate for any code-changing stage (implement, simplify, review), the orchestrator must
inspect the working diff itself: run `git status --short` and `git diff` (read-only) and compare what
changed against the issue's "What to build" and acceptance criteria. A clean report is not a substitute —
undocumented scope expansion gates `stop`, undocumented drift gates `hitl`, even when the report says
`NO FINDINGS`.

For every role (implement, simplify, review, test, and triage), compare `staged_paths` and
`staged_diff_sha256` in the launch snapshot (`launched <role>-<pass>`) against the capture
snapshot (`report-captured <role>-<pass>`) before recording its gate. A difference in either
field is an unauthorized delta: gate `hitl` even with a clean report, with the sorted union
of both snapshots' staged path lists in the gate reason (including when only the digest
changed). Also compare `head` between the same two snapshots: any HEAD change is an
unauthorized delta that gates `hitl` even with a clean report, with the before and after HEAD
values in the gate reason. The orchestrator never unstages on the worker's behalf. An unchanged
pre-staged human baseline is permitted. This index and HEAD check applies to test as well as
code-changing roles. For triage also compare the full `fingerprint`; any difference gates `hitl`.

Look for:

- files touched outside the issue's stated scope;
- product code changed where the issue only called for tests, docs, or config;
- new public API, hooks, or test seams added to production paths for the worker's own convenience;
- at the review gate, compare the review diff against the simplify report's `## Not Applied` list
  and documented kept choices in reports of the current pass and relevant prior passes of the same run.
  Include prior-pass `## Not Applied` lists in this comparison. Check any claimed supersession against
  recorded human approval identifying the decision and the authorized replacement or scope, including
  a marker-bearing triage-worker verdict as defined above. A reverted
  item without that approval or an `ask-user` finding gates `stop`. Record the reverted item in the
  `orchestrator.verified` event and relay it to the human verbatim as a finding, not a recommendation.
  Correcting a regression while preserving documented intended behavior is not a decision reversion
  and does not trigger this stop rule; changing that intended behavior still requires ask-user.
  An item the review worker restored and reported as a `Counter-proposal` under `## Recommendations`
  is not reverted in the diff and does not trigger it either.
- at the follow-up implement gate, compare the diff the pass added against the approved follow-up items:
  any edit outside them gates `stop`.

Record the inspection as an `orchestrator.verified` event with the commands used and a one-line verdict.
This is diff-reading only and distinct from the orchestrator quick-check, which re-runs the test suite
before the simplify gate; neither replaces the other. The product-code boundary holds: inspect, never edit.

## Canonical Check Commands

The tracker README's ground-rules section declares the canonical check commands for the tracker — at
minimum the test suite, optionally lint — as exact runnable commands. `render_prompt.py` embeds the ground
rules into every prompt, so every worker sees the same commands, and the prompt contract requires workers
to use them as the baseline suite instead of guessing their own. The orchestrator quick-check before the
simplify gate runs exactly these commands. Determinism is the point: implementer, tester, and quick-check
must not run three different suites.

Verify the declaration during run preflight, together with the branch check: if the ground rules declare
no runnable check commands, record a `hitl` gate instead of starting the chain — the human adds the
commands to the tracker README once, and every later run inherits them.

## Worker Wait Policy

Treat a missing worker report as `pending`, not as a failed gate. Never parse a missing report path as a failure condition. `parse_report.py` enforces this: a missing report prints `gate=pending` and exits 6 rather than raising. The gate can only evaluate after the worker has returned a final report, the worker pane has crashed/exited, or the wait policy below has been exceeded with evidence that the worker is idle.

Default minimum waits before intervention:

- Implementer: 45 minutes
- Simplifier: 30 minutes
- Tester: 30 minutes
- Triager: 30 minutes
- Reviewer: 90 minutes

A review pass (`/code-review medium --fix` on Claude Code in particular) can legitimately take 15 minutes or longer. Do not interrupt or fail a review worker just because no report appears during that window.

### Armed watcher, not polling

The orchestrator only exists within a turn; between turns nothing polls. Before ending any turn while a
worker pane is running, the orchestrator MUST arm a watcher that re-invokes it — ending a turn with a
worker running and no armed watcher is a policy violation. The watcher is `await_report.py`; it blocks on
the report handoff path (the ground truth), checks `cmux surface-health` for a dead pane, derives its
deadline from the role's minimum wait, and writes the `worker.waiting` heartbeats itself. For a local interactive Claude Code orchestrator (2.1.288 or later), use Bash
`run_in_background`: background tasks have no time limit and produce one wake-up at exit.
For other hosts and unattended sessions, use Monitor with re-arm (30 minutes by default,
up to 2 hours). If Monitor expires before the watcher exits, re-arm the same command;
this resumes the persisted deadline and does not grant more time.

The host timeout and worker deadline are separate: never shorten `--deadline-minutes`
to fit a Monitor cap (for example, 29 minutes under a 30-minute cap). A host timeout
is not exit 8 and calls for neither a screen check nor an extension, only the re-arm.
While the watcher runs, do not add sleeps, report-file polls, screen reads, or task-output
polls. Its start phase confirms the marker and continues in the same process; no separate
start-window watch is needed. After exit 0, capture and parse the report directly.
Outside input-readiness checks, reserve screen inspection for the documented exit-9
recovery or exit-8 intervention.

```
Bash(
  command: "python3 scripts/await_report.py --run-dir .scratch/orchestrator/runs/<run-id> --role review --pass 1 --surface <surface-id>",
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

Exit vocabulary: 0 = report, 1 = crash, 2 = usage, 3–6 = report gates, 7 = pane dead,
8 = deadline, 9 = not started. The watcher ends on exactly four conditions:

| Exit | Condition                             | Orchestrator action                                                                      |
|------|---------------------------------------|------------------------------------------------------------------------------------------|
| 0    | Report file exists                    | Snapshot, parse, gate — exit 0 is not an advance verdict                                 |
| 7    | Pane dead per `cmux surface-health`   | Stop as HITL; a dead pane with no report is orchestration uncertainty, not findings      |
| 8    | Deadline exceeded, pane alive/unknown | Extend once with a recorded reason (re-arm with `--deadline-minutes`), else stop as HITL |
| 9    | Assignment not started within `--start-minutes` (default 5) | Follow the exit-9 exception path below |

The start window applies only to the latest matching `worker.launch_sent` carrying `prompt_path`
without a `worker.started` for that launch ID. The watcher accepts a marker only with a matching
`worker.starting` and marker `st_mtime_ns >= start_time_ns`; a non-empty report arriving first also confirms
start only when its `st_mtime_ns >= start_time_ns`. Stale reports remain pending. It writes one `worker.started` with `evidence: "marker"` or `"report"` and continues the
report wait. Legacy launches and already-confirmed launches skip this phase. The role deadline
counts from the persisted first arm, including time spent waiting for start.

While a watcher is armed it is the sole emitter of `worker.waiting`; the orchestrator does not hand-write
waiting events in parallel. Silence is never success — only the report file is ground truth. A
static-looking pane may be a worker at an approval/confirmation prompt; that pane is alive, and the
watcher correctly keeps waiting. Only `surface-health` reporting the pane gone counts as dead. Do not
close the worker pane, and do not launch the next stage, until the report has been captured and parsed.
Exactly one deadline extension per stage; pass `--deadline-reason` so the watcher records its reason in a `worker.waiting`
event. Before spending it on a silent pane, check the screen for the not-started cases in CMUX Control:
re-delivering to a worker that never started restarts the wait clock and is not an extension.

Use `blocked` only for explicit blockers reported by a worker. Use `hitl` for orchestration uncertainty such as a silent or possibly stuck worker after the wait policy is exhausted.

Read when an environment outage blocks a worker: [references/infrastructure-blockers.md](references/infrastructure-blockers.md).

## Replanning

Workers report changed assumptions as `PLAN DRIFT`. Handle drift in two classes:

- Small factual changes: update the issue and run log yourself, then continue. Examples: renamed command, moved local file path, missing but equivalent local script.
- Scope, architecture, migration, deployment, data-loss, production-safety, security, or acceptance-risk changes: stop as HITL and record the decision needed.

Never delete obsolete acceptance criteria. Mark them as `superseded` in nearby prose and add replacement criteria or notes.

## Branch and Commit Policy

One branch per tracker. The tracker README declares the working branch in its ground-rules section, so
every rendered prompt carries it. Before launching the first worker of a run, verify
`git branch --show-current` matches the declared branch; on mismatch, record a `hitl` gate instead of
starting the chain. Workers never switch branches. Dependent issues (later issues consuming earlier ones'
changes) are the normal case and are why the branch is shared across the tracker.

The chain runs on a dirty working tree — the simplify and
review passes operate on the working diff, so nothing is committed until the chain completes. After
the final `advance` gate and `run_state.py complete`, prepare a commit proposal and record it with `run_commit.py propose`:

- build the product and Git-tracked tracker file lists as literal leaf paths from
  `git status --porcelain=v1 -z --untracked-files=all`, including both rename paths and tracked deletions;
  anything the issue did not cause is excluded from `--file` and listed with `--ride-along`;
- pass each proposed leaf with `--file`, grouping product changes with `--product-file` and Git-tracked
  tracker changes published by triage (new issue files, `decisions.md`) with `--tracker-file`; each group
  is a subset of `--file`. Never pass a directory or expand a filename as a glob;
- a draft commit message: English, what + why in the subject, optional body. Record the subject line as
  `subject` in the event data; the run recap reads it from there.

A completed HITL issue run always ends with `run_commit.py propose`; its proposal mode is `propose`.
The helper validates the message (one-line subject, no trailers), classifies ignored and pre-run dirty
files, and records the replay-safe `commit.proposed` event. Call it only after completion:

```bash
python3 scripts/run_commit.py propose --run-dir <run-dir> --subject "Describe what changed and why" --file <leaf> --product-file <leaf>
```

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

Never start preparing a commit while a worker pass is still
active; the tree belongs to the worker until its report is captured and snapshotted.

## Run Briefing

A fresh run opens with a compact briefing so the human sees what the run is about without opening a
file. After `run_state.py init` (HITL issues included) and before the first `pane_ctl.py launch`:

```bash
python3 scripts/run_briefing.py draft --run-dir <run-dir> --lang <de|en>
# Replace {{goal}} and {{scope}} in <run-dir>/briefing.md, then:
python3 scripts/run_briefing.py show --run-dir <run-dir> --lang <de|en>
```

- `draft` writes `briefing.md` with the facts filled in (issue ID and title, acceptance count, blockers,
  chain, triage mode, branch) and never overwrites an existing briefing. Pick `--lang` by the human's language.
- Fill only the placeholders, from the issue file: `{{goal}}` is one sentence on what the issue achieves;
  `{{scope}}` is what this run implements, one line or up to four short sub-bullets. Neutral wording per
  Reporting to the Human; keep the fixed lines and their order unchanged.
- `show` refuses while a placeholder remains, prints the briefing, records `run.briefing`, and sets the
  sidebar pill `cmux-issue-chain-run` (`<issue-id> · <title>`) in the pinned workspace. A failed pill is a
  stderr note, not a stop. Relay the printed briefing verbatim as its own message, without preamble.
- On resume, run `show` again: it is the reorientation after a context compaction as well.

## Reporting to the Human

Gate decisions, stage summaries, and the end-of-run report are technical status, not narration. The
orchestrator writes them neutrally and precisely, in whichever language the human uses:

- State what changed, what was checked, and what came out. Prefer counts, paths, file names, gate values,
  and command outcomes to adjectives.
- Do not evaluate the work — yours or a worker's. "clean", "solid", "exactly right", "the tricky half"
  add no information the gate value and the test counts do not already carry.
- No build-up and no closing flourish. The human is scanning for state and for the next decision.
- An assessment is allowed when it prepares a decision the human has to make. Mark it as an assessment
  and put the decision it serves at the end.
- Relay worker findings unparaphrased, as the Review Self-Fix Policy already requires. Rewording a
  finding is a form of evaluation, and a softened finding is how a real one gets dropped.

Every autonomous run ends with the Run Recap (below), followed by the details it does not carry:

- A triage table (ID, short title, verdict, consequence: `follow-up` / `ISSUE-0xx` / `ledger only`,
  reason verbatim). Identify the triage pass alongside the ID so repeated R numbers are unambiguous;
  open `for-the-human` verdicts have ledger-only consequences and are listed as open below.
- The follow-up result including `## Not Applied`, or that no follow-up ran.
- Open `for-the-human` items.
- `Created by triage: ISSUE-0xx, ...` (write `none` when no issues were created).
- The commit message proposal (`commit.proposed`), with the separate file lists required above.

After the recap, details, and proposal, the orchestrator waits for the human.

## Run Recap

The counterpart to the Run Briefing. After `run_state.py complete`, `run_commit.py propose`, and `run_commit.py commit` in commit mode, or
after a `hitl`, `blocked`, or `stop` gate that ends the run:

```bash
python3 scripts/run_briefing.py recap-draft --run-dir <run-dir> --lang <de|en>
# Replace {{outcome}} in <run-dir>/recap.md, then:
python3 scripts/run_briefing.py recap-show --run-dir <run-dir> --lang <de|en>
```

- `recap-draft` refuses an active run. It writes `recap.md` with the facts from `state.json` and
  `events.jsonl`: status (done, or halted at stage and decision), duration, the issue's live tracker
  status, every gate in order, triage consequences, open `for-the-human` items, the commit subject, and
  for a completed run the next step. It never overwrites an existing recap.
- The next step comes from the live tracker, triage-created issues included. Candidates are the
  startable issues (the `issue_state.py ready` rule, plus unblocked HITL issues); the default ranks AFK
  before HITL, `in_progress` before `todo`, then the issue that transitively unblocks the most open
  issues, then the lowest ID. Other candidates follow as `also ready`; with none startable the line names
  what waits on what, or that the tracker is complete. The orchestrator may replace the default with
  another candidate when the run gives a concrete reason (for example a triage-created issue touching the
  same files), and then adds a `Reason:` line (German: `Begründung:`) with one sentence under the
  next-step line. `recap-show` refuses a non-startable issue and an unexplained deviation, and records
  default, choice, and override in `run.recap`.
- Below the next-step line, `Prompt für den nächsten Lauf` / `Prompt for the next run` repeats the
  `--invocation` with the recommended issue swapped in (ID and issue file name); a run without one gets
  `/cmux-issue-chain <tracker> <issue-id>`. When the initial prompt never named the issue, it is repeated
  unchanged with a note. Remove additions that only applied to the finished issue, with the same one-line
  reason; keep everything else. `recap-show` refuses a missing next-step line or prompt block while an
  issue is startable, a prompt that drops the recommended issue, or one that differs from the generated
  prompt without a reason, and records `prompt_edited` in `run.recap`. When the tracker changed after
  `recap-draft`, delete `recap.md` and draft it again.
- Fill only `{{outcome}}`: one or two sentences on what the run actually delivered, or for a halted
  run what stopped it and what the human has to decide. Neutral wording per Reporting to the Human.
- `recap-show` refuses while the placeholder remains, prints the recap, records `run.recap`, and turns
  the sidebar pill into `✓ <issue-id> · <title>` (green) or `<decision> · <issue-id> · <title>` (red).
  `--clear-status` removes the pill instead, only when the human asks for it. Relay the printed recap
  verbatim as its own message, then the details listed above.

Read when the final test report parses advance, before recording that gate, or triaging follow-up recommendations: [references/recommendations-triage.md](references/recommendations-triage.md).

Read when triage accepts follow-up items or a follow-up pass is active: [references/follow-up-pass.md](references/follow-up-pass.md).

Read when the assigned issue is HITL: [references/hitl-issues.md](references/hitl-issues.md).

## Worker input readiness

Normal starts attach the assignment with `start-agent`; arm `await_report.py` immediately.
The watcher confirms `worker.started` from the marker or report, with no screen judgment.
After exit 9, use the exception path below. For recovery and follow-ups, follow
[Interactive worker readiness](references/worker-readiness.md): `observe`, explicitly
`assess`, resolve any dialog with `respond`, and use readiness-gated `deliver --prompt`
for re-delivery or `deliver --text` for follow-ups. Read each result before the next input.
`worker.ready` permits one delivery and is distinct from assignment start confirmation.

## CMUX Control

Prefer current CLI syntax discovered from `cmux --help` before launching workers. Workers must be visible in CMUX
panes. Never type a launch command into a worker pane by hand: `pane_ctl.py start-agent` owns it, so every worker
starts from the audited argument vector in its prepared stage snapshot with the assignment delivery line appended as its final argument. The default profiles produce:

```bash
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c 'sandbox_workspace_write.writable_roots=["~/.ddev"]' \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  -c tui.animations=false \
  -c tui.disable_paste_burst=true \
  --model gpt-6-astra \
  -c model_reasoning_effort=xhigh                # implement; test uses model_reasoning_effort=high
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model opus --effort high \
  --permission-mode auto                        # simplify, review
CMUX_AGENT_MANAGED_SUBAGENT=1 pi \
  --model openrouter/z-ai/glm-5.3 \
  --thinking high                               # only when a Pi profile is opted into
```

`CMUX_AGENT_MANAGED_SUBAGENT=1` marks the pane as a managed subagent, which is what cmux keys its notification
suppression on. Without it every turn end, idle reminder and approval prompt of a chain raises a desktop banner with
sound while the human is elsewhere — the point of an AFK run is that only the orchestrator interrupts. The worker
still appears in the Feed and in `surface-health`; only the banners are gone. Suppression follows
`automation.suppressSubagentNotifications` (on by default), and the variable is a cmux internal, so the failure mode
is noise, never a broken run.

The defaults use plain `codex` for implement and test workers and plain `claude` for simplify/refactor, review, and triage
workers. Typed preparation overrides may select Claude Code or Codex for every role. Simplify and review default
to Claude Code because its bundled `/simplify` and `/code-review medium --fix` fan out internal review agents; on
Codex the same duties are rendered inline as a single-agent pass, which is a deliberate, weaker substitute the
operator opts into per run or per tracker config. Every interactive Claude worker starts in `auto` permission mode;
the safe tool-disabled live provider probe remains in `plan` mode. `render_prompt.py` reads the harness from the prepared stage
snapshot, so the prompt variant and the launch command cannot disagree. Never use `cmux codex-teams` / `cmux claude-teams`. The teams wrappers open
worker-spawned subagents as extra cmux panes, and those splits anchor to the focused workspace instead of the worker's workspace: while the human works in another
workspace, subagent panes land there. Plain launches keep subagents internal to the worker's own TUI; neither the
simplify nor the review pass needs teams mode. The worker pane stays the visible unit of orchestration, and cmux
pane integration (hooks, notifications, `surface-health`) comes from the per-pane CLI shims, so it is unaffected.

### Pinned workspace, deterministic pane control

`run_state.py init` pins the run's cmux workspace and prepares `implement-1`: flag > `CMUX_WORKSPACE_ID` env > hard error (the env
var of the orchestrator pane is the only place that variable is ever read). Every cmux call after init
goes through `pane_ctl.py`, which reads the pinned `workspace_id` from `state.json` — never through raw
`cmux` with an env-var workspace, and never with a fallback to the focused workspace. An empty or missing
pinned ID is a stop, not a fallback: the human may be looking at a different workspace than the one the
run owns, and cmux resolves unscoped commands against the focused one.

The lifecycle verbs cover the error-prone multi-step sequences and record their events themselves:

```bash
# Prepare, render, launch, close the previous pane, snapshot, start-agent, then arm the watcher.
python3 scripts/run_state.py prepare --run-dir <run-dir> --stage review --pass 1
python3 scripts/render_prompt.py --tracker <tracker> --issue <issue> --run-dir <run-dir> --role review --pass 1
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --role review --pass 1 --anchor <prev-worker-surface-id>
python3 scripts/pane_ctl.py close --run-dir <run-dir> --surface <prev-worker-surface-id> --role <previous-role> --pass <previous-pass>
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "launched review-1"
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --surface <surface-id> --role review --pass 1
# Arm via background Bash (or Monitor with re-arm) as described above.
python3 scripts/await_report.py --run-dir <run-dir> --surface <surface-id> --role review --pass 1
```

- `launch` first validates that the requested role/pass matches the current, passed, untampered prepared
  snapshot, re-deriving its argument vector from the code-owned adapter policy so a restamped snapshot
  cannot widen the sandbox it launches under. Only then does it split from the anchor surface (`--direction right` default, `--focus false`), label the pane
  per the deterministic label scheme, records `pane.launched` + `pane.labeled`, and prints the new
  surface's stable UUID — use that UUID in every later command; positional refs like `surface:465` shift
  when panes close.
- `start-agent` revalidates the same snapshot and requires the rendered prompt before any cmux call.
  It appends the repository-relative assignment delivery line as one shell-quoted argument, records
  `worker.starting` and `worker.launch_sent` with a launch ID and nanosecond start time, and prints
  one JSON line containing `launch_id`, `surface_id`, `prompt_path`, `marker_path`, and the next step:
  arm the watcher. The default `--settle-seconds 0` sends only the command and Enter; a positive
  settle opts into a diagnostic screen echo on stderr.
- `deliver` is for the exception path and follow-ups. It requires a fresh, screen-bound readiness
  assessment, consumes it, sends the text and explicit Enter, records `worker.prompt_sent`, and echoes
  the pane screen after a short settle.
  Hand over a rendered prompt with `--prompt <prompt-path>`, never with hand-written `--text`: the
  wording is skill policy like the launch command, and getting it wrong stalls the worker (see the
  send/Enter rule below). `--text` is for follow-ups into a working pane — re-emission requests,
  clarifications, HITL messages.
- `close` closes the surface and records `pane.closed`.

Everything else (diagnosis, `read-screen`, `list-pane-surfaces`, `set-status`, …) runs through the
generic injector, which inserts `--workspace <pinned>` into any cmux command:

```bash
python3 scripts/pane_ctl.py cmux --run-dir <run-dir> -- read-screen --surface <surface-id> --lines 40
```

Avoid focus-changing commands unless the user explicitly asks. Store rendered
prompts under the run directory before sending them to worker sessions.

The sandbox flags above are fixed Codex adapter policy. Typed overrides select profile, harness, model, effort,
or executable; they never replace the safety arguments.

Pi has no equivalent policy surface, and its launch line above is the whole of it. Pi ships no sandbox
and no approval gate: its `read`, `bash`, `edit` and `write` tools run unconfined, so none of the two
limits below apply — `.git` and `.agents` are writable to a Pi worker, and nothing escalates to a
reviewer because nothing is ever blocked. Its only lever is a tool allow/denylist (`-t`/`-xt`/`-nt`),
which `bash` makes porous anyway. This is a deliberate, accepted asymmetry, not an oversight: a Pi
worker is weaker-contained than a Codex one, and picking a Pi profile is the point at which that is
accepted. Pi also reaches the network through `bash`, which is why it is the second harness allowed on
the grilling `web` lane. The launch command reaches the pane via
`pane_ctl.py start-agent`, whose `worker.launch_sent` event records its snapshot id and final argument vector.

Each flag earns its place, so keep them together:

- `-s workspace-write` makes the repo writable without per-write confirmations.
- `network_access=true` is what unblocks container-based projects. Connecting to the Docker socket counts as a network
  operation in the sandbox, not a file access, so `workspace-write` alone blocks every `ddev exec`, `ddev composer`, and
  containerised test run. Granting write access to the socket path does not help.
- `writable_roots=["~/.ddev"]` covers ddev's global state outside the workspace.
- `--ask-for-approval on-request` pins the escalation policy explicitly: workers run sandboxed and request
  approval only when the sandbox blocks something, instead of prompting before every command.
- `approvals_reviewer=auto_review` routes those approval requests to Codex's automated reviewer agent
  instead of a human prompt, so unattended workers do not stall at the sandbox boundary. It is a reviewer
  swap, not a permission grant — the sandbox limits above stay unchanged.
- `check_for_update_on_startup=false` suppresses the startup update prompt, which otherwise blocks an
  unattended worker before it reads its task. Set it only here, so interactive Codex sessions still get
  update notices; Codex itself is kept current through Homebrew.
- `tui.animations=false` disables decorative motion on the welcome screen, shimmer, and spinner, so
  the worker screen that readiness checks and `observe` read stays stable.
- `tui.disable_paste_burst=true` disables Enter suppression after a typed burst, so exception-path
  `deliver` submits text with a single Enter.

Two limits survive these flags, by design. `.git`, `.agents`, and `.codex` stay read-only inside an otherwise
writable workspace; the read-only git commands this skill uses (`status --short`, `diff`, `diff --stat`,
`branch --show-current`) work fine, and workers draft commit messages rather than committing. Overriding the
`.git` carve-out needs an absolute per-project path, so do not attempt it here. With `on-request` plus
`auto_review`, escalation requests are decided by the automated reviewer, not handed to the human, so a
quiet worker pane is one still working or already done — the report file settles which, never the screen.
If the same denial recurs in practice, capture its exact wording and report it rather than widening
permissions ad hoc.

`pane_ctl.py launch` labels every worker pane at creation with the deterministic role labels — no
separate `rename-tab` step:

- `Implementer <pass> - <issue-id>`
- `Simplifier <pass> - <issue-id>`
- `Tester <pass> - <issue-id>`
- `Reviewer <pass> - <issue-id>`

Current `cmux new-pane`/surface commands do not expose per-pane colors; do not invent color handling. If a future `cmux --help` exposes pane or tab colors, use role colors consistently. Until then, optional color may only be used as a workspace status pill with `cmux set-status` (via the injector), not as a pane color:

```bash
python3 scripts/pane_ctl.py cmux --run-dir <run-dir> -- set-status cmux-issue-chain "Tester 1 - ISSUE-001" --color "#34c759" --priority 80
```

Use this optional status color map when status pills are helpful: Implementer `#0a84ff`, Simplifier `#af52de`, Tester `#34c759`, Reviewer `#ff9500`, HITL/blocker `#ff3b30`.

Anchor worker panes to the worker they follow, not to the orchestrator pane: pass the previous worker's
surface ID as `--anchor` to `pane_ctl.py launch`. It splits without stealing focus and records the new
surface UUID in the `pane.launched` event.

Use this pane layout for the default chain:

- Implement: first worker pane may be opened from the orchestrator pane.
- Simplify: keep the implementer pane open and place the simplify pane to the right (preferred) or down of that implementer pane.
- Review after simplify: keep the simplify pane open and place the review pane to the right (preferred) or down of that simplify pane. The orchestrator quick-check between them opens no pane.
- Final test after review: keep the review pane open and place the test pane to the right (preferred) or down of that review pane.
- Triage: anchor the fresh Triager pane to the test pane; anchor any follow-up implement pane to the triage pane.

Do not open simplify, review, or test as down splits from the orchestrator pane just because the orchestrator pane is active after gate processing.

For every role (implement, simplify, review, test, and triage), including the initial implement launch,
record `run_state.py snapshot --label "launched <role>-<pass>"` right before `start-agent`.
Preserve that baseline until its report-capture comparison is complete; never replace it to
adopt an unchecked delta.

Close completed worker panes promptly:

1. Confirm the worker wrote its final report to the rendered report handoff path.
2. Record a working-tree fingerprint for the capture: `run_state.py snapshot --label "report-captured <role>-<pass>"`.
3. Compare the launch/capture staged fields and HEAD under Diff inspection at code-changing gates for every
   role, including test; then parse the report and record the gate/event state.
4. If the chain continues, run `run_state.py prepare --stage <next-role> --pass <n>`. This reloads and
   validates live configuration and publishes the only snapshot that `pane_ctl.py` may launch. A failed
   preparation stops before CMUX creates a pane. Render the next prompt only after this step:
   `render_prompt.py` refuses to run without the prepared snapshot, because the harness it targets comes
   from there.
5. Split the next worker pane anchored to the just-completed worker pane while it
   is still visible (`pane_ctl.py launch --anchor <completed-surface>`). Prefer `right` splits: every
   stacked down-split halves the remaining height, and a too-short pane cannot render its composer at all.
6. Close the completed worker pane as soon as the new pane exists — before sending the prompt to the new
   pane — with `pane_ctl.py close` (it records `pane.closed`). Its report is already captured
   and snapshotted (steps 1-2). Sending the prompt first and closing afterwards is the documented trap:
   with stacked splits the new pane may be unable to show its composer until the old pane is gone.
7. Record `run_state.py snapshot --label "launched <role>-<pass>"` right before `start-agent`.
   Start the new pane's worker with `pane_ctl.py start-agent --role <role> --pass <n>`.
   It attaches the rendered assignment. Immediately arm the watcher; no observe, assess, deliver,
   or started judgment is needed on the normal path.
8. On final completion, HITL, blocker, or run abort, close all completed worker panes after their reports
   and gate decisions are documented.

While a worker pass is active, the working tree belongs to that worker: neither the orchestrator nor the
human should edit product files until the report is captured and snapshotted. Before accusing a worker
report of inaccuracy (`report.integrity`), take a fresh snapshot and compare fingerprints against the one
recorded at capture: a mismatch means the tree changed after capture — by a human or another process, not
necessarily the worker. Attribute first; if an accusation turns out wrong, retract it explicitly with a
`report.integrity.retracted` event.

Keep at most the orchestrator pane and the current active worker pane. Do not leave old implementer, tester, simplify, reviewer, or triage panes open after their reports have been captured and used.

Before launching a worker, choose these paths deterministically and render them into the prompt:

- Prompt path: `.scratch/orchestrator/runs/<run-id>/prompts/<role>-<pass>.md`
- Report handoff path: `.scratch/orchestrator/runs/<run-id>/reports/<role>-<pass>.md`
- Worker artifact directory: `.scratch/orchestrator/runs/<run-id>/artifacts/<role>-<pass>/`
- Context files: every earlier report of the current pass, passed with `--context-file` — simplify
  receives the implement report; review receives implement and simplify; the final test receives all
  three. Prior reports carry the decisions, trade-offs, and drift notes of earlier stages; passing them
  forward is what lets a reviewer tell a deliberate decision from a mistake. For later reviewers,
  also pass relevant prior-pass reports from the same run with `--context-file`, including protected
  Not Applied items, documented intended behavior, and recorded human approvals that supersede them.
  Relevant prior reports are those carrying protected decisions or explicit human supersession records.
  Unrelated or decision-free historical reports are not required by default.
  `decisions.md` is embedded automatically with approved, rejected, deferred, recorded, and open records distinguished;
  supply approval records held elsewhere with `--context-file`.
  Keep the earlier decision and any explicit supersession together with their source paths and pass
  identities. Do not treat a later worker opinion as approval or infer supersession from report order.
  Verify the rendered review prompt includes this decision context before delivery. If relevant context
  is missing or scope/precedence is unresolved, ask the human before authorizing a disputed change.

Send the visible CMUX worker the prompt file path and require it to write the final report to the exact
rendered report handoff path before returning the same report body in the console. That exact report file
is the worker's only lifecycle-state write exception. The assigned artifact directory is separately
worker-writable; workers must not edit any other lifecycle-state file.

Read when the watcher exits 9 or sending any re-delivery or follow-up text: [references/startup-recovery.md](references/startup-recovery.md).

Do not use hidden subagents as worker substitutes during a live run. If CMUX cannot launch the visible worker, stop and report the CMUX failure. This rule covers the workers themselves; the internal subagents a worker spawns inside its own TUI (e.g. `/code-review` review agents) are part of that worker, not substitutes for it.

## Event Vocabulary

`commit.proposed` is written only by `run_commit.py propose`.
`commit.attempted`, `commit.created`, `commit.skipped`, and `commit.failed` are written only by
`run_commit.py commit`: attempt before Git, proven success, nothing to commit, or proposal fallback.

Read when writing any event with `run_state.py event` (including drift records) or interpreting lifecycle events: [references/event-vocabulary.md](references/event-vocabulary.md).

## Scripts

`run_commit.py propose` is the only writer of `commit.proposed`; generic `event` refuses `commit.*`.

`collect_recommendations.py --run-dir <run-dir> --pass <1|2>` writes the immutable recommendations list.
`run_state.py publish-triage --run-dir <run-dir> --pass <1|2>` publishes a passing triage report;
`parse_report.py --items-file <path> <report>` validates the verdicts.

The scripts are deterministic helpers. They live canonically at `scripts/`
(`~/.claude/skills/cmux-issue-chain` is a symlink to the same directory). Run them from the repo root.
`--tracker` is always required and points at the local tracker directory (e.g. `.scratch/<tracker>`).

Inspect issue state and blockers:

```bash
python3 scripts/issue_state.py list --tracker .scratch/<tracker>
python3 scripts/issue_state.py ready --tracker .scratch/<tracker>
python3 scripts/issue_state.py show --tracker .scratch/<tracker> --issue ISSUE-001
```

Issue files are `ISSUE-NNN-<slug>.md` or `NN-<slug>.md` — the latter is what `to-tickets` writes, and its
ids normalize to `ISSUE-NNN`, so every command still addresses issues as `ISSUE-001`. `## Blocked by`
entries may be `ISSUE-001` or the bare `01`.

The tracker preflight fails loudly instead of listing nothing: `*.md` files under `issues/` that match
neither naming form (`README.md`, `_index.md`, `decisions.md`, `spec.md` and `map.md` are allowed), issue
files without usable frontmatter, or a tracker with zero loadable issues make `issue_state.py` exit
non-zero and name the offending files. `load_issues` enforces this for every script, so `run_state.py init`
and `render_prompt.py` refuse malformed trackers too.

Read when a to-tickets tracker needs frontmatter adoption: [references/tracker-adoption.md](references/tracker-adoption.md).

Create and append run-state. The default run id is `<ISSUE-ID>-<YYYY-MM-DD>-<HHMM>` (UTC) — issue first
so runs group per issue, timestamped so re-runs never reuse a stale run directory (a leftover report from
an earlier attempt would satisfy the watcher instantly). `init` pins the run's cmux workspace
(`--workspace-id` > `CMUX_WORKSPACE_ID` > hard error; `--no-workspace` is the explicit opt-out for
offline runs outside cmux) and drops a self-ignoring `.gitignore` (`*`) into the runs root, so run state
never reaches git in any target repo. For an AFK issue, initialization requires the configuration
checkpoint above to be complete, then preflights every role and prepares `implement-1`; a missing or
invalid configuration and any preflight failure happen before a launchable state or stage snapshot is
written. HITL issues get no configuration source and no snapshot, so `prepare` stays unavailable on
them, and re-running `init` on an existing run re-prepares nothing — it refuses `--config` and typed
overrides instead of dropping them. Pass the human's initial prompt verbatim as `--invocation` (skill
command plus any additions) on the first init only; the run recap reuses it for the next issue. Omit it
on resume: a re-init refuses a value that differs from the recorded one, and only a run without a
recorded prompt adopts it (`run.invocation`):

```bash
python3 scripts/run_state.py init --tracker .scratch/<tracker> --issue ISSUE-001 --invocation "<human prompt, verbatim>"
python3 scripts/run_state.py init --tracker .scratch/<tracker> --issue ISSUE-001 --probe-profiles
python3 scripts/run_state.py event --run-dir .scratch/orchestrator/runs/<run-id> --type worker.started --message "assignment visibly working on exception path" --data '{"role":"review","pass":1,"surface_id":"<surface-id>","launch_id":"<launch-id>","evidence":"screen"}'
```

After every advance gate, prepare the next stage before `pane_ctl.py launch`. This reloads the run's pinned
configuration source and stores all temporary overrides only in that snapshot:

```bash
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage simplify --pass 1
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage test --pass 1 --probe-profiles --probe-timeout 180
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage test --pass 1 \
  --profile test=codex-sol-high --effort test=xhigh
```

Pane lifecycle events (`pane.launched`, `pane.labeled`, `worker.launch_sent`, `worker.prompt_sent`, `pane.closed`) are written
by `pane_ctl.py` (see CMUX Control); do not hand-write them in parallel.

Record a working-tree fingerprint (at every report capture, and before any `report.integrity` claim). An
unreadable or vanished untracked path fails the snapshot with a diagnostic naming it and records no event;
restore access or remove the path and retry. Git only warns about an unreadable untracked directory, so its
contents stay invisible rather than failing capture. Then:

```bash
python3 scripts/run_state.py snapshot --run-dir .scratch/orchestrator/runs/<run-id> --label "report-captured review-1" --data '{"role":"review","pass":1}'
```

Record a gate decision. `--next-stage` moves `current_stage` forward on `advance`:

```bash
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/<run-id> --stage simplify --decision advance --reason "no findings, checks run, quick-check green" --next-stage review
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/<run-id> --stage review --decision hitl --reason "unresolved must-fix after --fix"
```

Close a run after the final `advance` gate (or after a HITL issue is fully verified). First update the
issue file, which is lifecycle state and belongs to the orchestrator: tick each acceptance criterion the
test report (for a HITL issue, the recorded verification) confirmed, set `status: done` only when all
criteria are ticked, and keep a `progress` field in frontmatter in step. An unticked criterion keeps the
status open and is named in the recap outcome. Then `complete` sets `current_stage: done`, refreshes the
issue snapshot in `state.json`, and appends `run.completed`:

```bash
python3 scripts/run_state.py complete --run-dir .scratch/orchestrator/runs/<run-id> --message "chain complete, issue done 10/10"
```

Render role prompts. `--pass` is required and determines the prompt, report, and artifact paths. The
artifact directory always derives from `--run-dir`, role, and pass, even with custom prompt/report paths.
The prompt's harness variant
comes from the prepared stage snapshot for that role and pass (`init` prepares `implement-1`, `prepare` every
later stage), so rendering before preparation fails; the prompt header records `Harness:` and `Stage snapshot:`.
Implement and test prompts are identical across harnesses; simplify and review switch between Claude Code's
bundled skills and the inline passes. The tracker README's
ground-rules section (any `##` heading containing "ground rules") and the tracker's `decisions.md` triage
ledger (when present) are embedded into every prompt automatically. Pass every earlier report of the
current pass with `--context-file` (repeatable), plus relevant prior-pass decision reports and human
approval records for later reviewers, per the context-files rule in CMUX Control:

```bash
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role implement --pass 1 --run-dir .scratch/orchestrator/runs/<run-id>
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role review --pass 1 --run-dir .scratch/orchestrator/runs/<run-id> --context-file .scratch/orchestrator/runs/<run-id>/reports/implement-1.md --context-file .scratch/orchestrator/runs/<run-id>/reports/simplify-1.md
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role review --pass 2 --run-dir .scratch/orchestrator/runs/<run-id> --context-file .scratch/orchestrator/runs/<run-id>/reports/implement-1.md --context-file .scratch/orchestrator/runs/<run-id>/reports/simplify-1.md --context-file .scratch/orchestrator/runs/<run-id>/reports/review-1.md --context-file .scratch/orchestrator/runs/<run-id>/reports/implement-2.md --context-file .scratch/orchestrator/runs/<run-id>/reports/simplify-2.md
```

The pass-2 example assumes the pass-1 implement, simplify, and review reports carry protected decisions
or explicit human supersession records. Select prior reports by the relevance rule above.

Read when rendering an accepted follow-up pass: [references/follow-up-commands.md](references/follow-up-commands.md).

Parse worker reports. Exit code carries the gate; a missing report is `pending` (exit 6), never a crash:

```bash
python3 scripts/parse_report.py path/to/worker-report.md --json
```

Await a worker report deterministically (see Worker Wait Policy for the background Bash invocation). The deadline
defaults to the role's minimum wait; exit 0 = report exists, 7 = pane dead, 8 = deadline exceeded, 9 = not started.
`--start-minutes` defaults to 5; the role deadline keeps counting from arming.
Heartbeats go to `events.jsonl` as `worker.waiting`. Health checks are scoped to the run's pinned
`workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_report.py --run-dir .scratch/orchestrator/runs/<run-id> --role review --pass 1 --surface <surface-id>
```

Control worker panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints the pinned
id, `cmux` is the generic `--workspace` injector, `launch`/`deliver`/`close` are the lifecycle verbs.

Read when changing scripts or selecting their regression checks: [references/script-tests.md](references/script-tests.md).

Read when preparing a live worker pilot: [references/smoke-test.md](references/smoke-test.md).

Read when checking report structure or requesting report re-emission: [references/worker-report-contract.md](references/worker-report-contract.md).
