### Formatting failures: request re-emission, never override

When `parse_report.py` gates `stop` or `hitl` purely because of report format — prose after `- None`, a
missing required section, the unfilled `|` menu — and the substance looks clean, do not overrule the
parser with your own `advance`. Ask the still-open worker pane for exactly one contract-conforming
re-emission ("re-emit the report per the Worker Report Contract; fix the format, not the substance"),
record a `report.reformat_requested` event, re-parse, and gate on the new report. If the worker pane is
already gone or the re-emitted report still fails, stop as HITL for the human. The orchestrator never
records `advance` while the latest parsed gate says otherwise.

The same re-emission path covers quality-only findings. When every entry under `## Findings` is
`Recommendation: ask-user` with `Scope: other`, `parse_report.py` still gates `stop` but reports
`quality_only_findings: true` and the reason `quality-only ask-user findings: request re-emission under
Recommendations`. Such a finding names no acceptance, regression, security, or data-safety concern, so it
is a recommendation filed in the wrong section. Ask the worker for one re-emission that moves those
entries to `## Recommendations` unchanged, record `report.reformat_requested`, and gate on the new report.
A report mixing them with any other finding is a plain `stop`.

The same re-emission path covers stage-ownership findings. The chain runs on a deliberately uncommitted
working tree. After `complete`, the orchestrator commits in commit mode and the human commits otherwise;
push, PR, and CI stay with the human. A finding whose sole
claim is that the tree is uncommitted or that a commit, push, PR, or CI run is missing reports a deferral
as if it were a defect. Ask the worker for one re-emission without that finding, record
`report.reformat_requested`, and gate on the new report; substantive findings in the same report keep
their normal effect.

