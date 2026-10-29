# Test selection and evidence policy

This is the authoritative policy for test selection, report labels, and evidence validation.
The rendered worker prompt carries the applicable duties into each harness.

## Regular implement

Select tests by your own analysis of the diff. Canonical commands in the tracker are orientation
and fallback, rather than a mandatory suite for regular implement passes. Apply these four guardrails:

1. Always run tests of changed modules and the ticket's regression test.
2. For shared or imported code, also run tests of dependent modules.
3. Run affected repository protection tests, such as drift or contract tests.
4. When uncertain, run the next larger unit.

Prove that a regression fails without the change and execute the changed path end-to-end.
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

Regular implement reports must include exactly one `- selection:` bullet naming affected areas,
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

## Other roles

Simplify and marked follow-up implement still use every canonical command byte-for-byte, with
matching green before-evidence (own or cited) and distinct own after-runs, even for a no-op.
An unchanged review may cite matching green canonical evidence; a review that changes the tree
must run its own canonical after-suite. These stages continue checking the declared commands.

The final test remains unchanged: run the full canonical suite byte-for-byte through own wrapper
runs, one log per command, without citations. A freely chosen command cannot replace a canonical
command. The check requires every canonical command individually. Triage has no suite duty and is
evidence-exempt. An empty or placeholder canonical entry invalidates the entire declaration.
