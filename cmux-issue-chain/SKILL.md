---
name: cmux-issue-chain
description: Coordinate gated visible CMUX worker chains for local Markdown issue trackers. Use when an orchestrating agent needs to run AFK issues through implement, simplify/refactor, test, harness-aware code review (Claude Code /code-review --fix or an inline review pass on other harnesses), reviewer self-fix handling, blocker handling, plan-drift handling, run-state logging, prompt rendering, worker report parsing, or cmux worker-pane workflows without directly editing product code.
---

# CMUX Orchestrator

Use this skill to run a local issue through a gated multi-agent workflow. The orchestrator is a coordinator only: it may update lifecycle state, run logs, snapshots, issue status/progress, gate decisions, and documented plan changes, but it must not edit product code.

All `scripts/…` and `references/…` paths in this skill are relative to the skill's own
base directory (the directory containing this SKILL.md); resolve them against that
directory, not the working directory.

## Worker Profile Configuration

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v2. Older separately installed sibling skills cannot read the migrated schema-v2 shared configuration.

The dependency-free configuration CLI is `scripts/agents_config.py`. Run it from anywhere
inside the target Git repository; the default path is the repository root's
`.scratch/orchestrator/agents.json`:

```bash
python3 scripts/agents_config.py init
python3 scripts/agents_config.py validate
python3 scripts/agents_config.py show-resolved
python3 scripts/agents_config.py migrate
python3 scripts/agents_config.py migrate --accept
```

Use `--config <path>` after any command to select an explicit file, including outside Git,
or `--repo <path>` to resolve the default path from a specific target repository. `init`
atomically creates the complete shared defaults and never changes an existing file or the
repository's ignore rules. `validate` and `show-resolved` are local-only operations: they do
not launch workers or contact Claude Code, Codex, or any provider. They are read-only and stop
on schema v1 with the exact preview and acceptance commands; run initialization and stage
preparation do the same before publishing launchable state.

Treat configuration creation as a first-use human checkpoint, separate from run initialization.
Before starting any worker-bearing run, resolve the selected configuration path and follow this
protocol:

1. If the file already exists at schema v1, run `agents_config.py migrate` without `--accept`.
   Present its coordinated-upgrade warning and complete validated preview in the human's language,
   including every resolved workflow assignment. When `claude-fable-high` is unavailable, call out
   the displayed fallback profile name, harness, model, and effort without inferring relative quality.
   Ask whether to accept exactly that proposal. On refusal or interruption, make no further tool call.
   On confirmation, invoke the preview's exact `agents_config.py migrate --accept` command, digest
   argument included, then validate and continue. A schema-v2 file needs no migration question.
2. If it is missing, run `agents_config.py init` for that exact default or explicit path, then run
   `show-resolved`. Do not call `run_state.py init` yet.
3. Present the created path and all three workflows' resolved assignments, because the file is shared.
   Ask one single-select question in the human's language: whether to start the current run with
   these assignments. The choices mean **Yes, start now** and **No, I will edit the file**.
4. Use the host's native structured-input tool when it is available: `AskUserQuestion` in Claude
   Code or `request_user_input` in Codex. Do not assume Codex exposes it in the current mode; when
   no native tool is available, ask the same question in chat and end the turn for the answer.
5. On yes, reload and validate the current bytes before starting the run. On no, perform no more
   tool calls, tell the human to edit the file and reply when it is ready, and end the turn. When
   they return, validate and show the resolved assignments again; start only after validation
   succeeds. Report validation errors and remain stopped when it fails.

This checkpoint belongs to the interactive orchestrator, never to a worker pane or subagent. Do
not emulate it with shell input, a sleeping process, or polling while the human edits the file.

The ten shipped profiles are `claude-fable-high` and `claude-fable-medium` (`claude-code`,
`claude`, `fable`); `claude-opus-high`, `claude-opus-medium`, and `claude-opus-xhigh`
(`claude-code`, `claude`, `opus`); `claude-sonnet-medium` (`claude-code`, `claude`, `sonnet`);
`codex-astra-high`, `codex-astra-medium`, and `codex-astra-xhigh` (`codex`, `codex`,
`gpt-6-astra`); and `codex-luna-medium` (`codex`, `codex`, `gpt-5.6-luna`). Each tuple lists
harness, executable, and model; the profile suffix specifies effort. Issue-chain assigns Astra/xhigh to
`implement`, Opus/high to `simplify` and `review`, and Astra/high to `test`.
The `fable`, `opus`, and `sonnet` model strings are intentionally moving provider aliases;
deterministic selection of an alias does not pin the provider's underlying model version.

Configuration is strict and user-owned after its create-only bootstrap. Schema-v1 reads never migrate.
The read-only `migrate` preview validates the complete schema-v2 candidate before displaying it;
`migrate --accept` is the only shared-CLI path that atomically replaces the file. Existing profiles and
assignments are preserved, planning roles are selected deterministically, a collision-safe Codex
reviewer is added only when needed, and the original bytes remain untouched if validation or publication
fails. Migration refuses a resolved target with no write bit or more than one hard link. A symlink is
preserved and those same guards apply to its intended target.
The output-stream contract is stable: standalone read-only `migrate` writes the complete migration
guidance once on stdout, while stderr contains only its short refusal and never repeats either command.
For a schema-v1 refusal, planning initialization leaves stdout empty and writes one complete actionable
guidance block on stderr, with the candidate digest and exact preview and acceptance commands once each.
Unknown fields, versions,
harnesses, efforts, assignments, or profile references fail rather than falling back. Model
strings are syntax-checked, not looked up in a stale catalog, so local validation cannot prove
provider or model entitlement. `show-resolved` is the inspection command for the complete
profiles, assignments, sources, models, and efforts. Pi and Hermes remain explicit unsupported
entries in the code-owned adapter registry; that registry — rather than JSON — is the implementation
boundary for adding future harnesses. It lives in `scripts/agents_config.py` together with the
preflight rules, the launch and probe adapters, and the override parsing and profile resolution
all workflows share, so a harness is added in that one file; each workflow keeps its own
sandbox, approval, and network policy.

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

- Treat product code as worker-owned. Do not modify application, extension, frontend, deployment, or test implementation files from the orchestrator role.
- Write lifecycle state only: `.scratch/orchestrator/runs/<run-id>/`, local issue frontmatter/checklists, run logs, prompt files, worker reports, gate decisions, snapshots, documented plan changes, the tracker `decisions.md` triage ledger, and human-approved issue drafts from recommendations triage.
- Require workers to write structured reports to their exact rendered report handoff paths and return the
  same report body in the console. That exact report file is the only orchestration lifecycle state a worker
  may write; all other run state remains orchestrator-owned.
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
security fixes stay self-fixable even when the smallest fix re-adds a little previously deleted logic.

Do not route code-review findings back to the implementer for an automatic fix loop. The old review-driven `Implement -> Simplify -> Test -> Review` loop is disabled.

After review self-fix:

1. If the review report has no remaining must-fix findings, continue to the final Codex test.
2. If the review report has remaining must-fix or ask-user findings, a blocker, or unsafe fix uncertainty, record a `hitl` gate and stop.
3. If the final Codex test after review changes reports findings, record a `hitl` gate and stop unless the user explicitly authorizes another worker pass.
4. Review reports that contain only non-blocking recommendations may advance when `## Findings` is `None`.

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

Review reports must separate blocking findings from non-blocking recommendations. Only `Recommendation: must-fix` and `Recommendation: ask-user` items belong in `## Findings`. Low-risk cleanup, broader hardening, speculative edge cases, and nice-to-have improvements belong in `## Recommendations` and must not block the gate by themselves.

Unresolved must-fix or ask-user findings after the review worker's own self-fix pass become HITL. Do not launch another implementer or second reviewer automatically. Any blocker stops the issue chain and must be recorded in the issue and run log. Any major plan drift becomes a HITL blocker.

### Formatting failures: request re-emission, never override

When `parse_report.py` gates `stop` or `hitl` purely because of report format — prose after `- None`, a
missing required section, the unfilled `|` menu — and the substance looks clean, do not overrule the
parser with your own `advance`. Ask the still-open worker pane for exactly one contract-conforming
re-emission ("re-emit the report per the Worker Report Contract; fix the format, not the substance"),
record a `report.reformat_requested` event, re-parse, and gate on the new report. If the worker pane is
already gone or the re-emitted report still fails, stop as HITL for the human. The orchestrator never
records `advance` while the latest parsed gate says otherwise.

The same re-emission path covers stage-ownership findings. The chain runs on a deliberately uncommitted
working tree, and commit, push, PR, and CI belong to the human after `complete` — a finding whose sole
claim is that the tree is uncommitted or that a commit, push, PR, or CI run is missing reports a deferral
as if it were a defect. Ask the worker for one re-emission without that finding, record
`report.reformat_requested`, and gate on the new report; substantive findings in the same report keep
their normal effect.

### Diff inspection at code-changing gates

Before recording the gate for any code-changing stage (implement, simplify, review), the orchestrator must
inspect the working diff itself: run `git status --short` and `git diff` (read-only) and compare what
changed against the issue's "What to build" and acceptance criteria. A clean report is not a substitute —
undocumented scope expansion gates `stop`, undocumented drift gates `hitl`, even when the report says
`NO FINDINGS`.

Look for:

- files touched outside the issue's stated scope;
- product code changed where the issue only called for tests, docs, or config;
- new public API, hooks, or test seams added to production paths for the worker's own convenience.

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
- Reviewer: 90 minutes

A review pass (`/code-review medium --fix` on Claude Code in particular) can legitimately take 15 minutes or longer. Do not interrupt or fail a review worker just because no report appears during that window.

### Armed watcher, not polling

The orchestrator only exists within a turn; between turns nothing polls. Before ending any turn while a
worker pane is running, the orchestrator MUST arm a watcher that re-invokes it — ending a turn with a
worker running and no armed watcher is a policy violation. The watcher is `await_report.py`; it blocks on
the report handoff path (the ground truth), checks `cmux surface-health` for a dead pane, derives its
deadline from the role's minimum wait, and writes the `worker.waiting` heartbeats itself. Arm it through
the harness `Monitor` tool:

```
Monitor(
  command: "python3 scripts/await_report.py --run-dir .scratch/orchestrator/runs/<run-id> --role review --pass 1 --surface <surface-id>",
  description: "await review-1 report",
  persistent: true
)
```

`persistent: true` is required: Monitor's `timeout_ms` caps at 60 minutes and the review minimum wait is
90; the script's own role-derived deadline ends the watch. `Bash` with `run_in_background` is an
acceptable substitute only when the remaining wait is at most 10 minutes (Bash timeout caps at 600000 ms).

The watcher ends on exactly three conditions and nothing else:

| Exit | Condition                             | Orchestrator action                                                                      |
|------|---------------------------------------|------------------------------------------------------------------------------------------|
| 0    | Report file exists                    | Snapshot, parse, gate — exit 0 is not an advance verdict                                 |
| 7    | Pane dead per `cmux surface-health`   | Stop as HITL; a dead pane with no report is orchestration uncertainty, not findings      |
| 8    | Deadline exceeded, pane alive/unknown | Extend once with a recorded reason (re-arm with `--deadline-minutes`), else stop as HITL |

While a watcher is armed it is the sole emitter of `worker.waiting`; the orchestrator does not hand-write
waiting events in parallel. Silence is never success — only the report file is ground truth. A
static-looking pane may be a worker at an approval/confirmation prompt; that pane is alive, and the
watcher correctly keeps waiting. Only `surface-health` reporting the pane gone counts as dead. Do not
close the worker pane, and do not launch the next stage, until the report has been captured and parsed.
Exactly one deadline extension per stage; record its reason in a `decision.human` or `worker.waiting`
event. Before spending it on a silent pane, check the screen for the not-started cases in CMUX Control:
re-delivering to a worker that never started restarts the wait clock and is not an extension.

Use `blocked` only for explicit blockers reported by a worker. Use `hitl` for orchestration uncertainty such as a silent or possibly stuck worker after the wait policy is exhausted.

### Infrastructure blockers

A blocker whose cause is the environment, not the work — Docker/ddev daemon down, network gone, toolchain
unresponsive — is an infrastructure blocker, not a design blocker. Symptoms: commands hang or fail across
projects, the worker did nothing wrong, no code or design question is open. Design blockers (scope,
architecture, migration, data loss) keep the Replanning path.

Handle an infrastructure blocker in this order:

1. Record the outage as `orchestrator.halted`. If the blocked pass had already applied changes it could not
   verify, record them as `orchestrator.unverified_input` with the affected files.
2. Never restart shared infrastructure (Docker, ddev, databases) without explicit human consent when other
   projects may be affected — other projects' active containers or syncs make a restart the human's call.
3. Wait for recovery with a bounded, armed watcher — same mechanism as the Worker Wait Policy: hand the
   wait to the harness (`Monitor`, or `Bash run_in_background` for waits up to 10 minutes) with a stated
   deadline, and stop as HITL when the deadline passes without recovery. Never wait without an armed
   watcher and never poll indefinitely.
4. After recovery, verify before advancing: the orchestrator re-runs the issue's checks over the changes the
   blocked pass applied but could not verify, and records an `orchestrator.verified` event with commands and
   outcomes. Only then resume the same stage — the interrupted pass continues; the chain does not skip ahead.

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

The orchestrator never commits product code, and the chain runs on a dirty working tree — the simplify and
review passes operate on the working diff, so nothing is committed until the chain completes. After
the final `advance` gate and `run_state.py complete`, prepare a commit proposal for the human and record it
as a `commit.proposed` event:

- the exact file list of the issue diff (`git diff --stat`, `git status --short`) — anything the issue did
  not cause is flagged as ride-along and excluded from the proposal;
- a draft commit message: English, what + why in the subject, optional body.

The human reviews, commits, and pushes. Never start preparing a commit while a worker pass is still
active; the tree belongs to the worker until its report is captured and snapshotted.

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

## Recommendations Triage

Non-blocking `## Recommendations` from review and simplify reports must not silently evaporate. After
`run_state.py complete`, collect the recommendations from all reports of the run and present them to the
human for triage. For each accepted item, draft a new issue file in the tracker (next free `ISSUE-NNN`,
status `todo`, frontmatter per the tracker's convention) — creating an issue is a scope decision, so never
add one without explicit human acceptance. Record the outcome per item as a `recommendations.triaged`
event, including a one-line reason for rejected or deferred items, so the next retro can see what was
dropped and why. Also append rejected and deferred items to the tracker's `decisions.md` (one line each:
item, verdict, reason). `render_prompt.py` embeds that file into every worker prompt, so later reviewers
and simplifiers see what the human already declined and do not re-report it unless the code presents a
materially different problem. Triage never blocks the next issue chain: present it and continue; the
decision may stay open until the human responds.

## HITL Issues

Issues with `type: HITL` (releases, deploys, anything outward-facing) never get a worker chain.
`render_prompt.py` refuses them, and `run_state.py init` records `chain: []` with `current_stage: "hitl"`.
The orchestrator may still assist the human:

- Allowed: write verification checklists and docs (record `artifact.written`), verify results against the
  acceptance criteria, run read-only probes, record events and gate decisions.
- Never: deploy, `git push`, flush queues/spools, or send anything outward. Every acting step is the human's.
- Verify both directions. A guard that blocks the bad path is only half-proven; run a counterproof showing
  the allowed path still works (`hitl.verified` for the guard, `hitl.counterproof` for the inverse probe).
- Verification side effects (test orders, spooled mails, test rows) must be recorded in the event data with
  an `action_required` entry and tracked to closure before `run_state.py complete`. A probe that leaves a
  live side effect behind is an unresolved blocker, not a passed check.

## CMUX Control

Prefer current CLI syntax discovered from `cmux --help` before launching workers. Workers must be visible in CMUX
panes. Never type a launch command into a worker pane by hand: `pane_ctl.py start-agent` owns it, so every worker
starts from the exact audited argument vector in its prepared stage snapshot. The default profiles produce:

```bash
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c 'sandbox_workspace_write.writable_roots=["~/.ddev"]' \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  --model gpt-6-astra \
  -c model_reasoning_effort=xhigh                # implement; test uses model_reasoning_effort=high
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model opus --effort high \
  --permission-mode auto                        # simplify, review
```

`CMUX_AGENT_MANAGED_SUBAGENT=1` marks the pane as a managed subagent, which is what cmux keys its notification
suppression on. Without it every turn end, idle reminder and approval prompt of a chain raises a desktop banner with
sound while the human is elsewhere — the point of an AFK run is that only the orchestrator interrupts. The worker
still appears in the Feed and in `surface-health`; only the banners are gone. Suppression follows
`automation.suppressSubagentNotifications` (on by default), and the variable is a cmux internal, so the failure mode
is noise, never a broken run.

The defaults use plain `codex` for implement and test workers and plain `claude` for simplify/refactor and review
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

Three lifecycle verbs cover the error-prone multi-step sequences and record their events themselves:

```bash
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --role review --pass 1 --anchor <prev-worker-surface-id>
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --surface <surface-id> --role review --pass 1
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --surface <surface-id> --role review --pass 1 --prompt <prompt-path>
python3 scripts/pane_ctl.py close --run-dir <run-dir> --surface <surface-id> --role review --pass 1
```

- `launch` first validates that the requested role/pass matches the current, passed, untampered prepared
  snapshot, re-deriving its argument vector from the code-owned adapter policy so a restamped snapshot
  cannot widen the sandbox it launches under. Only then does it split from the anchor surface (`--direction right` default, `--focus false`), label the pane
  per the deterministic label scheme, records `pane.launched` + `pane.labeled`, and prints the new
  surface's stable UUID — use that UUID in every later command; positional refs like `surface:465` shift
  when panes close.
- `start-agent` revalidates the same snapshot, safely shell-quotes its argument vector, sends that exact
  launch command without reading live configuration, records `worker.launch_sent`, and echoes the screen.
- `deliver` sends the text, submits it with an explicit Enter key event, records `worker.prompt_sent`,
  and echoes the pane screen after a short settle. Judging that screen — worker started, or sitting at an
  approval prompt — stays the orchestrator's call; record `worker.started` only after that judgment.
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
or executable; they never replace the safety arguments. The launch command reaches the pane via
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

Do not open simplify, review, or test as down splits from the orchestrator pane just because the orchestrator pane is active after gate processing.

Close completed worker panes promptly:

1. Confirm the worker wrote its final report to the rendered report handoff path.
2. Record a working-tree fingerprint for the capture: `run_state.py snapshot --label "report-captured <role>-<pass>"`.
3. Parse the report and record the gate/event state.
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
7. Start the new pane's worker with `pane_ctl.py start-agent --role <role> --pass <n>`, judge the echoed
   screen (TUI up? trust prompt pending?), then send the prompt with `pane_ctl.py deliver --prompt` and
   confirm the worker started (see the send/Enter rule below).
8. On final completion, HITL, blocker, or run abort, close all completed worker panes after their reports
   and gate decisions are documented.

While a worker pass is active, the working tree belongs to that worker: neither the orchestrator nor the
human should edit product files until the report is captured and snapshotted. Before accusing a worker
report of inaccuracy (`report.integrity`), take a fresh snapshot and compare fingerprints against the one
recorded at capture: a mismatch means the tree changed after capture — by a human or another process, not
necessarily the worker. Attribute first; if an accusation turns out wrong, retract it explicitly with a
`report.integrity.retracted` event.

Keep at most the orchestrator pane and the current active worker pane. Do not leave old implementer, tester, simplify, or reviewer panes open after their reports have been captured and used.

Before launching a worker, choose both paths deterministically and render them into the prompt:

- Prompt path: `.scratch/orchestrator/runs/<run-id>/prompts/<role>-<pass>.md`
- Report handoff path: `.scratch/orchestrator/runs/<run-id>/reports/<role>-<pass>.md`
- Context files: every earlier report of the current pass, passed with `--context-file` — simplify
  receives the implement report; review receives implement and simplify; the final test receives all
  three. Prior reports carry the decisions, trade-offs, and drift notes of earlier stages; passing them
  forward is what lets a reviewer tell a deliberate decision from a mistake.

Send the visible CMUX worker the prompt file path and require it to write the final report to the exact
rendered report handoff path before returning the same report body in the console. That exact report file
is the worker's only lifecycle-state write exception; workers must not edit any other run-state file.

Send any instruction, prompt, or follow-up text to a worker with `pane_ctl.py deliver` — never with a
bare `cmux send`. The underlying trap: `cmux send --help` documents `\n` and `\r` as Enter, but a
trailing `\n` does not submit in either the Codex or the Claude Code TUI; the text lands in the composer
and waits there unsent. `deliver` therefore always sends the text and an explicit `send-key enter` as two
commands, then echoes the pane screen:

```bash
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --surface <surface-id> \
  --role test --pass 1 --prompt .scratch/orchestrator/runs/<run-id>/prompts/test-1.md
```

`--role`/`--pass` are what make the `worker.prompt_sent` event attributable; leaving them off records
`role: null`. `--prompt` builds the delivery line from `orchestrator_lib.delivery_text()` — do not write
that line by hand. A framing like "Read `<path>` and report back" is what a Claude worker answers with a
summary of the prompt, which is why the wording lives in the skill and not in the turn.

Do not send text and rely on noticing later that it is still waiting at the prompt. Judge the echoed
screen (or a later injector `read-screen`) to confirm the worker actually started before treating the
prompt as delivered, then record `worker.started`.

Two distinct not-started screens exist, and they need different handling:

- **Text unsent**: the prompt sits in the composer. `deliver` already sends the explicit Enter, so this
  means the send itself failed — diagnose the pane before resending.
- **Summarized and waiting**: the worker answered with a recap of the prompt ("the prompt is ready to
  execute; I only read it") and went idle. This is the Claude failure mode — the delivery line was read
  as a documentation request. The worker is not started: no `worker.started`. Re-deliver the same prompt
  with `deliver --prompt` (which carries the task framing), judge the screen again, and arm the watcher
  from the re-delivery. A worker that never started does not consume the stage's one deadline extension.

An empty or working-looking pane after `--prompt` delivery is neither case; that pane is working and the
armed watcher owns it.

Do not use hidden subagents as worker substitutes during a live run. If CMUX cannot launch the visible worker, stop and report the CMUX failure. This rule covers the workers themselves; the internal subagents a worker spawns inside its own TUI (e.g. `/code-review` review agents) are part of that worker, not substitutes for it.

## Event Vocabulary

Use these exact event types so runs stay comparable and greppable. New ad-hoc types are allowed, but they
must be dot-namespaced, lower-case, and used consistently within a run — do not spell the same event two
ways (`plan.drift.resolved`, never also `plan.drift_resolved`).

| Event                                                    | When                                                                                                                                             |
|----------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| `run.init`, `run.completed`                              | Written by `run_state.py init` / `complete`                                                                                                      |
| `stage.prepared`                                         | Passed stage snapshot published after full configuration resolution and local preflight; written by `run_state.py init` / `prepare`              |
| `pane.launched`, `pane.labeled`, `pane.closed`           | Worker pane lifecycle; written by `pane_ctl.py launch` / `close`                                                                                 |
| `pane.orphans_detected`                                  | A worker's tooling left panes behind; record IDs, then close them                                                                                |
| `worker.launch_sent`                                     | Worker launch command sent verbatim; written by `pane_ctl.py start-agent`                                                                         |
| `worker.prompt_sent`                                     | Text sent and submitted; written by `pane_ctl.py deliver`                                                                                        |
| `worker.started`                                         | Prompt delivered and confirmed via read-screen — the orchestrator's judgment, after `worker.prompt_sent`                                         |
| `worker.waiting`                                         | Watcher heartbeat while the report is pending; written by `await_report.py` while armed                                                          |
| `worker.finished`                                        | Report captured; data carries `{role, pass, surface_id, runtime}`                                                                                |
| `worker.launch_blocked`                                  | A worker launch was denied (permissions, environment)                                                                                            |
| `gate`                                                   | Only via `run_state.py gate`                                                                                                                     |
| `tree.snapshot`                                          | Only via `run_state.py snapshot`                                                                                                                 |
| `report.reformat_requested`                              | Re-emission asked for a format-only parse failure                                                                                                |
| `report.integrity`, `report.integrity.retracted`         | Report-claim accusation and its explicit retraction                                                                                              |
| `plan.drift`, `plan.drift.resolved`                      | Drift recorded / resolved per the Replanning rules                                                                                               |
| `hitl.resolved`, `decision.human`                        | Human decisions and HITL resolutions                                                                                                             |
| `commit.proposed`                                        | Commit proposal (file list + message draft) handed to the human after `complete`                                                                 |
| `recommendations.triaged`                                | Per-item accept/reject outcome of the post-run recommendations triage                                                                            |
| `artifact.written`, `hitl.verified`, `hitl.counterproof` | HITL-issue assistance (see HITL Issues)                                                                                                          |
| `orchestrator.verified`                                  | Orchestrator-run verification: quick-check test rerun before the simplify gate, or diff inspection at a code-changing gate (commands + outcomes) |
| `orchestrator.halted`, `orchestrator.unverified_input`   | Orchestrator-side anomalies                                                                                                                      |

## Scripts

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

### Adopting a `to-tickets` tracker

Tickets written by `to-tickets` carry no frontmatter, so the preflight rejects them until they are adopted.
`adopt_tracker.py` converts them in place — filenames stay untouched, so `to-tickets` and `/implement` keep
finding their tickets by the paths they expect:

```bash
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> --dry-run
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> \
  --branch feature/<slug> --check-command "<canonical test command>"
```

It writes the frontmatter (`id`, `title`, `type`, `status`, the original triage label under `labels`),
lifts the inline `**Blocked by:**` line into a `## Blocked by` section with normalized ids, drops the now
duplicated inline `**Status:**` line, and scaffolds `README.md` (ground rules) and `decisions.md` when they
are missing. Already adopted files are skipped, so a later batch of tickets can be adopted without
disturbing issues the chain has already advanced.

`type` is derived from the triage vocabulary in `docs/agents/triage-labels.md`, never guessed:
`ready-for-agent` is the only AFK status; `ready-for-human`, `needs-triage`, `needs-info` and `wontfix`
become HITL. A missing or unknown status aborts the whole adoption without writing anything — an issue
whose `type` is silently empty would read as AFK and be handed to autonomous workers.

Adoption writes issue files, so it belongs to the orchestrator's lifecycle-state boundary, not to product
code. If `to-tickets` later rewrites an adopted file, its frontmatter is gone: re-running adoption restores
the format, but a `status: done` recorded there is lost.

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
overrides instead of dropping them:

```bash
python3 scripts/run_state.py init --tracker .scratch/<tracker> --issue ISSUE-001
python3 scripts/run_state.py init --tracker .scratch/<tracker> --issue ISSUE-001 --probe-profiles
python3 scripts/run_state.py event --run-dir .scratch/orchestrator/runs/<run-id> --type worker.started --message "prompt delivered and confirmed via read-screen" --data '{"role":"review","pass":1,"pane_id":"<pane-id>","surface_id":"<surface-id>"}'
```

After every advance gate, prepare the next stage before `pane_ctl.py launch`. This reloads the run's pinned
configuration source and stores all temporary overrides only in that snapshot:

```bash
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage simplify --pass 1
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage test --pass 1 --probe-profiles --probe-timeout 180
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage test --pass 1 \
  --profile test=codex-luna-medium --effort test=high
```

Pane lifecycle events (`pane.launched`, `pane.labeled`, `worker.launch_sent`, `worker.prompt_sent`, `pane.closed`) are written
by `pane_ctl.py` (see CMUX Control); do not hand-write them in parallel.

Record a working-tree fingerprint (at every report capture, and before any `report.integrity` claim):

```bash
python3 scripts/run_state.py snapshot --run-dir .scratch/orchestrator/runs/<run-id> --label "report-captured review-1" --data '{"role":"review","pass":1}'
```

Record a gate decision. `--next-stage` moves `current_stage` forward on `advance`:

```bash
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/<run-id> --stage simplify --decision advance --reason "no findings, checks run, quick-check green" --next-stage review
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/<run-id> --stage review --decision hitl --reason "unresolved must-fix after --fix"
```

Close a run after the final `advance` gate (or after a HITL issue is fully verified). This sets
`current_stage: done`, refreshes the issue snapshot in `state.json`, and appends `run.completed`:

```bash
python3 scripts/run_state.py complete --run-dir .scratch/orchestrator/runs/<run-id> --message "chain complete, issue done 10/10"
```

Render role prompts. `--pass` is required and determines both handoff paths. The prompt's harness variant
comes from the prepared stage snapshot for that role and pass (`init` prepares `implement-1`, `prepare` every
later stage), so rendering before preparation fails; the prompt header records `Harness:` and `Stage snapshot:`.
Implement and test prompts are identical across harnesses; simplify and review switch between Claude Code's
bundled skills and the inline passes. The tracker README's
ground-rules section (any `##` heading containing "ground rules") and the tracker's `decisions.md` triage
ledger (when present) are embedded into every prompt automatically. Pass every earlier report of the
current pass with `--context-file` (repeatable), per the context-files rule in CMUX Control:

```bash
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role implement --pass 1 --run-dir .scratch/orchestrator/runs/<run-id>
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role review --pass 1 --run-dir .scratch/orchestrator/runs/<run-id> --context-file .scratch/orchestrator/runs/<run-id>/reports/implement-1.md --context-file .scratch/orchestrator/runs/<run-id>/reports/simplify-1.md
```

Parse worker reports. Exit code carries the gate; a missing report is `pending` (exit 6), never a crash:

```bash
python3 scripts/parse_report.py path/to/worker-report.md --json
```

Await a worker report deterministically (see Worker Wait Policy for the Monitor invocation). The deadline
defaults to the role's minimum wait; exit 0 = report exists, 7 = pane dead, 8 = deadline exceeded.
Heartbeats go to `events.jsonl` as `worker.waiting`. Health checks are scoped to the run's pinned
`workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_report.py --run-dir .scratch/orchestrator/runs/<run-id> --role review --pass 1 --surface <surface-id>
```

Control worker panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints the pinned
id, `cmux` is the generic `--workspace` injector, `launch`/`deliver`/`close` are the lifecycle verbs.

Run the regression tests after touching `parse_report.py`, `await_report.py`, `pane_ctl.py`, `run_state.py`,
`worker_snapshot.py`, or `agents_config.py`:

```bash
python3 scripts/test_parse_report.py
python3 scripts/test_await_report.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_stage_preparation.py
python3 scripts/test_agents_config.py
```

## Smoke Test

Before a live worker pilot, run the scripts against the real local tracker. Replace `.scratch/<tracker>`
with the tracker directory and `ISSUE-001` with an issue that is ready (type AFK, status todo/in_progress,
unblocked) — `render_prompt.py` refuses HITL and non-ready issues by design. Every command must exit 0, and
the whole block must be safe to run twice in a row:

```bash
python3 scripts/test_parse_report.py
python3 scripts/test_await_report.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_issue_state.py
python3 scripts/test_adopt_tracker.py
python3 scripts/test_agents_config.py
python3 scripts/test_stage_preparation.py
python3 scripts/test_render_prompt.py
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> --dry-run
python3 scripts/issue_state.py list --tracker .scratch/<tracker>
python3 scripts/issue_state.py ready --tracker .scratch/<tracker>
python3 scripts/run_state.py init --tracker .scratch/<tracker> --issue ISSUE-001 --run-id smoke-issue-001
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role implement --pass 1 --run-dir .scratch/orchestrator/runs/smoke-issue-001
python3 scripts/parse_report.py references/sample-no-findings.md --json
python3 scripts/run_state.py snapshot --run-dir .scratch/orchestrator/runs/smoke-issue-001 --label "smoke snapshot"
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/smoke-issue-001 --stage implement --decision advance --reason "smoke test" --next-stage simplify
python3 scripts/run_state.py complete --run-dir .scratch/orchestrator/runs/smoke-issue-001 --message "smoke complete"
```

The smoke test must prove gate correctness, issue parsing, blocker DAG evaluation, prompt rendering, run-state writing, tree fingerprinting, run closing, and report parsing without requiring product-code changes.

`references/sample-no-findings.md` is the shipped clean-report fixture. `run_state.py init` is idempotent, so re-running the block reuses the existing run directory instead of failing. Run the block from the orchestrator's cmux pane so `init` can pin the workspace; outside cmux, pass `--workspace-id <uuid>` or `--no-workspace` explicitly.

## Worker Report Contract

Ask every worker to finish with this report shape. `## Result`, `## Blockers`, and `## Plan Drift` are
required: absent or empty, they make the report malformed and the gate returns `hitl`. An omitted section
never reads as `None`. Under `## Result`, emit exactly one of `NO FINDINGS`, `FINDINGS`, `BLOCKER` — a
literal `NO FINDINGS | FINDINGS | BLOCKER` line is an unfilled template and is rejected.

```markdown
## Result
NO FINDINGS

## Tests / Checks
- `command`: outcome

## Findings
- None

## Blockers
- None

## Plan Drift
- None

## Notes
- Optional: caveats, method notes, context. Never must-fix content.
```

Use exact section labels where possible. Treat missing tests/checks as a failed gate even if the report says `NO FINDINGS`.

The bare-`None` rule: in `## Findings`, `## Blockers`, and `## Plan Drift`, an empty section is exactly the
line `- None` — no prose on or after that line. `parse_report.py` reads anything else in these sections as a
real finding, blocker, or drift; a `- None. Everything fine because …` gates the chain as if a finding were
reported. Explanations belong in the optional `## Notes` section (or `## Recommendations` for review and
simplify workers), which the gate does not parse. Rendered prompts instruct workers to self-validate their
draft with `parse_report.py`, write the same validated body to the exact handoff path, validate that path,
and only then return the report in the console, so format failures die at the source instead of at the gate.

Plan drift is not a finding. `## Plan Drift` is its own section with its own gate (`hitl`); never mirror
drift into `## Findings` or change `## Result` because of it. A report whose only irregularity is drift
keeps `## Result` at `NO FINDINGS`, keeps `## Findings` empty (`- None`), and carries the drift exclusively
in `## Plan Drift` — the parser gates `hitl` from that section alone. `FINDINGS` above an empty
`## Findings` section is a contradiction, not a convention. The allowed `## Result` values stay
`NO FINDINGS`, `FINDINGS`, `BLOCKER`.

For review workers, require severity and recommendation triage. The first check line names the pass the
harness ran: `/code-review medium --fix` on Claude Code, `review pass (standards, spec, correctness)` elsewhere:

```markdown
## Result
NO FINDINGS

## Tests / Checks
- `/code-review medium --fix`: outcome
- `command`: outcome

## Change Summary
- None, or concise list of review fixes applied by the review pass.

## Findings
- None

## Recommendations
- None, or non-blocking nice-to-have/follow-up items.

## Blockers
- None

## Plan Drift
- None
```

`## Findings` follows the bare-`None` rule; remaining must-fix and ask-user findings after the self-fix pass replace
the `- None` line entirely, each with Severity (critical|high|medium|low), `Recommendation: must-fix` or
`Recommendation: ask-user` (ask-user when the finding challenges a documented issue decision — the
reviewer must not fix those), Scope (acceptance|regression|security|data-safety|other), file/line
Evidence, and a concrete suggested fix.
`## Change Summary` and `## Recommendations` are not gate-parsed and may carry prose.

For simplify/refactor workers, require the simplify pass to be reported as a check (`/simplify` on Claude
Code, `simplify pass` elsewhere):

```markdown
## Tests / Checks
- `/simplify`: outcome
- `command`: outcome

## Change Summary
- None, or concise list of behavior-preserving refactorings applied.
```
