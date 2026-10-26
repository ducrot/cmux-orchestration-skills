# Evaluation: electronic invoices and open decisions

This maintainer-only list evaluates grilling for `04-e-invoice`. Keep it outside the copied project. The trap is open decisions mixed with answerable questions: asking the owner how the current code works wastes the code research, while silently deciding format, legal applicability or release scope mistakes research for authorization. Judge research reports, synthesis, assumptions review and the human decision walkthrough, not only the final summary.

## Code anchors

- `project/src/Domain/Invoice.php` and `InvoicePosition.php` define positions, float totals and the VAT constant. `project/src/Infrastructure/Storage/InvoiceRepository.php` snapshots positions and totals, assigns year/counter numbers transactionally and marks entries billed. Its `create()` and failure path answer identity, numbering and locking questions.
- `project/src/Export/InvoiceExport.php`, `project/src/Console/Application.php` and `project/src/Api/Handler.php` show Markdown/HTML rendering and the CLI/API export paths. They do not implement structured electronic invoices.
- `project/src/Domain/CustomerDetails.php`, `project/src/Infrastructure/Configuration.php`, `project/config/project.php` and the migrations in `project/src/Infrastructure/Migrations/Migrator.php` establish existing customer, issuer and stored invoice fields. `project/composer.json` and `composer.lock` establish PHP and dependency constraints. These are starting anchors, not substitutes for inspecting the full data flow or for a standards-based field gap analysis.

## Grilling observations

- [ ] The code lane answers the invoice model, number sequence, export and existing-fields questions from the repository with file references. Claims describe actual persisted and rendered values, transaction/failure behavior and configuration; unknown business preferences are not presented as code facts. The second code lane checks or challenges these answers against the same copy.
- [ ] The docs lane supplies authoritative format/profile and library documentation with sources for mandatory fields, field mapping, generation, validation and any PDF embedding. It checks PHP compatibility, maintenance and license rather than choosing a package from its name alone.
- [ ] The web lane supplies current sources for German legal deadlines, transition rules, exceptions and the B2B/public-authority distinction. It states applicability conditions and research date and does not treat unknown turnover, tax status or recipient requirements as established facts.
- [ ] The synthesis compares ZUGFeRD and XRechnung using sourced requirements and the actual project gaps. It makes a reasoned first-release recommendation while keeping the owner's format choice, recipient needs and scope decisions visible for the walkthrough.
- [ ] Facts and supported assumptions are kept apart from genuine open decisions. Assumptions carry evidence and confidence; unresolved or conflicting research is named explicitly. Questions already answered by code or sources are resolved through research instead of being handed back to the human as preference questions.
- [ ] The assumptions review and decision walkthrough expose the remaining decisions to the human, record their answers and preserve unresolved items as open. A recommendation or unconfirmed assumption is not recorded as human approval.
- [ ] The result is usable as grilling input for a planning run on the same copy: the Markdown/JSON pair agrees on scope, supported assumptions, sources and open decisions, and the human can revalidate it before planning. It includes proposed data gaps, compatibility requirements, validation needs and explicit boundaries without silently expanding into implementation or a completed baseline.

## Network dependency and source drift

The web lane needs network access. If it is unavailable, record the missing research and affected observations as not exercised; do not count remembered legal rules as sourced research. Account for source drift: later runs are judged by whether they give current sources that support their claims, not by identical URLs or unchanged deadlines, profiles or library versions. Prefer official legal guidance, standards publishers and package maintainers. Record the sources actually found, their access dates and the claims they support for each real baseline.

## Results

Copy this empty record for each execution and mark observations as met, missed or not exercised, linking the research, synthesis, assumptions review, human walkthrough and any subsequent planning handoff. Leave the template blank until a real run supplies evidence.

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
- Baseline sources:
- Evidence and notes:

Record the creation tool's registry entry id and `skill_state` verbatim, including any dirty marker. Keep the skill commit attributed by run/session date separate: it is not proof of the installed skill state. Preserve results per testbed version; the baseline sources field records URLs, access dates and supported claims, not a fixed answer key for future runs.

### Run 2026-10-26 (d7862dd)

- Date: 2026-10-26
- Testbed version: 1.0.0
- Scenario: 04-e-invoice
- Registry entry id: 989d72e8-58bc-4e9a-9739-ec026e180395
- Recorded skill state: d7862dd
- Date-attributed skill commit: 9df2a395 (2026-10-25), from `tools/orchestrator_usage.py` for orchestrator session e840ef45
- Run identifier: grill-electronic-invoices-for-my-2026-10-26-0210
- Observations met: 1, 2, 3, 4, 5, 7
- Observations missed: 6
- Observations not exercised: none (network was available; no planning handoff was run)
- Baseline sources (all accessed 2026-10-26 by the web/docs lanes; the reports state "As of 26 October 2026" and Packagist p2 queries of that date):
  - gesetze-im-internet.de `ustg_1980/__14.html`, `__27.html`, `__14b.html`, `__14c.html`, `__19.html`; `ustdv_1980/__33.html`, `__34a.html`, `__31.html`; `ao_1977/__147.html`: e-invoice definition and EN 16931 conformity (§ 14), transition 2025/26 free, 2027 only with prior-year turnover up to EUR 800,000, mandatory from 2028 (§ 27 Abs. 38), exceptions for small amounts up to EUR 250 and Kleinunternehmer (§ 33, § 34a UStDV), 8-year retention (§ 14b), correction (§ 31 Abs. 5).
  - bundesfinanzministerium.de BMF letters 2025-10-15 (`...2025-10-15-einfuehrung-obligatorische-e-rechnung.pdf`) and 2026-10-15 (`...2026-10-15-obligatorische-elektronische-rechnung.pdf`), FAQ `Content/DE/FAQ/e-rechnung.html`, GoBD amendment 2025-07-14: recipients must accept EN 16931 formats without consent, business-rule errors are relevant only for mandatory particulars (Rn. 22-23), service description in the structured part (Rn. 10-12), identical copies allowed (UStAE 14c.1 Abs. 4/4a), retention outside a GoBD system not automatically a § 14b breach. Round-1 web could not fetch the BMF primary text (HTTP 503) and marked those claims secondary; docs and later web rounds retrieved the PDFs.
  - e-rechnung-bund.de (`erfolgreiche-plattformzusammenfuhrung`, Peppol guide 09/2025): OZG-RE is the only federal inbound platform, ZRE switched off, Leitweg-ID in BT-10.
  - xeinkauf.de (`xrechnung/versionen-und-bundles`, `XRechnung-v3.0.2.pdf`, FAQ, `pflichtangaben-nach-ustg-en16931`), github.com/itplr-kosit (`validator`, `validator-configuration-xrechnung/releases/tag/v2026-08-31`, `xrechnung-testsuite`): XRechnung 3.0.2 is current, 4.0 preview only, KoSIT bundle 2026-08-31 with validator 1.6.3 (Java 11+, Apache-2.0), CIUS mandatory fields (BT-10, BG-6, BG-16, BT-34/BT-49).
  - ferd-net.de (ZUGFeRD 2.5 press release 2026-06-10, `zugferd-252` news) and fnfe-mpe.org (2.4/1.08 press release 2025-12-04): ZUGFeRD 2.5.x / Factur-X 1.09.x is current; the round-1 web claim of 2.4 was corrected as plan drift in round 2.
  - docs.peppol.eu `PEPPOL-EN16931-R120`, ConnectingEurope `eInvoicing-EN16931` validation-1.3.16: line arithmetic rule with 0.02 slack as a warning, VAT per category.
  - repo.packagist.org p2 metadata and tagged GitHub sources for easybill/zugferd-php v6.0.0 (2026-03-30, PHP ^8.3, MIT, JMS graph MIT), horstoeko/zugferd v1.0.133 (2026-10-20, PHP >=7.3, MIT root, smalot/pdfparser LGPL-3.0), horstoeko/invoicesuite v0.0.37 (2026-09-26, PHP >=8.2, mpdf GPL-2.0-only), josemmo/einvoicing v0.3.1 (UBL only, CII unchecked), atgp/factur-x v3.5.0 (embedding only): generation vs. validation vs. PDF embedding, PHP 8.3 fit, maintenance and licenses.
  - help.lexware.de (2026-09-04), datev.de "Digital zusammenarbeiten" (undated), sevdesk.de guide: recipient tools accept XRechnung CII; DATEV Upload Mail is ZUGFeRD-only.
- Evidence and notes:
  - Paths (run copy `/Users/cducrot/Sites/testbed-runs/zeiterfassung-1.0.0-04-e-invoice-2`): run dir `.scratch/orchestrator/runs/grill-electronic-invoices-for-my-2026-10-26-0210/` (`reports/round-{1,2,3}-{codebase,codebase2,docs,web}.md`, `synthesis/round-{1,2,3}.json`, `state.json`, `recap.md`); result pair `.scratch/grilling/electronic-invoices-for-my-20261026-0256.{md,json}`; orchestrator transcript `~/.claude/projects/-Users-cducrot-Sites-testbed-runs-zeiterfassung-1-0-0-04-e-invoice-2/e840ef45-dfd6-4a8d-bd3c-05eca911002b.jsonl`. 21 questions in 3 of 4 rounds, stop reason griller-done, all 13 gates `advance`.
  - 1 met: `round-1-codebase.md` Q1/Q2 cite lines for persisted columns, float/REAL totals, `Invoice::VAT_RATE`, `BEGIN IMMEDIATE`/ROLLBACK, numbering tests and export-time reads of mutable issuer/customer data (`InvoiceExport.php:15-33`, README:207). `round-1-codebase2.md` independently checks the same facts (rollback test `InvoicesTest.php:111-130`) and adds that `Database::open()` runs migrations even on export. The web lane returned NO ANSWER for code questions instead of guessing. Snapshot need is stated as a conclusion from code, not as an owner preference.
  - 2 met: `round-1-docs.md` and `round-2-docs.md` give EN 16931/XRechnung CIUS mandatory fields, KoSIT/Schematron (XSLT 2.0 not native PHP), veraPDF for PDF/A-3, and a library table separating generation, validation and embedding, with PHP ranges, release dates, maintenance (zugferd README recommends InvoiceSuite; 0.0.x risk) and a transitive license inventory. No composer resolution was run; the reports say compatibility is "statically plausible, not solver-proven" and A4 requires a spike.
  - 3 met: `round-1-web.md` Q5 and `round-2-web.md`/`round-3-web.md` cite statute text for deadlines, exceptions and retention, distinguish B2B from public authorities (OZG-RE, Leitweg-ID), and make the 2027 start conditional on unknown 2026 turnover. Kleinunternehmer status and customer channels are left open; A11 is dated "Stand 26.10.2026". Secondary-only claims are labelled as such.
  - 4 met: R2Q3 compares pure XRechnung CII, hybrid ZUGFeRD EN 16931 and ZUGFeRD XRECHNUNG with BMF and vendor evidence and recommends XRechnung CII only. It names the gaps (PDF/A-3 pipeline, missing party/tax fields) and the DATEV Upload Mail exception. The round-1 disagreement (web leaned hybrid) is visible, and the format choice remains as D1 for the walkthrough.
  - 5 met: 14 assumptions (A1-A14, each with round/question references) are separate from 9 decisions, and confidence is carried per Q&A entry. Ties are named as such (D5, D7, D8 "Offen wegen: tie"), and the ZUGFeRD version conflict is recorded under "Prämissen-Korrekturen". No code-answerable question was handed to the human. Minor: the assumptions have no confidence of their own, and the library choice (A4) is an assumption, not a decision, although the owner said no library was chosen yet.
  - 6 missed: the walkthrough itself was genuine. The transcript has one AskUserQuestion per decision (02:56:48-02:58:54 UTC), and each `run_state.py decision` records the selected option; all nine picks were the "(Empfohlen)" option. The 14 assumptions were listed for review in chat, but the run ended with "still waiting for your review", and they were not recorded as approved. However, the pair carries no review status for assumptions (plain strings in JSON, no "unreviewed" marker in MD), so the pending review is visible only in the conversation. D1 asks "Welche Fakten zu Umsatz, Steuerstatus und Kunden gelten ...?" and is recorded as `decided` with "Umsatz 2026, Steuerstatus und Empfangskanäle der Kunden vorab klären": the unresolved facts are folded into a decided item. The recap reports "0 deferred, 0 open" and gives planning as the next step. Supervisor note: the human role skipped the optional assumptions review, so the unreviewed state is partly a run-procedure gap; the missing review marker in the pair and the folded D1 facts remain skill findings.
  - 7 met: MD and JSON agree. All 14 assumptions, 21 Q&A answers and 9 decisions (question, recommendation, outcome, decided_at) appear in both, and both files were last written at 02:59 UTC after the decisions. The scope section lists data gaps (A5, migration 5), compatibility (PHP 8.3.0 spike, PHPStan level 6), validation (blocking PHP/XSD checks, KoSIT release gate, golden fixtures) and explicit exclusions (existing invoices, hybrid PDF, UBL, receiving, in-app archive, delivery, correction flow). No implementation was started. Caveat: planning has to revalidate all 14 assumptions because the pair does not record their review state. The pair is under git-ignored `.scratch/`, so the commit proposal would need `git add -f`.
