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

The fresh independent reviewer returns exactly one verdict:

- `pass`: references the unchanged draft digest and writes no candidate.
- `pass_with_fixes`: writes a complete candidate plus a structured correction summary. Corrections
  may repair only established-intent defects such as contradictions, stale wording, cross-references,
  clearly implied traceability, structure, or acceptance-criterion clarity.
- `blocked`: records the missing product, scope, behavior, priority, or architecture decision and
  writes no approval candidate.

Empty report sections use exactly `- None` as their entire body, without punctuation or appended
explanation. For `pass`, Findings, Corrections, Blockers, and Plan Drift must have this exact body;
for `pass_with_fixes`, Blockers and Plan Drift must. Put explanatory context in Methods. Reviewers
run the rendered self-validation command on the final saved files, inspect its exit code and output,
and repair report-format errors before handoff. After any further edit, rerun validation; only exit
code 0 for the handed-off bytes supports a claim of successful self-validation. Preserve substantive
findings and blockers rather than replacing them with an empty sentinel to satisfy the gate.

Every spec and tickets review report requires `## Checked`. The recommended template order places
it between `## Findings` and `## Methods`; parsing is order-independent.
Use evidence bullets of the form:

```markdown
- `<reference>`: <what was checked>: <outcome>
```

Backtick-quoted references must collectively cover all nine input specification section names listed
above, or every ticket id in the input proposal for a tickets review. Every bullet must name at least
one reference and state both a check and its outcome. A reference is delimited by its backticks, so
`src/cli.py:42` is one reference and its colon is not a field separator. Missing or empty `Checked`
is malformed; `- None`, prose-only evidence, unquoted references, and reference-only bullets are
rejected for every verdict. A clean findings list alone is not evidence of a complete review.

Complete coverage is required for `pass` and `pass_with_fixes`. A `blocked` review stops at the
decision it cannot make, so it may cover only what it reached, but it must still carry a present,
non-empty `Checked` section with at least one structurally valid bullet alongside its substantive
blocker. Identity binding and the prohibition on an approval candidate are unchanged.

Any current-scope open decision blocks a passing review. A deferred decision is non-blocking only
after the candidate explicitly moves it outside current scope. A passing review is still not human
approval. `pass_with_fixes` goes through deterministic validation and a human-visible diff; it does
not trigger automatic model re-review.

## Ticket and native tracker contract

Ticket authoring starts only from the immutable digest of an explicitly approved specification from the
same planning run. Its schema-version-one JSON proposal contains the source spec identity, tracker slug,
title, branch and canonical checks, plus a complete ordered ticket list. The accompanying Markdown is a
deterministic numbered rendering of that JSON, never an independent source of truth.

`tracker.slug` must equal the frozen `tracker_slug` at author, review, approval, and publication
gates. The `tracker_contract.py` commands `proposal`, `author-report`, and `review-report` accept
optional `--tracker-slug` to check this equality outside the run; the orchestrator supplies the frozen
value at its gates. This does not authorize ticket revision after approval.

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
