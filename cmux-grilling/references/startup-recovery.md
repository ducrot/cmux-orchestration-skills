After exit 9, take one `observe` and `assess` for each lane named in `not_started` only:

- Dialog: `respond` with the assessed action, then re-arm without re-delivery. Resolve
  further dialogs individually.
- Failed startup: stop as HITL/blocker under the existing failure rules.
- Ready but assignment idle, summarized, or unsent: one readiness-gated
  `deliver --round N --kind round --prompt <run-dir>/prompts/round-<N>-<lane>.md`, then re-arm.
- Visibly working: record `run_state.py event --type worker.started` with
  `{lane, round, surface_id, launch_id, evidence: "screen", marker_path}` from the current
  launch, then re-arm. A missing marker alone does not justify re-delivery.

Always re-arm the full round watcher with the same four UUIDs; recovery input targets only
`not_started` lanes. Existing start confirmations remain valid for their launch IDs.
`deliver --kind round` is only for exit-9 recovery. `deliver --text` is for the one report
re-emission or clarifications, also readiness-gated. Before every `deliver`, obtain a fresh
screen-bound readiness assessment; it is consumed before input. Readiness identity remains
`{lane}`, so replacing its pane invalidates earlier observations and ready events. Use the
shared readiness reference for assessment and individual dialog handling. Everything else
(`read-screen`, `set-status`, diagnosis) runs through `pane_ctl.py cmux`, which injects the
pinned workspace. Do not route input through raw CMUX commands to bypass readiness.

