Validate the artifact's decisions at finalize, record one outcome during the walkthrough, and
check for an unfinished walkthrough at session start (see Resuming an unfinished walkthrough):

```bash
python3 scripts/run_state.py validate-artifact --artifact <artifact.json>
python3 scripts/run_state.py decision --run-dir <run-dir> --artifact <artifact.json> --id D1 --status decided --decision "Ab 12 Jahren"
python3 scripts/run_state.py pending-decisions
```

Render self-contained round prompts once per lane per round, with one
`--question` (or `--question-file`) per frontier question, numbered `Q1..Qn` in order:

```bash
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/<run-id> --lane web --round 1 --question "Which HTTP client does the frontend use?" --question "Which API base URL does it use?"
```

Await a round's reports. One watcher per round, armed through background Bash or Monitor with re-arm (see Lane Wait
Policy); exits 0 = all reports, 7 = pending lane's pane dead,
8 = round deadline, 9 = round not started. Health checks are
scoped to the run's pinned `workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --questions 2 --lane-surface codebase=<UUID> --lane-surface codebase2=<UUID> --lane-surface docs=<UUID> --lane-surface web=<UUID>
```

Parse lane reports. `--questions <n>` demands blocks `Q1..Qn`. The exit code carries the most severe
question gate, `--json` the gate of every question; a missing report is `pending` (exit 6):

```bash
python3 scripts/parse_research_report.py .scratch/orchestrator/runs/<run-id>/reports/round-1-web.md --questions 2 --json
```

Record events, snapshots, gates; close the run. An unreadable or vanished untracked path fails the snapshot
with a diagnostic naming it and records no event; restore access or remove the path and retry. Git only
warns about an unreadable untracked directory, so its contents stay invisible rather than failing capture.
Then:

```bash
python3 scripts/run_state.py event --run-dir <run-dir> --type grill.question --message "round 1 Q1" --data '{"round":1,"id":"Q1","question":"...","depends_on":[]}'
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "reports-captured round-1"
python3 scripts/run_state.py gate --run-dir <run-dir> --stage round-1-web --decision advance --reason "well-formed ANSWERED, sources cited"
python3 scripts/run_state.py complete --run-dir <run-dir> --markdown <output-dir>/<slug>.md --json <output-dir>/<slug>.json --message "grilling complete" --data '{"stop_reason":"griller-done"}'
```

Control lane panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints
the pinned id, `cmux` is the generic `--workspace` injector, `open-round`/`start-round` own normal round lifecycle;
`launch`/`start-agent`/`close` remain for recovery and final close.

Run the regression tests after touching `parse_research_report.py`, `await_reports.py`,
`pane_ctl.py`, `run_state.py`, `launch_wave.py`, or `agents_config.py`:

```bash
python3 scripts/test_parse_research_report.py
python3 scripts/test_await_reports.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_run_state.py
python3 scripts/test_agents_config.py
python3 scripts/test_launch_wave.py
```

