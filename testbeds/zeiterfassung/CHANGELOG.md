# Zeiterfassung changelog

## 1.0.0 — 2026-10-25

- Initial PHP/SQLite time-tracking project: customers, projects and rate periods,
  rounded time entries, CSV import, invoices with billed-entry protection, and
  Markdown/HTML export. The project deliberately retains its documented small
  weaknesses, including float invoice amounts and an untested export module.
- Four scenarios with private evaluation lists: `01-partial-invoices`,
  `02-vat-rate` (including separate human input), `03-billed-entries-migration`,
  and `04-e-invoice`.
- Versioned `agents.json` worker fixture generated unchanged by
  `python3 cmux-planning/scripts/agents_config.py init --config testbeds/zeiterfassung/agents.json`;
  it contains the shipped schema-v3 defaults at this skill state.
- Product code: **1,575 lines**, below the specified **3,000–5,000 lines**.
  Count includes all lines (including blanks and comments) in `project/src/**/*.php`,
  `project/bin/console`, `project/public/index.php`, and `project/config/project.php`;
  excludes tests, dependencies, caches and documentation. The human accepted
  this shortfall in advance; the project has not been padded.

### Baseline copy head commits

The human baseline runs fill these lines with the creation tool's printed
`Head commit` (the scenario copy's initial HEAD, before running a skill), and
record run identity, skill state and observations in the matching evaluation list.

- `01-partial-invoices` head commit: pending baseline run
- `02-vat-rate` head commit: pending baseline run
- `03-billed-entries-migration` head commit: pending baseline run
- `04-e-invoice` head commit: pending baseline run

Real-project cross-check run: pending; record the date, project reference, skill
state, run identifier and observed differences here when performed.

## Versioning policy

- Any change to the project, scenario files (including human input), or worker
  fixture requires a changelog entry, a version bump in `VERSION`, and a new
  baseline. Keep the version and changelog entry aligned.
- Evaluation lists may change without a version bump. Note changed expectations
  in this changelog so results remain interpretable.
- Record a real-project cross-check run in this changelog, alongside the
  synthetic testbed baselines. Pending fields do not claim a completed run.
