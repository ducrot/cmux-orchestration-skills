---
name: cmux-grilling
description: Coordinate a gated autonomous CMUX grilling session that stress-tests a plan or task through visible research worker panes. Use when an orchestrating agent should grill a plan without user answers - rounds of decision-level questions (the whole frontier per round, no per-round question cap), four persistent research lanes (Claude codebase, Codex second-opinion codebase, docs, web), gate-parsed research reports, synthesis with confidence and sources, defined assumptions and open decisions written as a Markdown+JSON pair under the tracker's grilling directory, assumptions review, a decision walkthrough with the human, run-state logging, and cmux worker-pane workflows. For interactive grilling where the user answers the questions, use the grilling skill instead.
---

# CMUX Grilling

Use this skill to grill a task autonomously: the orchestrator asks decision-level questions
about a plan, four persistent visible research lanes answer each question against the
current repository and the web, and the session ends with distilled defined assumptions the
human reviews. The orchestrator is a coordinator plus judgment role: it formulates questions
(griller), consolidates lane reports (synthesizer), and distills assumptions (finalize), but
all research runs in visible CMUX worker panes.

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
on schema v1 with the exact preview and acceptance commands; run initialization does the same
before publishing a launch wave.

Treat configuration creation as a first-use human checkpoint, separate from run initialization.
Before starting any worker-bearing run, resolve the selected configuration path and follow this
protocol. Never offer profile overrides the human did not ask for.

1. If the file already exists at schema v1, run `agents_config.py migrate` without `--accept`.
   Present its coordinated-upgrade warning and complete validated preview in the human's language,
   including every resolved workflow assignment. When `claude-fable-high` is unavailable, call out
   the displayed fallback profile name, harness, model, and effort without inferring relative quality.
   Ask whether to accept exactly that proposal. On refusal or interruption, make no further tool call.
   On confirmation, invoke the preview's exact `agents_config.py migrate --accept` command, digest
   argument included, then validate and continue.
2. If the file already exists and is valid schema v2, continue with its assignments.
   A schema-v2 file needs no migration question.
   An existing valid schema-v2 file needs no start confirmation either; the start question
   belongs only to a newly created default (accepted with the **Yes, start now** answer).
3. If it is missing, run `agents_config.py init` for that exact default or explicit path, then run
   `show-resolved`. Do not call `run_state.py init` yet.
4. Present the created path and all three workflows' resolved assignments, because the file is shared.
   Ask one single-select question in the human's language: whether to start the current run with
   these assignments. The choices mean **Yes, start now** and **No, I will edit the file**.
5. Use the host's native structured-input tool when it is available: `AskUserQuestion` in Claude
   Code or `request_user_input` in Codex. Do not assume Codex exposes it in the current mode; when
   no native tool is available, ask the same question in chat and end the turn for the answer.
6. On yes, reload and validate the current bytes before starting the run. On no, perform no more
   tool calls, tell the human to edit the file and reply when it is ready, and end the turn. When
   they return, validate and show the resolved assignments again; start only after validation
   succeeds. Report validation errors and remain stopped when it fails.

This checkpoint belongs to the interactive orchestrator, never to a worker pane or subagent. Do
not emulate it with shell input, a sleeping process, or polling while the human edits the file.

The sixteen shipped profiles are `claude-fable-high` and `claude-fable-medium` (`claude-code`,
`claude`, `fable`); `claude-opus-high`, `claude-opus-medium`, and `claude-opus-xhigh`
(`claude-code`, `claude`, `opus`); `claude-sonnet-medium` (`claude-code`, `claude`, `sonnet`);
`codex-astra-high`, `codex-astra-medium`, and `codex-astra-xhigh` (`codex`, `codex`,
`gpt-6-astra`); `codex-luna-medium` (`codex`, `codex`, `gpt-5.6-luna`);
`pi-gemini-pro-high` and `pi-gemini-pro-medium` (`pi`, `pi`, `google/gemini-3.1-pro-preview`);
`pi-glm-high` and `pi-glm-medium` (`pi`, `pi`, `openrouter/z-ai/glm-5.3`); and `pi-grok-high`
and `pi-grok-medium` (`pi`, `pi`, `xai/grok-4.7`). Each tuple lists
harness, executable, and model; the profile suffix specifies effort. No workflow assigns a Pi
profile by default; Pi is opted into per run or per tracker config. Grilling assigns Opus/high, Astra/high, Luna/medium, and Sonnet/medium to
`codebase`, `codebase2`, `docs`, and `web`, respectively. The `fable`, `opus`, and `sonnet`
strings are intentionally moving provider aliases; deterministic selection of an alias does not
pin the provider's underlying model version.

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
profiles, assignments, sources, models, and efforts. A Pi model must name its provider
(`provider/id`, such as `openrouter/z-ai/glm-5.3`), because Pi has no provider-wide auth status and
its preflight check is scoped to the model it is given. Hermes remains an explicit unsupported
entry in the code-owned adapter registry; that registry — rather than JSON — is the implementation
boundary for adding future harnesses. It lives in `scripts/agents_config.py` together with the
preflight rules, the launch and probe adapters, and the override parsing and profile resolution
all workflows share, so a harness is added in that one file; each workflow keeps its own
sandbox, approval, and network policy.

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
2. **Research lanes** — four persistent visible panes, launched once and kept open for the
   whole session:
   - `codebase` — repo-only research, no web (Claude Opus/high by default).
   - `codebase2` — independent second-opinion repo research, no web (Codex by default).
   - `docs` — official documentation for the versions the repo pins (Codex Luna/medium by default).
   - `web` — public-web research (Claude Sonnet/medium and Claude-only by policy).
3. **Synthesizer** — orchestrator step. Consolidates the four lane reports of a round into
   one answer with confidence, sources, and reasoning.
4. **Finalize** — orchestrator step. Distills the defined assumptions, writes the artifact
   pair, and presents the assumptions for human review.

This deliberately deviates from the sibling skill's "at most orchestrator plus one worker
pane" rule: a grilling session keeps the orchestrator pane plus all four lane panes open
until the session ends.

## Run Briefing

A fresh session opens with a compact briefing so the human sees what is being grilled without
opening a file. After `run_state.py init` and before the first `pane_ctl.py launch`:

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

Capture a baseline snapshot before initial lane delivery:
`run_state.py snapshot --label "launched session"`. After all lanes adopt their session
contracts, capture `run_state.py snapshot --label "adopted session"` and compare the session
baseline before arming the first round. Before each round delivery, capture
`run_state.py snapshot --label "launched round-<N>"`; compare that round baseline with its
`reports-captured round-<N>` snapshot before any advance gate. Never replace a baseline
before checking the interval it covers, including on re-delivery.

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
   `{"round": N, "id": "Q1", "question": "..."}` (`"depends_on": ["R1Q2"]`, round 1 Q2, when the
   question builds on an earlier answer). The questions of a round must be independent of each other; a
   question deferred from an earlier round (see Question failures) is asked again as a new
   question with its own id.
2. Render the four round prompts with `render_prompt.py round` (one per lane, every question
   passed as its own `--question`/`--question-file`), capture the
   delivery baseline under Delivery baselines and staged deltas, and send each
   lane its prompt with `pane_ctl.py deliver --lane <lane> --kind round --prompt <path>`
   (send + Enter + screen echo). Judge the echoed screen per lane before treating the round as
   started; a lane that answers with a summary of the prompt and goes idle has not started (see
   CMUX Control).
3. Arm the round watcher (`await_reports.py --questions <n>` under `Monitor`) per the Lane Wait
   Policy before ending the turn. Reports land at
   `.scratch/orchestrator/runs/<run-id>/reports/round-<N>-<lane>.md`.
4. When all four reports exist, record one tree snapshot:
   `run_state.py snapshot --label "reports-captured round-<N>"`. Compare the staged fields
   and HEAD against the round delivery baseline before parsing advance gates.
5. Parse each report with `parse_research_report.py --questions <n>` and record one gate per lane
   with `--stage round-<N>-<lane>`; the gate reason names each non-advancing question. Record
   `worker.finished` per lane with `{"lane": ..., "round": N, "surface_id": ...}`.
6. Every question whose four lane gates are `advance` is synthesized: write
   `synthesis/round-<N>.json` (format below) and record `grill.synthesis` per question. Questions
   that failed on form follow Question failures. Then either open the next round, or stop the
   loop when the budget is exhausted or the frontier is empty (`grill.done` with the reason;
   `stopReason` is `max-rounds` or `griller-done`).
7. A `blocked` or `hitl` gate that is not a pure form failure stops the session (see Gate Rule),
   with one exception: a `hitl` whose sole reason is plan drift goes through Drift Triage and may
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

## Gate Rule

`parse_research_report.py` gates every `## Q<n>` block of a lane report on its own and emits
one of five values per question; the report gate is the most severe question gate.
`run_state.py gate --decision` accepts the same five. Never invent a sixth.

| Gate      | Meaning                                        | Exit code | Orchestrator action                  |
|-----------|------------------------------------------------|-----------|--------------------------------------|
| `advance` | Well-formed report (`ANSWERED` or `NO ANSWER`) | 0         | Count the lane as delivered          |
| `stop`    | Ungrounded or contradictory question           | 3         | Do not synthesize it; Question failures |
| `blocked` | Lane reported a `BLOCKER`                      | 4         | Stop the session, record the blocker |
| `hitl`    | Plan drift, or a malformed question or report  | 5         | Form: Question failures; drift: Drift Triage; else stop |
| `pending` | Report not written yet                         | 6         | Keep waiting per the wait policy     |

The gate is the **most severe** triggered condition: `blocked` > `hitl` > `stop` >
`advance`. Research-specific semantics:

- `NO ANSWER` with an explanation under `### Answer` is a clean `advance`. The gate checks
  form; the synthesizer judges research quality.
- `ANSWERED` without at least one real source is `stop` — ungrounded answers must not reach
  the synthesizer.
- `### Plan Drift` is for a stale or wrong task premise (the plan contradicts what research
  found). The parser gates any drift as `hitl`; the orchestrator then triages it in two
  classes (see Drift Triage) — only load-bearing drift reaches the human mid-run.
- A required section (`### Result`, `### Answer`, `### Sources`, `### Method`, `### Blockers`,
  `### Plan Drift`) that is absent or empty makes its question malformed and yields `hitl`. An
  omitted section never reads as `None`. So does a missing, duplicate, or unexpected `## Q<n>`
  block; a report without any question block is `hitl` for the whole report.

A question synthesizes only when all four lanes gate `advance` for it. A failing lane never
silently degrades to an empty finding, and a question is never synthesized from fewer than four
lanes. A `blocked` question, a load-bearing drift, a dead pane, or an exhausted deadline stops the
whole session. A form failure (`stop` or malformed `hitl` without blocker or drift) is handled per
question, below. The one other exception is small-factual drift, triaged next.

### Question failures: re-emit once, then defer

A question whose gate is `stop` or `hitl` purely because of form (ungrounded `ANSWERED`, missing
method, missing or empty section, unfilled `|` menu, missing question block) does not stop the session:

1. Ask the still-open lane pane once to re-emit the whole report, fixing exactly the named
   questions ("re-emit the report per the Research Report Contract; fix the format of Q2 and Q3,
   not the substance"), and record `report.reformat_requested` naming the questions. Re-parse.
2. A question still failing on any lane is **deferred**: record `grill.question_deferred` with
   `{round, id, lanes, reason}`, leave it out of the synthesis, and ask it again in a later round as
   a new question, so all four lanes see it again. The other questions of the round synthesize
   normally.
3. A question that cannot be deferred because no round is left is `hitl` for the session; a human
   decides. Every deferral appears in the final artifact's `## Q&A` protocol.

Never overrule the parser with your own `advance`.

### Drift Triage

When a question's only gate reason is `plan drift present`, the orchestrator — the
judgment role that reads all four reports — triages the drift in two classes, mirroring the
issue chain's replanning rule:

- **Small factual** (stale doc wording, a renamed command or path, a premise detail that
  does not change what would be built): resolve it yourself. Record `plan.drift` with
  `{"class": "small-factual"}` and `plan.drift.resolved` with
  `{"resolved_by": "orchestrator"}`, then record the lane gate as `advance` with a reason
  naming that resolution. Fold the correction into later question texts where relevant.
- **Load-bearing** (scope, architecture, security, data-safety, acceptance-risk — anything
  that changes the assumptions being built): record `plan.drift` with
  `{"class": "load-bearing"}`, gate `hitl`, and stop the session for the human, as before.

When in doubt, the drift is load-bearing. Never rewrite `task.md` silently — corrections
live in events, later question texts, and the artifact. Every self-resolved drift must
appear in the final artifact and in the assumptions review, so the human is guaranteed to
see it, just after the run instead of blocking it.

This triage is the one documented case where the orchestrator's recorded gate may diverge
from the parser's exit code, and only when drift is the sole reason. A report whose drift
rides along with findings, blockers, or format failures is not eligible.

The orchestrator never records `advance` for a question or lane while the latest parsed gate says
otherwise; re-emission and deferral (Question failures) are the only ways past a form failure.

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
itself. Arm it through the harness `Monitor` tool:

```
Monitor(
  command: "python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --questions 3 --lane-surface codebase=<surface-id> --lane-surface codebase2=<surface-id> --lane-surface docs=<surface-id> --lane-surface web=<surface-id>",
  description: "await round-1 lane reports",
  persistent: true
)
```

`persistent: true` is the safe choice: `Monitor`'s `timeout_ms` caps at 60 minutes and is
ignored when persistent, so the script's own deadline ends the watch. `Bash` with
`run_in_background` caps at 600000 ms = 10 minutes and is therefore too short for the
round wait — do not substitute it.

Health is checked only for lanes whose report is still missing. A lane whose pane exits right
after writing its report has delivered, not died.

The watcher ends on exactly three conditions and nothing else:

| Exit | Condition                                               | Orchestrator action                                                                               |
|------|---------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| 0    | All awaited lane reports exist                          | Snapshot, parse each lane, gate — exit 0 is not an advance verdict                                |
| 7    | A pending lane's pane is dead per `cmux surface-health` | Stop as HITL for that lane; a dead pane with no report is orchestration uncertainty, not findings |
| 8    | Deadline exceeded, pending panes alive/unknown          | Extend once with a recorded reason (re-arm with `--deadline-minutes`), else stop as HITL          |

The stdout line carries the detail the exit code cannot:
`outcome=… round=1 elapsed_seconds=… delivered=codebase,docs missing=codebase2,web dead=codebase2`
(`none` where a list is empty). The files remain the ground truth — parse them, do not trust
the line alone.

While a watcher is armed it is the sole emitter of `worker.waiting`; the orchestrator does not
hand-write waiting events in parallel. Silence is never success — only the report files are
ground truth, never status words on screen (the Claude TUI shows ever-changing gerunds, Codex
shows `Working`). A static-looking pane is not a dead one: Codex lanes route approvals to
their reviewer agent rather than to the human, so a quiet pane is a lane still thinking or
one already finished, and the watcher correctly keeps waiting either way. Only
`surface-health` reporting the surface gone counts as dead.

- Exactly one deadline extension per round; record its reason as a `worker.waiting` or
  `decision.human` event before re-arming. Before spending it on a silent lane, check the
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

The order of the closing steps is fixed: finalize (below) → assumptions review → decision
walkthrough → update both artifacts → commit proposal → run recap. The sections after this one expand
the steps past finalize.

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
corrections from Drift Triage — to the human for review: confirm, correct, or discard per
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

### Resuming an unfinished walkthrough

Check at session start whether the previous walkthrough is unfinished:

```bash
python3 scripts/run_state.py pending-decisions
```

It prints the newest artifact's `open` and `deferred` ids separately. Any `open` id means the
walkthrough was cut short: offer to finish it before starting a new session. `deferred` ids
are reported for completeness — do not re-ask them. This is the only handling of "the human
walked away": at the next contact, not on a clock.

## Commit Proposal

Always propose a commit for the artifact pair as a `commit.proposed` event: the exact file
list (the two artifact files; anything else
is a ride-along and excluded) plus a draft commit message (English, what + why) whose subject line
goes into the event data as `subject`. Name
explicitly which decisions are being committed unresolved (`open` or `deferred`), so the
human sees what is still outstanding. The human reviews, commits, and pushes. Never run
`git push`.

## Run Recap

The counterpart to the Run Briefing and the last message of a session. After the commit proposal,
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

Before starting or messaging any worker, follow [Interactive worker readiness](references/worker-readiness.md).
After `start-agent`, inspect with `observe`, explicitly `assess` the current screen, resolve pending
startup dialogs, and only then `deliver`. Read each tool result before the next input; never batch
start and task delivery. The gate applies to Codex, Claude Code and Pi, all roles/lanes, and follow-ups.
`worker.ready` permits one delivery and is distinct from `worker.started`. On recovery, observe again.

## CMUX Control

Prefer current CLI syntax discovered from `cmux --help` before launching lanes. Lanes must
be visible in CMUX panes. Never type a launch command into a lane pane by hand:
`pane_ctl.py start-agent` owns it and reads only the lane's matching entry from the immutable
prepared launch wave. Both `launch` and `start-agent` validate the entire wave first, so a
missing, failed, mismatched, or tampered lane blocks every pane. The default wave sends:

```bash
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model opus --effort high \
  --permission-mode auto                                   # codebase
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  --model gpt-6-astra \
  -c model_reasoning_effort=high                          # codebase2
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  -c sandbox_workspace_write.network_access=true \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  --model gpt-5.6-luna \
  -c model_reasoning_effort=medium                         # docs
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model sonnet --effort medium \
  --permission-mode auto                                   # web
```

`CMUX_AGENT_MANAGED_SUBAGENT=1` marks the pane as a managed subagent, which is what cmux
keys its notification suppression on. Without it a session fires a desktop banner with sound
for every turn end, idle reminder and approval prompt across four lanes, and the human ends
up muting cmux entirely. The lane still appears in the Feed and in `surface-health`; only the
banners are gone. Suppression follows `automation.suppressSubagentNotifications` (on by
default), and the variable is a cmux internal, so the failure mode is noise, never a
broken run.

Use plain `claude` / `codex`, not `cmux claude-teams` / `cmux codex-teams`. The teams
wrappers open lane-spawned subagents as extra cmux panes, and those splits anchor to the
focused workspace instead of the lane's workspace — while the human works in another
workspace, subagent panes land there. Plain launches keep subagents internal to the lane's
Claude Code process. Every interactive Claude lane starts in `auto` permission mode; the safe,
tool-disabled live provider probe remains in `plan` mode.
own TUI; the lane pane stays the visible unit, and cmux pane integration (hooks,
notifications, `surface-health`) comes from the per-pane CLI shims, so it is unaffected.

The configured harness, executable, model, and effort come from the wave. Codebase,
codebase2, and docs accept Claude Code or Codex; web remains Claude Code-only because that
is the existing tested network policy. The Codex flags are fixed lane policy; do not ask the
human for startup options at session start. Each flag earns its place:

- `-s workspace-write` lets a Codex lane write its draft and report handoff files without a per-write
  confirmation (in the first pilot, a lane stuck at that prompt cost most of a round).
- `--ask-for-approval on-request` pins the escalation policy explicitly: the lane runs
  sandboxed and requests approval only when the sandbox blocks something.
- `approvals_reviewer=auto_review` routes those approval requests to Codex's automated
  reviewer agent instead of a human prompt, so an unattended lane does not stall at the
  sandbox boundary. It is a reviewer swap, not a permission grant.
- `check_for_update_on_startup=false` suppresses the startup update prompt, which otherwise
  blocks an unattended lane before it reads its task. Set it only here, so interactive Codex
  sessions still get update notices.

Which lanes may reach the network is declared by `launch_wave.CODEX_NETWORK_LANES`. Only a
Codex docs lane receives `sandbox_workspace_write.network_access=true`, preserving its
documentation access; the web lane is Claude Code-only and has no sandbox to grant. Codebase and
codebase2 remain no-web lanes, and no grilling lane
receives `writable_roots`; those container grants belong to `cmux-issue-chain` workers. The
launch command is stored as an argument vector in the wave and converted to shell text with
safe quoting by `pane_ctl.py start-agent`; its `worker.launch_sent` event records the wave id,
argument vector, resolved executable, and detected version. With
`approvals_reviewer=auto_review` a Codex lane decides its
own escalations, so it does not stop at a human approval prompt; a lane that looks idle is
either working or done, and only its report file settles which.

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

```bash
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --lane codebase --anchor <surface-id>
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --surface <surface-id> --lane codebase
# Read each result; ready is a judgment, not an unconditional startup command.
python3 scripts/pane_ctl.py observe --run-dir <run-dir> --surface <surface-id> --lane codebase
python3 scripts/pane_ctl.py assess --run-dir <run-dir> --surface <surface-id> --lane codebase --observation <observation-id> --state ready --reason "<screen evidence>"
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --surface <surface-id> --lane codebase --kind round --prompt <prompt-path>
python3 scripts/pane_ctl.py close --run-dir <run-dir> --surface <surface-id> --lane codebase
python3 scripts/pane_ctl.py cmux --run-dir <run-dir> -- read-screen --surface <surface-id> --lines 40
```

`launch` first validates the prepared launch wave, then splits from the anchor without stealing focus, labels the pane, records
`pane.launched` + `pane.labeled`, and prints the new surface's stable UUID — use that UUID in
every later command; positional refs like `surface:465` shift when panes close. `start-agent`
revalidates that same wave and sends only the requested lane's prepared launch command
(configuration is never re-read), records `worker.launch_sent`, and echoes the screen.
`deliver` requires a fresh, screen-bound readiness assessment, consumes it, then
sends the text, submits it with an explicit Enter key event (a trailing `\n` does not submit
in either TUI; the text waits unsent in the composer), records `worker.prompt_sent`, and
echoes the pane screen. Hand over a rendered prompt with `--prompt <path>` plus `--kind
session|round`, never with hand-written `--text`: the wording comes from
`orchestrator_lib.delivery_text()` and is skill policy like the launch command. `--kind`
matters because the two prompts want opposite behavior — a session contract is adopt-and-wait,
a round prompt is answer-now. `--text` is for follow-ups into a working lane (re-emission
requests, clarifications). `close` closes the surface and records `pane.closed`. Everything else
(diagnosis, `read-screen`, `set-status`, …) runs through the generic `cmux` injector, which
inserts `--workspace <pinned>` into any cmux command. Avoid focus-changing commands.

After a *round* delivery, a lane that answers with a recap of the prompt ("the prompt is ready
to execute; I only read it") and then goes idle has not started — no `worker.started`. That is
a Claude failure mode: the delivery line was read as a documentation request. Re-deliver the
same prompt with `deliver --kind round --prompt`
(which carries the task framing), judge the screen again, and arm the round watcher from the
re-delivery. A lane that never started does not consume the round's one deadline extension.
The same screen after a *session* delivery is the expected outcome, not a failure.

Session start:

1. Check the previous session first (`run_state.py pending-decisions`, see Resuming an
   unfinished walkthrough); then `run_state.py init` with the task, show the Run Briefing,
   and render the four session prompts with `render_prompt.py session`.
2. Launch the four lanes one after another with `pane_ctl.py launch`, each split anchored to
   the previously launched lane (`--anchor <previous-lane-surface-id>`); the first lane
   may split from the orchestrator pane. A 2×2 arrangement next to the orchestrator pane
   works well (`--direction right|down`).
3. Labels are applied by `launch`: `Researcher Codebase`, `Researcher Codebase2`,
   `Researcher Docs`, `Researcher Web`, each suffixed `- grill-<slug>`. Optional status
   pills via `set-status` through the injector (not pane colors): Codebase `#0a84ff`,
   Codebase2 `#5e5ce6`, Docs `#af52de`, Web `#34c759`, HITL/blocker `#ff3b30`.
4. Start each lane's agent with `pane_ctl.py start-agent --lane <lane>`; judge the echoed
   screen, then complete the observe/assess/dialog protocol before sending it any text.
5. Before sending any session prompt, capture
   `run_state.py snapshot --label "launched session"` under Delivery baselines and staged deltas.
   Send each lane its session prompt with `pane_ctl.py deliver --lane <lane> --kind session
   --prompt .scratch/orchestrator/runs/<run-id>/prompts/session-<lane>.md`. Judge the echoed
   screen, then record `worker.started`. A lane that confirms in one line and goes idle here is
   correct — the session prompt is a contract, not work.
   After all lanes adopt their session contracts, capture
   `run_state.py snapshot --label "adopted session"` and compare it with the session baseline
   before arming the first round, following Delivery baselines and staged deltas.

Lane panes stay open across rounds; they are closed only at session end, HITL stop, blocker
stop, or run abort — after their reports and gate decisions are documented (`pane_ctl.py
close` per lane, which records `pane.closed`). If a lane's tooling leaves orphan panes
behind, record `pane.orphans_detected` with the IDs, then close them.

While a round is in flight, the four reports belong to the lanes: do not edit anything under
`reports/` yourself, and compare snapshot fingerprints before any `report.integrity` claim.

## Event Vocabulary

Use these exact event types. New ad-hoc types must be dot-namespaced, lower-case, and used
consistently within a run.

| Event                                                  | When                                                                                                                               |
|--------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `run.init`, `run.completed`                            | Written by `run_state.py init` / `complete`                                                                                        |
| `run.briefing`                                         | Briefing shown to the human, pill text in data; written by `run_briefing.py show`                                                 |
| `run.recap`                                            | Recap shown to the human, outcome and pill in data; written by `run_briefing.py recap-show`                                       |
| `launch_wave.prepared`                                 | All four lanes resolved, preflighted, audited, and frozen before pane creation                                                     |
| `pane.launched`, `pane.labeled`, `pane.closed`         | Lane pane lifecycle; written by `pane_ctl.py launch` / `close`                                                                     |
| `pane.orphans_detected`                                | Lane tooling left panes behind; record IDs, then close them                                                                        |
| `worker.launch_sent`                                   | Lane agent launch command sent verbatim; written by `pane_ctl.py start-agent`                                                       |
| `worker.prompt_sent`                                   | Text sent and submitted; written by `pane_ctl.py deliver`                                                                          |
| `worker.started`                                       | Session prompt delivered and confirmed via read-screen — the orchestrator's judgment, after `worker.prompt_sent`                   |
| `worker.waiting`                                       | Written by the armed round watcher only: heartbeats plus its final outcome                                                         |
| `worker.finished`                                      | Round report captured; data carries `{lane, round, surface_id}`                                                                    |
| `worker.launch_blocked`                                | A lane launch was denied (permissions, environment)                                                                                |
| `gate`                                                 | Only via `run_state.py gate`                                                                                                       |
| `tree.snapshot`                                        | Only via `run_state.py snapshot`                                                                                                   |
| `report.reformat_requested`                            | Re-emission asked for a format-only parse failure                                                                                  |
| `report.integrity`, `report.integrity.retracted`       | Report-claim accusation and its retraction                                                                                         |
| `plan.drift`, `plan.drift.resolved`                    | Task-premise drift recorded / resolved; data carries `class` (small-factual, load-bearing) and `resolved_by` (orchestrator, human) |
| `hitl.resolved`, `decision.human`                      | Human decisions and HITL resolutions                                                                                               |
| `grill.question`                                       | Round question recorded before delivery, one per question; data `{round, id, question, depends_on?}`                               |
| `grill.question_deferred`                              | Question dropped from a round's synthesis after a failed re-emission; data `{round, id, lanes, reason}`                             |
| `grill.synthesis`                                      | One question synthesized; data `{round, id, confidence}`                                                                           |
| `grill.done`                                           | Griller ends the loop (empty frontier or round budget spent); data `{round, reason}`                                                |
| `grill.assumptions`                                    | Defined assumptions distilled; data `{count}`                                                                                      |
| `grill.assumptions_triaged`                            | Per-assumption human review outcome                                                                                                |
| `grill.open_decisions`                                 | Open decisions distilled at finalize; data `{count}`                                                                               |
| `grill.decision_recorded`                              | One walkthrough answer; written by `run_state.py decision`                                                                         |
| `commit.proposed`                                      | Artifact commit proposal handed to the human after `complete`                                                                      |
| `orchestrator.halted`, `orchestrator.unverified_input` | Orchestrator-side anomalies                                                                                                        |

## Scripts

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

Validate the artifact's decisions at finalize, record one outcome during the walkthrough, and
check for an unfinished walkthrough at session start (see Resuming an unfinished walkthrough):

```bash
python3 scripts/run_state.py validate-artifact --artifact <artifact.json>
python3 scripts/run_state.py decision --run-dir <run-dir> --artifact <artifact.json> --id D1 --status decided --decision "Ab 12 Jahren"
python3 scripts/run_state.py pending-decisions
```

Render prompts. Session prompts once per lane at launch, round prompts once per round with one
`--question` (or `--question-file`) per frontier question, numbered `Q1..Qn` in order:

```bash
python3 scripts/render_prompt.py session --run-dir .scratch/orchestrator/runs/<run-id> --lane codebase
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/<run-id> --lane web --round 1 --question "Which HTTP client does the frontend use?" --question "Which API base URL does it use?"
```

Await a round's reports. One watcher per round, armed through `Monitor` (see Lane Wait
Policy); exits 0 = all reports, 7 = pending lane's pane dead, 8 = deadline. Health checks are
scoped to the run's pinned `workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --questions 2 --lane-surface codebase=surface:465 --lane-surface codebase2=surface:466 --lane-surface docs=surface:467 --lane-surface web=surface:468
```

Parse lane reports. `--questions <n>` demands blocks `Q1..Qn`. The exit code carries the most severe
question gate, `--json` the gate of every question; a missing report is `pending` (exit 6):

```bash
python3 scripts/parse_research_report.py .scratch/orchestrator/runs/<run-id>/reports/round-1-web.md --questions 2 --json
```

Record events, snapshots, gates; close the run. An unreadable or vanished untracked path fails the snapshot
with a diagnostic naming it and records no event; restore access or remove the path and retry. Git only
warns about an unreadable untracked directory, so its contents stay invisible rather than failing capture.
Then:

```bash
python3 scripts/run_state.py event --run-dir <run-dir> --type grill.question --message "round 1 Q1" --data '{"round":1,"id":"Q1","question":"..."}'
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "reports-captured round-1"
python3 scripts/run_state.py gate --run-dir <run-dir> --stage round-1-web --decision advance --reason "well-formed ANSWERED, sources cited"
python3 scripts/run_state.py complete --run-dir <run-dir> --markdown <output-dir>/<slug>.md --json <output-dir>/<slug>.json --message "grilling complete" --data '{"stop_reason":"griller-done"}'
```

Control lane panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints
the pinned id, `cmux` is the generic `--workspace` injector, `launch`/`deliver`/`close` are
the lifecycle verbs.

Run the regression tests after touching `parse_research_report.py`, `await_reports.py`,
`pane_ctl.py`, `run_state.py`, `launch_wave.py`, or `agents_config.py`:

```bash
python3 scripts/test_parse_research_report.py
python3 scripts/test_await_reports.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_run_state.py
python3 scripts/test_agents_config.py
python3 scripts/test_launch_wave.py
```

## Smoke Test

Before a live lane pilot, run the scripts end-to-end. Every command must exit 0, and the
whole block must be safe to run twice in a row (`init` is idempotent):

```bash
python3 scripts/test_parse_research_report.py
python3 scripts/test_await_reports.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_run_state.py
python3 scripts/test_agents_config.py
python3 scripts/test_launch_wave.py
python3 scripts/run_state.py init --task "Smoke: validate the grilling scripts" --run-id smoke-grill --max-rounds 2 --output-dir .scratch/grilling
python3 scripts/run_state.py pending-decisions --output-dir .scratch/grilling
python3 scripts/render_prompt.py session --run-dir .scratch/orchestrator/runs/smoke-grill --lane codebase
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/smoke-grill --lane web --round 1 --question "Which HTTP client does the frontend use?"
python3 scripts/parse_research_report.py references/sample-research-report.md --questions 1 --json
python3 scripts/run_state.py snapshot --run-dir .scratch/orchestrator/runs/smoke-grill --label "smoke snapshot"
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/smoke-grill --stage round-1-web --decision advance --reason "smoke test"
python3 scripts/run_state.py complete --run-dir .scratch/orchestrator/runs/smoke-grill --markdown .scratch/grilling/smoke.md --json .scratch/grilling/smoke.json --message "smoke complete" --data '{"stop_reason":"smoke"}'

# The watcher without reports must hit its deadline (exit 8), file-only, in ~1 second:
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/smoke-grill --round 1 --questions 1 --deadline-minutes 0.01 --poll-seconds 0.2; [ $? -eq 8 ]
```

`references/sample-research-report.md` is the shipped clean-report fixture. Run the block
from the orchestrator's cmux pane so `init` can pin the workspace; outside cmux, pass
`--workspace-id <uuid>` or `--no-workspace` explicitly.

## Research Report Contract

Ask every lane to finish each round with one `## Q<n>` block per round question, numbered as in
the round prompt (`Q1..Qn`, also for a round of a single question). Inside a block the sections are
`###` headings. `### Result`, `### Answer`, `### Sources`, `### Method`, `### Blockers`, and
`### Plan Drift` are required: absent or empty, they make the question malformed and its gate
`hitl`. Under `### Result`, emit exactly one of `ANSWERED`, `NO ANSWER`, `BLOCKER` — a literal
`ANSWERED | NO ANSWER | BLOCKER` line is an unfilled template and is rejected. A missing, duplicate,
or unexpected question block is malformed too. Each question is gated independently; the parser
takes the expected count as the required `--questions <n>`, so a report that leaves out a
question never passes as clean.

```markdown
## Q1
### Result
ANSWERED

### Answer
The finding in prose. For NO ANSWER: why this lane cannot answer the question.

### Sources
- relative/repo/path or URL

### Method
- what was searched, read, or run: outcome

### Blockers
- None

### Plan Drift
- None

### Notes
- Optional: caveats, confidence hints, context. Never load-bearing evidence.

## Q2
### Result
...
```

The bare-`None` rule: in `### Sources`, `### Blockers`, and `### Plan Drift`, an empty section
is exactly the line `- None` — no prose on or after that line. Explanations belong in
`### Answer` or `### Notes`, which the gate does not parse for content. Question blocks end at the
next `##` heading, so a trailing `## Notes` never joins a section.

Research-specific gate requirements:

- `ANSWERED` needs at least one real source; without one the gate is `stop`.
- `NO ANSWER` needs an explanation under `### Answer`; `### Sources` may be `- None`.
- `### Method` must be substantive in every report, including `NO ANSWER` — what was searched
  and found nothing is evidence too.

Lanes may write exactly two files per round: the draft path and the report handoff path
named in the round prompt. `init` creates `drafts/` alongside `prompts/`, `reports/`, and
`synthesis/`. Rendered prompts name `<run-dir>/drafts/round-<N>-<lane>.md` and instruct lanes
to self-validate that exact file with `parse_research_report.py` before writing the handoff
file. `render_prompt.py round --draft-path <path>` overrides the draft location; it must
resolve strictly inside the run-local `drafts/` directory (never run state, prompts,
synthesis, or any lane's report) and differ from the report handoff path.

Run layout: `state.json` records `workflow: grilling`, `layout_version: 1`, `max_rounds`, and `slug` (at most 30
characters; override with `init --slug <value>` using lowercase words separated by hyphens).
`complete` requires `--markdown` and `--json` paths resolving under the recorded `output_dir` and
records them in `deliverables`. Artifact JSON and `pending-decisions` discovery remain unchanged.
Before continuing an existing run, inspect it with `run_state.py status --run-dir <run-dir>`.
An unsupported legacy layout — including a run whose state has `max_questions` instead of
`max_rounds` — must be restarted; never infer its identity or continue it.
