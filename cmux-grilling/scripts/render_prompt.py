#!/usr/bin/env python3
"""Render self-contained prompts for fresh per-round research workers."""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

from orchestrator_lib import (
    LANES,
    read_json,
    read_run_state,
    read_text,
    round_marker_path,
    round_prompt_path,
    round_report_path,
    utc_now,
)

from round_context import render_context

INDEX_HEAD_PROHIBITION = 'Never run `git add`, `git rm --cached`, `git stash`, `git commit`, `git reset`, or any other command that changes the index or HEAD; staging and committing happen after the run, outside the worker.'


LANE_RULES = {
    "codebase": (
        "You are the codebase researcher. Answer every question exclusively from this "
        "repository: source code, configuration, local docs, and git history. Use read-only "
        "repo tools (file reading, content search, file globbing, read-only git commands). Do not use web search or web "
        "fetch. Cite real, resolvable file paths relative to the repo root under `## Sources`."
    ),
    "codebase2": (
        "You are the independent second-opinion codebase researcher. Answer "
        "every question exclusively from this repository: source code, configuration, local "
        "docs, and git history, using read-only inspection. Do not use web search. Form your "
        "own view of the code from scratch each round; you cannot see the other lanes' "
        "answers, and you must not guess at them. Cite real, resolvable file paths relative "
        "to the repo root under `## Sources`."
    ),
    "docs": (
        "You are the documentation researcher. Answer from official library, framework, and "
        "API documentation, changelogs, and reference material for the technologies this "
        "repository actually uses. Verify the versions in use first (composer.json, "
        "package.json, lock files) so your documentation matches reality. Web access is "
        "allowed for documentation sources. Cite documentation URLs plus the repo files that "
        "pin the relevant versions under `## Sources`."
    ),
    "web": (
        "You are the web researcher. Answer from the public web: standards, best practices, "
        "security advisories, known issues, and comparable implementations. Prefer "
        "authoritative sources. You may read the repository only to understand the question's "
        "context, never as your evidence base — project-internal facts are the codebase "
        "lanes' job, and 'this is not web-answerable' is a valid `NO ANSWER`. Cite URLs "
        "under `## Sources`."
    ),
}

def fenced_content(content: str, language: str) -> str:
    """Use a fence longer than any backtick run so embedded fences cannot close it."""
    longest = max(map(len, re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{content.rstrip()}\n{fence}"


def parser_path() -> str:
    """Parser path as lanes invoke it from the repo root, wherever the skill is installed.

    The skill may live under .agents/skills/ (canonical), as a copy under .claude/skills/,
    or outside the repo entirely; hardcoding one location broke the first cross-repo pilot.
    """
    script = Path(__file__).resolve().parent / "parse_research_report.py"
    try:
        return str(script.relative_to(Path.cwd()))
    except ValueError:
        return str(script)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    round_cmd = subparsers.add_parser("round", help="Render a lane's per-round question prompt")
    round_cmd.add_argument("--run-dir", required=True)
    round_cmd.add_argument("--lane", choices=sorted(LANES), required=True)
    round_cmd.add_argument("--round", dest="round_number", type=positive_int, required=True)
    round_cmd.add_argument(
        "--question",
        action="append",
        default=[],
        help="One question of the round; repeat for each question (numbered Q1.. in order)",
    )
    round_cmd.add_argument(
        "--question-file",
        action="append",
        default=[],
        help="File containing one question; repeatable, ordered after any --question",
    )
    round_cmd.add_argument("--out", help="Prompt path. Defaults to run-dir/prompts/round-<N>-<lane>.md")
    round_cmd.add_argument(
        "--report-path",
        help="Report handoff path. Defaults to run-dir/reports/round-<N>-<lane>.md",
    )
    round_cmd.add_argument(
        "--draft-path",
        help=(
            "Self-validation draft path; must resolve inside run-dir/drafts/. "
            "Defaults to run-dir/drafts/round-<N>-<lane>.md"
        ),
    )

    round_cmd.add_argument("--context-digest", type=Path, help="Authored neutral earlier-round digest, at most 16 KiB UTF-8")
    return parser


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("--round must be >= 1")
    return number


def main() -> int:
    args = build_parser().parse_args()
    run_dir = Path(args.run_dir)
    state = read_run_state(run_dir)
    if args.round_number > int(state["max_rounds"]):
        raise SystemExit(f"round {args.round_number} exceeds max_rounds {state['max_rounds']}")
    questions = [text.strip() for text in args.question] + [
        read_text(Path(path)).strip() for path in args.question_file
    ]
    if not questions:
        raise SystemExit("At least one --question or --question-file is required")
    if any(not question for question in questions):
        raise SystemExit("Question text is empty")
    out = Path(args.out) if args.out else round_prompt_path(run_dir, args.round_number, args.lane)
    report_path = (Path(args.report_path) if args.report_path
                   else round_report_path(run_dir, args.round_number, args.lane))
    draft_path = Path(args.draft_path) if args.draft_path else run_dir / "drafts" / f"round-{args.round_number}-{args.lane}.md"
    try:
        prompt = render_round(
            args.lane, state, run_dir, args.round_number, questions, report_path, draft_path, args.context_digest
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    report_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(out)
    return 0


def render_round(
    lane: str, state: dict, run_dir: Path, round_number: int, questions: list[str],
    report_path: Path, draft_path: Path | None = None, context_digest: Path | None = None,
) -> str:
    if not questions:
        raise ValueError("A round needs at least one question")
    if draft_path is None:
        draft_path = run_dir / "drafts" / f"round-{round_number}-{lane}.md"
    resolved_draft = draft_path.resolve()
    if resolved_draft == report_path.resolve():
        raise ValueError("Draft path must differ from the report handoff path")
    if run_dir.resolve() not in resolved_draft.parents:
        raise ValueError("Draft path must be inside the run directory")
    # Keeps an override off run state, prompts, and other lanes' reports.
    if (run_dir / "drafts").resolve() not in resolved_draft.parents:
        raise ValueError("Draft path must be inside the run-local drafts directory")
    context_path = render_context(run_dir, round_number, questions, context_digest)
    marker = round_marker_path(run_dir, round_number, lane)
    task = read_text(run_dir / str(state["task_file"])).rstrip()
    count = len(questions)
    listing = "\n\n".join(f"### Q{number}\n\n{question}" for number, question in enumerate(questions, start=1))
    return f"""# Round {round_number} Questions — lane {lane}

## First Step

Before doing anything else, create or overwrite `{marker}`. Create its parent directory
if necessary and refresh its modification time even if it already exists.

This file is your round task, not a document to summarize. Answer the questions now and write
your report to the handoff path below.

Run: {state["run_id"]}
Created: {utc_now()}

{LANE_RULES[lane]}

Answer every question independently on its own evidence: Q2's answer must not shape Q1's.
Do not reuse an earlier round's conclusion without re-verifying it. Read `{context_path}`
as context to re-verify, not evidence. Never read earlier lane reports or per-lane findings.
You never talk to the user. Answer now; after writing the report stay idle for a possible
re-emission. Do not invent follow-up work.

## Boundaries

{INDEX_HEAD_PROHIBITION}

Read-only research: never create, edit, or delete repository files or run state-changing
commands. The only allowed writes are the round marker `{marker}`, draft `{draft_path}`,
and report handoff `{report_path}`. Do not write other orchestration lifecycle state.
Return `NO ANSWER` with an explanation when the question is outside this lane's sources.
Report `BLOCKER` if the environment is broken. If the premise is stale or wrong, give the
smallest accurate correction under `### Plan Drift`.

## Task Under Grilling

{fenced_content(task, "markdown")}

## Questions ({count})

{listing}

## Handoff

{INDEX_HEAD_PROHIBITION}

- Draft path: `{draft_path}`
- Report handoff path: `{report_path}`
- Earlier-round context: `{context_path}`

Write your final report to the handoff path:
exactly one `## Q<n>` block per question, Q1..Q{count}, each with its own sections.
Before writing it, self-validate your draft with

```bash
python3 {shlex.quote(parser_path())} {shlex.quote(str(draft_path))} --questions {count}
```

A well-formed report prints `gate=advance` (or `blocked`/`hitl` if you are genuinely
reporting a blocker or plan drift). Fix the format, never the substance.

{contract_block()}"""


def contract_block() -> str:
    return f"""## Research Report Contract

The report holds one `## Q<n>` block per round question, numbered as in the round prompt. Every
section below except `### Notes` is required in every block. Emit exactly one token under
`### Result` — not the `|` menu. An omitted or empty required section, or a missing question block,
is treated as a malformed report; it never reads as `None`. Each question is gated on its own.

```markdown
## Q1
### Result
ANSWERED

### Answer
Your finding in prose. For NO ANSWER: why this lane cannot answer the question.

### Sources
- relative/repo/path or URL

### Method
- what you searched, read, or ran: outcome

### Blockers
- None

### Plan Drift
- None

### Notes
- Optional: caveats, confidence hints, context. Never load-bearing evidence.

## Q2
### Result
...
```

Allowed `### Result` values: `ANSWERED`, `NO ANSWER`, `BLOCKER`.

Formatting rules the gate parser enforces:

- Use `## Q<n>` for question blocks and `###` for the sections inside; no other `##` headings.
- In `### Sources`, `### Blockers`, and `### Plan Drift`, an empty section is exactly the line `- None` —
  no prose on or after that line. Explanations belong in `### Answer` or `### Notes`.
- `ANSWERED` requires at least one real source; an ungrounded answer is gated `stop`.
- `NO ANSWER` requires an explanation under `### Answer` and allows `### Sources: - None`.
- `### Method` must list what you actually searched or read, even when the result is `NO ANSWER`.

Before returning, self-validate: write your draft report to the draft path named in each round prompt
and run

```bash
python3 {shlex.quote(parser_path())} <draft-path-named-in-round-prompt> --questions <number-of-questions>
```

A clean report must print `gate=advance`. If you are genuinely reporting a blocker or plan drift,
`blocked`/`hitl` is expected — anything else means your report is malformed. Fix the format, never the
substance.
"""


if __name__ == "__main__":
    raise SystemExit(main())
