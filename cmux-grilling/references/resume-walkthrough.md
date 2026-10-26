### Resuming an unfinished walkthrough

Check at session start whether the previous walkthrough is unfinished:

```bash
python3 scripts/run_state.py pending-decisions
```

It prints the newest artifact's `open` and `deferred` ids separately. Any `open` id means the
walkthrough was cut short: offer to finish it before starting a new session. `deferred` ids
are reported for completeness — do not re-ask them. This is the only handling of "the human
walked away": at the next contact, not on a clock.

Apply the same deferral rule on resume: an option whose only content is "collect the missing facts first"
is a deferral even when it is the recommended option and even when the human selects it by label.
The orchestrator must record `deferred`, never `decided`, name the facts in the outcome, and add
each missing fact to `open_facts` in JSON and `## Offene Fakten` in Markdown, matching both halves.
Run `run_state.py validate-artifact --artifact <artifact.json>` afterwards. An exact label passing
the command's selection traceability check does not establish that missing facts were resolved.

Before presenting a resumed pair as synchronized, repair interrupted assumption-marker
transcription from the recorded `assumption_review` outcomes (script reference recovery renderer).
Do not record those answers again. Validate both halves with `run_state.py validate-artifact`
after transcription and before the commit proposal and recap. The assumptions review remains
advisory and non-blocking; unreviewed assumptions do not prevent continuation.

