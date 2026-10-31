# Ticket staging and publication recovery

Status distinguishes publication not started, fully staged but not yet recorded, recorded and validated,
already moved but not recorded, and completed. Repeating explicit ticket approval adopts complete
unrecorded staging only after it validates against the reviewed proposal and approved spec; partial or
changed staging stops for inspection. If interruption happens after the atomic move but before the final
state write, rerunning `publish` validates the existing target against the approved spec, proposal,
ticket set, and staged artifact identities before completing state. Changed identities, duplicate grilling
directories, or an already complete run refuse publication.

The target is the frozen `feature_dir` directly in repository `.scratch/`, named `YYYY-MM-DD-<slug>`.
Ticket approval takes no `--target` and asks no target-path question. The proposal's `tracker.slug`
and frozen `tracker_slug` stay the pure slug. Approval accepts an absent folder or exactly one real
`grilling/` directory (variant B).
Other entries (including hidden files), a grilling file or symlink, and an empty target are refused.
Publish validates approval identities, tracker digests, canonical paths and the shared filesystem
before moving anything. It moves the whole grilling directory into staging, removes the now empty
target, then atomically renames staging to the target. The pair bytes remain unchanged.

Status reports `grilling_locations` and these recoverable states:

- Grilling-only target plus staging: `validated`; publish moves grilling, removes target, then renames.
- Empty target plus staging with grilling: `validated`; publish removes target, then renames.
- Absent target plus staging with grilling: `validated`; publish renames staging.
- Published tracker with grilling: `published`; publish validates and completes the state write.

An empty target is accepted only when this run's canonical staging already holds grilling.
Grilling in both target and staging is `inconsistent` and nothing moves. These checks also apply
when recovering each interruption. Native validation and `published_tracker.artifacts` enumerate
only required tracker files and issues; build the commit proposal from those leaves, excluding grilling.
Re-init with the same feature is idempotent even after the move or
completion; a different feature is refused before target or staging changes.

Discarding publication staging (specification revision, ticket revision, worker relaunch, or failed
staging cleanup) first restores its complete `grilling/` directory unchanged by rename into the frozen
feature folder. An absent target is created; an empty target is accepted. Only after restoration is
the remaining staging removed. The restored grilling-only folder is valid for the next publication.
Revision state changes are saved after restoration succeeds.

The same publication layout checks refuse duplicate grilling directories, foreign entries, symlinks,
and non-directory targets before anything moves. A failed rename preserves staging and the prior
stage; a target created for that attempt is removed again. Inspect `grilling_locations` and the
`inconsistent` status, resolve the conflict, then repeat the same command. Repeating also finishes
an interruption before the rename or between the rename and staging removal. Staging without
grilling is discarded normally; a symlinked staging directory is left alone.
