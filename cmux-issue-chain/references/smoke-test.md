## Smoke Test

Before a live worker pilot, run the scripts against the real local tracker. Replace `.scratch/<tracker>`
with the tracker directory and `ISSUE-001` with an issue that is ready (type AFK, status todo/in_progress,
unblocked) — `render_prompt.py` refuses HITL and non-ready issues by design. Every command must exit 0, and
the whole block must be safe to run twice in a row:

```bash
python3 scripts/test_parse_report.py
python3 scripts/test_collect_recommendations.py
python3 scripts/test_await_report.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_issue_state.py
python3 scripts/test_adopt_tracker.py
python3 scripts/test_agents_config.py
python3 scripts/test_stage_preparation.py
python3 scripts/test_render_prompt.py
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> --dry-run
python3 scripts/issue_state.py list --tracker .scratch/<tracker>
python3 scripts/issue_state.py ready --tracker .scratch/<tracker>
python3 scripts/run_state.py init --tracker .scratch/<tracker> --issue ISSUE-001 --run-id smoke-issue-001
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/smoke-issue-001 --stage implement --decision pending --reason "prepare repeatable smoke"
python3 scripts/run_state.py prepare --run-dir .scratch/orchestrator/runs/smoke-issue-001 --stage implement --pass 1
python3 scripts/collect_recommendations.py --run-dir .scratch/orchestrator/runs/smoke-issue-001 --pass 1
python3 scripts/render_prompt.py --tracker .scratch/<tracker> --issue ISSUE-001 --role implement --pass 1 --run-dir .scratch/orchestrator/runs/smoke-issue-001
python3 scripts/parse_report.py references/sample-no-findings.md --json
python3 scripts/run_state.py snapshot --run-dir .scratch/orchestrator/runs/smoke-issue-001 --label "smoke snapshot"
python3 scripts/run_state.py gate --run-dir .scratch/orchestrator/runs/smoke-issue-001 --stage implement --decision stop --reason "smoke test"
python3 scripts/run_state.py complete --run-dir .scratch/orchestrator/runs/smoke-issue-001 --message "smoke complete"
```

The collector on the fresh smoke run exits 0 with zero items and no items file; on the second run it
exits 0 again without an extra collection event. The smoke-only gate and preparation reset the reusable
smoke stage before rendering. The smoke gates use `pending` and `stop` because an `advance` gate
requires passing `check_evidence.py` evidence the smoke block cannot produce.

The smoke test must prove gate correctness, issue parsing, blocker DAG evaluation, prompt rendering, run-state writing, tree fingerprinting, run closing, and report parsing without requiring product-code changes.

`references/sample-no-findings.md` is the shipped clean-report fixture. `run_state.py init` is idempotent, so re-running the block reuses the existing run directory instead of failing. Run the block from the orchestrator's cmux pane so `init` can pin the workspace; outside cmux, pass `--workspace-id <uuid>` or `--no-workspace` explicitly.

