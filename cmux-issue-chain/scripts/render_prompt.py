#!/usr/bin/env python3
"""Render deterministic worker prompts for a local issue."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from orchestrator_lib import blocker_status, issue_ready, load_issues, read_issue_markdown, utc_now
from worker_snapshot import SnapshotError, load_launchable_snapshot


ROLES = ("implement", "simplify", "review", "test")
CLAUDE_CODE = "claude-code"

# Role rules keyed by harness. Implement and test are harness-neutral. Simplify and review
# drive Claude Code's bundled skills when the worker runs there; any other harness gets the
# same duties spelled out inline, because no other harness ships /simplify or /code-review.
ROLE_RULES = {
    "implement": (
        "You are the implementation worker. You may edit product code and tests needed "
        "for this issue. Do not edit orchestrator run state. Keep changes scoped to the issue. "
        "Testing is part of implementation, not a later stage: every new or changed behavior needs a "
        "regression test that demonstrably fails without your change, and you must execute the changed "
        "path end-to-end (real request, browser, or CLI run) before reporting. "
        "Do not handle code-review findings unless the orchestrator explicitly assigns a human-approved follow-up pass."
    ),
    "test": (
        "You are the test worker. Do not edit product code. Run relevant checks, inspect "
        "behavior, and report findings with exact commands and outcomes. Earlier passes may have "
        "changed observable behavior, so re-verify the acceptance criteria against the current tree, "
        "including any end-to-end or browser verification the issue required."
    ),
    "simplify": (
        "You are the simplify/refactor worker in Claude Code. You may edit product code to reduce complexity "
        "without changing behavior. Run `/simplify`, apply behavior-preserving refactorings when they are within "
        "the issue scope, and report changed files plus verification. Do not broaden scope. "
        "This role runs after every implementation pass."
    ),
    "review": (
        "You are the code review worker in Claude Code. You may edit product code by running "
        "`/code-review medium --fix` before writing the final report. Apply safe review fixes "
        "inside the issue scope, classify any remaining issues by severity and recommendation, and put only "
        "unresolved must-fix and ask-user items in Findings. Never fix a finding that contradicts a "
        "documented issue decision — report it as ask-user instead. Put nice-to-have or broader hardening "
        "in Recommendations."
    ),
}
PORTABLE_ROLE_RULES = {
    "simplify": (
        "You are the simplify/refactor worker. You may edit product code to reduce complexity "
        "without changing behavior. Run the simplify pass described in the contract below, apply "
        "behavior-preserving refactorings when they are within the issue scope, and report changed files "
        "plus verification. Do not broaden scope. This role runs after every implementation pass."
    ),
    "review": (
        "You are the code review worker. You may edit product code to apply safe review fixes before "
        "writing the final report. Run the three-axis review pass described in the contract below, apply "
        "safe review fixes inside the issue scope, classify any remaining issues by severity and "
        "recommendation, and put only unresolved must-fix and ask-user items in Findings. Never fix a "
        "finding that contradicts a documented issue decision — report it as ask-user instead. Put "
        "nice-to-have or broader hardening in Recommendations."
    ),
}

# Review check line and fix label differ by harness; the triage rules below them do not.
REVIEW_CHECK_LINE = {CLAUDE_CODE: "`/code-review medium --fix`"}
REVIEW_FIX_LABEL = {CLAUDE_CODE: "`--fix`"}
PORTABLE_REVIEW_CHECK_LINE = "`review pass (standards, spec, correctness)`"
PORTABLE_REVIEW_FIX_LABEL = "the review pass"

# Fowler smells (Refactoring, ch. 3) as a fixed judgement-call baseline for the portable review
# pass. Documented repo standards override it; skip anything tooling already enforces.
SMELL_BASELINE = """- Mysterious Name: a name that does not reveal what it does or holds -> rename.
- Duplicated Code: the same logic shape in more than one hunk or file -> extract and share.
- Feature Envy: a method reaching into another object's data more than its own -> move it.
- Data Clumps: the same few fields or params always travelling together -> bundle into one type.
- Primitive Obsession: a primitive standing in for a domain concept -> give it a small type.
- Repeated Switches: the same switch/if-cascade recurring across the change -> polymorphism or one shared map.
- Shotgun Surgery: one logical change forcing scattered edits across many files -> gather into one module.
- Divergent Change: one module edited for several unrelated reasons -> split by reason.
- Speculative Generality: abstraction or hooks for needs the spec does not have -> delete, inline back.
- Message Chains: long a.b().c().d() navigation -> hide behind one method on the first object.
- Middle Man: a unit that mostly delegates onward -> cut it, call the target directly.
- Refused Bequest: an implementer ignoring most of what it inherits -> composition instead."""


def role_rules(role: str, harness: str) -> str:
    if harness != CLAUDE_CODE and role in PORTABLE_ROLE_RULES:
        return PORTABLE_ROLE_RULES[role]
    return ROLE_RULES[role]


def review_check_line(harness: str) -> str:
    return REVIEW_CHECK_LINE.get(harness, PORTABLE_REVIEW_CHECK_LINE)


def review_fix_label(harness: str) -> str:
    return REVIEW_FIX_LABEL.get(harness, PORTABLE_REVIEW_FIX_LABEL)


def parser_path() -> str:
    """Parser path as workers invoke it from the repo root, wherever the skill is installed.

    The skill may live under .agents/skills/ (canonical), as a copy under .claude/skills/,
    or outside the repo entirely; hardcoding one location broke the first cross-repo pilot.
    """
    script = Path(__file__).resolve().parent / "parse_report.py"
    try:
        return str(script.relative_to(Path.cwd()))
    except ValueError:
        return str(script)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", required=True, help="Tracker directory, e.g. .scratch/<tracker>")
    parser.add_argument("--issue", required=True)
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--pass", dest="pass_number", type=positive_int, required=True, help="Pass number, 1-based")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", help="Prompt path. Defaults to run-dir/prompts/<role>-<pass>.md")
    parser.add_argument(
        "--report-path",
        help="Expected worker report handoff path. Defaults to run-dir/reports/<role>-<pass>.md",
    )
    parser.add_argument("--context-file", action="append", default=[], help="Additional report/context file to append")
    return parser


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("--pass must be >= 1")
    return number


def main() -> int:
    args = build_parser().parse_args()
    tracker = Path(args.tracker)
    issues = load_issues(tracker)
    issue, markdown = read_issue_markdown(tracker, args.issue)
    blockers = blocker_status(issue, issues)
    if issue.type.upper() == "HITL":
        raise SystemExit(f"{issue.id} is HITL and must not be started as an AFK worker chain")
    if not issue_ready(issue, issues):
        raise SystemExit(f"{issue.id} is not ready: {blockers}")

    run_dir = Path(args.run_dir)
    # The prepared stage snapshot is the only source for the worker's harness, so the prompt
    # text and the launch command cannot drift apart. Render after run_state.py prepare.
    try:
        snapshot = load_launchable_snapshot(run_dir, args.role, args.pass_number)
    except SnapshotError as error:
        raise SystemExit(f"cannot render {args.role}-{args.pass_number}: {error}")
    harness = snapshot["selected_worker"]["harness"]
    stem = f"{args.role}-{args.pass_number}"
    out = Path(args.out) if args.out else run_dir / "prompts" / f"{stem}.md"
    report_path = Path(args.report_path) if args.report_path else run_dir / "reports" / f"{stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = render(
        args.role,
        issue.id,
        markdown,
        blockers,
        [Path(path) for path in args.context_file],
        out,
        report_path,
        args.pass_number,
        tracker_ground_rules(tracker),
        tracker_decisions(tracker),
        harness=harness,
        snapshot_id=snapshot["snapshot_id"],
        artifact_path=run_dir / "artifacts" / stem,
    )
    out.write_text(prompt, encoding="utf-8")
    print(out)
    return 0


def render(
    role: str,
    issue_id: str,
    markdown: str,
    blockers: dict,
    context_files: list[Path] | None = None,
    prompt_path: Path | None = None,
    report_path: Path | None = None,
    pass_number: int = 1,
    ground_rules: str = "",
    decisions: str = "",
    harness: str = CLAUDE_CODE,
    snapshot_id: str | None = None,
    artifact_path: Path | None = None,
) -> str:
    context_files = context_files or []
    context = render_context(context_files)
    review_contract = render_review_contract(harness) if role == "review" else ""
    prompt_path_text = str(prompt_path) if prompt_path else "(not provided)"
    report_path_text = str(report_path) if report_path else "(not provided)"
    artifact_path_text = str(artifact_path) if artifact_path else "(not provided)"
    ground_rules_block = f"\n## Tracker Ground Rules\n\nThese rules bind every worker on this tracker:\n\n{ground_rules}\n" if ground_rules else ""
    decisions_block = (
        "\n## Tracker Decisions\n\nThe human already rejected or deferred these items in earlier triage. "
        "Do not re-report or re-apply them unless the code now presents a materially different problem:\n\n"
        f"{decisions}\n"
    ) if decisions else ""
    return f"""# Worker Prompt: {role} {issue_id} (pass {pass_number})

This file is your task assignment, not a document to summarize. Execute it now and write your
final report to the handoff path below.

Created: {utc_now()}
Pass: {pass_number}
Harness: {harness}
Stage snapshot: {snapshot_id or "(not provided)"}

{role_rules(role, harness)}

## Handoff Paths

- Prompt file: `{prompt_path_text}`
- Final report handoff path: `{report_path_text}`
- Worker artifact directory: `{artifact_path_text}`

## Orchestrator Contract

Never run `git add`, `git rm --cached`, `git stash`, `git commit`, `git reset`, or any other command that changes the index or HEAD; staging and committing belong to the human after the run.

- Do not write `.scratch/orchestrator/**` except the exact final report handoff path and your worker
  artifact directory above.
- You MUST write the final report body to the exact final report handoff path before returning it in the
  console. That one report file is the only orchestration lifecycle file you may write; do not edit state,
  events, prompts, snapshots, gates, or other lifecycle state.
- Create your artifact directory as needed and use it for task-specific helper scripts, report drafts,
  logs, snapshots, and raw evidence. Do not create ad-hoc `.scratch/issue-*` directories. Reusable tests
  belong in the repository's normal test locations, subject to your role's editing permissions.
- You may read earlier workers' artifacts; write your own artifacts only in your assigned artifact directory.
  Reference relevant artifacts in your final report. Keep artifacts after the stage and run finish;
  the human deletes run directories manually. Do not perform automatic end-of-run cleanup.
- If you find a blocker, include `BLOCKER` and stop after documenting the minimum evidence.
- If the issue plan is stale or wrong, include `PLAN DRIFT` with the smallest accurate correction.
- Finish with the Worker Report Contract below.
- A gate can advance only on `NO FINDINGS` plus concrete tests/checks.
- The chain runs on a deliberately uncommitted working tree. Never report the uncommitted state or a missing commit, push, PR, or CI run as a finding; commit and push happen after the chain completes and belong to the human.
- Use the canonical check commands declared in the tracker ground rules as the baseline suite. Narrower targeted checks may be added, but never substitute a different suite.
- Stay inside the assigned role. Do not perform adjacent roles unless explicitly instructed by the orchestrator.
{role_specific_contract(role, harness)}
{ground_rules_block}{decisions_block}
## Blocker Status

```json
{json.dumps(blockers, indent=2, sort_keys=True)}
```

## Issue

```markdown
{markdown.rstrip()}
```
{context}

## Worker Report Contract

Every section below except `## Notes` is required. Emit exactly one token under `## Result` — not the `|`
menu. An omitted or empty required section is treated as a malformed report and stops the chain as HITL; it
never reads as `None`.

```markdown
## Result
NO FINDINGS

## Tests / Checks
- `command`: outcome

## Findings
- None

## Blockers
- None

## Plan Drift
- None

## Notes
- Optional: caveats, method notes, context. Never must-fix content.
```

Allowed `## Result` values: `NO FINDINGS`, `FINDINGS`, `BLOCKER`.

Formatting rules the gate parser enforces:

- In `## Findings`, `## Blockers`, and `## Plan Drift`, an empty section is exactly the line `- None` —
  no prose on or after that line. Anything else in these sections is parsed as a real finding, blocker,
  or drift and stops the chain. Explanations, caveats, and methodology belong in `## Notes`.
- Real findings/blockers/drift go in their section with file/line evidence; do not soften them into Notes.

Before returning, self-validate: write your draft report inside your worker artifact directory (not the
handoff path) and run

```bash
python3 {parser_path()} <your-draft-file>
```

A clean report must print `gate=advance`. If you are genuinely reporting findings, a blocker, or plan
drift, `stop`/`blocked`/`hitl` is expected — anything else means your report is malformed. Fix the format,
never the substance. After validation, write that exact validated report body to `{report_path_text}`, run
the parser once more against that handoff path, and only then return the same report body in the console.
Do not delete or replace the handoff report with a summary.
{review_contract}
"""


def role_specific_contract(role: str, harness: str = CLAUDE_CODE) -> str:
    if role == "review":
        return review_contract_lines(harness)
    if role == "simplify":
        return simplify_contract_lines(harness)
    if role == "test":
        return "- Do not edit product code. If a check requires setup, report the exact setup gap instead of patching."
    return (
        "- Implement the assigned issue scope only. Do not take over review self-fixes unless explicitly instructed after HITL.\n"
        "- Prove your change: add or extend regression tests and verify at least one fails without the change; state that verification in the report.\n"
        "- Run the full relevant suite and execute the changed path end-to-end; list both under `## Tests / Checks`."
    )


def review_contract_lines(harness: str) -> str:
    if harness == CLAUDE_CODE:
        head = (
            "- Run `/code-review medium --fix` in Claude Code against the current working diff.\n"
            "- Apply safe fixes produced by `/code-review --fix` when they stay inside the current issue scope.\n"
        )
    else:
        head = (
            "- Review the current working diff yourself: `git diff HEAD` plus untracked files, with `HEAD` as the "
            "fixed point. The spec is the issue embedded in this prompt (What to build, acceptance criteria, "
            "recorded plan changes). Never ask for a fixed point or a spec location.\n"
            "- Run three review axes and keep their findings separate; do not rerank one axis against another:\n"
            "  - Standards: does the diff follow the repo's documented standards (AGENTS.md, CLAUDE.md, "
            "CONTRIBUTING.md, coding-standard docs, tracker ground rules) plus the smell baseline below? A "
            "documented repo standard overrides the baseline; baseline smells are judgement calls; skip anything "
            "tooling already enforces.\n"
            "  - Spec: requirements that are missing or partial, behavior nobody asked for (scope creep), and "
            "requirements that look implemented but wrong. Quote the spec line for each finding.\n"
            "  - Correctness: regressions, security, data-safety, and closure of prior must-fix findings from the "
            "context reports.\n"
            "- Smell baseline for the Standards axis:\n"
            f"{indent_block(SMELL_BASELINE)}\n"
            "- Apply safe fixes from all three axes yourself when they stay inside the current issue scope, then "
            "re-run the baseline suite.\n"
        )
    fix = review_fix_label(harness)
    return head + (
        f"- Include a `## Change Summary` section listing changed files and fixes applied by {fix}.\n"
        "- Classify every remaining issue with `Severity` and `Recommendation`.\n"
        "- `Recommendation: must-fix` is for objective correctness, regression, security, or data-safety issues. "
        "`Recommendation: ask-user` is for findings that challenge a documented issue decision (What to build, "
        "acceptance criteria, recorded plan changes): never apply a fix that undoes such a decision, even a safe "
        "one — report it verbatim for the human.\n"
        "- Put only unresolved `Recommendation: must-fix` and `Recommendation: ask-user` items in `## Findings`.\n"
        "- Put low-risk cleanup, speculative edge cases, broader hardening, and nice-to-have items in `## Recommendations`.\n"
        "- Do not hand findings back to the implementer for an automatic fix loop.\n"
        "- Do not create an unbounded hardening review; focus on acceptance criteria, regressions, security/data-safety, and prior must-fix closure."
    )


def simplify_contract_lines(harness: str) -> str:
    if harness == CLAUDE_CODE:
        head = (
            "- Run `/simplify` in Claude Code and report the outcome under `## Tests / Checks`.\n"
            "- Apply behavior-preserving `/simplify` refactorings yourself when they stay inside the current issue scope.\n"
        )
    else:
        head = (
            "- Run a simplify pass yourself over the current working diff (`git diff HEAD` plus untracked files) "
            "and report its outcome under `## Tests / Checks` as `simplify pass`. Look for: logic an existing "
            "helper already covers (reuse), needless indirection or over-general abstractions (simplification), "
            "obvious inefficiencies on the changed path (efficiency), and code sitting at the wrong abstraction "
            "level (altitude). This is a quality pass, not a bug hunt; leave correctness to the review stage.\n"
            "- Apply behavior-preserving refactorings yourself when they stay inside the current issue scope, and "
            "run the baseline suite before and after.\n"
        )
    return head + (
        "- Include a `## Change Summary` section listing changed files and the behavior-preserving refactorings applied.\n"
        "- Preserve behavior. If simplification would require design, acceptance, or scope changes, report it instead of editing."
    )


def indent_block(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def tracker_decisions(tracker: Path) -> str:
    """Read the tracker's triage ledger of human-rejected or deferred items."""
    decisions = tracker / "decisions.md"
    if not decisions.is_file():
        return ""
    return decisions.read_text(encoding="utf-8").strip()


def tracker_ground_rules(tracker: Path) -> str:
    """Extract the tracker README's ground-rules section (any `##` heading containing "ground rules")."""
    readme = tracker / "README.md"
    if not readme.is_file():
        return ""
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"^##\s+.*ground rules.*$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def render_context(context_files: list[Path]) -> str:
    if not context_files:
        return ""
    chunks = ["\n## Additional Context\n"]
    for path in context_files:
        chunks.append(f"\n### {path}\n\n```markdown\n{path.read_text(encoding='utf-8').rstrip()}\n```\n")
    return "".join(chunks)


def render_review_contract(harness: str = CLAUDE_CODE) -> str:
    check = review_check_line(harness)
    fix = review_fix_label(harness)
    return f"""

Review workers **extend** the contract above; they do not replace it. Keep every section listed there,
including `## Blockers` and `## Plan Drift`. A report missing a required section is treated as malformed
and stops the chain as HITL. Add these sections and this stricter findings triage:

```markdown
## Tests / Checks
- {check}: outcome
- `command`: outcome

## Change Summary
- None, or concise list of review fixes applied by {fix}.

## Findings
- None

## Recommendations
- None, or non-blocking nice-to-have/follow-up items.
```

`## Findings` follows the bare-`None` rule above. Remaining must-fix findings after {fix} replace the
`- None` line entirely, each with:

- Severity: critical|high|medium|low
- Recommendation: must-fix|ask-user — ask-user when the finding challenges a documented issue decision; the reviewer must not fix those
- Scope: acceptance|regression|security|data-safety|other
- Evidence: file/line and observed behavior
- Suggested fix: concrete action

`## Change Summary` and `## Recommendations` are not gate-parsed and may carry prose.
"""


if __name__ == "__main__":
    raise SystemExit(main())
