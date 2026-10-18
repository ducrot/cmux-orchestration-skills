## Follow-up Pass

A follow-up pass applies small accepted triage items to the still uncommitted issue instead of queueing a
full ticket for them. It runs inside the same run, after triage and before `run_state.py complete`, and
needs no approval beyond the triage verdict: the orchestrator prepares, launches, gates, and tests it on
its own.

Entry conditions — all four, otherwise the item becomes a new issue or stays deferred:

- the change is behavior-preserving;
- it stays inside the files of the issue diff;
- the proposal is concrete: described precisely or available as an artifact;
- no acceptance criterion changes.

Procedure:

1. In autonomous mode `publish-triage` records the verdicts and writes `followup-items.md`, one bullet
   per accepted eligible item with ID, source, supersedes, files, verbatim item text and triage reason.
   In human mode record the human verdicts and write the same approved item list.
2. In autonomous mode record the triage gate as `advance` with `--next-stage implement`; the final test
   gate already moved the run to triage. In human mode the final test gate moves to implement instead.
3. Prepare `implement` with the next pass number and `--followup`, then render with `--followup-file`. Anchor the follow-up
   implement pane to the triage pane (the test pane in human mode). The variant replaces the implement
   contract: apply exactly the listed items, prove behavior preservation with cite-before, run-after
   instead of a failing regression test, and leave existing tests unedited. Cite the most recent stage
   with green evidence for the same starting tree (normally test), one log per applicable command;
   otherwise, run your own before-run of the full applicable suite through `run_check.py` before editing. Always produce an
   own after-run of every applicable command through `run_check.py`, even for a no-op.
4. Gate the implement report as usual, including diff inspection against the item list, then run the
   final test for the same pass with the follow-up report and the item list as context files.
5. In autonomous mode, after the follow-up test report parses `advance` and before that gate event is recorded,
   run `python3 scripts/collect_recommendations.py --run-dir <run-dir> --pass 2`. With new items record
   the test gate `advance --next-stage triage`, then run triage pass 2 using the launch, anchoring,
   snapshot comparison, parse, and publish steps in Recommendations Triage. Otherwise record
   `advance` with no next stage and complete. After the triage-2 gate, complete the run; triage-2 never
   starts another follow-up pass. In human mode, relay new recommendations for human triage as described in `recommendations-triage.md`;
   no further follow-up pass is available. The commit proposal covers the issue and the follow-up together.

Limits: one follow-up pass per issue, all accepted items bundled; no simplify or review stage in it;
recommendations from its reports go to triage but never start another pass. An item the worker lists
under `## Not Applied` is not retried. These items do not trigger `triage-2`. For each such item,
append a factual line to `decisions.md` identifying the run and triage-1 item:
`accepted in triage-1, not applied in the follow-up pass: <reason verbatim> — OPEN`.
For example: `- <issue> triage-1 R<n> (<source>): <title> — accepted in triage-1, not applied in the follow-up pass: <reason verbatim> — OPEN. [run <run-id>]`
List these open items in the final summary; do not turn them into new recommendations or retry them.
Findings from the follow-up implement or test
report gate `hitl` like findings after review changes. Select a lighter implement profile for the pass
with the typed `prepare` overrides when the default is oversized for the items.

`prepare --followup` is valid only for implement passes after the first and records the choice in the immutable stage
snapshot and `stage.prepared` event. The renderer requires `--followup-file` exactly when that
marker is set. A corrective pass after a HITL is a regular implement pass: prepare it without
`--followup`, render without `--followup-file`, and require regression proof and green own
after-evidence, with no before-evidence duty. Only a follow-up implement pass owes before-evidence.
