# Ticket staging and publication recovery

Status distinguishes publication not started, fully staged but not yet recorded, recorded and validated,
already moved but not recorded, and completed. Repeating explicit ticket approval adopts complete
unrecorded staging only after it validates against the reviewed proposal and approved spec; partial or
changed staging stops for inspection. If interruption happens after the atomic move but before the final
state write, rerunning `publish` validates the existing target against the approved spec, proposal,
ticket set, and staged artifact identities before completing state. If both staging and target exist,
identities differ, or the run is already complete, publication refuses to duplicate or partially
overwrite anything.

The target is the frozen `feature_dir` directly in repository `.scratch/`, named `YYYY-MM-DD-<slug>`.
Ticket approval takes no `--target` and asks no target-path question. The proposal's `tracker.slug`
and frozen `tracker_slug` stay the pure slug. Approval requires an absent feature folder; publish
also refuses existing targets (including empty ones) unless validating the already-moved approved
tracker for recovery as above. Re-init with the same feature is idempotent even after the move or
completion; a different feature is refused before target or staging changes.
