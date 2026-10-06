## Confirm author/reviewer model diversity

No role is pinned to a harness, so independent review rests on this gate alone. Before preparing any
stage, planning compares the resolved `planning.spec` or `planning.tickets` profile with the resolved
`planning.reviewer`. A reviewer stage is compared against the author it is about to check, so a
configuration change or typed override between author and review is caught instead of launched. When
both resolve to the same harness and model, preparation stops before a launchable snapshot exists and
prints a warning naming both roles, profile names, harnesses, and models. Present that warning and ask
the confirmation question in the user's language. Never substitute or fall back to another profile
automatically. One decision covers one harness-and-model combination: an author stage and the reviewer
stage that checks it share it, so a confirmed combination is never asked twice.
This expected gate is not a crash: every public command that reaches the blocked preparation
prints structured JSON with `prepared: null`, the warning, and the exact confirmation command, exits
with exit code 2, and writes no traceback to stderr. A diverse or already-confirmed resolution remains
successful and exits 0 with its launchable snapshot and no extra warning.

Exit code 2 is not unique to the diversity gate: argument-usage errors and other precondition
refusals also use it. Wrappers must inspect stdout and stderr, identifying a gated preparation by
`prepared: null` and `diversity_warning` in its structured stdout response, rather than treating the
exit code alone as a request for diversity confirmation.

A non-zero preparation result does not roll back an earlier state transition. For example,
`approval --decision approve` can persist spec approval and move to `tickets` before ticket author
preparation exits 2. Revision, revalidation, and relaunch commands can likewise persist progress before
reaching the gate. A wrapper using `set -e` must handle this outcome explicitly: read `status` and
`context` for the same run, then follow the recommended next command. Do not blindly retry the original
transition command; its approval or revision may already be recorded and its original stage guard may
no longer apply.

If the human knowingly accepts same-harness-and-model operation, translate the recorded decision and
their human-authored reason into English and run the exact command reported by `status`:

```bash
python3 scripts/planning_state.py diversity-confirmation --run-dir <run-dir> \
  --decision confirm --reason <human-reason-in-English>
```

That decision is persisted in state and events and prepares the waiting author stage. It covers later
passes and the other author stage only while the resolved author/reviewer harness-and-model combination
is unchanged. A changed combination invalidates the decision; another collision asks again. Profile
names or effort may change without invalidation when the resolved harnesses and models remain the same.

Refusal is also explicit and reasoned:

```bash
python3 scripts/planning_state.py diversity-confirmation --run-dir <run-dir> \
  --decision refuse --reason <human-reason-in-English>
```

Refusal leaves the run at its current `spec` or `tickets` stage with no launchable snapshot. Follow the
printed guidance naming the shared configuration file and the exact
`workflows.planning.spec` or `workflows.planning.tickets` assignment to change. Refusal never prepares
a snapshot even when the resolved combination changed meanwhile and is now diverse: the refusal and its
reason are recorded, the guidance is printed, and launching that stage takes a later explicit `prepare`.
A genuinely diverse resolution prepares normally with no warning or extra prompt.

