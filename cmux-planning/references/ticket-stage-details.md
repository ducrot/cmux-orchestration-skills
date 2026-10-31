# Ticket stage procedure

See the Gate the author and reviewer section in the entry point for the gate commands.
Gate a clean report with `accept-author` as above. It validates approved-spec identity, proposal structure, summary equality, ticket count, ready
frontier, genuine blockers, cycles, qualitative sizing, merge/split rationale, and wide-refactor
sequences, then prepares a fresh immutable `tickets-review` snapshot. Run that stage in a new visible
pane; gate its report with `accept-review` as above.

For the ticket approval and publication target:
The target must be absent or contain only a real `grilling/` directory (variant B); its basename must
equal the dated feature name `YYYY-MM-DD-<slug>`; `tracker.slug` remains the pure slug.

Publish on one filesystem; variant B moves `grilling/` first:

```bash
python3 scripts/planning_state.py publish --run-dir <run-dir>
```

For the `run_commit.py propose` subject after publish:
Use an English one-line subject explaining what changed and why, an optional body, and no trailers.
