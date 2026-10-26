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

### Run 2026-10-26 (b39fbdd)

- Date: 2026-10-26
- Testbed version: 1.0.0
- Scenario: 01-partial-invoices
- Registry entry id: 2ed11a27-3b25-421a-8e32-290908a5f36d
- Recorded skill state: b39fbdd
- Date-attributed skill commit: b39fbddc (2026-10-26), reported by `tools/orchestrator_usage.py --workflow planning --project partial-invoices-3` for this run; matches the recorded skill state.
- Run identifier: plan-partial-invoices-incoming-2026-10-26-1717 (planning only, no issue-chain run)
- Observations met: Planning 2 (vertical slices), Planning 3 (blocker edges, with caveat), Planning 4 (owner rules in the specification, with caveat).
- Observations missed: Planning 1 (money prefactor).
- Observations not exercised: all five complete issue-chain observations (no issue chain was run).
- Evidence and notes:
  - Paths below are relative to the run copy `zeiterfassung-1.0.0-01-partial-invoices-3`: tracker `docs/partial-invoices-incoming/` (uncommitted, proposal mode), run dir `.scratch/orchestrator/runs/plan-partial-invoices-incoming-2026-10-26-1717/`. `recap.md` reports status done after 1 h 45 min, "Revisions: spec 4 · tickets 1", 7 issues, ready frontier ISSUE-001. Spec author passes 1 to 5, spec reviews 1 to 5, tickets and tickets review 2 passes each. Gates, decided by the supervising agent with the recommended option each time:
    - spec review 1 blocked: "Migrate to integer cents";
    - spec review 2 blocked: "Preflight refusal";
    - spec review 3 blocked: "Exact JSON number tokens";
    - spec review 4 `pass_with_fixes`, approved as `artifacts/spec-reviewed-4.md`;
    - tickets review 1 blocked: "Revise spec: per-feature migrations" (`events.jsonl`, `from_spec_pass: 4`), which forced spec pass 5 (review `pass`, approved `artifacts/spec-5.md`);
    - tickets review 2 `pass_with_fixes`, approved `artifacts/tickets-reviewed-2.json`; quiz Fits/Correct/No change.
  - Planning 1 missed. All seven issue files carry `slice_type: vertical`. None is a prefactor. The first ticket, `issues/ISSUE-001-exact-cent-invoice-amounts-and-the-version-5-monetary-upgrade.md`, does cover positions, totals, persistence and both document formats in cents. But it is not behavior-preserving, and it is not only money:
    - New behavior: it adds overflow rejection, an "invoice ceiling" that rejects new invoices above 9,999,999,999,999.99, and a version-5 preflight that refuses an upgrade and leaves the database at version 4.
    - Unrelated scope: it also adds kind, currency, project and description columns and invoice fields.
    - The value object is not in it. The "dedicated money value" only appears in ISSUE-002, on the representation/JSON side.

    Both ticket authors and both reviewers rejected the prefactor label on purpose:
    - ISSUE-001 rationale: "It cannot be a behavior-preserving prefactor: the overflow rejection, the invoice ceiling and the refused upgrade are new user-visible behaviour".
    - `reports/tickets-review-1.md`: "the cent conversion has real user-visible effects and is not a mislabeled behavior-preserving prefactor".
    - `reports/tickets-review-2.md`: "labeling either whole slice a behavior-preserving prefactor would be misleading".

    Given the approved spec, that judgment is consistent. Version 5 fixes preflight and conversion as one migration ("exactly two ordered steps", `spec.md` Invoice model and schema). So the persistence change cannot be split from the refusal behavior without changing the spec. A behavior-preserving split was available only one level up:
    - A money value object for domain arithmetic and export.
    - An exact cent conversion of in-range legacy data.
    - The extreme-magnitude rules (ceiling, overflow and preflight refusal) as a later vertical slice.

    The spec never asked for that decomposition. The kind/currency/project/description columns could also have moved to ISSUE-004. Tickets review 1 hinted at this ("Keep advance-specific storage with the advance outcome"), but spec pass 5 kept them in version 5 (`spec.md` Assumptions). Notably, spec pass 1 had a prefactor-like design: cents in the domain, legacy REAL columns kept and converted at the boundary (`artifacts/spec-1.md` Assumptions). Review 1 rejected it for losing a cent at 100001 h × 999,999,999.99.
  - Planning 2 met. ISSUE-003 to ISSUE-007 are vertical slices with console, API and README outcomes: selection invoices, fixed advances, payments with history, deductions, and open items. ISSUE-001 is a vertical monetary/upgrade slice.
    - No test-only ticket exists. The position-building extraction is an in-slice step of ISSUE-003.
    - After spec pass 5, storage arrives with its first writer: version 6 payments in ISSUE-005, version 7 deductions in ISSUE-006.
    - Caveat: ISSUE-002 (exact JSON tokens) is a cross-cutting serialization change. Its only user-visible difference is for legacy invoices above about 7.04 × 10^13, and it is byte-identical below that. It is observable on both adapters, so it is not a layer-only ticket, but it is close to one.
    - This is an improvement over the baseline, which had a test-only and a service-only ticket.
  - Planning 3 met with caveat. Every edge has a stated reason in `map.md`:
    - 002/003/004→001: cents, ceiling, currency and version-5 columns.
    - 005→002: serialized one-cent balance text.
    - 005→004: the largest-advance closing payment is a decided boundary test.
    - 006→003/004/005: selection-mode verification and the shared position seam; the advance being deducted; the payable-after-deduction acceptance and version 7 following version 6.
    - 007→006: zero-balance exclusion and deducted-advance inclusion.

    Money slices depend on ISSUE-001 directly. Settlement depends on advances and the selection path. Open balances reach payments transitively. 002, 003 and 004 are parallel. Caveat: 005→004 and partly 006→005 are driven by test fixtures and migration numbering, not by functional prerequisites. Together they give a mostly serial chain 001→004→005→006→007, comparable to the baseline's 007→004/005/006 edges, which were judged met.
  - Planning 4 met (`spec.md`):
    - Selection validation runs "inside the creation transaction" with one `BEGIN IMMEDIATE`, rollback, and no number consumed.
    - Advances "lock no entries" (user story 10).
    - Deduction once: "can be referenced by at most one deduction, enforced by a storage uniqueness rule". The receivable survives: ISSUE-006 says "advance invoice keeps its gross 119.00 and its own payment history", and user story 37 keeps separate histories.
    - One currency per invoice; mixed selections, mixed period invoices and mismatched deductions are rejected.
    - "issued invoices are never recomputed"; the preflight takes cents from the legacy document value so documents are "identical by construction".
    - "Period mode stays as it is".
    - Open Decisions: "None".

    Caveat: legacy invoices get their currency "backfilled from its first position" without addressing legacy mixed-currency positions. The baseline grandfathered these explicitly.
  - Revision churn: the baseline needed 2 spec author passes. This run needed 5, with 3 spec-review blockers and 1 tickets-review blocker.
    - All three spec-review blockers came from extreme-magnitude probes on inputs the current validators accept, a rate of 999,999,999.99 with unbounded entry duration:
      - Review 1: REAL storage loses a cent at 100001 h.
      - Review 2: a legacy gross above the ceiling cannot be paid, and an entry from year 0001 to 9999 (gross ≈1.04 × 10^17) overflows int64 cents and clamps under `CAST(ROUND(...))`.
      - Review 3: float JSON reports 119001189998809.98 after a one-cent payment, and float-scaled conversion lands 0.96 off at 10000001 h.
      - Review 4 (fix, not blocker): SQLite `printf` differs from the legacy formatter at 8.33 × 10^16.
    - The new enforced-rule check contributed, especially to the first blocker.
      - Spec pass 1 kept REAL columns because "the existing suite asserts the stored numeric type; this choice needs no data rewrite and no removed test".
      - Review 1's enforced-rule audit then classed the REAL-type and numeric-JSON assertions as compatibility rules that "must not [be] silently relax[ed]", so storage became a human decision, not a reviewer fix.
      - Review 3 likewise treated the numeric JSON contract as binding, which produced the "exact JSON tokens" decision.
      - The magnitude probes supplied the defects; the enforced-rule check turned their remedies into human-owned blockers instead of `pass_with_fixes`.
    - Pass 5 came from the strict first-use storage rule: tickets review 1 F1, because version 5 created payment and deduction tables for later slices.
    - Net effect: the spec is much more rigorous about extreme values (ceiling, preflight, exact tokens). It is also heavier than the owner input needs, and ISSUE-001 has ten criteria.
  - Comparison with baseline (d7862dd):
    - Planning 2 moved from missed to met: no test-only or speculative service ticket, storage owned by its first writer, and `slice_type` published.
    - Planning 1 is still missed, but now for a principled reason instead of a test-only first ticket: the reviewers correctly refused to label the cents slice a prefactor, because the spec bundles new behavior into it.
    - Planning 3 and 4 are met in both runs.
    - Ticket count went from 8 to 7.
    - Wall time was 105 min (spec 44 min, spec review 25 min, tickets 15 min, tickets review 8 min, human gates 10.5 min, per `orchestrator_usage.py`).
  - Issue chain not run, so there is no simplify, review, test, end-to-end or migration evidence. The export trap is addressed only in planning:
    - ISSUE-001: byte-identical documents from cents, and stored currency in place of the first position's currency.
    - ISSUE-004 and ISSUE-006: document criteria.
