Run the regression tests after touching `parse_report.py`, `await_report.py`, `pane_ctl.py`, `run_state.py`,
`worker_snapshot.py`, `agents_config.py`, `collect_recommendations.py`, `triage_contract.py`, or
`publish_triage.py`:

```bash
python3 scripts/test_parse_report.py
python3 scripts/test_collect_recommendations.py
python3 scripts/test_await_report.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_stage_preparation.py
python3 scripts/test_agents_config.py
```

