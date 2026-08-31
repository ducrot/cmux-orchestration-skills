# Specification and review contract

The specification is English, while literal product copy and domain terminology stay in their
actual language. It contains substantive sections named exactly:

- `Problem Statement`
- `Solution`
- `User Stories`
- `Implementation Decisions`
- `Testing Decisions`
- `Assumptions`
- `Open Decisions`
- `Out of Scope`
- `Further Notes`

`Testing Decisions` identifies the highest useful existing test seam, cites a relevant prior-art
test, describes the externally observable verification, and justifies any new seam. An open
decision contains the question, context, options, an evidence-backed recommendation when one is
available, and the reason it remains open. Use `- None` only when no open decision remains.

The author report is separate from the draft. It names concrete repository sources and methods,
proposed test seams, blockers, plan drift, and the exact draft path. A clean author handoff moves
only to independent review.

The fresh Codex reviewer returns exactly one verdict:

- `pass`: references the unchanged draft digest and writes no candidate.
- `pass_with_fixes`: writes a complete candidate plus a structured correction summary. Corrections
  may repair only established-intent defects such as contradictions, stale wording, cross-references,
  clearly implied traceability, structure, or acceptance-criterion clarity.
- `blocked`: records the missing product, scope, behavior, priority, or architecture decision and
  writes no approval candidate.

Any current-scope open decision blocks a passing review. A deferred decision is non-blocking only
after the candidate explicitly moves it outside current scope. A passing review is still not human
approval. `pass_with_fixes` goes through deterministic validation and a human-visible diff; it does
not trigger automatic model re-review.
