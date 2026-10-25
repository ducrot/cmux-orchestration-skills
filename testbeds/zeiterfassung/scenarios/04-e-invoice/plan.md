# Electronic invoices for my freelance work

I use this PHP application to track my work and invoice German business customers as a solo developer. I want to issue electronic invoices that my customers can process, using ZUGFeRD or XRechnung. I have not chosen a format or a library yet. Please work through the unclear points with me before turning this into an implementation plan.

## What can we build on?

- How does the invoice model work today? Which values are stored when an invoice is created, how are positions and totals calculated, and what happens to the underlying time entries?
- How does the number sequence work, including year changes and failed invoice creation? Can an electronic document reuse the existing invoice identity without creating a second invoice or consuming another number?
- How does export work through the console and HTTP API today? Which formats and output paths exist, and where would another format fit?
- Which fields already exist for issuer, customer, invoice and positions? Which come from configuration, which are persisted, and which are assembled at export time? I do not know whether we already have everything an electronic invoice needs.

## Questions I still need resolved

- What are the mandatory fields and relevant profiles or versions for ZUGFeRD and XRechnung? How do they map to our existing fields, and what information would I need to collect from customers or configure about myself?
- Which format should I start with for domestic German business customers? Compare a structured XML document with a PDF containing structured invoice data, including recipient compatibility, validation and the effort of maintaining it. I have not decided whether the first release needs both.
- What legal deadlines, transition rules and exceptions apply to me for issuing and receiving electronic invoices? Distinguish private business customers from public authorities. My turnover, tax status and any customer-specific delivery requirements still need to be clarified; please do not silently assume them. Use the rules current at the time of planning.
- Which Composer library fits this project's PHP and dependency constraints, the proposed format/profile and its validation needs? Check maintained versions, license, documentation and whether it actually generates the required output; distinguish generation from validation and from PDF embedding.

## First release and remaining choices

I would like to generate the chosen document for an existing invoice through both the console and API, with useful errors for missing data and invalid output. Keep the existing Markdown and HTML exports available. I send documents to customers myself; automatic email delivery, accounting integrations and a web interface are outside this release.

We still need to decide where new issuer and customer details belong, whether any invoice-time snapshots are needed, how existing invoices with incomplete information should behave, and whether receiving or archiving documents belongs in this release or in later work. I want a small usable release, but I need to understand any compliance obligations before agreeing to that boundary.

Please ground the current behavior in repository files and the format, legal and library advice in current authoritative documentation. Separate facts and supported assumptions from choices that still need my decision. End with a recommended first-release scope, its reasons, unresolved decisions and verification needs so we can use the result to plan the work on this repository.
