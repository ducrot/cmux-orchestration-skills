## Smoke Test

Before a live lane pilot, run the canonical baseline suites from the repository root:

```bash
python3 -m unittest discover -s cmux-issue-chain/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-planning/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-grilling/scripts -p 'test_*.py'
python3 tools/test_orchestrator_usage.py
```

`test_fresh_rounds.py` executes two rounds through the real CLIs with fake cmux and simulated
workers: frontier rendering, open-round, launched snapshot, start-round, markers/reports,
watching, parser gates, reports-captured snapshot, replacement anchoring, and final close.
It also verifies stale readiness cannot authorize input after pane replacement. The watcher
suite covers missing starts (exit 9), dead pending panes (7), stale artifacts, and re-armed
deadlines (8). `test_round_context.py` verifies the dependency projection and UTF-8 cap.
`references/sample-research-report.md` remains the clean-report fixture for live pilots.
Live usage comparison is a separate human-assisted rollout task.

