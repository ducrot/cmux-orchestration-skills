The status JSON reports the run and repository, task/source digest, copied and normalized grilling
identities, revalidation progress, exact stage/mode/pass, prepared snapshot validity, live or last-known
pane, pending report, latest review verdict and candidate digest, both digest-bound approvals, staging
and publication phase, consistency errors, and one recommended next command. Its classifications
distinguish awaiting or interrupted grilling revalidation, spec authoring/review, ticket authoring/review,
pending model-diversity confirmation, pending report, both approval boundaries, requested revision,
review-blocked, HITL, completed, and inconsistent state. A `pending-diversity-confirmation`
classification includes the warning, but its decision status controls the recovery guidance. A
`pending` decision means awaiting confirmation and recommends the exact
`diversity-confirmation --decision confirm` command. A `refused` decision is a recorded refusal and
recommends human inspection and configuration recovery through `context`; it never recommends
confirmation. The short action text refers to a diverse profile in the shared configuration.
For the exact file and assignment, inspect `shared_configuration_path` and `assignment_path` in the
`diversity_confirmation` payload returned by `status`; it names the role of the stage that is
blocked (`workflows.planning.spec`, `workflows.planning.tickets`, or `workflows.planning.reviewer`).
Initialization persists a validated `input` checkpoint before activating the first
stage, so an interruption there reports `input-validation` and resumes that same prepared identity. A
pre-run input or configuration failure has no run state and remains an initialization error rather than
being inferred as a worker stage.

After context compaction, run `context` and status before acting. The context manifest enumerates the
persisted task, copied grilling pair, normalized handoff, latest author and review artifacts, approved
spec, latest ticket proposal, state, events, immutable stage and tree snapshots, reports, and digests.
Read the applicable artifacts and human diff (`approval-view` or `ticket-approval-view`) plus reported
pane health; do not reconstruct progress from conversation memory.

Follow the status command exactly for active work:

- A live pane whose deterministic prompt was sent and whose report is pending is rejoined with the
  armed `await_report.py` command. Never launch a duplicate worker.
- A normally launched pane, even before start confirmation, uses the armed watcher. An unanswered
  exit 9 or assessed unresolved startup dialog recommends `observe` and the exception procedure.
  A recorded dialog response or authorized re-delivery recommends the watcher again with
  `--extension 0`. A stage with no pane uses `launch`; a pane without launch input uses `start-agent`.
  Interrupted launch or delivery input stops at HITL with `read-screen`, never blind input.
- A non-empty handoff is gated or inspected and never overwritten as an uncertain retry.
- A first live-pane deadline may receive the run's one human-reasoned `resume --decision extend`
  watcher extension. Pane death, expiry of that extension, snapshot tampering, an integrity violation,
  an unknown state shape, or an uncertain handoff stops at HITL. None automatically advances or
  relaunches.
- At either approval boundary, rerun the corresponding view. It reopens the same reviewed,
  digest-bound candidate and never invokes a worker.

An explicit human decision may replace a dead or expired worker with one fresh numbered pass:

```bash
python3 scripts/planning_state.py resume --run-dir <run-dir> \
  --decision relaunch --reason <human-authored-reason>
```

For relaunch and revise, `--reason` quotes the human's answer verbatim without orchestrator additions.
Reviewer findings arrive only as the attached review report. Both relaunch and revise attach the latest
applicable review report by its finalized manifest identity and render it inline for the next author.
`approval --decision revise` attaches the latest finalized spec review; `ticket-approval --decision revise`
attaches the latest finalized tickets review, including when `--scope spec` returns to a spec author.
A revise without a finalized review keeps the existing reason-only feedback. A relaunch clears earlier
revision feedback only when a later pass already acted on it. Relaunching a dead revised author before
it finalizes a handoff keeps the unconsumed feedback and attached review in the new recovery context.

The relaunch recovery prompt includes the reason plus prior candidates, reports, reviews, and feedback
only by their finalized manifest identities; failed panes, snapshots, events, and handoffs remain in history.
Unexpected files are listed as audit information and are never attached implicitly. A dead author gets
a new author pass. A dead reviewer gets a new reviewer pass over the unchanged author identity. A
blocked review routes back to an author and cannot be relabeled as another reviewer pass. If ticket
review found an approved-spec defect, use `ticket-approval --decision revise --scope spec` so the full
spec author/review/approval sequence repeats.

