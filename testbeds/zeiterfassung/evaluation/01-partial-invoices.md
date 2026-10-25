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

No runs recorded yet. Copy the empty record below for each execution; leave this template blank until a real run supplies evidence. Record observations as met, missed or not exercised, with links to the specification/tracker, worker reports and check logs. Do not mark unchecked observations as failures when the relevant stage was not run.

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
