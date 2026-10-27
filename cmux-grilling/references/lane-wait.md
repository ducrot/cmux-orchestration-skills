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
pass `--extend --reason "<recorded reason>" --deadline-minutes <additional-minutes>`;
the watcher records the reason and grants that duration from the later of the existing
deadline and extension arm. Re-arm without `--extend` to keep that persisted deadline;
a second `--extend` is refused. The compatible `--deadline-reason` spelling retains
idempotent replay of the same reason and duration, sharing the same one-extension budget. The start window is not extended by this flag. Only a recorded exit-9 recovery for a
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
| 8    | Round deadline exceeded, pending panes alive/unknown          | Extend once with `--extend --reason`, else stop as HITL                                          |
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

- Exactly one deadline extension per round; use `await_reports.py --extend --reason <text>`
  with the usual round arguments and `--deadline-minutes` to record the
  extension and re-arm. The watcher records a structured `worker.waiting` extension event;
  a second extension in the same round, a blank or missing reason, or a missing deadline is refused.
  Before spending it on a silent lane, check the
  screen for the not-started case in CMUX Control: re-delivering a round prompt to a lane that
  never started restarts the wait clock and is not an extension.
- After an exhausted extension with no report, or a dead pane: record a `hitl` gate for
  `round-<N>-<lane>` and stop the session. Use `blocked` only for blockers a lane itself
  reported.
- Never close a lane pane while its report is pending, and never send the next round while
  any report of the current round is outstanding.

