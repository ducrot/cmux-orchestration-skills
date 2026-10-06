### Resuming after a confirming HITL

A HITL decision that confirms the tree as the review left it needs no second review pass. When the human
decision authorizes no product edit, take a fresh `run_state.py snapshot` and compare it with
`report-captured review-<pass>`: identical tree fingerprint, `head`, `staged_paths`, and
`staged_diff_sha256` mean nothing is left to review. Record `decision.human` and `hitl.resolved`, append
the decision to `decisions.md`, record the review gate as `advance` with a reason naming the human
resolution, and continue with the final test. This is the only case in which the orchestrator records
`advance` over a parsed `stop`: the human resolved the gate, the orchestrator did not overrule it.

Any authorized product edit, or any snapshot difference, takes the existing path instead: a scoped
follow-up worker pass for the approved items, then the final test.

