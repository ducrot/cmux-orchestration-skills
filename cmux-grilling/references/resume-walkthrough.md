### Resuming an unfinished walkthrough

Check at session start whether the previous walkthrough is unfinished:

```bash
python3 scripts/run_state.py pending-decisions
```

It prints the newest artifact's `open` and `deferred` ids separately. Any `open` id means the
walkthrough was cut short: offer to finish it before starting a new session. `deferred` ids
are reported for completeness — do not re-ask them. This is the only handling of "the human
walked away": at the next contact, not on a clock.

