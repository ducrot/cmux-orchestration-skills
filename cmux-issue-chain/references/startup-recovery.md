Send re-delivery or follow-up text to a worker with `pane_ctl.py deliver` — never with a
bare `cmux send`. The underlying trap: `cmux send --help` documents `\n` and `\r` as Enter, but a
trailing `\n` does not submit in either the Codex or the Claude Code TUI; the text lands in the composer
and waits there unsent. `deliver` therefore always sends the text and an explicit `send-key enter` as two
commands, then echoes the pane screen:

```bash
# Read each result; ready is a judgment, not an unconditional startup command.
python3 scripts/pane_ctl.py observe --run-dir <run-dir> --surface <surface-id> --role test --pass 1
python3 scripts/pane_ctl.py assess --run-dir <run-dir> --surface <surface-id> --role test --pass 1 --observation <observation-id> --state ready --reason "<screen evidence>"
python3 scripts/pane_ctl.py deliver --run-dir <run-dir> --surface <surface-id> \
  --role test --pass 1 --prompt .scratch/orchestrator/runs/<run-id>/prompts/test-1.md
```

`--role`/`--pass` are required: they bind readiness and the `worker.prompt_sent` event to the worker. `--prompt` builds the delivery line from `orchestrator_lib.delivery_text()` — do not write
that line by hand. A framing like "Read `<path>` and report back" is what a Claude worker answers with a
summary of the prompt, which is why the wording lives in the skill and not in the turn.

After exit 9, take one `observe` and `assess` and follow this exception path:
- `prompt`: use `respond` for the assessed dialog, then re-arm without re-delivery. The assignment
  is already attached to the launch. Resolve further dialogs individually under the readiness protocol.
- `failed`: follow the existing blocker/recovery rules.
- Idle after a recap or line unsent: perform one readiness-gated `deliver --prompt`, then re-arm.
  A worker that never started does not consume the stage's one deadline extension.
- Visibly working: record `run_state.py event --type worker.started` with `evidence: "screen"`,
  the current `launch_id`, `role`, `pass`, and `surface_id`, then re-arm.

A re-armed watcher keeps the same launch identity and can accept a refreshed marker. Screen-based
confirmation is reserved for this exception path; normal starts are confirmed by the watcher.

For numbered dialog options, use readiness-gated `respond --key 1|2|3` for the
visible choice. Digits are sent as text, without an extra Enter; named navigation
keys still use `cmux send-key`. Inspect and assess the returned observation before
any separate confirmation. In Claude Code, `escape` interrupts the worker's turn
as well as closing the dialog; use the numbered choice to answer it, then inspect
the harness's response. See `references/worker-readiness.md` for the full protocol.
