# Correct billed work and upgrade my existing database

I use this application for my freelance time tracking and customer invoices. Sometimes I discover a wrong duration or description after sending an invoice. I want to correct already billed time entries through the console and HTTP API and have the existing invoice updated accordingly. I also need my production SQLite file migrated to the changed schema so I can keep working with my current data rather than starting over. Please document the commands and the upgrade procedure in the README.

## Correct an entry and its invoice

Let me change the start time, end time and description of an already billed entry. Keep the entry assigned to its existing project and invoice. Use the same timestamp validation and overlap checks as for other entries, including conflicts with other billed entries. Deleting billed work, moving it between projects or invoices, and creating credit notes are outside this release.

Update the corresponding position on the existing invoice: its date, description, billable hours and amount must reflect the correction. Apply the project's rounding step and the hourly rate valid on the corrected entry's UTC start date. Recalculate the invoice's net, 19% VAT and gross totals using the existing rounding conventions. Keep its ID, invoice number, customer and issue date. Leave its other positions unchanged. Invoice details through the console and API, and subsequent Markdown and HTML exports, must all show the corrected values.

For example, an entry from 09:00 to 10:00 at 100.00 EUR per hour has a net amount of 100.00 EUR. Correcting its end to 10:30 should give that position 1.5 hours and 150.00 EUR net. If it is the invoice's only position, the same invoice should then show 28.50 EUR VAT and 178.50 EUR gross. A description-only correction must also appear in the position and exports. I will send the corrected document to the customer myself.

Keep a persistent correction history with the entry and invoice references, correction time, previous and new values, and a required reason supplied with the correction. Extend the SQLite schema for this history and any additional data the feature needs. A failed correction, including an overlap, missing applicable rate or missing reason, must leave the entry, invoice and history unchanged. Unbilled entry editing, CSV import and ordinary invoice creation must continue to work as before.

## Upgrade my production installation

My existing production SQLite file contains customers, projects, rates, entries and issued invoices. Use the application's versioned migration mechanism to upgrade that file in place to the new schema, preserving IDs, invoice numbers, stored amounts and relationships. Do not require reimporting data or recreating invoices. Existing rows need a defined initial state for any new fields; the upgrade itself must not invent historical corrections or recalculate issued amounts. Running the upgrade again must not duplicate data or history.

I need an explicit operations procedure covering backup, run and verify for the actual production database, as well as rehearsal on a copy. Explain how I identify the configured database path, stop the CLI/API writers, take a consistent backup, check that it can be restored, deploy the matching application version and run the migration. Account for SQLite journal or WAL files when preparing the backup. Keep writers stopped until verification completes.

Describe verification of schema versions, database integrity, row counts, invoice totals and entry-to-invoice relationships against the backup. Include a read-only inspection of an existing invoice through the console and API and both export formats. Exercise a correction on the rehearsal copy; do not create sample changes in production. Explain when it is safe to resume service and how to restore the backup together with the previous application version if migration or verification fails. The production upgrade of my existing file is part of the delivery, alongside the code and instructions.

Cover corrections, rejection cases, persisted history across restarts and upgrades from an existing populated schema with automated checks. Preserve the existing console and API error conventions. I do not need a web interface, payment management or a different invoice numbering scheme.
