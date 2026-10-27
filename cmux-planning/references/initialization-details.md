# Initialization examples and retry behavior

Concrete direct-task and optional grilling-pair starts are:

```bash
python3 scripts/planning_state.py init --feature 2026-10-27-example --task-file ./task.md --repo . \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
python3 scripts/planning_state.py init --feature 2026-10-27-example --task-file ./task.md --repo . \
  --grilling-json ./grilling-result.json --grilling-markdown ./grilling-result.md \
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

## Feature name at initialization

For planning without grilling input, ask for the feature folder name in the same dialog as the
commit-mode question, only after the human chooses a fresh run. Propose today's local date and a
short lowercase slug from the title or Goal: `YYYY-MM-DD-<slug>`, with the proposal recommended
and free text allowed. Pass the approved name to `init --feature <name>`; without grilling input,
init requires it before any writes.
Skip this name question with explicit `--feature`, on resume, re-init, the exit-3 unfinished-run
path, and smoke tests. Inspect unfinished runs before asking.

The feature folder lives directly in repository `.scratch/`. `--feature` accepts its basename,
repository-relative path, or absolute path. Its prefix must be a valid calendar date; the slug is
lowercase kebab-case, at most 30 characters. The folder and pure slug are frozen as `feature_dir`
and `tracker_slug`. There is no `--slug` option. Init does not create the feature folder; a fresh
run refuses an existing folder unless it contains exactly the `grilling/` directory. Ticket approval
and publication currently require the target to be absent, including refusing an empty folder.
Re-init with a different feature folder is refused, while the same folder remains idempotent after
interrupted or completed publication, without changing target or staging.
