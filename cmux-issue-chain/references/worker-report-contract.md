## Worker Report Contract

Ask every worker to finish with this report shape. `## Result`, `## Blockers`, and `## Plan Drift` are
required: absent or empty, they make the report malformed and the gate returns `hitl`. An omitted section
never reads as `None`. Under `## Result`, emit exactly one of `NO FINDINGS`, `FINDINGS`, `BLOCKER` — a
literal `NO FINDINGS | FINDINGS | BLOCKER` line is an unfilled template and is rejected.

```markdown
## Result
NO FINDINGS

## Tests / Checks
- `command`: outcome; evidence: artifacts/<role>-<pass>/check-<hash>.log

## Findings
- None

## Blockers
- None

## Plan Drift
- None

## Notes
- Optional: caveats, method notes, context. Never must-fix content.
```

For every own check, use `run_check.py --artifact-dir <own-artifact-dir> --command '<declared command>'`
and list the resulting evidence log under `## Tests / Checks`. Commands must match the applicable
tracker declaration byte-for-byte. Cite earlier logs only when the role permits citation, using a bullet
beginning with the literal `cited:` label and a path relative to the run directory, one citation per
applicable command:

```markdown
- cited: artifacts/<earlier-stage>/check-<hash>.log
```

Simplify and marked follow-up implement passes may cite before-evidence but always owe distinct own
after-runs. An unchanged review may cite; a changed review, regular implement, and test require own
after-evidence. The evidence check validates commands, repository, HEAD, and tree fingerprints rather
than accepting the report's claims alone.

Use exact section labels where possible. Treat missing tests/checks as a failed gate even if the report says `NO FINDINGS`.

The bare-`None` rule: in `## Findings`, `## Blockers`, and `## Plan Drift`, an empty section is exactly the
line `- None` — no prose on or after that line. `parse_report.py` reads anything else in these sections as a
real finding, blocker, or drift; a `- None. Everything fine because …` gates the chain as if a finding were
reported. Explanations belong in the optional `## Notes` section (or `## Recommendations` for review and
simplify workers), which the gate does not parse. Rendered prompts instruct workers to self-validate their
draft with `parse_report.py`, write the same validated body to the exact handoff path, validate that path,
and only then return the report in the console, so format failures die at the source instead of at the gate.

Plan drift is not a finding. `## Plan Drift` is its own section with its own gate (`hitl`); never mirror
drift into `## Findings` or change `## Result` because of it. A report whose only irregularity is drift
keeps `## Result` at `NO FINDINGS`, keeps `## Findings` empty (`- None`), and carries the drift exclusively
in `## Plan Drift` — the parser gates `hitl` from that section alone. `FINDINGS` above an empty
`## Findings` section is a contradiction, not a convention. The allowed `## Result` values stay
`NO FINDINGS`, `FINDINGS`, `BLOCKER`.

For review workers, require severity and recommendation triage. The first check line names the pass the
harness ran: `/code-review medium --fix` on Claude Code, `review pass (standards, spec, correctness)` elsewhere:

```markdown
## Result
NO FINDINGS

## Tests / Checks
- `/code-review medium --fix`: outcome
- `command`: outcome

## Change Summary
- None, or concise list of review fixes applied by the review pass.

## Findings
- None

## Recommendations
- None, or non-blocking nice-to-have/follow-up items.

## Blockers
- None

## Plan Drift
- None
```

`## Findings` follows the bare-`None` rule; remaining must-fix and ask-user findings after the self-fix pass replace
the `- None` line entirely, each with Severity (critical|high|medium|low), `Recommendation: must-fix` or
`Recommendation: ask-user` (ask-user when the finding challenges a documented issue decision, or an
earlier-stage decision for a non-quality reason — the reviewer must not fix those), Scope
(acceptance|regression|security|data-safety|other), file/line Evidence, and a concrete suggested fix.
`Scope: other` never carries `ask-user`; the parser flags a report whose findings are all of that shape for
re-emission. `## Change Summary` and `## Recommendations` are not gate-parsed and may carry prose;
quality-only counter-proposals to earlier-stage decisions go under `## Recommendations` marked
`Counter-proposal`.

For simplify/refactor workers, require the simplify pass to be reported as a check (`/simplify` on Claude
Code, `simplify pass` elsewhere):

```markdown
## Tests / Checks
- `/simplify`: outcome
- `command`: outcome

## Change Summary
- None, or concise list of behavior-preserving refactorings applied.

## Not Applied
- None

## Recommendations
- None, or refactorings that need a human decision.
```

Require one bullet per considered-but-not-applied refactoring and a one-line reason under
`## Not Applied`, or `- None`. This section is not gate-parsed by `parse_report.py`; it records
decisions for the review worker and the orchestrator's review-gate diff inspection. It holds only
refactorings the simplifier decided against itself; one that needs a human decision goes under
`## Recommendations` and reaches triage from there.

A follow-up implement report adds `## Change Summary` (changed files per approved item) and
`## Not Applied` (approved items that no longer fit the code, each with a one-line reason).

Runs use the shared `.scratch/orchestrator/runs/` root and default UTC id
`chain-issue-NNN-<YYYY-MM-DD>-<HHMM>`. Each `state.json` records `workflow: issue-chain`,
`layout_version: 1`, and `deliverables` with the tracker and issue paths. Inspect an existing run
read-only with `run_state.py status --run-dir <run-dir>`; an unsupported legacy layout must be
restarted before recovery, preparation, launch, or lifecycle writes.
