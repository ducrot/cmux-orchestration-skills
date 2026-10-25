# Show VAT details on invoice positions

I use this application to invoice my freelance work. Customers want to see the VAT rate and tax amount alongside each position, instead of having to infer them from the invoice totals. Please add these details to invoice responses through the console and HTTP API and to both Markdown and HTML exports. Explain the output in the README.

## Current behavior

Invoices select a customer's unbilled time entries, optionally within a UTC start-date range. Each position snapshots its description, billable hours, hourly rate, currency and net amount. The invoice stores net, VAT and gross totals, assigns a year-counter number and locks its entries. The rate is currently defined by `Invoice::VAT_RATE` at 19%; the export also uses that constant to label the VAT total. Position responses and export rows do not yet show VAT details.

## Required output and calculation

Show the VAT rate, VAT amount and gross amount for every position, keeping the existing net amount available. Use the same rate for all positions on an invoice. Keep the VAT rate at 19% as a constant in code, using `Invoice::VAT_RATE` as the single definition for calculations and labels. Do not introduce a configuration setting, environment variable or request parameter for the rate: this installation bills one standard-rate service, and keeping one reviewed definition prevents an accidental local setting from changing issued tax amounts. Reduced-rate services and mixed tax rates are outside this release.

For a position with a net amount of 100.00 EUR, show a 19% rate, VAT of 19.00 EUR and gross of 119.00 EUR. Round monetary output to two decimal places. Preserve the existing invoice-level totals and their rounding. If individually rounded position VAT amounts differ from the invoice VAT total by a cent, show that difference explicitly as a rounding adjustment in invoice details and both exports so the displayed figures reconcile.

## Compatibility and verification

Keep existing CLI commands, API routes and response fields working; add fields rather than renaming existing ones. Invoice numbers, entry selection, applicable hourly-rate lookup, entry rounding and billed-entry locks must retain their behavior. Previously issued invoices must keep their stored net, VAT and gross totals, and the new details must also be available when those invoices are read after an upgrade. Use the existing migration mechanism if additional stored fields are needed.

Cover the console and API output, persistence across restarts, both document formats and the rounding adjustment with automated checks. Include an invoice with several positions whose rounded position VAT amounts differ from the invoice VAT total. Keep existing error conventions and ensure a failed creation leaves neither an invoice nor locked entries behind. No web interface or new invoice selection mode is needed.
