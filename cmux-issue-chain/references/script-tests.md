Run the regression tests after touching `parse_report.py`, `await_report.py`, `pane_ctl.py`, `run_state.py`,
`worker_snapshot.py`, `agents_config.py`, `collect_recommendations.py`, `triage_contract.py`,
`publish_triage.py`, `run_check.py`, `check_evidence.py`, `check_commands.py`, or
`evidence_contract.py` (including the evidence enforcement in `run_state.py gate`):

```bash
python3 scripts/test_run_check.py
python3 scripts/test_check_evidence.py
python3 scripts/test_check_commands.py
python3 scripts/test_evidence_contract.py
python3 scripts/test_gate_evidence.py
python3 scripts/test_parse_report.py
python3 scripts/test_collect_recommendations.py
python3 scripts/test_await_report.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_stage_preparation.py
python3 scripts/test_agents_config.py
```

