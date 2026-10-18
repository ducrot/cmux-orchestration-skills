Render a follow-up pass (see Follow-up Pass). `--followup-file` applies to `--role implement` only and
swaps the implement contract for the follow-up contract; the test prompt stays the normal one and
receives the follow-up report and the item list as context files:

```bash
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/<run-id> --stage triage --decision advance --reason "triage published; follow-up items accepted" --next-stage implement
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage implement --pass 2 --followup
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role implement --pass 2 --run-dir .scratch/orchestrator/runs/<run-id> --followup-file .scratch/orchestrator/runs/<run-id>/followup-items.md
```

`prepare --followup` is valid only for implement passes after the first and records the choice in the immutable stage
snapshot and `stage.prepared` event. The renderer requires `--followup-file` exactly when that
marker is set. A corrective pass after a HITL is a regular implement pass: prepare it without
`--followup`, render without `--followup-file`, and require regression proof and green own
after-evidence, with no before-evidence duty. Only a follow-up implement pass owes before-evidence.
