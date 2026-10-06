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
   wait to the harness (`Bash run_in_background`, or Monitor with re-arm) with a stated
   deadline, and stop as HITL when the deadline passes without recovery. Never wait without an armed
   watcher and never poll indefinitely.
4. After recovery, verify before advancing: the orchestrator re-runs the issue's checks over the changes the
   blocked pass applied but could not verify, and records an `orchestrator.verified` event with commands and
   outcomes. Only then resume the same stage — the interrupted pass continues; the chain does not skip ahead.

