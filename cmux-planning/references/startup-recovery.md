After exit 9, take one `observe` and `assess` using the current launch identity:

- A startup dialog: authorize the specific `respond` key, then re-arm without re-delivery.
- `failed`: stop and follow the existing failure/HITL rules; do not blindly restart.
- A confirmed summarized-and-waiting or idle assignment: use one readiness-gated `deliver --prompt`
  with the same baseline-bound prompt, then re-arm.
- Visibly working: use `mark-started` with screen evidence, then re-arm.

Re-arm with `--extension 0`; startup recovery does not consume the stage's one deadline extension.
Unresolved assessed dialogs continue to recommend `observe`. Never send a second assignment merely
because its marker has not appeared.

For numbered dialog options, use readiness-gated `respond --key 1|2|3` for the
visible choice. Digits are sent as text, without an extra Enter; named navigation
keys still use `cmux send-key`. Inspect and assess the returned observation before
any separate confirmation. In Claude Code, `escape` interrupts the worker's turn
as well as closing the dialog; use the numbered choice to answer it, then inspect
the harness's response. See `references/worker-readiness.md` for the full protocol.
