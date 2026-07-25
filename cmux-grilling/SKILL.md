---
name: cmux-grilling
description: Coordinate a gated autonomous CMUX grilling session that stress-tests a plan or task through visible research worker panes. Use when an orchestrating agent should grill a Vorhaben without user answers - one decision-level question per round, four persistent research lanes (Claude codebase, Codex second-opinion codebase, docs, web), gate-parsed research reports, synthesis with confidence and sources, defined assumptions written to grill-sessions Markdown+JSON, assumptions review, run-state logging, and cmux worker-pane workflows. For interactive grilling where the user answers the questions, use the grilling skill instead.
---

# CMUX Grilling

Use this skill to grill a task autonomously: the orchestrator asks decision-level questions
about a Vorhaben, four persistent visible research lanes answer each question against the
current repository and the web, and the session ends with distilled defined assumptions the
human reviews. The orchestrator is a coordinator plus judgment role: it formulates questions
(griller), consolidates lane reports (synthesizer), and distills assumptions (finalize), but
all research runs in visible CMUX worker panes.

All `scripts/…` and `references/…` paths in this skill are relative to the skill's own
base directory (the directory containing this SKILL.md); resolve them against that
directory, not the working directory.

## Relationship to the `grilling` Skill

Two skills share the grilling concept; keep them apart. `grilling` is a separate,
optional interactive skill that is not bundled with this one — without it installed the
distinction still applies, there is just no interactive counterpart to invoke.

- `grilling` (interactive): the agent grills the **user**; the user answers each decision.
- `cmux-grilling` (this skill): research lanes answer; the **user is not asked during the
  run** and reviews the defined assumptions at the end.

The task input is a Vorhaben (what should be built) plus its already-fixed constraints.
The constraints belong in the task so the griller does not waste questions on decided
matters and attacks the open decisions behind them instead.

## Boundaries

- The orchestrator never edits product code and never performs the research itself. It may
  write lifecycle state only: `.scratch/orchestrator/runs/<run-id>/`, run logs, prompts,
  gate decisions, snapshots, synthesis files, and the final artifact pair in the output
  directory (`grill-sessions/` by default).
- Research lanes are strictly read-only towards the repository: no file edits, no
  state-changing commands. The single file a lane may write is its own report handoff path
  under the run directory — report capture is explicitly delegated to the lanes because four
  reports arrive in parallel each round.
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

1. **Griller** — orchestrator step. One question per round, on decision level: a question
   whose answer changes what would be built. Never ask what the task's fixed constraints
   already decide. Respect the remaining question budget (`max_questions`, default 10).
2. **Research lanes** — four persistent visible panes, launched once and kept open for the
   whole session:
   - `codebase` — plain `claude`, repo-only research, no web.
   - `codebase2` — plain `codex`, independent second-opinion repo research, no web.
   - `docs` — plain `claude`, official documentation for the versions the repo pins.
   - `web` — plain `claude`, public-web research (standards, practices, known issues).
3. **Synthesizer** — orchestrator step. Consolidates the four lane reports of a round into
   one answer with confidence, sources, and reasoning.
4. **Finalize** — orchestrator step. Distills the defined assumptions, writes the artifact
   pair, and presents the assumptions for human review.

This deliberately deviates from the sibling skill's "at most orchestrator plus one worker
pane" rule: a grilling session keeps the orchestrator pane plus all four lane panes open
until the session ends.

## Round Loop

For each round `N` (1-based), in order:

1. Formulate the question and record it: `run_state.py event --type grill.question`
   with `{"round": N, "question": "..."}`.
2. Render the four round prompts with `render_prompt.py round` (one per lane) and send each
   lane its prompt file path via `pane_ctl.py deliver` (send + Enter + screen echo). Judge the
   echoed screen per lane before treating the round as started.
3. Arm the round watcher (`await_reports.py` under `Monitor`) per the Lane Wait Policy before
   ending the turn. Reports land at
   `.scratch/orchestrator/runs/<run-id>/reports/round-<N>-<lane>.md`.
4. When all four reports exist, record one tree snapshot:
   `run_state.py snapshot --label "reports-captured round-<N>"`.
5. Parse each report with `parse_research_report.py` and record one gate per lane with
   `--stage round-<N>-<lane>`. Record `worker.finished` per lane with
   `{"lane": ..., "round": N, "surface_id": ...}`.
6. All four gates `advance` → synthesize: write `synthesis/round-<N>.json` (format below),
   record `grill.synthesis`, then either ask the next question, or stop the loop when the
   budget is exhausted or no open decision-level question remains (`grill.done` with the
   reason; `stopReason` is `max-questions` or `griller-done`).
7. Any other gate → the session stops on that lane (see Gate Rule), with one exception: a
   `hitl` whose sole reason is plan drift goes through Drift Triage and may continue as
   small-factual. There is no empty-finding degradation and no automatic lane relaunch: a
   failed lane is a session-level `hitl`/`blocked`, resumable only through a human decision
   (`hitl.resolved`, `decision.human`).

The last lane gate of a clean round carries `--next-stage round-<N+1>` (or `finalize` after
the final round) so `state.json` tracks the position; the coarse `chain` stays
`["research", "finalize"]`.

### Synthesis

Synthesis is judgment, not vote counting:

- Weigh lanes by authority: project-internal questions → the codebase lanes are
  authoritative; library/API questions → docs; external practice questions → web.
- A `NO ANSWER` lane neither conflicts nor adds evidence.
- Disagreement between `codebase` and `codebase2` lowers confidence, must be named in the
  reasoning, and is a legitimate trigger for a follow-up question next round.
- An answer's sources are the union of the supporting lanes' sources, not everything any
  lane mentioned.

`synthesis/round-<N>.json`:

```json
{
  "round": 1,
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
```

## Gate Rule

`parse_research_report.py` decides the gate per lane report and emits one of five values.
`run_state.py gate --decision` accepts the same five. Never invent a sixth.

| Gate      | Meaning                                        | Exit code | Orchestrator action                  |
|-----------|------------------------------------------------|-----------|--------------------------------------|
| `advance` | Well-formed report (`ANSWERED` or `NO ANSWER`) | 0         | Count the lane as delivered          |
| `stop`    | Ungrounded or contradictory report             | 3         | Do not synthesize; triage            |
| `blocked` | Lane reported a `BLOCKER`                      | 4         | Stop the session, record the blocker |
| `hitl`    | Plan drift, or a malformed report              | 5         | Stop; a human decides                |
| `pending` | Report not written yet                         | 6         | Keep waiting per the wait policy     |

The gate is the **most severe** triggered condition: `blocked` > `hitl` > `stop` >
`advance`. Research-specific semantics:

- `NO ANSWER` with an explanation under `## Answer` is a clean `advance`. The gate checks
  form; the synthesizer judges research quality.
- `ANSWERED` without at least one real source is `stop` — ungrounded answers must not reach
  the synthesizer.
- `## Plan Drift` is for a stale or wrong task premise (the plan contradicts what research
  found). The parser gates any drift as `hitl`; the orchestrator then triages it in two
  classes (see Drift Triage) — only load-bearing drift reaches the human mid-run.
- A required section (`## Result`, `## Answer`, `## Sources`, `## Method`, `## Blockers`,
  `## Plan Drift`) that is absent or empty makes the report malformed and yields `hitl`. An
  omitted section never reads as `None`.

A round synthesizes only when all four lanes gate `advance`. Any `stop`, `blocked`, or
`hitl` stops the whole session — strict like the issue chain: a failing lane never silently
degrades to an empty finding. The one exception is small-factual drift, triaged below.

### Drift Triage

When a lane report's only gate reason is `plan drift present`, the orchestrator — the
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

### Formatting failures: request re-emission, never override

When a gate is `stop` or `hitl` purely because of report format — prose after `- None`, a
missing required section, the unfilled `|` menu — and the substance looks clean, do not
overrule the parser with your own `advance`. Ask the still-open lane pane for exactly one
contract-conforming re-emission ("re-emit the report per the Research Report Contract; fix
the format, not the substance"), record a `report.reformat_requested` event, re-parse, and
gate on the new report. If the re-emitted report still fails, stop as HITL for the human.
The orchestrator never records `advance` while the latest parsed gate says otherwise.

## Lane Wait Policy

Treat a missing lane report as `pending`, not as a failed gate. `parse_research_report.py`
enforces this: a missing report prints `gate=pending` and exits 6 rather than raising.

Minimum wait per lane and round: **15 minutes**, uniform across lanes.

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
  command: "python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --lane-surface codebase=<surface-id> --lane-surface codebase2=<surface-id> --lane-surface docs=<surface-id> --lane-surface web=<surface-id>",
  description: "await round-1 lane reports",
  persistent: true
)
```

`persistent: true` is the safe choice: `Monitor`'s `timeout_ms` caps at 60 minutes and is
ignored when persistent, so the script's own deadline ends the watch. `Bash` with
`run_in_background` caps at 600000 ms = 10 minutes and is therefore too short for the
15-minute wait — do not substitute it.

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
shows `Working`). A static-looking pane may be a Codex lane at an approval prompt the
auto-reviewer handed back to the human (circuit breaker); that pane is alive, and the watcher
correctly keeps waiting. Only `surface-health`
reporting the surface gone counts as dead.

- Exactly one deadline extension per round; record its reason as a `worker.waiting` or
  `decision.human` event before re-arming.
- After an exhausted extension with no report, or a dead pane: record a `hitl` gate for
  `round-<N>-<lane>` and stop the session. Use `blocked` only for blockers a lane itself
  reported.
- Never close a lane pane while its report is pending, and never send the next round while
  any report of the current round is outstanding.

## Finalize and Artifact

When the loop ends cleanly (`max-questions` or `griller-done`):

1. Distill the **defined assumptions** from all round syntheses: concrete, decision-ready
   statements a plan can build on — each traceable to Q&A rounds, none invented beyond the
   research. Record `grill.assumptions` with the count.
2. Write the artifact pair to the output directory (default `grill-sessions/`, configured at
   init):
   - `grill-sessions/<slug>-<timestamp>.md` — human-readable protocol in the established
     grill-session format: header (generation time, question count, stop reason), `## Aufgabe`,
     `## Q&A` (per round: question, Antwort, Confidence, Quellen, Reasoning, plus the four
     lane findings in a collapsible block), `## Definierte Annahmen`, and — when any drift
     was self-resolved — `## Prämissen-Korrekturen` listing each small-factual drift and its
     resolution. Keep this heading vocabulary stable so grill-session artifacts stay
     comparable across sessions.
   - `grill-sessions/<slug>-<timestamp>.json` — machine-readable result assembled from the
     `synthesis/round-*.json` files:

   ```json
   {
     "run_id": "...",
     "task": "...",
     "codebasePath": ".",
     "maxQuestions": 10,
     "questionsAsked": 7,
     "stopReason": "griller-done",
     "qa": ["... the synthesis objects, in round order ..."],
     "assumptions": ["..."],
     "markdownPath": "grill-sessions/<slug>-<timestamp>.md",
     "jsonPath": "grill-sessions/<slug>-<timestamp>.json"
   }
   ```

   The JSON schema is deliberately stable: the same top-level fields and one findings entry
   per lane in every session, so downstream consumers can build on it.
3. Record the finalize gate (`--stage finalize --decision advance`) and close the run:
   `run_state.py complete --data '{"stop_reason": ..., "markdown": ..., "json": ...}'`.
4. Close the four lane panes after their last reports and the gates are documented; record
   `pane.closed` per lane.

## Assumptions Review

After `complete`, present the defined assumptions — together with any self-resolved premise
corrections from Drift Triage — to the human for review: confirm, correct, or discard per
assumption. Record the outcome per item as a
`grill.assumptions_triaged` event, including a one-line reason for corrected or discarded
items. The review never blocks: present it and stop; the decision may stay open until the
human responds. Do not draft tracker issues from assumptions — handing results to
`cmux-issue-chain` is a human planning step, not part of this skill.

Then propose a commit for the artifact pair as a `commit.proposed` event: the exact file
list (the two artifact files; anything else is a ride-along and excluded) plus a draft
commit message (English, what + why). The human reviews, commits, and pushes. Never run
`git push`.

## CMUX Control

Prefer current CLI syntax discovered from `cmux --help` before launching lanes. Lanes must
be visible in CMUX panes. Launch commands:

```bash
claude                        # codebase, docs, web
codex -s workspace-write \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false   # codebase2
```

Use plain `claude` / `codex`, not `cmux claude-teams` / `cmux codex-teams`. The teams
wrappers open lane-spawned subagents as extra cmux panes, and those splits anchor to the
focused workspace instead of the lane's workspace — while the human works in another
workspace, subagent panes land there. Plain launches keep subagents internal to the lane's
own TUI; the lane pane stays the visible unit, and cmux pane integration (hooks,
notifications, `surface-health`) comes from the per-pane CLI shims, so it is unaffected.

Launch the Codex lane with these flags every time; do not ask the human for startup options at
session start. Each flag earns its place:

- `-s workspace-write` lets the lane write its report handoff file without a per-write
  confirmation (in the first pilot, a lane stuck at that prompt cost most of a round).
- `--ask-for-approval on-request` pins the escalation policy explicitly: the lane runs
  sandboxed and requests approval only when the sandbox blocks something.
- `approvals_reviewer=auto_review` routes those approval requests to Codex's automated
  reviewer agent instead of a human prompt, so an unattended lane does not stall at the
  sandbox boundary. It is a reviewer swap, not a permission grant.
- `check_for_update_on_startup=false` suppresses the startup update prompt, which otherwise
  blocks an unattended lane before it reads its task. Set it only here, so interactive Codex
  sessions still get update notices.

Do not add `network_access` or `writable_roots` here — the codebase2 lane is read-only
research with no web and no containers; those grants belong to `cmux-issue-chain` workers.
The launch command reaches the pane via `pane_ctl.py deliver`, whose `worker.prompt_sent`
event records it verbatim. A lane can still stop at a human
prompt when the auto-reviewer's circuit breaker trips after repeated denials — a lane sitting
at that prompt looks idle but is not, so during waits check the pane screen for a pending
prompt before judging a Codex lane stalled.

### Pinned workspace, deterministic pane control

`run_state.py init` pins the run's cmux workspace: flag > `CMUX_WORKSPACE_ID` env > hard error
(the env var of the orchestrator pane is the only place that variable is ever read;
`--no-workspace` is the explicit opt-out for offline runs outside cmux). Every cmux call after
init goes through `pane_ctl.py`, which reads the pinned `workspace_id` from `state.json` —
never through raw `cmux` with an env-var workspace, and never with a fallback to the focused
workspace. An empty or missing pinned ID is a stop, not a fallback: the human may be looking
at a different workspace than the one the run owns, and cmux resolves unscoped commands
against the focused one.

```bash
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --lane codebase --anchor <surface-id>
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --surface <surface-id> --text "Read <prompt-path> ..."
python3 scripts/pane_ctl.py close --run-dir <run-dir> --surface <surface-id> --lane codebase
python3 scripts/pane_ctl.py cmux --run-dir <run-dir> -- read-screen --surface <surface-id> --lines 40
```

`launch` splits from the anchor without stealing focus, labels the pane, records
`pane.launched` + `pane.labeled`, and prints the new surface's stable UUID — use that UUID in
every later command; positional refs like `surface:465` shift when panes close. `deliver`
sends the text, submits it with an explicit Enter key event (a trailing `\n` does not submit
in either TUI; the text waits unsent in the composer), records `worker.prompt_sent`, and
echoes the pane screen. `close` closes the surface and records `pane.closed`. Everything else
(diagnosis, `read-screen`, `set-status`, …) runs through the generic `cmux` injector, which
inserts `--workspace <pinned>` into any cmux command. Avoid focus-changing commands.

Session start:

1. `run_state.py init` with the task; render the four session prompts with
   `render_prompt.py session`.
2. Launch the four lanes one after another with `pane_ctl.py launch`, each split anchored to
   the previously launched lane (`--anchor <previous-lane-surface-id>`); the first lane
   may split from the orchestrator pane. A 2×2 arrangement next to the orchestrator pane
   works well (`--direction right|down`).
3. Labels are applied by `launch`: `Researcher Codebase`, `Researcher Codebase2 (Codex)`,
   `Researcher Docs`, `Researcher Web`, each suffixed `- grill-<slug>`. Optional status
   pills via `set-status` through the injector (not pane colors): Codebase `#0a84ff`,
   Codebase2 `#5e5ce6`, Docs `#af52de`, Web `#34c759`, HITL/blocker `#ff3b30`.
4. Send each lane its session prompt path with `pane_ctl.py deliver` ("Read
   `.scratch/orchestrator/runs/<run-id>/prompts/session-codebase.md` - it is your standing
   contract for this session. Confirm, then wait for round prompts."). Judge the echoed
   screen, then record `worker.started`.

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
| `pane.launched`, `pane.labeled`, `pane.closed`         | Lane pane lifecycle; written by `pane_ctl.py launch` / `close`                                                                     |
| `pane.orphans_detected`                                | Lane tooling left panes behind; record IDs, then close them                                                                        |
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
| `grill.question`                                       | Round question recorded before delivery; data `{round, question}`                                                                  |
| `grill.synthesis`                                      | Round synthesis written; data `{round, confidence}`                                                                                |
| `grill.done`                                           | Griller ends the loop before the cap; data `{round, reason}`                                                                       |
| `grill.assumptions`                                    | Defined assumptions distilled; data `{count}`                                                                                      |
| `grill.assumptions_triaged`                            | Per-assumption human review outcome                                                                                                |
| `commit.proposed`                                      | Artifact commit proposal handed to the human after `complete`                                                                      |
| `orchestrator.halted`, `orchestrator.unverified_input` | Orchestrator-side anomalies                                                                                                        |

## Scripts

The scripts are deterministic helpers. Run them from the repo root.

Create a run (idempotent; prints the run directory). `init` pins the run's cmux workspace
(`--workspace-id` > `CMUX_WORKSPACE_ID` > hard error; `--no-workspace` is the explicit opt-out
for offline runs outside cmux) and drops a self-ignoring `.gitignore` (`*`) into the runs
root, so run state never reaches git in any target repo:

```bash
python3 scripts/run_state.py init --task "Vorhaben plus fixed constraints" --max-questions 10
python3 scripts/run_state.py init --task-file path/to/task.md --run-id grill-example
```

Render prompts. Session prompts once per lane at launch, round prompts per question:

```bash
python3 scripts/render_prompt.py session --run-dir .scratch/orchestrator/runs/<run-id> --lane codebase
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/<run-id> --lane web --round 1 --question "Which HTTP client does the frontend use?"
```

Await a round's reports. One watcher per round, armed through `Monitor` (see Lane Wait
Policy); exits 0 = all reports, 7 = pending lane's pane dead, 8 = deadline. Health checks are
scoped to the run's pinned `workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --lane-surface codebase=surface:465 --lane-surface codebase2=surface:466 --lane-surface docs=surface:467 --lane-surface web=surface:468
```

Parse lane reports. Exit code carries the gate; a missing report is `pending` (exit 6):

```bash
python3 scripts/parse_research_report.py .scratch/orchestrator/runs/<run-id>/reports/round-1-web.md --json
```

Record events, snapshots, gates; close the run:

```bash
python3 scripts/run_state.py event --run-dir <run-dir> --type grill.question --message "round 1 question" --data '{"round":1,"question":"..."}'
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "reports-captured round-1"
python3 scripts/run_state.py gate --run-dir <run-dir> --stage round-1-web --decision advance --reason "well-formed ANSWERED, sources cited"
python3 scripts/run_state.py complete --run-dir <run-dir> --message "grilling complete" --data '{"stop_reason":"griller-done"}'
```

Control lane panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints
the pinned id, `cmux` is the generic `--workspace` injector, `launch`/`deliver`/`close` are
the lifecycle verbs.

Run the regression tests after touching `parse_research_report.py`, `await_reports.py`, or
`pane_ctl.py`:

```bash
python3 scripts/test_parse_research_report.py
python3 scripts/test_await_reports.py
python3 scripts/test_pane_ctl.py
```

## Smoke Test

Before a live lane pilot, run the scripts end-to-end. Every command must exit 0, and the
whole block must be safe to run twice in a row (`init` is idempotent):

```bash
python3 scripts/test_parse_research_report.py
python3 scripts/test_await_reports.py
python3 scripts/test_pane_ctl.py
python3 scripts/run_state.py init --task "Smoke: validate the grilling scripts" --run-id smoke-grill --max-questions 2
python3 scripts/render_prompt.py session --run-dir .scratch/orchestrator/runs/smoke-grill --lane codebase
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/smoke-grill --lane web --round 1 --question "Which HTTP client does the frontend use?"
python3 scripts/parse_research_report.py references/sample-research-report.md --json
python3 scripts/run_state.py snapshot --run-dir .scratch/orchestrator/runs/smoke-grill --label "smoke snapshot"
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/smoke-grill --stage round-1-web --decision advance --reason "smoke test"
python3 scripts/run_state.py complete --run-dir .scratch/orchestrator/runs/smoke-grill --message "smoke complete" --data '{"stop_reason":"smoke"}'

# The watcher without reports must hit its deadline (exit 8), file-only, in ~1 second:
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/smoke-grill --round 1 --deadline-minutes 0.01 --poll-seconds 0.2; [ $? -eq 8 ]
```

`references/sample-research-report.md` is the shipped clean-report fixture. Run the block
from the orchestrator's cmux pane so `init` can pin the workspace; outside cmux, pass
`--workspace-id <uuid>` or `--no-workspace` explicitly.

## Research Report Contract

Ask every lane to finish each round with this report shape. `## Result`, `## Answer`,
`## Sources`, `## Method`, `## Blockers`, and `## Plan Drift` are required: absent or empty,
they make the report malformed and the gate returns `hitl`. Under `## Result`, emit exactly
one of `ANSWERED`, `NO ANSWER`, `BLOCKER` — a literal `ANSWERED | NO ANSWER | BLOCKER` line
is an unfilled template and is rejected.

```markdown
## Result
ANSWERED

## Answer
The finding in prose. For NO ANSWER: why this lane cannot answer the question.

## Sources
- relative/repo/path or URL

## Method
- what was searched, read, or run: outcome

## Blockers
- None

## Plan Drift
- None

## Notes
- Optional: caveats, confidence hints, context. Never load-bearing evidence.
```

The bare-`None` rule: in `## Sources`, `## Blockers`, and `## Plan Drift`, an empty section
is exactly the line `- None` — no prose on or after that line. Explanations belong in
`## Answer` or `## Notes`, which the gate does not parse for content.

Research-specific gate requirements:

- `ANSWERED` needs at least one real source; without one the gate is `stop`.
- `NO ANSWER` needs an explanation under `## Answer`; `## Sources` may be `- None`.
- `## Method` must be substantive in every report, including `NO ANSWER` — what was searched
  and found nothing is evidence too.

Rendered prompts instruct lanes to self-validate their draft with
`parse_research_report.py` before writing the handoff file, so format failures die at the
source instead of at the gate.
