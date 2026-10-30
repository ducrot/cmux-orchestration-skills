# Initialization examples and retry behavior

Concrete direct-task and optional grilling-pair starts are:

```bash
python3 scripts/planning_state.py init --feature 2026-10-27-example --task-file ./task.md --repo . \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --grilling-json .scratch/2026-10-27-example/grilling/result.json \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
```

Relative `--runs-root` and `--run-dir` paths are interpreted from the command's working directory,
as in grilling and issue-chain; init refuses a runs root inside the skill directory. Stored artifact pointers are canonical run-relative paths; readers
join them to the run directory exactly once. Absolute worker handoff paths remain supported.

Re-init with `state.json` prints the run directory; no input replacement, preparation, or advance.
Use `status` and `resume` through human gates. Re-init refuses configuration,
typed overrides, live probes, and `--accept-config`; use stage preparation. Without `state.json`,
retry even if input copies exist.

For a different run ID, init prints this repository's newest unfinished run and exact `resume`
command, then exits before creation. Without `--run-id`, this check precedes input validation,
so `init` without inputs already reports an unfinished run. Completed runs do not block init. Use
`--new-run` only after the human chooses a separate session; it never resets an existing run.

Direct input starts at `spec` with an immutable prepared snapshot. If author and reviewer share a
harness and model, init instead prints an extra warning object (`prepared: null`) before the run
directory, exits with code 2, and awaits confirmation at `spec` without a snapshot. Grilling starts at
`awaiting-grilling-revalidation` without a snapshot.

## Feature name at initialization

For planning without grilling input, ask for the feature folder name in the same dialog as the
commit-mode question, only after the human chooses a fresh run. Propose today's local date and a
short lowercase slug from the title or Goal: `YYYY-MM-DD-<slug>`, with the proposal recommended
and free text allowed. Pass the approved name to `init --feature <name>`; without grilling input,
init requires it before any writes.
Skip this name question with explicit `--feature`, on resume, re-init, the exit-3 unfinished-run
path, and smoke tests. Inspect unfinished runs before asking.

With grilling input, ask no feature-name question. Inherit the folder and slug from the JSON's
location in `.scratch/YYYY-MM-DD-<slug>/grilling/`. The tracker is published in that same feature
folder. An optional `--feature` must identify the same folder; invalid locations and conflicts
are refused before writes. The JSON format and existing pair validation stay unchanged.

The feature folder lives directly in repository `.scratch/`. `--feature` accepts its basename,
repository-relative path, or absolute path. Its prefix must be a valid calendar date; the slug is
lowercase kebab-case, at most 30 characters. The folder and pure slug are frozen as `feature_dir`
and `tracker_slug`. There is no `--slug` option. Init does not create the feature folder; a fresh
run refuses an existing folder unless it contains exactly the `grilling/` directory.
For the ticket approval and publication target rule, see [references/ticket-stage-details.md](ticket-stage-details.md).
Re-init with a different feature folder is refused, while the same folder remains idempotent after
interrupted or completed publication, without changing target or staging.
