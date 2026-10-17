# Initialization examples and retry behavior

Concrete direct-task and optional grilling-pair starts are:

```bash
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
python3 scripts/planning_state.py init --task-file ./task.md --repo . \
  --grilling-json ./grilling-result.json --grilling-markdown ./grilling-result.md \
  --workspace-id "$CMUX_WORKSPACE_ID" --accept-config
```

Relative `--runs-root` and `--run-dir` paths are interpreted from the command's working directory,
as in grilling and issue-chain. Stored artifact pointers are canonical run-relative paths; readers
join them to the run directory exactly once. Absolute worker handoff paths remain supported.

Re-init with `state.json` prints the run directory; no input replacement, preparation, or advance.
Use `status` and `resume` through human gates. Re-init refuses configuration,
typed overrides, live probes, and `--accept-config`; use stage preparation. Without `state.json`,
retry even if input copies exist.

For a different run ID, init prints this repository's newest unfinished run and exact `resume`
command, then exits before creation. Without `--run-id`, this check precedes input validation,
so `init` without inputs already reports an unfinished run. Completed runs do not block init. Use
`--new-run` only after the human chooses a separate session; it never resets an existing run.
