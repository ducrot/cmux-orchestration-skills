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

## Worker Profile Configuration

> **Codex TUI flags upgrade:** Snapshots and launch waves prepared before this change must be prepared again; loaders reject the old `tui.whimsy` argument vector.

> **Trust preflight upgrade:** Stage snapshots and launch waves prepared before the trust-preflight upgrade fail validation and must be prepared again. Before preparing, start each assigned `claude` or `codex` harness once in the exact repository root, accept its trust dialog, then exit. In a linked Git worktree, both harnesses record that trust for the main checkout, which preparation accepts. Parent-directory trust does not count. Pi workers require a build supporting `--no-approve`; preparation checks the flag and launch adds it. Python 3.11 or newer is required.

> **Codex hook trust:** Before preparing, start `codex` once in the repository root, review and trust the hooks (via `/hooks`), then exit and prepare again. Preparation reads `$CODEX_HOME/hooks.json` and `$CODEX_HOME/config.toml` (default `~/.codex`), plus the repository's `.codex/hooks.json` and `.codex/config.toml`. Enabled hooks without a positional trust record stop preparation before any pane exists; `features.hooks = false` and per-hook `[hooks.state."<key>"].enabled = false` are respected. The audit records checked sources and trusted-key counts. Hash values are unverifiable: changed hooks are not detected and remain on the watcher exit-9 exception path. Re-prepare older Codex snapshots and launch waves that lack `preflight.hook_trust`.

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v3. Older separately installed sibling skills cannot read the migrated schema-v3 shared configuration.

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
on schema v1 or v2 with the exact preview and acceptance commands; run initialization does the same
before publishing a launch wave.

Treat configuration creation as a first-use human checkpoint, separate from run initialization.
Before starting any worker-bearing run, resolve the selected configuration path and follow this
protocol. Never offer profile overrides the human did not ask for.

1. If the file already exists at schema v1 or v2, run `agents_config.py migrate` without `--accept`.
   Present its coordinated-upgrade warning and complete validated preview in the human's language,
   including every resolved workflow assignment. When `claude-fable-high` is unavailable, call out
   the displayed fallback profile name, harness, model, and effort without inferring relative quality.
   Also call out every added required assignment the preview names, such as `issue-chain.triage`.
   Ask whether to accept exactly that proposal. On refusal or interruption, make no further tool call.
   On confirmation, invoke the preview's exact `agents_config.py migrate --accept` command, digest
   argument included, then validate and continue.
2. If the file already exists and is valid schema v3, continue with its assignments.
   A schema-v3 file needs no migration question.
   An existing valid schema-v3 file needs no start confirmation either; the start question
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

Configuration is strict and user-owned after its create-only bootstrap. Schema-v1 and schema-v2 reads never migrate.
The read-only `migrate` preview validates the complete schema-v3 candidate before displaying it;
`migrate --accept` is the only shared-CLI path that atomically replaces the file. Existing profiles and
assignments are preserved. From schema v1, planning roles are selected deterministically and a
collision-safe Codex reviewer is added only when needed. A missing `issue-chain.triage` is assigned
`claude-opus-high`, copied from the defaults when the file lacks that profile. The original bytes remain
untouched if validation or publication fails. Migration refuses a resolved target with no write bit or more than one hard link. A symlink is
preserved and those same guards apply to its intended target.
The output-stream contract is stable: standalone read-only `migrate` writes the complete migration
guidance once on stdout, while stderr contains only its short refusal and never repeats either command.
For a schema-v1 or schema-v2 refusal, planning initialization leaves stdout empty and writes one complete actionable
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
missing, failed, mismatched, or tampered lane blocks every pane. The default wave sends:

```bash
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model opus --effort high \
  --permission-mode auto                                   # codebase
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  -c tui.animations=false \
  -c tui.disable_paste_burst=true \
  --model gpt-6-astra \
  -c model_reasoning_effort=high                          # codebase2
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  -c sandbox_workspace_write.network_access=true \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  -c tui.animations=false \
  -c tui.disable_paste_burst=true \
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
- `tui.animations=false` disables decorative motion on the welcome screen, shimmer, and spinner, so
  the lane screen that readiness checks and `observe` read stays stable.
- `tui.disable_paste_burst=true` disables Enter suppression after a typed burst, so exception-path
  `deliver` submits text with a single Enter.

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

After exit 9, take one `observe` and `assess` for each lane named in `not_started` only:

- Dialog: `respond` with the assessed action, then re-arm without re-delivery. Resolve
  further dialogs individually.
- Failed startup: stop as HITL/blocker under the existing failure rules.
- Ready but assignment idle, summarized, or unsent: one readiness-gated
  `deliver --round N --kind round --prompt <run-dir>/prompts/round-<N>-<lane>.md`, then re-arm.
- Visibly working: record `run_state.py event --type worker.started` with
  `{lane, round, surface_id, launch_id, evidence: "screen", marker_path}` from the current
  launch, then re-arm. A missing marker alone does not justify re-delivery.

Always re-arm the full round watcher with the same four UUIDs; recovery input targets only
`not_started` lanes. Existing start confirmations remain valid for their launch IDs.
`deliver --kind round` is only for exit-9 recovery. `deliver --text` is for the one report
re-emission or clarifications, also readiness-gated. Before every `deliver`, obtain a fresh
screen-bound readiness assessment; it is consumed before input. Readiness identity remains
`{lane}`, so replacing its pane invalidates earlier observations and ready events. Use the
shared readiness reference for assessment and individual dialog handling. Everything else
(`read-screen`, `set-status`, diagnosis) runs through `pane_ctl.py cmux`, which injects the
pinned workspace. Do not route input through raw CMUX commands to bypass readiness.

Keep current round panes open until the next `open-round` or session end, after reports,
re-emission, gates, and snapshot are recorded. At session end use `close --round N --lane
<lane> --surface <UUID>` per lane. Never close a pending report's pane during a normal wait.

While a round is in flight, the four reports belong to the lanes: do not edit anything under
`reports/` yourself, and compare snapshot fingerprints before any `report.integrity` claim.

## Event Vocabulary

`commit.proposed` is written only by `run_commit.py propose`.
`commit.attempted`, `commit.created`, `commit.skipped`, and `commit.failed` are written only by
`run_commit.py commit`: attempt before Git, proven success, nothing to commit, or proposal fallback.

Use these exact event types. New ad-hoc types must be dot-namespaced, lower-case, and used
consistently within a run.

| Event                                                  | When                                                                                                                               |
|--------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `run.init`, `run.completed`                            | Written by `run_state.py init` / `complete`                                                                                        |
| `run.briefing`                                         | Briefing shown to the human, pill text in data; written by `run_briefing.py show`                                                 |
| `run.recap`                                            | Recap shown to the human, outcome and pill in data; written by `run_briefing.py recap-show`                                       |
| `launch_wave.prepared`                                 | All four lanes resolved, preflighted, audited, and frozen before pane creation                                                     |
| `pane.launched`, `pane.labeled`, `pane.closed`         | Lane pane lifecycle with round; written by `open-round`, `launch`, or `close`                                                                     |
| `pane.orphans_detected`                                | Lane tooling left panes behind; record IDs, then close them                                                                        |
| `worker.starting`                                    | Launch about to be sent; invalidates earlier readiness, includes round, launch_id, prompt_path, marker_path, and start_time_ns |
| `worker.observed`, `worker.ready`, `worker.startup_status`, `worker.readiness_consumed`, `worker.dialog_response` | Readiness events: exception-path and follow-up only; observe/assess/respond before gated input |
| `worker.launch_sent`                                   | Lane agent launch command with attached round prompt; written by `pane_ctl.py start-agent`                                                       |
| `worker.prompt_sent`                                   | Text sent and submitted; written by `pane_ctl.py deliver`                                                                          |
| `worker.started`                                       | Current launch confirmed by fresh marker or report (`evidence: "marker"|"report"`), or exception-path `"screen"`; data binds lane, round, surface_id, launch_id, marker_path                   |
| `worker.waiting`                                       | Written by the armed round watcher only: heartbeats plus its final outcome                                                         |
| `worker.finished`                                      | Round report captured; data carries `{lane, round, surface_id}`                                                                    |
| `worker.launch_blocked`                                | A lane launch was denied (permissions, environment)                                                                                |
| `gate`                                                 | Only via `run_state.py gate`                                                                                                       |
| `tree.snapshot`                                        | Only via `run_state.py snapshot`                                                                                                   |
| `report.reformat_requested`                            | Re-emission asked for a format-only parse failure                                                                                  |
| `report.integrity`, `report.integrity.retracted`       | Report-claim accusation and its retraction                                                                                         |
| `plan.drift`, `plan.drift.resolved`                    | Task-premise drift recorded / resolved; data carries `class` (small-factual, load-bearing) and `resolved_by` (orchestrator, human) |
| `hitl.resolved`, `decision.human`                      | Human decisions and HITL resolutions                                                                                               |
| `grill.question`                                       | Round question recorded before delivery, one per question; data `{round, id, question, depends_on}`                               |
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

Validate the artifact's decisions at finalize, record one outcome during the walkthrough, and
check for an unfinished walkthrough at session start (see Resuming an unfinished walkthrough):

```bash
python3 scripts/run_state.py validate-artifact --artifact <artifact.json>
python3 scripts/run_state.py decision --run-dir <run-dir> --artifact <artifact.json> --id D1 --status decided --decision "Ab 12 Jahren"
python3 scripts/run_state.py pending-decisions
```

Render self-contained round prompts once per lane per round, with one
`--question` (or `--question-file`) per frontier question, numbered `Q1..Qn` in order:

```bash
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/<run-id> --lane web --round 1 --question "Which HTTP client does the frontend use?" --question "Which API base URL does it use?"
```

Await a round's reports. One watcher per round, armed through background Bash or Monitor with re-arm (see Lane Wait
Policy); exits 0 = all reports, 7 = pending lane's pane dead,
8 = round deadline, 9 = round not started. Health checks are
scoped to the run's pinned `workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --questions 2 --lane-surface codebase=<UUID> --lane-surface codebase2=<UUID> --lane-surface docs=<UUID> --lane-surface web=<UUID>
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
python3 scripts/run_state.py event --run-dir <run-dir> --type grill.question --message "round 1 Q1" --data '{"round":1,"id":"Q1","question":"...","depends_on":[]}'
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "reports-captured round-1"
python3 scripts/run_state.py gate --run-dir <run-dir> --stage round-1-web --decision advance --reason "well-formed ANSWERED, sources cited"
python3 scripts/run_state.py complete --run-dir <run-dir> --markdown <output-dir>/<slug>.md --json <output-dir>/<slug>.json --message "grilling complete" --data '{"stop_reason":"griller-done"}'
```

Control lane panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints
the pinned id, `cmux` is the generic `--workspace` injector, `open-round`/`start-round` own normal round lifecycle;
`launch`/`start-agent`/`close` remain for recovery and final close.

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

Before a live lane pilot, run the canonical baseline suites from the repository root:

```bash
python3 -m unittest discover -s cmux-issue-chain/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-planning/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-grilling/scripts -p 'test_*.py'
python3 tools/test_orchestrator_usage.py
```

`test_fresh_rounds.py` executes two rounds through the real CLIs with fake cmux and simulated
workers: frontier rendering, open-round, launched snapshot, start-round, markers/reports,
watching, parser gates, reports-captured snapshot, replacement anchoring, and final close.
It also verifies stale readiness cannot authorize input after pane replacement. The watcher
suite covers missing starts (exit 9), dead pending panes (7), stale artifacts, and re-armed
deadlines (8). `test_round_context.py` verifies the dependency projection and UTF-8 cap.
`references/sample-research-report.md` remains the clean-report fixture for live pilots.
Live usage comparison is a separate human-assisted rollout task.

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

Lanes may write only their round marker, draft path, and report handoff path
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
