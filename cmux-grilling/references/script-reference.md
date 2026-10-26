Validate both halves of the artifact pair at finalize, record one outcome during the walkthrough, and
check for an unfinished walkthrough at session start (see Resuming an unfinished walkthrough):

```bash
python3 scripts/run_state.py validate-artifact --artifact <artifact.json>
python3 scripts/run_state.py decision --run-dir <run-dir> --artifact <artifact.json> --id D1 --status decided --decision "Ab 12 Jahren"
python3 scripts/run_state.py assumption-review --run-dir <run-dir> --artifact <artifact.json> --index 1 --outcome corrected --corrected-text "Neue Annahme" --reason "Neue Fakten"
python3 scripts/run_state.py pending-decisions
```

`assumption-review` records one one-based assumption index: `--outcome confirmed`, `corrected`
(requires `--corrected-text` and `--reason`), or `discarded` (requires `--reason`). It writes
`index`, `outcome`, `corrected_text`, `reason`, and `reviewed_at` into `assumption_review` and
emits exactly one `grill.assumptions_triaged` event carrying the same fields plus `artifact`.
Unknown indexes, missing correction/reason, and `--corrected-text` with another outcome are refused
without changing JSON or events.
The original assumption text stays intact. Transcribe the printed numbered line with its
`[Prüfung: …]` marker into Markdown. Until then `validate-artifact` reports that assumption's
disagreement; validate after transcription and before the commit proposal and recap, also on resume.
Review is advisory and non-blocking; unreviewed entries remain valid.

For interrupted transcription, recover lines from recorded outcomes without a second recording
or changing review time. From the skill directory, render the saved records with the same renderer:

```bash
python3 - <artifact.json> <<'PY'
import json, sys
sys.path.insert(0, "scripts")
from artifact_pair import render_assumption
with open(sys.argv[1], encoding="utf-8") as source:
    data = json.load(source)
for text, review in zip(data["assumptions"], data["assumption_review"]):
    print(render_assumption(text, review))
PY
```

Replace the assumption lines and validate both halves before presenting them as synchronized.

`validate-artifact` preserves decision checks and, for new pairs, validates `assumption_review`
(one-based indexes in assumption order, known outcome, correction/reason requirements and review
time) and `open_facts` (unique id, question, why_needed, open/answered status, answer/time).
It reads `markdownPath` from the current repository root (or the JSON's sibling `.md` when omitted)
and compares numbered lines under `## Definierte Annahmen` verbatim, including the German JSON
`[Prüfung: {"Ergebnis":"ungeprüft","Korrektur":"","Grund":""}]` suffix. It also compares the
`- {…}` JSON entries under `## Offene Fakten` in order. See Finalize for the full field contract.
Missing sections, files, entries and mismatches fail with entry diagnostics; matching pairs,
including all-unreviewed or empty lists, pass and print review/fact counts. Both extension lists
are required together. Legacy artifacts without either list keep decision-only validation and
output (`open_decisions=N valid`), without reading Markdown or reporting review/fact counts.

Render self-contained round prompts once per lane per round, with one
`--question` (or `--question-file`) per frontier question, numbered `Q1..Qn` in order:

```bash
python3 scripts/render_prompt.py round --run-dir .scratch/orchestrator/runs/<run-id> --lane web --round 1 --question "Which HTTP client does the frontend use?" --question "Which API base URL does it use?"
```

Await a round's reports. One watcher per round, armed through background Bash or Monitor with re-arm (see Lane Wait
Policy); exits 0 = all reports, 7 = pending lane's pane dead,
8 = round deadline, 9 = round not started. Health checks are
scoped to the run's pinned `workspace_id` from `state.json`; there is no env fallback:

```bash
python3 scripts/await_reports.py --run-dir .scratch/orchestrator/runs/<run-id> --round 1 --questions 2 --lane-surface codebase=<UUID> --lane-surface codebase2=<UUID> --lane-surface docs=<UUID> --lane-surface web=<UUID>
```

Parse lane reports. `--questions <n>` demands blocks `Q1..Qn`. The exit code carries the most severe
question gate, `--json` the gate of every question; a missing report is `pending` (exit 6):

```bash
python3 scripts/parse_research_report.py .scratch/orchestrator/runs/<run-id>/reports/round-1-web.md --questions 2 --json
```

Record events, snapshots, gates; close the run. An unreadable or vanished untracked path fails the snapshot
with a diagnostic naming it and records no event; restore access or remove the path and retry. Git only
warns about an unreadable untracked directory, so its contents stay invisible rather than failing capture.
Then:

```bash
python3 scripts/run_state.py event --run-dir <run-dir> --type grill.question --message "round 1 Q1" --data '{"round":1,"id":"Q1","question":"...","depends_on":[]}'
python3 scripts/run_state.py snapshot --run-dir <run-dir> --label "reports-captured round-1"
python3 scripts/run_state.py gate --run-dir <run-dir> --stage round-1-web --decision advance --reason "well-formed ANSWERED, sources cited"
python3 scripts/run_state.py complete --run-dir <run-dir> --markdown <output-dir>/<slug>.md --json <output-dir>/<slug>.json --message "grilling complete" --data '{"stop_reason":"griller-done"}'
```

Control lane panes with `pane_ctl.py` (verbs and rules in CMUX Control): `workspace` prints
the pinned id, `cmux` is the generic `--workspace` injector, `open-round`/`start-round` own normal round lifecycle;
`launch`/`start-agent`/`close` remain for recovery and final close.

Run the regression tests after touching `parse_research_report.py`, `await_reports.py`,
`pane_ctl.py`, `run_state.py`, `launch_wave.py`, or `agents_config.py`:

```bash
python3 scripts/test_parse_research_report.py
python3 scripts/test_await_reports.py
python3 scripts/test_pane_ctl.py
python3 scripts/test_worker_readiness.py
python3 scripts/test_run_state.py
python3 scripts/test_agents_config.py
python3 scripts/test_launch_wave.py
```

