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

No runs recorded yet. Copy this empty record for each execution and mark observations as met, missed or not exercised, linking the research, synthesis, assumptions review, human walkthrough and any subsequent planning handoff. Leave the template blank until a real run supplies evidence.

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
