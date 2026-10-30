# Integrity boundaries

Two explicit integrity boundaries apply. The product-tree detector covers tracked changes, staged
changes, untracked paths and their content (regular files up to the 8 MiB size cap and symlink
target bytes), and HEAD movement. It does not cover ignored product files or skipped untracked
content (files above the size cap or unsupported types), or contents of unreadable untracked
directories omitted by Git with a warning. Separately, every trusted file in the Git-ignored run
directory is finalized in `state.json`'s artifact manifest with its canonical run-relative path,
kind, stage, pass, attempt, byte size, SHA-256, producer event, and immutable status. A baseline
arms one pass and is never recaptured against different product-tree bytes, so a relaunch cannot
adopt an unauthorized delta as its new "before".
Before each launch, capture complete Git status, tracked and staged diffs; after the report,
compare paths and diff content. `compare_tree` compares the whole before/after `staged_diff` independently
of the allowed-write list. Any difference gates `integrity-violation`, including staging an allowed
artifact in a non-ignored custom run root. Ordinary permitted artifact content writes and an
unchanged pre-staged human baseline remain allowed.
An unreadable or vanished untracked path fails capture with a diagnostic naming it instead of
being skipped; restore access or remove the path and retry. Git only warns about an unreadable
untracked directory, so its contents stay invisible rather than failing capture.

Every worker emission has an immutable attempt identity. The first attempt retains the concise
stage/pass filenames; every later same-pass attempt uses an `-attempt-N` suffix for its prompt,
report, draft/proposal, optional corrected candidate, stage snapshot, and tree snapshots. Preparing
a retry closes the earlier attempt and never reuses, deletes, or silently re-baselines its paths.

In-flight runs with pre-change untracked baselines must restart after upgrading; never migrate
those baselines or bypass seals.
