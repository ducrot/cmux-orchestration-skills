Status is read-only and derives progress from `state.json`, digest-bound files, structured lifecycle
events, and optional CMUX surface health. It never treats pane text or a worker narrative as success:

```bash
python3 scripts/planning_state.py status --run-dir <run-dir>
python3 scripts/planning_state.py resume --run-dir <run-dir>
python3 scripts/planning_state.py context --run-dir <run-dir>
```

