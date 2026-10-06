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

