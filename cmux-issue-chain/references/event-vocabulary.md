Use these exact event types so runs stay comparable and greppable. New ad-hoc types are allowed, but they
must be dot-namespaced, lower-case, and used consistently within a run — do not spell the same event two
ways (`plan.drift.resolved`, never also `plan.drift_resolved`).

| Event                                                    | When                                                                                                                                             |
|----------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| `run.init`, `run.completed`                              | Written by `run_state.py init` / `complete`                                                                                                      |
| `run.briefing`                                           | Briefing shown to the human, pill text in data; written by `run_briefing.py show`                                                               |
| `run.recap`                                              | Recap shown to the human, outcome and pill in data; written by `run_briefing.py recap-show`                                                     |
| `run.invocation`                                         | Initial prompt adopted on re-init by a run that had none; written by `run_state.py init`                                                        |
| `stage.prepared`                                         | Passed stage snapshot published after full configuration resolution and local preflight; written by `run_state.py init` / `prepare`              |
| `pane.launched`, `pane.labeled`, `pane.closed`           | Worker pane lifecycle; written by `pane_ctl.py launch` / `close`                                                                                 |
| `pane.orphans_detected`                                  | A worker's tooling left panes behind; record IDs, then close them                                                                                |
| `worker.launch_sent`                                     | Worker launch command with assignment attached; written by `pane_ctl.py start-agent`                                                                         |
| `worker.observed`, `worker.ready`, `worker.startup_status`, `worker.dialog_response`, `worker.readiness_consumed`, `worker.delivery_attempted` | Readiness events for exception-path and follow-up only |
| `worker.prompt_sent`                                     | Text sent and submitted; written by `pane_ctl.py deliver`                                                                                        |
| `worker.started`                                         | Assignment start confirmed by the watcher from marker or report, or by the orchestrator on the exception path                                         |
| `worker.waiting`                                         | Watcher heartbeat while the report is pending; written by `await_report.py` while armed                                                          |
| `worker.finished`                                        | Report captured; data carries `{role, pass, surface_id, runtime}`                                                                                |
| `worker.launch_blocked`                                  | A worker launch was denied (permissions, environment)                                                                                            |
| `gate`                                                   | Only via `run_state.py gate`                                                                                                                     |
| `tree.snapshot`                                          | Only via `run_state.py snapshot`                                                                                                                 |
| `report.reformat_requested`                              | Re-emission asked for a format-only parse failure                                                                                                |
| `report.integrity`, `report.integrity.retracted`         | Report-claim accusation and its explicit retraction                                                                                              |
| `plan.drift`, `plan.drift.resolved`                      | Drift recorded / resolved per the Replanning rules                                                                                               |
| `hitl.resolved`, `decision.human`                        | Human decisions and HITL resolutions                                                                                                             |
| `commit.proposed`                                        | Commit proposal (file list + message draft) handed to the human after `complete`                                                                 |
| `recommendations.triaged`                                | Per-item verdict, reason, supersedes, consequence, issue and authority (`human` or `triage-worker`)                                                                        |
| `triage.collected` | Immutable recommendations list: pass, item count, scanned reports, items path and SHA-256 (null for zero items) |
| `triage.published` | Counts per verdict, created issues, follow-up IDs, for-the-human IDs and follow-up file path |
| `artifact.written`, `hitl.verified`, `hitl.counterproof` | HITL-issue assistance (see HITL Issues)                                                                                                          |
| `orchestrator.verified`                                  | Orchestrator-run verification: quick-check test rerun before the simplify gate, or diff inspection at a code-changing gate (commands + outcomes) |
| `orchestrator.halted`, `orchestrator.unverified_input`   | Orchestrator-side anomalies                                                                                                                      |

