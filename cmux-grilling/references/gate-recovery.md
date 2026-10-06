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

