---
name: cmux-grilling
description: Coordinate a gated autonomous CMUX grilling session that stress-tests a plan or task through visible research worker panes. Use when an orchestrating agent should grill a plan without user answers - rounds of decision-level questions (the whole frontier per round, no per-round question cap), four fresh research lanes per round (Claude codebase, Codex second-opinion codebase, docs, web), gate-parsed research reports, synthesis with confidence and sources, defined assumptions and open decisions written as a Markdown+JSON pair under the tracker's grilling directory, assumptions review, a decision walkthrough with the human, run-state logging, and cmux worker-pane workflows. For interactive grilling where the user answers the questions, use the grilling skill instead.
---

# CMUX Grilling

Use this skill to grill a task autonomously: the orchestrator asks decision-level questions
about a plan, four fresh visible research lanes per round answer each question against the
current repository and the web, and the session ends with distilled defined assumptions the
human reviews. The orchestrator is a coordinator plus judgment role: it formulates questions
(griller), consolidates lane reports (synthesizer), and distills assumptions (finalize), but
all research runs in visible CMUX worker panes.

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

`run_state.py init` requires an existing configuration at the default or explicit path; it never
creates one. After the first-use checkpoint, it resolves and preflights all four lanes as one
cohort. It publishes run state only after every lane passes and records one immutable launch-wave
snapshot. Preparation resolves each unique assigned executable, captures its version, checks
required help capabilities and local authentication status, and records provider entitlement as
`unverified` by default. This local preflight is mandatory.

Initialization accepts repeatable typed overrides in `LANE=VALUE` form: `--profile`,
`--harness`, `--model`, `--effort`, and `--executable`. File assignment resolves first,
then profile selection, then direct field overrides. Overrides live only in the new run's
launch wave. Existing runs refuse configuration inputs during idempotent re-initialization;
configuration changes intentionally take effect only in a new grilling run.

Opt into live entitlement checks during initialization with `--probe-profiles`; use
`--probe-timeout <seconds>` with it to change the CLI-only 120-second default. The option makes
one real request per unique named and fully resolved assigned profile after all four lanes pass
validation and local preflight. Duplicate assignments share a request and unused profiles are
not contacted. Claude runs in safe, non-persistent print mode with every tool disabled; Codex
runs ephemerally in a read-only sandbox with approvals disabled. Each probe's own options are
checked against the CLI's help before its request goes out, so an installation that cannot be
probed reports a missing capability instead of a failed entitlement. Both must exit zero and print
exactly `CMUX_PROFILE_PROBE_OK_V1`. A nonzero exit, timeout, malformed output, or missing sentinel
fails initialization before pane creation. Success changes the matching entitlement to `verified`;
no probe leaves it `unverified`.

The frozen launch wave audits the configuration source and hash, overrides, resolved profiles,
executable/version/preflight data, final lane argv, probe enablement and timeout, and each probe's
status and timing without saving provider output, credentials, or ambient environment values.
Harness safety remains code-owned: JSON and typed overrides cannot supply free-form arguments,
environment values, capabilities, sandbox or approval policy, network access, writable roots,
prompt delivery, or other runtime safety overrides.

## Relationship to the `grilling` Skill

Two skills share the grilling concept; keep them apart. `grilling` is a separate,
optional interactive skill that is not bundled with this one — without it installed the
distinction still applies, there is just no interactive counterpart to invoke.

- `grilling` (interactive): the agent grills the **user**; the user answers each decision.
- `cmux-grilling` (this skill): research lanes answer; the **user is not asked during the
  run** and reviews the defined assumptions at the end.

The task input is a plan (what should be built) plus its already-fixed constraints.
The constraints belong in the task so the griller does not waste questions on decided
matters and attacks the open decisions behind them instead.

## Boundaries

- Only after successful completion, the orchestrator's new Git writes through `run_commit.py commit`
  are literal leaf `git add`, `git commit`, path-limited `git reset -q --`, and compare-and-swap
  `git update-ref HEAD <P> <C>` to undo its proven commit. Never `--no-verify`; workers retain their
  index and HEAD prohibition. A HITL issue run always proposes.

- The orchestrator never edits product code and never performs the research itself. It may
  write lifecycle state only: `.scratch/orchestrator/runs/<run-id>/`, run logs, prompts,
  gate decisions, snapshots, synthesis files, and the final artifact pair in the output
  directory (`<tracker>/grilling/` by default, see Artifact Location).
- Research lanes are strictly read-only towards the repository: no file edits, no
  state-changing commands. A lane may write exactly two files per round: its named draft
  path and its report handoff path. Drafts default to
  `<run-dir>/drafts/round-<N>-<lane>.md`; reports default to
  `<run-dir>/reports/round-<N>-<lane>.md`. Draft validation and report capture are explicitly
  delegated to the lanes because four reports arrive in parallel each round.
- Lanes must not write any other orchestration lifecycle state.
- Start lanes visibly in CMUX panes. Do not substitute hidden subagents, background shells,
  or non-CMUX subprocesses for live research lanes. If CMUX cannot launch a lane, stop and
  report the CMUX failure. This covers the lanes themselves; the internal subagents a lane
  spawns inside its own TUI are part of that lane, not substitutes for it.
- The working tree must stay untouched apart from the run directory and the artifact output
  directory. Tree snapshots at every round capture verify this; an unexpected fingerprint
  change is investigated before any integrity accusation (attribute first, retract
  explicitly with `report.integrity.retracted` if wrong).
- No branch requirement: grilling changes no product code, so there is no branch gate. Do
  not create branches for a grilling run.

## Session Shape

Roles:

1. **Griller** — orchestrator step. Works the plan as a design tree in **rounds**. Each round
   asks the whole **frontier**: every decision-level question whose prerequisites the earlier
   rounds' syntheses already settled, numbered `Q1..Qn`. A question is decision-level when its
   answer changes what would be built. There is no cap on questions per round; the budget
   counts rounds (`max_rounds`, default 4). A question whose answer depends on another question
   still open in the same round belongs to a later round. Never ask what the task's fixed
   constraints already decide. Facts are the lanes' job; nothing is put to the human during the
   run. The loop ends when the frontier is empty (`griller-done`) or the round budget is spent
   (`max-rounds`).
2. **Research lanes** — four fresh visible panes per round, with the round task attached
   to each launch:
   - `codebase` — repo-only research, no web (Claude Opus/high by default).
   - `codebase2` — independent second-opinion repo research, no web (Codex by default).
   - `docs` — official documentation for the versions the repo pins (Codex Luna/medium by default).
   - `web` — public-web research (Claude Sonnet/medium and Claude-only by policy).
3. **Synthesizer** — orchestrator step. Consolidates the four lane reports of a round into
   one answer with confidence, sources, and reasoning.
4. **Finalize** — orchestrator step. Distills the defined assumptions, writes the artifact
   pair, and presents the assumptions for human review.

This deliberately deviates from the sibling skill's "at most orchestrator plus one worker
pane" rule: a grilling round keeps the orchestrator pane plus all four lane panes open.
At the next round, replacement panes are created before the old panes close.

## Run Briefing

A fresh session opens with a compact briefing so the human sees what is being grilled without
opening a file. After `run_state.py init` and before the first `pane_ctl.py open-round`:

```bash
python3 scripts/run_briefing.py draft --run-dir <run-dir> --lang <de|en>
# Replace {{subject}}, {{focus}} and {{constraints}} in <run-dir>/briefing.md, then:
python3 scripts/run_briefing.py show --run-dir <run-dir> --lang <de|en>
```

- `draft` writes `briefing.md` with the facts filled in (question budget, lanes, artifact directory)
  and never overwrites an existing briefing. Pick `--lang` by the human's language.
- Fill only the placeholders, from `task.md`: `{{subject}}` is the plan or task in one or two
  sentences; `{{focus}}` names the three to five decision areas the griller intends to probe,
  which previews the round questions; `{{constraints}}` lists the fixed constraints that will not
  be questioned. Neutral wording; keep the fixed lines and their order unchanged.
- `show` refuses while a placeholder remains, prints the briefing, records `run.briefing`, and sets
  the sidebar pill `cmux-grilling-run` (`Grilling · <slug>`) in the pinned workspace. A failed pill
  is a stderr note, not a stop. Relay the printed briefing verbatim as its own message, without
  preamble.
- On resume, run `show` again: it is the reorientation after a context compaction as well.

## Delivery baselines and staged deltas

Before each round delivery, run `open-round`, then capture
`run_state.py snapshot --label "launched round-<N>"` before `start-round`.
Compare that round baseline with its `reports-captured round-<N>` snapshot after report
capture and before any advance gate. Never replace a baseline before checking the interval
it covers, including on re-delivery.

Compare `staged_paths` and `staged_diff_sha256` for each interval. Any staged-path or
staged-digest change prevents advance: gate `hitl` even with clean reports, recording the
sorted union of the baseline and capture staged path lists in the gate reason. Also compare
`head` for each interval: any HEAD change prevents advance and gates `hitl` even with clean
reports, recording the before and after HEAD values in the gate reason. An unchanged
pre-staged human baseline is permitted. Preserve attribution-first handling: investigate
who changed the index before accusing a lane; retract a mistaken accusation explicitly with
`report.integrity.retracted`. Never unstage on a lane's behalf.

## Round Loop

For each round `N` (1-based), in order:

1. Compute the frontier and record one `grill.question` event per question with
   `{"round": N, "id": "Q1", "question": "...", "depends_on": []}`. The explicit array is
   mandatory, including in round 1; use earlier IDs such as `"R1Q2"` when building on an
   earlier answer. The event command validates that dependencies name earlier recorded
   questions. Questions in one round must be independent. Re-ask deferred questions with
   new IDs in a later round.
2. Render the four self-contained prompts with `render_prompt.py round`, passing the same
   frontier with repeated `--question`/`--question-file` flags. Each prompt includes its lane
   policy, task, report contract, marker, and a shared `prompts/round-<N>-context.md` reference.
   The renderer requires exactly one matching event per question. It projects dependencies
   from earlier synthesis files (id, question, answer, confidence, sources, and reasoning
   carrying caveats or disagreement) and indexes every other settled question with its
   synthesis-file reference. No per-lane findings or earlier lane reports enter that context.
   Context is for re-verification, not evidence. The shared file is capped at **16 KiB UTF-8**;
   missing metadata or overflow fails closed. Supply an authored neutral digest through
   `--context-digest <path>` (same cap) as the only recovery. A recorded round frontier
   cannot be narrowed, and a recorded round id cannot be recorded again.
   The digest may recover missing legacy `depends_on` metadata but never duplicate or
   mismatched current question events. Include source references and all relevant caveats.
3. Run `pane_ctl.py open-round --round <N>` (round 1 also needs `--anchor <orchestrator-UUID>`).
   It reuses and validates the immutable launch wave, opens four new panes, then closes the
   previous round's panes. Capture `run_state.py snapshot --label "launched round-<N>"`,
   then run `pane_ctl.py start-round --round <N>`. Read its one JSON result and arm one
   `await_reports.py --round <N> --questions <n> --lane-surface …` watch using the Lane Wait
   Policy. No normal-path observation or separate delivery is needed. First-step markers are
   `artifacts/round-<N>-<lane>/started`; reports land at `reports/round-<N>-<lane>.md`.
4. When all four reports exist, record one tree snapshot:
   `run_state.py snapshot --label "reports-captured round-<N>"`. Compare the staged fields
   and HEAD against the round delivery baseline before parsing advance gates.
5. Parse each report with `parse_research_report.py --questions <n>` and record one gate per lane
   with `--stage round-<N>-<lane>`; the gate reason names each non-advancing question. Record
   `worker.finished` per lane with `{"lane": ..., "round": N, "surface_id": ...}`.
6. Every question whose four lane gates are `advance` is synthesized: write
   `synthesis/round-<N>.json` (format below) and record `grill.synthesis` per question. Questions
   that failed on form follow Question failures in `references/gate-recovery.md`. Then either open the next round, or stop the
   loop when the budget is exhausted or the frontier is empty (`grill.done` with the reason;
   `stopReason` is `max-rounds` or `griller-done`).
7. A `blocked` or `hitl` gate that is not a pure form failure stops the session (see Gate Rule),
   with one exception: a `hitl` whose sole reason is plan drift goes through Drift Triage in `references/gate-recovery.md` and may
   continue as small-factual. There is no empty-finding degradation and no automatic lane relaunch:
   a failed lane is a session-level `hitl`/`blocked`, resumable only through a human decision
   (`hitl.resolved`, `decision.human`).

The last lane gate of a clean round carries `--next-stage round-<N+1>` (or `finalize` after
the final round) so `state.json` tracks the position; the coarse `chain` stays
`["research", "finalize"]`.

### Synthesis

Synthesis is judgment, not vote counting, and runs per question:

- Weigh lanes by authority: project-internal questions → the codebase lanes are
  authoritative; library/API questions → docs; external practice questions → web.
- A `NO ANSWER` lane neither conflicts nor adds evidence.
- Disagreement between `codebase` and `codebase2` lowers confidence, must be named in the
  reasoning, and is a legitimate trigger for a follow-up question in a later round.
- An answer's sources are the union of the supporting lanes' sources, not everything any
  lane mentioned.

`synthesis/round-<N>.json` holds every synthesized question of the round:

```json
{
  "round": 1,
  "questions": [
    {
      "id": "Q1",
      "question": "...",
      "answer": "...",
      "confidence": "high|medium|low",
      "sources": ["..."],
      "reasoning": "...",
      "reasoning_for_context": true,
      "findings": {
        "codebase": {"result": "ANSWERED", "answer": "...", "sources": ["..."]},
        "codebase2": {"result": "ANSWERED", "answer": "...", "sources": ["..."]},
        "docs": {"result": "NO ANSWER", "answer": "...", "sources": []},
        "web": {"result": "NO ANSWER", "answer": "...", "sources": []}
      }
    }
  ]
}
```

For each non-empty `reasoning`, set `reasoning_for_context` to `true` only when that
reasoning carries caveats or disagreement needed by a later dependent question; otherwise
set it to `false`. Keep a `true` reasoning focused on those caveats. The renderer uses this
explicit judgment instead of guessing from keywords or language. Missing classification
for a dependency fails closed to `--context-digest`. Write a synthesis file with an empty
`questions` array even if every question was deferred, so context can distinguish no settled
answers from missing metadata.

## Gate Rule

`parse_research_report.py` gates every `## Q<n>` block of a lane report on its own and emits
one of five values per question; the report gate is the most severe question gate.
`run_state.py gate --decision` accepts the same five. Never invent a sixth.

| Gate      | Meaning                                        | Exit code | Orchestrator action                  |
|-----------|------------------------------------------------|-----------|--------------------------------------|
| `advance` | Well-formed report (`ANSWERED` or `NO ANSWER`) | 0         | Count the lane as delivered          |
| `stop`    | Ungrounded or contradictory question           | 3         | Do not synthesize it; Question failures in `references/gate-recovery.md` |
| `blocked` | Lane reported a `BLOCKER`                      | 4         | Stop the session, record the blocker |
| `hitl`    | Plan drift, or a malformed question or report  | 5         | Form: Question failures in `references/gate-recovery.md`; drift: Drift Triage in `references/gate-recovery.md`; else stop |
| `pending` | Report not written yet                         | 6         | Keep waiting per the wait policy     |

The gate is the **most severe** triggered condition: `blocked` > `hitl` > `stop` >
`advance`. Research-specific semantics:

- `NO ANSWER` with an explanation under `### Answer` is a clean `advance`. The gate checks
  form; the synthesizer judges research quality.
- `ANSWERED` without at least one real source is `stop` — ungrounded answers must not reach
  the synthesizer.
- `### Plan Drift` is for a stale or wrong task premise (the plan contradicts what research
  found). The parser gates any drift as `hitl`; the orchestrator then triages it in two
  classes (see Drift Triage in `references/gate-recovery.md`) — only load-bearing drift reaches the human mid-run.
- A required section (`### Result`, `### Answer`, `### Sources`, `### Method`, `### Blockers`,
  `### Plan Drift`) that is absent or empty makes its question malformed and yields `hitl`. An
  omitted section never reads as `None`. So does a missing, duplicate, or unexpected `## Q<n>`
  block; a report without any question block is `hitl` for the whole report.

A question synthesizes only when all four lanes gate `advance` for it. A failing lane never
silently degrades to an empty finding, and a question is never synthesized from fewer than four
lanes. A `blocked` question, a load-bearing drift, a dead pane, or an exhausted deadline stops the
whole session. A form failure (`stop` or malformed `hitl` without blocker or drift) is handled per
question, below. The one other exception is small-factual drift, triaged next.

Read when a question has a form failure or plan drift: [references/gate-recovery.md](references/gate-recovery.md).

## Lane Wait Policy

Treat a missing lane report as `pending`, not as a failed gate. `parse_research_report.py`
enforces this: a missing report prints `gate=pending` and exits 6 rather than raising.

Minimum wait per lane and round: **15 minutes for the first question plus 5 minutes per further
question** (30 minutes for four), uniform across lanes. Pass the round's question count to the
watcher as `--questions <n>`; the flag is required, so a forgotten count cannot shorten the wait.

### Armed watcher, not polling

The orchestrator only exists within a turn; between turns nothing polls. Before ending any
turn while a round is in flight, the orchestrator MUST arm a watcher that re-invokes it —
ending a turn with lanes running and no armed watcher is a policy violation. The watcher is
`await_reports.py`: **one watcher per round, not per lane**, because a round synthesizes only
when all four lanes delivered. It blocks on the four report handoff paths (the ground truth),
checks `cmux surface-health` for dead panes, and writes the `worker.waiting` heartbeats
itself. For a local interactive Claude Code orchestrator (2.1.288 or later), use Bash
`run_in_background`: background tasks have no time limit and produce one wake-up at exit.
For other hosts and unattended sessions, use Monitor with re-arm (30 minutes by default,
up to 2 hours). If Monitor expires before the watcher exits, re-arm the same command;
this resumes the persisted deadline and does not grant more time.

```
Bash(
  command: "python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --questions 3 --lane-surface codebase=<surface-id> --lane-surface codebase2=<surface-id> --lane-surface docs=<surface-id> --lane-surface web=<surface-id>",
  run_in_background: true
)
```

Both deadlines are persisted on first arm in a `worker.waiting` event for the round,
anchored to its earliest recorded launch `start_time_ns`. Every invocation computes the remaining time;
re-arming, including after a host timeout, never moves either deadline. Initial
`--deadline-minutes` overrides the minimum for a bounded smoke run. For the one extension,
pass `--deadline-minutes <additional-minutes> --deadline-reason "<recorded reason>"`;
the watcher records the reason and grants that duration from the later of the existing
deadline and extension arm. Repeating the same extension is idempotent; a second extension
is refused. The start window is not extended by this flag. Only a recorded exit-9 recovery for a
`not_started` lane (`respond`, readiness-gated re-delivery, a recovery launch, or screen
confirmation) starts a new window without spending the extension. A follow-up, new launch
outside exit-9 recovery, observation, assessment, or re-arm does not renew the round clock.
Never run two watchers for the same work concurrently.

The same poll loop tracks starts and reports independently for every lane. A round marker
with mtime ≥ the current launch's `start_time_ns`, or a non-empty current-round report with
that freshness, confirms start. Marker evidence is preferred. The watcher records exactly
one `worker.started` per `launch_id`, including lane, round, surface UUID, evidence, and
marker path. A previous round's marker or report cannot confirm the new round.

Health is checked only for lanes whose report is still missing. A lane whose pane exits right
after writing its report has delivered, not died.

The watcher uses these exit codes:

| Exit | Condition                                               | Orchestrator action                                                                               |
|------|---------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| 0    | All fresh non-empty round reports exist | Snapshot, parse each lane, gate — exit 0 is not an advance verdict |
| 7    | A pending lane's pane is dead per `cmux surface-health` | Stop as HITL for that lane; a dead pane with no report is orchestration uncertainty, not findings |
| 8    | Round deadline exceeded, pending panes alive/unknown          | Extend once with a recorded reason (re-arm with `--deadline-minutes`), else stop as HITL          |
| 9    | Round lanes not started within the start window | Inspect only `not_started` lanes using the round exception path, then re-arm |

The stdout line carries the detail the exit code cannot:
`outcome=… round=1 elapsed_seconds=… started=codebase,docs not_started=codebase2,web delivered=codebase,docs missing=codebase2,web dead=codebase2`
(`none` where a list is empty). The files remain the ground truth — parse them, do not trust
the line alone.

While a watcher is armed it is the sole emitter of `worker.waiting`; the orchestrator does not
hand-write waiting events in parallel. Silence is never success — only the report files are
ground truth, never status words on screen (the Claude TUI shows ever-changing gerunds, Codex
shows `Working`). A static-looking pane is not a dead one: Codex lanes route approvals to
their reviewer agent rather than to the human, so a quiet pane is a lane still thinking or
one already finished, and the watcher correctly keeps waiting either way. Only
`surface-health` reporting the surface gone counts as dead.

- Exactly one deadline extension per round; pass `--deadline-reason` so the watcher records its reason
  when re-arming. Before spending it on a silent lane, check the
  screen for the not-started case in CMUX Control: re-delivering a round prompt to a lane that
  never started restarts the wait clock and is not an extension.
- After an exhausted extension with no report, or a dead pane: record a `hitl` gate for
  `round-<N>-<lane>` and stop the session. Use `blocked` only for blockers a lane itself
  reported.
- Never close a lane pane while its report is pending, and never send the next round while
  any report of the current round is outstanding.

## Artifact Location

The artifact pair lands next to the tracker it belongs to. `run_state.py init` resolves the
location once and records it in `state.json` as `output_dir` (with the `tracker` it came
from); every later step of the run reads it from there. `pending-decisions` — which runs
before `init` — resolves by the same table. First match wins:

| Input                            | Output directory        |
|----------------------------------|-------------------------|
| `--output-dir <path>`            | `<path>`, verbatim      |
| `--tracker .scratch/<tracker>`   | `.scratch/<tracker>/grilling/` |
| nothing, exactly one `.scratch/*/issues/` | that tracker's `grilling/` |
| nothing, several such trackers   | hard stop — ask the human which tracker, pass `--tracker` |
| nothing, no tracker at all       | `.scratch/grilling/`    |

## Finalize and Artifact

The order of the closing steps is fixed: finalize, ending with `complete` (below) → assumptions
review → decision walkthrough → transcribe outcomes into the Markdown → commit proposal → commit
(commit mode) → run recap. The sections after this one expand the steps past finalize.

When the loop ends cleanly (`max-rounds` or `griller-done`):

1. Distill the **defined assumptions** from all round syntheses: concrete, decision-ready
   statements a plan can build on — each traceable to Q&A rounds, none invented beyond the
   research. Record `grill.assumptions` with the count.
2. Distill the **open decisions** in the same step (see Open Decisions below). Record
   `grill.open_decisions` with the count.
3. Write the artifact pair to the output directory from `state.json`:
   - `<output-dir>/<slug>-<timestamp>.md` — human-readable protocol in the established
     grill-session format: header (generation time, question count, stop reason), `## Aufgabe`,
     `## Q&A` (per round a `### Runde <N>` heading, per question: question, Antwort, Confidence,
     Quellen, Reasoning, plus the four lane findings in a collapsible block; deferred questions
     are listed with their reason), `## Definierte Annahmen`, `## Entscheidungen`
     (one top-level block per open decision, rendering the `open_decisions` fields in German —
     Frage, Kontext, Belege, Optionen mit Implikation, Empfehlung — plus its Ausgang once
     decided), and — when any drift was self-resolved — `## Prämissen-Korrekturen` listing
     each small-factual drift and its resolution. Keep this heading vocabulary stable so
     grill-session artifacts stay comparable across sessions.
   - `<output-dir>/<slug>-<timestamp>.json` — machine-readable result assembled from the
     `synthesis/round-*.json` files:

   ```json
   {
     "run_id": "...",
     "task": "...",
     "codebasePath": ".",
     "maxRounds": 4,
     "roundsRun": 3,
     "questionsAsked": 7,
     "stopReason": "griller-done",
     "qa": ["... every synthesized question, flattened in round order, each with its round and id ..."],
     "assumptions": ["..."],
     "open_decisions": ["... see Open Decisions ..."],
     "markdownPath": "<output-dir>/<slug>-<timestamp>.md",
     "jsonPath": "<output-dir>/<slug>-<timestamp>.json"
   }
   ```

   `qa` holds exactly one entry per synthesized question (`len(qa) == questionsAsked`), each
   the question object from `synthesis/round-<N>.json` plus `round`; `(round, id)` is unique and
   `round <= roundsRun <= maxRounds`. Deferred questions are not entries. The JSON schema is
   deliberately stable: the same top-level fields and one findings entry per lane in every
   session, so downstream consumers can build on it. Artifacts with `maxQuestions` instead of
   `maxRounds` come from before multi-question rounds; `cmux-planning` does not import them —
   rerun the grilling.
4. Validate what was just written: `run_state.py validate-artifact --artifact <json>`. It
   checks every `open_decisions` entry against the schema here, so a thin entry is repaired
   while the rounds are still in context.
5. Record the finalize gate (`--stage finalize --decision advance`) and close the run:
   `run_state.py complete --run-dir <run-dir> --markdown <artifact.md> --json <artifact.json> --data '{"stop_reason": ...}'`.
6. Close the four lane panes after their last reports and the gates are documented; record
   `pane.closed` per lane.

The artifact pair is written **before** the walkthrough with the human, while every decision
still carries `"status": "open"`. The run is technically finished at that point, so nothing
is lost if the human never returns.

### Open Decisions

An **assumption** is settled. An **open decision** is a fork the research deliberately cannot
close: product taste (`product`), a deviation from a written specification
(`spec-deviation`), or a genuine tie in the evidence (`tie`). Decided points never migrate
into the assumptions — they stay their own list with a cross-reference.

Each entry in `open_decisions`:

```json
{ "id": "D1", "question": "…", "why_open": "product|spec-deviation|tie",
  "context": "3-6 Sätze: was heute im Code/Issue steht, was die Recherche fand, was auf dem Spiel steht",
  "evidence": ["Runde 2 — Wortlaut", "Project.php:411-414", "ISSUE-013 AC2"],
  "options": [{"label": "…", "implication": "…", "preview": "optional, Monospace-Block"}],
  "recommendation": "…", "rationale": "…",
  "status": "open|decided|deferred", "decision": "…", "decided_at": "…" }
```

Write `context`, `evidence`, `options`, `recommendation` and `rationale` **during finalize**,
while all rounds are still present — distilled later, at asking time, they come out thin and
unusable.

## Assumptions Review

After `complete`, present the defined assumptions — together with any self-resolved premise
corrections from Drift Triage in `references/gate-recovery.md` — to the human for review: confirm, correct, or discard per
assumption. Record the outcome per item as a
`grill.assumptions_triaged` event, including a one-line reason for corrected or discarded
items. The review never blocks: present it and stop; the decision may stay open until the
human responds. Do not draft tracker issues from assumptions — handing results to
`cmux-issue-chain` is a human planning step, not part of this skill.

## Decision Walkthrough

After the assumptions are presented, walk the human through the open decisions — one at a
time, in id order.

- **One decision per `AskUserQuestion` call** — the points depend on each other (a wording
  decision changes what the test asserts), and each needs its own context paragraph.
- **Post the entry's `context` and `evidence` as a chat paragraph before each question**, so
  the question card itself stays readable.
- **Use `preview`** wherever there is something to see: the rendered sentence per variant,
  the markup with and without a test hook. Only possible for single-select questions.
- The **recommendation is the first option**, labelled `(Empfohlen)`.
- **"Später entscheiden" is a regular option in every question** → `status: "deferred"`;
  `AskUserQuestion` has no timeout.
- Questions and options in **German**, like the artifacts; this skill's own text stays
  English.
- Record every answer with `run_state.py decision`, which writes `status`, `decision` and
  `decided_at` into the artifact JSON and emits `grill.decision_recorded`. It prints the
  `Ausgang` line back; collect those lines and transcribe them into the `## Entscheidungen`
  blocks of the Markdown in one pass after the last question, so both halves of the pair
  carry the same outcome.

Read when checking for unfinished decisions at session start or resuming a walkthrough: [references/resume-walkthrough.md](references/resume-walkthrough.md).

## Commit Proposal

After `complete`, always record the artifact pair with `run_commit.py propose`. Supply the two recorded
markdown/json deliverables as repository-relative literal leaf paths with repeated `--file`; anything
else is a ride-along, excluded from `--file` and listed with `--ride-along`. Use an English one-line
subject explaining what changed and why, an optional body, and no trailers. Name each decision still
`open` or `deferred` with `--unresolved` so the human sees what is outstanding.

```bash
python3 scripts/run_commit.py propose --run-dir <run-dir> --subject "Record decisions and assumptions" --file <markdown-leaf> --file <json-leaf> --unresolved <decision-id>
```

The helper records the replay-safe `commit.proposed` event and classifies ignored and pre-run dirty
files.

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

## Run Recap

The counterpart to the Run Briefing and the last message of a session. After the commit proposal and `run_commit.py commit` in commit mode,
or after a `hitl`, `blocked`, or `stop` gate that ends the session:

```bash
python3 scripts/run_briefing.py recap-draft --run-dir <run-dir> --lang <de|en>
# Replace {{outcome}} in <run-dir>/recap.md, then:
python3 scripts/run_briefing.py recap-show --run-dir <run-dir> --lang <de|en>
```

- `recap-draft` refuses an active run. It writes `recap.md` with the facts from `state.json`,
  `events.jsonl`, and the artifact JSON: status (done, or halted at stage and decision), duration,
  questions asked in the rounds run against the round budget and the stop reason, assumption count, decisions by status, the
  artifact paths, the commit subject, and for a completed session the next step: resolving the
  decisions still `open` in the walkthrough, or else planning with the artifact JSON, followed by a
  prompt block with `/cmux-planning <artifact.json>`; additions from the grilling prompt are not
  carried over. It never overwrites an existing recap.
- Fill only `{{outcome}}`: one or two sentences on the key findings, or for a halted session what
  stopped it and what the human has to decide. Neutral wording.
- `recap-show` refuses while the placeholder remains, prints the recap, records `run.recap`, and
  turns the sidebar pill into `✓ Grilling · <slug>` (green) or `<decision> · Grilling · <slug>` (red).
  `--clear-status` removes the pill instead, only when the human asks for it. Relay the printed recap
  verbatim as its own message.

## Worker input readiness

Normal round starts attach each self-contained prompt through `start-round` / `start-agent`.
One `await_reports.py --round N` watch confirms starts and waits for reports. Readiness
observations are exception-path and follow-up only: after exit 9, or before re-delivery
and follow-up input, follow
[Interactive worker readiness](references/worker-readiness.md). Use `observe`, explicitly
`assess` the current screen, resolve dialogs with `respond`, then consume one fresh
`worker.ready` with `deliver`. Read each tool result before the next input. The gate applies
to Codex, Claude Code and Pi. `worker.ready` permits one delivery and is distinct from
`worker.started`; on recovery, observe again.

## CMUX Control

Prefer current CLI syntax discovered from `cmux --help` before launching lanes. Lanes must
be visible in CMUX panes. Never type a launch command into a lane pane by hand:
`pane_ctl.py start-agent` owns it and reads only the lane's matching entry from the immutable
prepared launch wave. Both `launch` and `start-agent` validate the entire wave first, so a
missing, failed, mismatched, or tampered lane blocks every pane.

Read when inspecting the default launch wave, harness arguments, sandbox policy, or notification behavior: [references/launch-policy.md](references/launch-policy.md).

### Pinned workspace, deterministic pane control

`run_state.py init` prepares the full launch wave before it publishes a launchable run and
pins the run's cmux workspace: flag > `CMUX_WORKSPACE_ID` env > hard error
(the env var of the orchestrator pane is the only place that variable is ever read;
`--no-workspace` is the explicit opt-out for offline runs outside cmux). Every cmux call after
init goes through `pane_ctl.py`, which reads the pinned `workspace_id` from `state.json` —
never through raw `cmux` with an env-var workspace, and never with a fallback to the focused
workspace. An empty or missing pinned ID is a stop, not a fallback: the human may be looking
at a different workspace than the one the run owns, and cmux resolves unscoped commands
against the focused one.

Round start:

```bash
python3 scripts/pane_ctl.py open-round --run-dir <run-dir> --round 1 --anchor <orchestrator-UUID>
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "launched round-1"
python3 scripts/pane_ctl.py start-round --run-dir <run-dir> --round 1
python3 scripts/await_reports.py --run-dir <run-dir> --round 1 --questions <n> --lane-surface codebase=<UUID> --lane-surface codebase2=<UUID> --lane-surface docs=<UUID> --lane-surface web=<UUID>
```

Check `run_state.py pending-decisions` before fresh init, then show the Run Briefing and
record/render the frontier before this sequence. `open-round` validates the entire immutable
wave and prints one JSON mapping of lanes to stable surface UUIDs. Use UUIDs only, never
positional `surface:N` refs. Round 1 splits right from the orchestrator and stacks subsequent
lanes down from the preceding lane. Later rounds split down from each lane's previous-round
surface. All four replacements exist before any old surface closes. Labels include the
lane, `grill-<slug>`, and `round-<N>`; pane lifecycle events carry `round`.

Before opening the next round, finish the previous round's reports, its one permitted
re-emission, capture snapshot, integrity comparison, and gates. `open-round` refuses without
the previous capture snapshot and lane gates. It stops at the first failure and names
launched, closed, and orphaned surfaces; it never rolls back. Inspect partial results and
use the single-lane `launch`, `start-agent`, and `close` verbs for recovery, with `--round N`.
Do not replay a failed batch blindly. Record orphan evidence and close only known owned UUIDs.

`start-round` requires the newest `tree.snapshot` to be `launched round-<N>` and newer than
that round's last pane event. It starts each lane via the existing `start-agent` implementation,
attaching `delivery_text("round", prompts/round-<N>-<lane>.md)` as one quoted last argument.
It records `worker.starting` and `worker.launch_sent` with round, launch identity,
`start_time_ns`, prompt path, and marker path. It stops at the first failure and names
started and unstarted lanes. It refuses a repeated batch start; use single-lane recovery.
Default settle time is zero; single-lane `--settle-seconds` enables a diagnostic screen read.

Read when the watcher exits 9 or re-delivering a round assignment: [references/startup-recovery.md](references/startup-recovery.md).

Keep current round panes open until the next `open-round` or session end, after reports,
re-emission, gates, and snapshot are recorded. At session end use `close --round N --lane
<lane> --surface <UUID>` per lane. Never close a pending report's pane during a normal wait.

While a round is in flight, the four reports belong to the lanes: do not edit anything under
`reports/` yourself, and compare snapshot fingerprints before any `report.integrity` claim.

## Event Vocabulary

`commit.proposed` is written only by `run_commit.py propose`.
`commit.attempted`, `commit.created`, `commit.skipped`, and `commit.failed` are written only by
`run_commit.py commit`: attempt before Git, proven success, nothing to commit, or proposal fallback.

Read when writing any event with `run_state.py event` (including drift records) or interpreting lifecycle events: [references/event-vocabulary.md](references/event-vocabulary.md).

## Scripts

`run_commit.py propose` is the only writer of `commit.proposed`; generic `event` refuses `commit.*`.

The scripts are deterministic helpers. Run them from the repo root.

Create a run (idempotent; prints the run directory). After the configuration checkpoint above,
`init` loads the existing worker configuration, validates and preflights all four lanes together,
writes one immutable launch wave, and pins the run's cmux workspace
(`--workspace-id` > `CMUX_WORKSPACE_ID` > hard error; `--no-workspace` is the explicit opt-out
for offline runs outside cmux) and drops a self-ignoring `.gitignore` (`*`) into the runs
root, so run state never reaches git in any target repo:

```bash
python3 scripts/run_state.py init --task "Plan plus fixed constraints" --max-rounds 4
python3 scripts/run_state.py init --task-file path/to/task.md --tracker .scratch/<tracker>
python3 scripts/run_state.py init --task-file path/to/task.md --config path/to/agents.json
python3 scripts/run_state.py init --task-file path/to/task.md --probe-profiles --probe-timeout 180
```

`init` also resolves the artifact location; the precedence is in Artifact Location.

Read when using artifact, rendering, parsing, snapshot, gate, completion, or regression-test CLI examples: [references/script-reference.md](references/script-reference.md).

Read when preparing a live lane pilot: [references/smoke-test.md](references/smoke-test.md).

Read when checking research report structure or requesting re-emission: [references/research-report-contract.md](references/research-report-contract.md).
