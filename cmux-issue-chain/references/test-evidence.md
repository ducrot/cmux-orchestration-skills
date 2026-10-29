# Test selection and evidence policy

This is the authoritative policy for test selection, report labels, and evidence validation.
The rendered worker prompt carries the applicable duties into each harness.

## Test selection

Select tests by your own analysis of the diff. Canonical commands in the tracker are orientation
and fallback for regular implement, review, simplify, and marked follow-up implement passes. Apply these four guardrails:

1. Always run tests of changed modules and the ticket's regression test.
2. For shared or imported code, also run tests of dependent modules.
3. Run affected repository protection tests, such as drift or contract tests.
4. When uncertain, run the next larger unit.

Regular implement proves that a regression fails without the change and executes the changed path end-to-end.
Run checks one after another, never in parallel, through `run_check.py` in your own stage artifact
directory. Freely chosen commands are allowed.

## Report labels and paths

Under `## Tests / Checks`, give every relied-upon own run's command, outcome, and log path using a
separate `- evidence: <path>` bullet. Copy the path from the wrapper's
`run_check: log written to <path>` stderr line unchanged.
Each `evidence:` or `cited:` bullet must contain only the path after the label, with no trailing
annotations; put the command and outcome on a separate bullet.
The checker accepts repository-relative or absolute wrapper paths and run-directory-relative paths;
it normalizes them before enforcing the allowed stage artifact boundary, including symlink targets.
Paths in the evidence event identify the resolved log; run-relative report paths remain supported.
For example:

```markdown
- `python3 -m unittest example`: passed
- evidence: .scratch/orchestrator/runs/<run-id>/artifacts/implement-1/check-<hash>.log
- selection: Changed parser; module, regression and dependent contract tests cover its callers.
```

All test-selecting reports must include exactly one `- selection:` bullet naming affected areas,
applied guardrails, and why the selection is sufficient. This is a prompt duty for triage and human
review; neither the evidence check nor the report parser gate-checks this explanation.

Use a separate `- cited: <path>` bullet for an earlier log only when the role allows citation.
Copy the reported path unchanged; the same normalization applies. Citations must resolve inside a
stage directory under the run's artifacts. Regular implement and final test do not allow citations.

## Evidence validation

Regular implement requires at least one named green own run on the capture tree. Only logs named
with `evidence:` are checked; each must resolve inside the worker's own stage directory. The checker
reads the command from the wrapper header, validates repository, HEAD and before/after tree
fingerprints against the capture snapshot, and reports `pass`, `missing`, `red`, or `stale`.
A named passing repeat for the same command supersedes named red or stale attempts. Missing or
unreadable named logs fail closed. An empty selection of named runs fails. Unlisted own logs,
including red attempts, do not block and are recorded separately in `unlisted_logs`; `checked_logs`
records each named readable run, its verdict and tree identity. This preserves evidence for comparing
an earlier green stage with a later red final test on the same tree.

A passing check writes the existing test-evidence event used by `run_state.py gate` to advance.
Combined report/evidence gates retain report severity: blocked, hitl, stop, advance.

## Review citations

Review selects the affected tests using the four guardrails above and reports its selection.
Only an unchanged review, with identical launch and capture HEAD and fingerprint, may cite the
previous stage's green logs for the same tree, including freely chosen commands, with `cited:`.
A changed review must name its own green capture-tree runs with `evidence:`; citations are rejected
even when own evidence passes. Review checks only named own runs and citations, using the same
validation and repeat rules as regular implement. At least one named run is required. Cited logs
must resolve inside a stage artifact directory under the run; their command, resolved path,
repository, HEAD and fingerprints are recorded in `checked_logs`. Unlisted own logs are recorded
separately and do not block.

## Simplify and marked follow-up implement

Both roles select commands using the four guardrails above and report `evidence:` and `selection:`.
For every chosen command, obtain green before-evidence on the launch tree before the first edit:
cite a matching green log with `cited:`, or run the command yourself and name its log with `evidence:`.
Then name a distinct green own after-run of the same command on the capture tree, even for a no-op.
This is the cite-before, run-after rule: selection is free, but both sides are mandatory for every
chosen command. The checker derives commands from named own runs and citations, never from the
canonical list or unlisted logs. An empty selection, missing side, unreadable log, red or stale
evidence fails; one log cannot serve as both before and after. A cited command takes its
before-evidence only from citations, even when an own before-run is green. Unlisted own logs remain
available in `unlisted_logs` and cannot satisfy either side.

In a follow-up, citable test evidence covers only canonical commands from the most recent stage
with green evidence for the same starting tree (normally test). Targeted commands need your own
before-runs before editing. This is a worker selection duty; the checker accepts freely chosen
commands from cited logs and enforces their launch-tree identity.

## Final test and triage

The final test remains unchanged: run the full canonical suite byte-for-byte through own wrapper
runs, one log per command, without citations. A freely chosen command cannot replace a canonical
command. The check requires every canonical command individually. Triage has no suite duty and is
evidence-exempt. An empty or placeholder canonical entry invalidates the entire declaration.
