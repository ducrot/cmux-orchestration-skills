# Stage pass execution details

For `spec`, `spec-review`, `tickets`, or `tickets-review`, use the current pass from `state.json`:

```bash
python3 scripts/render_prompt.py --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/tree_integrity.py baseline --run-dir <run-dir> --stage <stage> --pass <n>
python3 scripts/pane_ctl.py launch --run-dir <run-dir> --stage <stage> --pass <n> \
  --anchor <caller-surface>
python3 scripts/pane_ctl.py start-agent --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
python3 scripts/await_report.py --run-dir <run-dir> --stage <stage> --pass <n> \
  --surface <launch-surface-id>
```

In the table's exit 9 row, "the exception path below" means [references/startup-recovery.md](startup-recovery.md).

| Exit | Meaning |
| --- | --- |
| 0 | Report captured; validate and gate it. |
| 7 | Pane dead; stop at the existing HITL recovery boundary. |
| 8 | Report deadline; use the existing human-approved extension rules. |
| 9 | Assignment not started; inspect the exception path below. |

Workers self-validate in `report-draft.md` beside their started marker and write the handoff
report once, last.

Read [references/spec-contract.md](spec-contract.md) when judging author or review handoffs.

A failed board update is a stderr note and never a stop.
