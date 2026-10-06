Use these exact event types. New ad-hoc types must be dot-namespaced, lower-case, and used
consistently within a run.

| Event                                                  | When                                                                                                                               |
|--------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `run.init`, `run.completed`                            | Written by `run_state.py init` / `complete`                                                                                        |
| `run.briefing`                                         | Briefing shown to the human, pill text in data; written by `run_briefing.py show`                                                 |
| `run.recap`                                            | Recap shown to the human, outcome and pill in data; written by `run_briefing.py recap-show`                                       |
| `launch_wave.prepared`                                 | All four lanes resolved, preflighted, audited, and frozen before pane creation                                                     |
| `pane.launched`, `pane.labeled`, `pane.closed`         | Lane pane lifecycle with round; written by `open-round`, `launch`, or `close`                                                                     |
| `pane.orphans_detected`                                | Lane tooling left panes behind; record IDs, then close them                                                                        |
| `worker.starting`                                    | Launch about to be sent; invalidates earlier readiness, includes round, launch_id, prompt_path, marker_path, and start_time_ns |
| `worker.observed`, `worker.ready`, `worker.startup_status`, `worker.readiness_consumed`, `worker.dialog_response` | Readiness events: exception-path and follow-up only; observe/assess/respond before gated input |
| `worker.launch_sent`                                   | Lane agent launch command with attached round prompt; written by `pane_ctl.py start-agent`                                                       |
| `worker.prompt_sent`                                   | Text sent and submitted; written by `pane_ctl.py deliver`                                                                          |
| `worker.started`                                       | Current launch confirmed by fresh marker or report (`evidence: "marker"|"report"`), or exception-path `"screen"`; data binds lane, round, surface_id, launch_id, marker_path                   |
| `worker.waiting`                                       | Written by the armed round watcher only: heartbeats plus its final outcome                                                         |
| `worker.finished`                                      | Round report captured; data carries `{lane, round, surface_id}`                                                                    |
| `worker.launch_blocked`                                | A lane launch was denied (permissions, environment)                                                                                |
| `gate`                                                 | Only via `run_state.py gate`                                                                                                       |
| `tree.snapshot`                                        | Only via `run_state.py snapshot`                                                                                                   |
| `report.reformat_requested`                            | Re-emission asked for a format-only parse failure                                                                                  |
| `report.integrity`, `report.integrity.retracted`       | Report-claim accusation and its retraction                                                                                         |
| `plan.drift`, `plan.drift.resolved`                    | Task-premise drift recorded / resolved; data carries `class` (small-factual, load-bearing) and `resolved_by` (orchestrator, human) |
| `hitl.resolved`, `decision.human`                      | Human decisions and HITL resolutions                                                                                               |
| `grill.question`                                       | Round question recorded before delivery, one per question; data `{round, id, question, depends_on}`                               |
| `grill.question_deferred`                              | Question dropped from a round's synthesis after a failed re-emission; data `{round, id, lanes, reason}`                             |
| `grill.synthesis`                                      | One question synthesized; data `{round, id, confidence}`                                                                           |
| `grill.done`                                           | Griller ends the loop (empty frontier or round budget spent); data `{round, reason}`                                                |
| `grill.assumptions`                                    | Defined assumptions distilled; data `{count}`                                                                                      |
| `grill.assumptions_triaged`                            | Per-assumption human review outcome                                                                                                |
| `grill.open_decisions`                                 | Open decisions distilled at finalize; data `{count}`                                                                               |
| `grill.decision_recorded`                              | One walkthrough answer; written by `run_state.py decision`                                                                         |
| `commit.proposed`                                      | Artifact commit proposal handed to the human after `complete`                                                                      |
| `orchestrator.halted`, `orchestrator.unverified_input` | Orchestrator-side anomalies                                                                                                        |

