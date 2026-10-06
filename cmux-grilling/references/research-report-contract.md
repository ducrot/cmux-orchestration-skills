## Research Report Contract

Ask every lane to finish each round with one `## Q<n>` block per round question, numbered as in
the round prompt (`Q1..Qn`, also for a round of a single question). Inside a block the sections are
`###` headings. `### Result`, `### Answer`, `### Sources`, `### Method`, `### Blockers`, and
`### Plan Drift` are required: absent or empty, they make the question malformed and its gate
`hitl`. Under `### Result`, emit exactly one of `ANSWERED`, `NO ANSWER`, `BLOCKER` — a literal
`ANSWERED | NO ANSWER | BLOCKER` line is an unfilled template and is rejected. A missing, duplicate,
or unexpected question block is malformed too. Each question is gated independently; the parser
takes the expected count as the required `--questions <n>`, so a report that leaves out a
question never passes as clean.

```markdown
## Q1
### Result
ANSWERED

### Answer
The finding in prose. For NO ANSWER: why this lane cannot answer the question.

### Sources
- relative/repo/path or URL

### Method
- what was searched, read, or run: outcome

### Blockers
- None

### Plan Drift
- None

### Notes
- Optional: caveats, confidence hints, context. Never load-bearing evidence.

## Q2
### Result
...
```

The bare-`None` rule: in `### Sources`, `### Blockers`, and `### Plan Drift`, an empty section
is exactly the line `- None` — no prose on or after that line. Explanations belong in
`### Answer` or `### Notes`, which the gate does not parse for content. Question blocks end at the
next `##` heading, so a trailing `## Notes` never joins a section.

Research-specific gate requirements:

- `ANSWERED` needs at least one real source; without one the gate is `stop`.
- `NO ANSWER` needs an explanation under `### Answer`; `### Sources` may be `- None`.
- `### Method` must be substantive in every report, including `NO ANSWER` — what was searched
  and found nothing is evidence too.

Lanes may write only their round marker, draft path, and report handoff path
named in the round prompt. `init` creates `drafts/` alongside `prompts/`, `reports/`, and
`synthesis/`. Rendered prompts name `<run-dir>/drafts/round-<N>-<lane>.md` and instruct lanes
to self-validate that exact file with `parse_research_report.py` before writing the handoff
file. `render_prompt.py round --draft-path <path>` overrides the draft location; it must
resolve strictly inside the run-local `drafts/` directory (never run state, prompts,
synthesis, or any lane's report) and differ from the report handoff path.

Run layout: `state.json` records `workflow: grilling`, `layout_version: 1`, `max_rounds`, and `slug` (at most 30
characters; override with `init --slug <value>` using lowercase words separated by hyphens).
`complete` requires `--markdown` and `--json` paths resolving under the recorded `output_dir` and
records them in `deliverables`. Artifact JSON and `pending-decisions` discovery remain unchanged.
Before continuing an existing run, inspect it with `run_state.py status --run-dir <run-dir>`.
An unsupported legacy layout — including a run whose state has `max_questions` instead of
`max_rounds` — must be restarted; never infer its identity or continue it.
