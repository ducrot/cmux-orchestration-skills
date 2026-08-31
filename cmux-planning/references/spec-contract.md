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

## Ticket and native tracker contract

Ticket authoring starts only from the immutable digest of an explicitly approved specification from the
same planning run. Its schema-version-one JSON proposal contains the source spec identity, tracker slug,
title, branch and canonical checks, plus a complete ordered ticket list. The accompanying Markdown is a
deterministic numbered rendering of that JSON, never an independent source of truth.

Every ticket states user-observable delivered behavior, stable acceptance criteria, genuine blockers,
technical context, and explicit merge/split rationale. Prefer a small number of cohesive tracer-bullet
vertical slices suitable for one fresh context. Do not default to layer, directory, file-type, test, or
worker-specialty boundaries, and do not write token counts or estimates. Wide mechanical work that
cannot land green as normal slices uses explicit expand, bounded migrate, and contract phases; a final
integration exception requires a concrete reason.

The tickets reviewer has the same three verdicts and intent boundary as the spec reviewer. A substantive
scope, behavior, architecture, ticket-boundary, dependency, or approved-spec correction is `blocked`.
A passing candidate must have unique ISSUE-NNN IDs, known acyclic blockers, and expose all tickets with no
blockers as the initial ready frontier.

After explicit human approval, the orchestrator renders a native tracker containing `README.md`,
`spec.md`, `map.md`, `decisions.md`, and one English frontmatter issue per approved ticket under
`issues/`. Only fully specified work is `AFK` and `ready-for-agent`. The standalone planning validator
must accept the complete staged tracker before one collision-checked atomic publication move; no sibling
skill or adoption conversion is a runtime dependency.
