# Partial invoices, incoming payments and open items

I use this application to track my freelance work and invoice customers. I need to bill completed portions of work before a project is finished, record the payments I receive, and see what customers still owe me. Please make these workflows available through both the console and the HTTP API, with the README explaining their use.

## Where we are today

An invoice currently takes all of a customer's unbilled entries, optionally filtered by their UTC start date with an inclusive from date and exclusive to date. It snapshots descriptions, billable hours and rates, assigns a year-counter number and locks the entries. Each entry is rounded up separately according to its project's rounding step, and the hourly rate comes from the validity period containing the entry's UTC start date. Rates are stored in integer cents; invoice position amounts and net, VAT and gross totals currently use floats. Invoices have 19% VAT and can be exported as Markdown or HTML.

Keep the existing full-period invoicing workflow working. Issued invoices must remain immutable snapshots, and changes to rates or rounding must not alter them. Keep numbering shared across customers per issue year, with no number consumed on failure. An invalid request must leave no invoice, entry lock, payment or settlement allocation behind.

## Bill a selected portion of work

I want to create an invoice from an explicit, non-empty selection of a customer's unbilled entry IDs, including entries from several of that customer's projects. Bill each selected entry in full using the existing rounding and applicable-rate rules. Leave unselected entries available for later invoices. Reject duplicate IDs, unknown entries, entries belonging to another customer, already billed entries and missing applicable rates; do not silently skip any of them. A selection and a date-period selection are alternative modes, so combining them must be rejected.

For example, when a customer has three unbilled entries, I should be able to invoice just the first and third. Only those two become locked. Later I can invoice the second using either the selection or the existing period workflow. Manual edits, deletion and overlapping CSV imports must continue to respect billed-entry locks and identify the invoice in their errors.

## Bill a fixed amount against a project

Sometimes a customer agrees to an advance before I know the final hours. I want to issue a fixed partial invoice for one of their projects, specifying a positive net amount, currency, description and issue date. Apply the same 19% VAT. This must work before any time has been recorded and must not mark unrelated or future entries as billed. Use the normal invoice number sequence and make the project and nature of the advance visible in invoice details and both document formats.

On a later entry-based invoice I need to explicitly select outstanding advances from the included projects to deduct from that invoice. Deduct their net amounts before calculating VAT, show each deduction with its original invoice number, and retain an auditable link. Only advances for the same customer, included project and currency may be used. Reject duplicate, already settled or partially selected advances: for this release an advance is deducted in full on one later invoice, and deductions may not exceed that invoice's entry net total. Allow a zero balance invoice when they exactly match. Never apply an advance automatically or deduct it twice. Whether the customer has paid the advance does not change its eligibility for deduction: its original invoice remains payable in its own right.

Use one currency per invoice and reject mixed-currency entry selections or mismatched deductions. Do not convert currencies. A fixed advance has an explicit currency; it does not require a rate for its issue date. Existing issued invoice amounts must retain their value when upgrading the application. I care about exact cent-level results and consistent rounding across repeated deductions, totals and displayed documents; choose a suitable internal representation.

## Record incoming payments

I want to record an incoming payment against an existing invoice with its payment date, positive gross amount, matching currency and an optional bank reference. Allow several payments, including payments received on different days. Reject amounts greater than the invoice's remaining gross balance, unknown invoices, currency mismatches and invalid dates. Reject another payment on an invoice already fully paid. Payments do not change the issued invoice's positions, totals, number or entry locks. Payment corrections, refunds, credit notes and bank import can wait; this release only adds payments and lists their history per invoice.

For a net invoice of 100.00 EUR, gross is 119.00 EUR. Recording 50.00 EUR leaves 69.00 EUR open; recording the remaining 69.00 EUR closes it. An advance invoice and its later invoice each have their own payment history: if the later invoice deducts a net advance of 100.00 EUR from 300.00 EUR of work, its net is 200.00 EUR and gross 238.00 EUR. The advance invoice still has its original gross 119.00 EUR and any payments already recorded against it.

## Show open items

I need an open-items view for all customers or one selected customer. Show invoice ID and number, customer, issue date, currency, original gross total, total received and outstanding gross amount, ordered by issue date then invoice ID. Include fixed advances as well as entry-based invoices. Show only invoices with a positive remaining balance; zero balance and fully paid invoices stay accessible through invoice details and payment history. An unknown customer filter is an error. Keep currencies separate when showing any aggregate balances. There is no due-date or overdue calculation in this release.

Cover the workflows and rejection cases with automated checks, including persistence across application restarts and unchanged values in both invoice document formats. Keep existing CLI/API error conventions and migrations for existing databases. No web interface, configurable VAT, foreign exchange or general project-budget management is needed.
