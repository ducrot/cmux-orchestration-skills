Render a follow-up pass (see Follow-up Pass). `--followup-file` applies to `--role implement` only and
swaps the implement contract for the follow-up contract; the test prompt stays the normal one and
receives the follow-up report and the item list as context files:

```bash
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/<run-id> --stage triage --decision advance --reason "triage published; follow-up items accepted" --next-stage implement
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/<run-id> --stage implement --pass 2
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role implement --pass 2 --run-dir .scratch/orchestrator/runs/<run-id> --followup-file .scratch/orchestrator/runs/<run-id>/followup-items.md
```

