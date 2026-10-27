# Specification and review contract

Inputs keep their original language. Specification prose and ticket content follow the chosen language
(`artifact_language`, default English for legacy runs). Localized ticket fields are `title`,
`delivered_behavior`, `acceptance_criteria`, `merge_split_rationale`, and `tracker.title`.
Headings, markers, JSON keys, `technical_layers`, fixed renderer labels, worker reports, state,
events, and prompts stay English. Literal product copy and domain terminology stay in their actual
language. The specification contains substantive sections named exactly:

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
`User Stories` is a numbered list in the artifact language. `Implementation Decisions` holds only
decisions established by the inputs or imposed by the repository; the author's own inferences go to
`Assumptions` with their basis. Specifications and tickets contain no ordinary file paths or code
snippets, with the following exceptions. Handover locations may be named by path: artifacts one
ticket produces and another reads, and the tracker's documentation folder. Prescribed commands whose
flags carry the safety of a step may be stated verbatim. A trimmed prototype snippet that encodes a
decision more precisely than prose is also allowed. Ticket `canonical_check_commands` may contain
paths. Spec and tickets reviewers, when removing ordinary file paths, keep exempt handover locations
and safety-carrying commands verbatim.

The author report is separate from the draft. It names concrete repository sources and methods,
proposed test seams, blockers, plan drift, and the exact draft path. A clean author handoff moves
only to independent review.

The specification author checks the requested behavior against existing enforced rules: a code guard,
validation, constraint, documented rule, or test (except tests that only pin an internal
representation, described below). If one must be removed, weakened, or bypassed, name
the rule and put how it changes under `Open Decisions` with options and a recommendation. Name the
rule and its evidence by module, behavior, and test name; paths and line references go in the author
report under `Repository Sources / Methods`. Only when human input explicitly names the rule and how it
changes is that change exempt; a general request for the outcome does not grant this exemption.
Human specification revision feedback counts as human input. Record an exempt change under
`Implementation Decisions` and name the human input that decides it. Follow the input precedence:
only brief entries the human stated outrank revalidated grilling decisions, which outrank plan files;
entries taken from files retain their source's rank, and other contradictions belong under
`Open Decisions`.

The specification reviewer independently checks the repository for the same conflicts and exemption.
If such a conflict is unresolved or was decided by the author alone, return `blocked` with a finding
anchored in code or documentation. For this blocker, include the `Recommendation:` bullet inside
Blockers and name the concrete choices for the human in it; do not decide the rule change with
`pass_with_fixes`. The reviewer sees the human specification revision feedback to verify the exemption.

Code guards, validations, and constraints, including those that reject user actions, remain enforced
rules, as do documented rules and observable contracts (documented or public output formats and
user-visible behavior). A test that only pins an internal representation (a storage type, an
internal format, or a private helper's shape) is not an enforced rule. Changing it while preserving
observable behavior is the author's implementation choice; the reviewer may correct it with
`pass_with_fixes`. The author names the test and why it is internal in the author report under
`Repository Sources / Methods`.

When requested behavior depends on changing a shared representation or seam that several later
behaviors use, describe that change as a behavior-preserving step where it can be one (same observable
results for supported data). Keep new rules, limits, refusals, and storage with the behaviors that
need them. A reviewer who finds such a change bundled with new behavior reports it as a finding and
may separate it with `pass_with_fixes` when the split preserves established intent; block only when
the separation needs a new behavior decision.

The specification reviewer blocks on an edge case only when existing persisted data, a documented
use, or a plausible input reaches it, or when existing persisted data would be lost or corrupted
silently. A defect that appears only for inputs far beyond realistic use is reported once under
Findings with a `pass_with_fixes` correction that records the supported range under Assumptions;
recording that range counts as an established-intent correction, and the defect does not by itself
require new validation, refusal paths, or a human decision. The specification author states the
supported range when it matters instead of designing behavior for every value the validators accept.

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

Author and reviewer share the state and recovery check. A missing recovery point before a
production mutation the spec prescribes is `blocked`, never `pass_with_fixes`.

Any current-scope open decision blocks a passing review. A deferred decision is non-blocking only
after the candidate explicitly moves it outside current scope. A passing review is still not human
approval. `pass_with_fixes` goes through deterministic validation and a human-visible diff; it does
not trigger automatic model re-review.

## Ticket and native tracker contract

Ticket authoring starts only from the immutable digest of an explicitly approved specification from the
same planning run. Its schema-version-two JSON proposal contains the source spec identity, tracker slug,
title, branch and canonical checks, plus a complete ordered ticket list with required `execution_mode`
(`AFK` or `HITL`) on every ticket. Legacy version 1 proposals remain accepted and every ticket defaults
to AFK. The accompanying Markdown is a
deterministic numbered rendering of that JSON, never an independent source of truth.

`tracker.slug` must equal the frozen `tracker_slug` at author, review, approval, and publication
gates. The `tracker_contract.py` commands `proposal`, `author-report`, and `review-report` accept
optional `--tracker-slug` to check this equality outside the run; the orchestrator supplies the frozen
value at its gates. This does not authorize ticket revision after approval.

Every ticket states user-observable delivered behavior, stable acceptance criteria, genuine blockers,
technical context, and explicit merge/split rationale. Each slice is narrow but complete through every
layer it needs and suits one fresh context. Do not default to layer, directory, file-type, test, or
worker-specialty boundaries, and do not write token counts or estimates. A standalone prefactor uses
`slice_type: prefactor`, describes preserved behavior verified by existing tests plus its own
characterization tests, and blocks the slices it prepares. Every blocker has a smaller ticket ID. Wide
mechanical work that cannot land green as normal slices uses explicit expand, bounded migrate, and
contract phases; a final integration exception requires a concrete reason.

The tickets reviewer has the same three verdicts and intent boundary as the spec reviewer. A substantive
scope, behavior, architecture, ticket-boundary, dependency, or approved-spec correction is `blocked`.
A passing candidate must have unique ISSUE-NNN IDs, known acyclic blockers, and expose all tickets with no
blockers as the initial ready frontier.

After explicit human approval, the orchestrator renders a native tracker containing `README.md`,
`spec.md`, `map.md`, `decisions.md`, and one frontmatter issue per approved ticket under
`issues/`, carrying its `slice_type` and, for wide refactors, its `wide_refactor_phase`: AFK issues
with ready-for-agent and HITL issues with ready-for-human. Only fully specified
approved work is ready for execution. The standalone planning validator
must accept the complete staged tracker before one collision-checked atomic publication move; no sibling
skill or adoption conversion is a runtime dependency.
