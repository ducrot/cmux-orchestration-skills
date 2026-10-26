# Evaluation: partial invoices and incoming payments

This maintainer-only list evaluates planning and a complete issue-chain run for `01-partial-invoices`. Keep it outside the copied project. Judge evidence from the generated specification, tracker and worker reports; do not infer success from a plausible final summary. The owner input deliberately describes outcomes without prescribing a money model or ticket structure.

## Built-in traps and code anchors

- Float money: `project/src/Domain/InvoicePosition.php` stores and calculates `amount` as float; `project/src/Domain/Invoice.php` uses floats for net, VAT and gross. `project/src/Infrastructure/Storage/InvoiceRepository.php` persists and reloads those snapshots. Rates already use integer cents (`project/src/Domain/Rate.php`), so treating all money as already exact misses the weakness. Repeated deductions and payments make this material.
- Untested export: `project/src/Export/InvoiceExport.php` takes float money and formats positions and totals for Markdown and HTML. Its currency comes from the first position. A money refactor and fixed advances touch this path even if export is overlooked in the feature list. The starting project intentionally has no export tests.
- Duplicated time-entry validation: `project/src/Console/Application.php` and `project/src/Api/Handler.php` repeat entry input validation; `project/src/Application/Entries.php` and `project/src/Domain/CsvImport.php` also contain related validation. Overlap logic exists in storage SQL and `project/src/Domain/TimeEntry.php`. Look for concrete duplicated rules and an evidence-based simplification recommendation when the entry and invoice locking paths are exercised; do not require unrelated architecture work.

## Planning observations

- [ ] The first ticket is one behavior-preserving money value-object prefactor, explicitly marked `slice_type: prefactor`, before partial invoices and payments. It covers position amounts, totals, persistence boundaries and export formatting, preserving issued values, rounding and public behavior with checks. Merely using cents for new payments leaves the float trap intact.
- [ ] Subsequent tickets are vertical slices with user-observable outcomes, for example selected-entry invoicing, fixed advances with explicit settlement, payment recording and open items. There are no database-only, service-only, API-only or test-only layer tickets. Exact grouping may vary if each slice remains verifiable.
- [ ] Blocker edges express genuine prerequisites: money-dependent slices depend on the prefactor; settlement depends on advances and the entry invoice path it changes; payment-backed open balances depend on payment recording. Every edge has a concrete reason; there is no arbitrary serial chain or invented dependency between independent outcomes.
- [ ] The specification resolves the owner rules: selected entries lock atomically, fixed advances leave entries unbilled, settlement deducts an advance once without erasing its receivable, payment histories remain separate, currencies cannot mix, and existing invoice snapshots and full-period invoicing survive migrations.

## Complete issue-chain observations

Run the full generated tracker through implementation, simplify, test and review to completion, including any approved follow-ups and the final checks. Planning alone cannot satisfy these observations. Record stage/run identifiers and concrete file or test evidence for each item.

- [ ] Simplify passes identify the float-money weakness and duplicated time-entry validation, or explicitly verify their removal by an earlier slice with evidence. Recommendations stay scoped to touched rules; a finding recorded for triage is distinguishable from an applied fix.
- [ ] Review passes independently check the float arithmetic/persistence boundaries and duplicated CLI/API validation, with concrete findings or verification of the earlier fixes. A generic claim that tests passed is insufficient.
- [ ] The test pass adds and executes export coverage when the money refactor touches export, checking both Markdown and HTML, exact amounts and totals, and fixed-advance/settlement documents. It does not preserve the starting coverage gap simply because export was originally untested.
- [ ] End-to-end CLI and API evidence covers selection with unselected entries left unbilled, fixed advances and one-time deductions, multiple payments and open balances. Invalid selections, billed-entry locks (including CSV import), mixed currencies, duplicate settlement and overpayment are checked for atomic refusal.
- [ ] Migration and regression evidence preserves existing issued invoice values, rate-date lookup, entry rounding, full-period invoicing and failure-safe numbering. The complete issue-chain reaches its final checks; incomplete or interrupted execution is recorded as such.

## Results

Copy the empty record below for each execution; leave this template blank until a real run supplies evidence. Record observations as met, missed or not exercised, with links to the specification/tracker, worker reports and check logs. Do not mark unchecked observations as failures when the relevant stage was not run.

### Run record template

- Date:
- Testbed version:
- Scenario:
- Registry entry id:
- Recorded skill state:
- Date-attributed skill commit:
- Run identifier:
- Observations met:
- Observations missed:
- Observations not exercised:
- Evidence and notes:

Use the creation tool's registry entry id and recorded `skill_state` verbatim, retaining a dirty marker. Record the skill commit attributed by run/session date separately: a date-attributed commit is not proof of the installed state. Distinguish the planning run identifier from issue-chain identifiers in the evidence when both were executed. Take the testbed version from the created copy's registry record; do not backfill results from a later version.

### Run 2026-10-26 (d7862dd)

- Date: 2026-10-26
- Testbed version: 1.0.0
- Scenario: 01-partial-invoices
- Registry entry id: 6190903d-d855-42d3-9e5d-adff5f61802b
- Recorded skill state: d7862dd
- Date-attributed skill commit: 9df2a395 (2026-10-25), reported by `tools/orchestrator_usage.py` for this run; differs from the recorded skill state.
- Run identifier: plan-partial-invoices-incoming-2026-10-26-0209 (planning only, no issue-chain run)
- Observations met: Planning 3 (blocker edges), Planning 4 (owner rules in the specification).
- Observations missed: Planning 1 (money prefactor), Planning 2 (no layer-only tickets).
- Observations not exercised: all five complete issue-chain observations (no issue chain was run).
- Evidence and notes:
  - Paths below are relative to the run copy `zeiterfassung-1.0.0-01-partial-invoices-2`: tracker `docs/partial-invoices-incoming/` (uncommitted, proposal mode), run dir `.scratch/orchestrator/runs/plan-partial-invoices-incoming-2026-10-26-0209/`. `state.json` has `current_stage: complete`, with spec, spec-review, tickets and tickets-review each at 2 passes. Gates, decided by the supervising agent: spec review 1 blocked on legacy mixed-currency invoices (`reports/spec-review-1.md` F1), resolved as "grandfather, exclude"; tickets review 1 blocked on ISSUE-006's advance-history prerequisite (`reports/tickets-review-1.md`), resolved by moving the proof to ISSUE-007; quiz answers Fits/Correct/No change. Result: 8 tickets, ready frontier ISSUE-001.
  - Planning 1 missed. None of the eight issue files has a `slice_type` field; the frontmatter has only `id, title, type: AFK, status, labels`. The first ticket, `issues/ISSUE-001-record-pre-upgrade-reference-outputs-of-the-current-release.md`, is a test-only characterization baseline: "Nothing changes for the user", "No product code ... changes". It is not a money refactor. The cents conversion is in `issues/ISSUE-002-upgrade-invoices-to-integer-cents-with-kind-currency-and-legacy-grandfat.md`. That ticket covers positions, totals, persistence and documents ("integer-cent columns for position amount, net, VAT and gross", "both document formats ... byte-identical"), but it is not behavior-preserving. It also bundles the kind/currency/legacy marker, the whole schema for advances, deductions and payments ("creates the storage for advances, deductions and payments that the later slices fill"), a period-workflow behavior change ("rejects a set of entries whose applicable rates mix currencies") and README work. No money value object is named; the spec says only "integer cents" (`spec.md` Money representation). "Prefactor" appears only as prose for ISSUE-001 and ISSUE-003 in `map.md` and `decisions.md`.
  - Planning 2 missed. ISSUE-004 to ISSUE-008 are vertical slices with CLI/API/README outcomes: selection invoice, fixed advance, payments with history, deductions, and open items with the restart check folded in. Three tickets are not:
    - ISSUE-001 is a test-only ticket.
    - `issues/ISSUE-003-separate-position-collection-from-invoice-persistence-in-creation.md` is a service/repository-only refactor that adds speculative entry points: "can accept ... an explicit list of entry IDs and an explicit list of advance IDs, without yet implementing their behaviour; ... not reachable from the console or the API".
    - ISSUE-002 carries a database-only part: the schema for later slices.
    - Both tickets reviews accepted ISSUE-001 and ISSUE-003 as "justified standalone prefactors" (`reports/tickets-review-2.md`).
  - Planning 3 met. Every edge has a stated reason in `map.md`:
    - 002→001: the baseline must be recorded before the migration.
    - 003→002: persistence writes the kind/currency columns.
    - 004→003 and 005→003: shared persistence step.
    - 006→002: needs cents, currency and the legacy marker.
    - 007→004/005/006: both modes take the advance list, an advance must exist to deduct, and the paid/unpaid and separate-history proofs need payments.
    - 008→006/007: received amounts, plus the deduction-created zero-balance case in its acceptance criteria.
    - Money-dependent slices reach the cents change transitively. 004, 005 and 006 can run in parallel; there is no arbitrary serial chain. Caveat: the prefactor the edges hang on is not the one Planning 1 expects.
  - Planning 4 met (`spec.md`):
    - Atomic selection: "rejects, without creating anything", one write transaction with rollback.
    - Advances "lock no time entries".
    - One-time deduction ("A settled advance cannot be deducted again", plus a uniqueness constraint), with the receivable kept: user story 40 "each keep their own payment history", and ISSUE-007's "the advance keeps its gross 119.00".
    - Currencies cannot mix for new invoices; legacy mixed-currency invoices are grandfathered.
    - Migration preserves values and byte-identical documents.
    - "The existing full-period workflow keeps working".
    - Open Decisions: "None".
  - Issue chain not run, so no simplify, review, test, end-to-end or migration evidence exists. The export trap is addressed only in planning: ISSUE-002 has byte-identical document references, ISSUE-005 and ISSUE-007 have document criteria.
