### Question failures: re-emit once, then defer

A question whose gate is `stop` or `hitl` purely because of form (ungrounded `ANSWERED`, missing
method, missing or empty section, unfilled `|` menu, missing question block) does not stop the session:

1. Request once that the still-open lane pane re-emit the whole report, fixing exactly the named
   questions ("re-emit the report per the Research Report Contract; fix the format of Q2 and Q3,
   not the substance"), using the waited procedure below, naming the questions. Re-parse only after
   the watcher returns the re-emitted report.
2. A question still failing on any lane is **deferred**: record `grill.question_deferred` with
   `{round, id, lanes, reason}`, leave it out of the synthesis, and ask it again in a later round as
   a new question, so all four lanes see it again. The other questions of the round synthesize
   normally.
3. A question that cannot be deferred because no round is left is `hitl` for the session; a human
   decides. Every deferral appears in the final artifact's `## Q&A` protocol.

Never overrule the parser with your own `advance`.

### Wait for the re-emission

Record the request **before sending** the correction prompt, so an immediate rewrite cannot replace
the baseline before it is recorded:

```bash
python3 scripts/run_state.py event --run-dir <run-dir> --type report.reformat_requested \
  --message "question format correction requested" --data '{"round":1,"lane":"web","questions":["Q2","Q3"]}'
```

Use the failing round and lane. The command adds `report_sha256`, the SHA-256 of that lane's current
non-empty report bytes; do not supply a digest yourself. A missing or empty report cannot establish a
baseline. If recording fails, stop as HITL rather than sending an untracked request. Send the correction
prompt to the still-open lane, then arm the watcher immediately using the usual round arguments:

```bash
python3 scripts/await_reports.py --run-dir <run-dir> --round 1 --questions 3 \
  --lane-surface codebase=<surface-id> --lane-surface codebase2=<surface-id> \
  --lane-surface docs=<surface-id> --lane-surface web=<surface-id>
```

Use one round watcher, through the normal background Bash or Monitor procedure. For the requested
lane, the recorded digest keeps it waiting until different non-empty bytes settle on two consecutive
polls. Other lanes keep their normal settled-report behavior. Parse and gate on the report the watcher returns;
exit 0 itself is not `advance`. Exits 7, 8 and 9 retain their normal recovery paths.

The request opens a fresh wait window on first arm without spending the one deadline extension or
resuming the exceeded deadline. Re-arming resumes this window without renewing it. A second request
for the same round/lane is refused and requires HITL, rather than opening a third window. If the
re-emission still fails on form, use Question failures above to defer those questions; do not request
another re-emission. A legacy request without a recorded digest requires HITL.

When re-arming a persisted clock that has already expired, reports already on disk get exactly one
settling poll: all eligible reports unchanged return 0; missing or changing reports return 8. This
does not renew the deadline or accept a rejected baseline digest.

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

