## Recommendations Triage

Recommendations triage is autonomous by default. `run_state.py init` records `triage_mode: autonomous`;
`--human-triage` opts out and records `human`. Runs without that field read as human, including old
runs with a `decision.human` event. The orchestrator never decides recommendation content.

After the final test report parses `advance` and before that gate event is recorded:

1. Run `python3 scripts/collect_recommendations.py --run-dir <run-dir> --pass 1`. It scans every
   non-triage implement, simplify, review, and test report by pass then chain order, preserving every
   `## Recommendations` entry verbatim, including duplicates and leading prose. It marks Counter-proposal
   entries and attaches named same-run `## Not Applied` sections. It writes immutable `triage-items-1.md`
   with `R1..Rn`, source reports and the issue diff files (both rename paths and untracked files),
   and records `triage.collected`. A matching repeated collection exits 0 without writes. An orphan
   items file or digest mismatch refuses; gate `hitl` with the error. Only passes 1 and 2 are supported;
   higher values refuse without writes.
2. With zero items, record the test gate `advance` with no `--next-stage`, then complete from `test`.
3. Otherwise, in autonomous mode record `advance --next-stage triage`, then
   `prepare --stage triage --pass 1`. Render `--role triage --pass 1 --items-file <run-dir>/triage-items-1.md`
   with all non-triage run reports supplied as `--context-file`. Keep the issue ready until completion.
4. Launch a fresh visible Triager pane anchored to the test pane. Snapshot, start-agent, and arm the watcher
   as for every role. Between `launched triage-<pass>` and `report-captured triage-<pass>`, compare
   `staged_paths`, `staged_diff_sha256`, `head`, and the full `fingerprint`. Any difference gates `hitl`:
   triage is read-only, and its diff files were captured before launch.
5. Parse `reports/triage-1.md` with `--items-file <run-dir>/triage-items-1.md`. The gate requires exactly
   one verdict per ID, matching sources, present titles and reasons, eligible files inside the captured diff,
   a Supersedes reference for accepted counter-proposals, and a valid issue draft for each accepted
   non-follow-up item. `verdicts_malformed` uses the existing single re-emission request: fix the
   format, not the substance. Quote the offending item and paths for a failed file check without
   suggesting a verdict. A second failure gates `hitl`.
6. After a passing gate, run `python3 scripts/run_state.py publish-triage --run-dir <run-dir> --pass 1`.
   It rechecks the digest, capture snapshot, report, draft blockers and issue path/slug collisions
   before writing. A failed publication precondition gates `hitl` with the error. Publication creates
   `todo` issues from accepted non-follow-up drafts, appends `decisions.md`, writes `followup-items.md`
   when needed, and records `recommendations.triaged` and `triage.published`.
7. Record the triage gate `advance --next-stage implement` when publication prints `next_stage: implement`;
   otherwise record `advance` with no next stage and run `complete`.

After the follow-up test report parses `advance` and before that gate event is recorded, run
`python3 scripts/collect_recommendations.py --run-dir <run-dir> --pass 2`. It scans only non-triage
reports not listed under `Scanned reports` in `triage-items-1.md`, retaining same-run counter-proposal
context, and writes `triage-items-2.md` with `Triage pass: 2` and `Follow-up pass allowed: no` when nonempty.
The extraction, immutability, `triage.collected`, and idempotency rules above also apply to pass 2.
With zero new items, record the test gate `advance` with no next stage and complete. Otherwise record
`advance --next-stage triage` and repeat steps 3–7 with `--pass 2`, `triage-items-2.md`, and
`reports/triage-2.md`. Supply every non-triage report plus `reports/triage-1.md` and `followup-items.md`
as `--context-file`. Launch a fresh Triager 2 anchored to the follow-up test pane; use the same
snapshot comparison, watcher, parse, and publication steps. Pass 2 forbids `Follow-up eligible: yes`;
the gate marks it `verdicts_malformed` and `hitl`. `publish-triage --pass 2` writes issues, ledger lines,
and events, writes no `followup-items.md`, and prints `next_stage: null`. Record the triage-2 gate
`advance` with no next stage, then complete. Triage-2 never starts another follow-up pass.

The `triage` worker needs an assignment in the configuration like every other worker, even though its
run is optional; `--human-triage` only decides whether it launches. `init` writes `claude-opus-medium`,
and migration from schema v1 or v2 adds `claude-opus-high` when it is missing. Every preparation
resolves, preflights, and optionally probes all five workers, including in human mode.

The triage worker decides every item autonomously and must never ask the human or the orchestrator
anything. The orchestrator never answers a triage worker's content question; treat a worker that asks
as a silent worker, following the wait policy until `hitl`. Uncertainty is a reasoned `for-the-human`
or `deferred` verdict, never a question. The fixed vocabulary is:

- `accepted`: follow-up when eligible, otherwise an issue draft.
- `rejected`: do not do it; any earlier decision stands.
- `deferred`: not this run, no issue now.
- `recorded`: already handled or informational, no action (`resolved` maps here). Write `recorded` in the report, never `resolved`.
- `for-the-human`: cannot decide or human-only action (`accepted-human` maps here). Write `for-the-human` in the report, never `accepted-human`. It is open, not approval.

`for-the-human` never blocks. Rejected, deferred, and recorded items are ledger only. For a
Counter-proposal the default is the earlier decision: accept only when the proposal refutes the
recorded reason with evidence, such as a measurement or concrete failure case.
After a triage `hitl` or `blocked` gate, the rest of that run's recommendations triage falls back to
the human procedure; no automatic relaunch is allowed.

In human mode, the human decides the same collector-owned numbered verbatim list. The orchestrator
never decides. The human may answer "later": complete the run, keep open items pending, and route later
acceptance to a new issue — a follow-up pass exists only while the issue is uncommitted. Record each
verdict and reason in `recommendations.triaged` and append a ledger line carrying
`[human verdict, run <run-id>]`. An open recommendations triage never blocks the next issue chain.
Only the human's acceptance creates issues in human mode; only `publish-triage` from gated `accepted`
verdicts creates issues in autonomous mode. An accepted new issue does not by itself authorize changing
a protected decision in the current issue.

The ledger distinguishes approved, rejected, deferred, recorded, and open items by human or triage-worker
authority. Explicit recorded supersession approvals identify the earlier decision and the authorized
replacement or scope; a marker-bearing triage-worker verdict satisfies the recorded approval rule.
`render_prompt.py` embeds the ledger into every worker prompt. Do not re-report or re-apply rejected,
deferred, or recorded items unless the code presents a materially different problem. Open items are
not approvals and must not be applied.

