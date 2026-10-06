After exit 9, take one `observe` and `assess` using the current launch identity:

- A startup dialog: authorize the specific `respond` key, then re-arm without re-delivery.
- `failed`: stop and follow the existing failure/HITL rules; do not blindly restart.
- A confirmed summarized-and-waiting or idle assignment: use one readiness-gated `deliver --prompt`
  with the same baseline-bound prompt, then re-arm.
- Visibly working: use `mark-started` with screen evidence, then re-arm.

Re-arm with `--extension 0`; startup recovery does not consume the stage's one deadline extension.
Unresolved assessed dialogs continue to recommend `observe`. Never send a second assignment merely
because its marker has not appeared.

