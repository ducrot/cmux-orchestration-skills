### Formatting failures: request re-emission, never override

When `parse_report.py` gates `stop` or `hitl` purely because of report format — prose after `- None`, a
missing required section, the unfilled `|` menu — and the substance looks clean, do not overrule the
parser with your own `advance`. Request exactly one contract-conforming
re-emission ("re-emit the report per the Worker Report Contract; fix the format, not the substance")
using the waited procedure below. If the worker pane is
already gone or the re-emitted report still fails, stop as HITL for the human. The orchestrator never
records `advance` while the latest parsed gate says otherwise.

The same re-emission path covers quality-only findings. When every entry under `## Findings` is
`Recommendation: ask-user` with `Scope: other`, `parse_report.py` still gates `stop` but reports
`quality_only_findings: true` and the reason `quality-only ask-user findings: request re-emission under
Recommendations`. Such a finding names no acceptance, regression, security, or data-safety concern, so it
is a recommendation filed in the wrong section. Ask the worker for one re-emission that moves those
entries to `## Recommendations` unchanged, using the same waited procedure below.
A report mixing them with any other finding is a plain `stop`.

The same re-emission path covers stage-ownership findings. The chain runs on a deliberately uncommitted
working tree. After `complete`, the orchestrator commits in commit mode and the human commits otherwise;
push, PR, and CI stay with the human. A finding whose sole
claim is that the tree is uncommitted or that a commit, push, PR, or CI run is missing reports a deferral
as if it were a defect. Request one re-emission without that finding using the same waited procedure;
substantive findings in the same report keep
their normal effect.

### Wait for the re-emission

Record the request **before sending** the re-emission prompt, so an immediate rewrite cannot replace
the baseline before it is recorded:

```bash
python3 scripts/run_state.py event --run-dir <run-dir> --type report.reformat_requested \
  --message "report format correction requested" --data '{"role":"review","pass":1}'
```

Use the failing role and pass. The command reads that handoff file and adds `report_sha256`, the
SHA-256 of its current non-empty bytes; do not supply a digest yourself. A missing or empty report
cannot establish a baseline. If recording fails, stop as HITL rather than sending an untracked request.
Then send the correction prompt to the still-open worker and arm the watcher immediately:

```bash
python3 scripts/await_report.py --run-dir <run-dir> --role review --pass 1 --surface <surface-id>
```

Use the normal background Bash or Monitor procedure, with the same role, pass and surface. The old
digest keeps the watcher waiting. Only different non-empty bytes that settle across two consecutive
polls return exit 0. Parse and gate on the report the watcher returns; exit 0 itself is not `advance`.
Exits 7, 8 and 9 retain their normal recovery paths.

The request opens a fresh wait window on first arm, without spending the one deadline extension or
resuming the exceeded deadline. Re-arming resumes this new window; it never renews it. A second request
for the same role/pass is refused and requires HITL, rather than opening a third window. If the
re-emitted report still fails, stop as HITL. A legacy request without a recorded digest also requires HITL.

When re-arming a persisted clock that has already expired, an eligible report already on disk gets
exactly one settling poll: unchanged bytes return 0; missing or changing bytes return 8. This does not
renew the deadline or accept the rejected baseline digest.
