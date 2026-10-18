# Conversation brief

Keep headings in English and content in the human's language. Preserve quotations verbatim.
Record explicit decisions with their reasons and quote important human statements. Use `None`
where a section has no entries.

Show the complete brief as its own message, not in a question preview. Directly after it, ask one
`AskUserQuestion` single-select in the human's language: "Is this brief correct?" / "Ist dieser
Brief so richtig?" Offer "Confirm" / "Bestätigen" first and recommended, then "Change" / "Ändern";
Other allows the change as free text. Name every entry the human did not state, such as one taken
from memory or repository notes, in the confirm option's description. After a change, show the
revised brief in full and ask again. Pass the saved path to init with `--brief-confirmed` only after
"Confirm".

## Goal

Describe the outcome from the user's perspective.

## Decisions made

Record explicit choices, reasons, and important verbatim statements.

## Rejected alternatives

Record alternatives the human rejected and why.

## Constraints / Non-goals

Record limits and excluded work.

## Referenced material

List files, tickets, and URLs mentioned in the conversation. Workers may read URLs when their
harness permits it.

## Still open

List questions that remain unresolved.
