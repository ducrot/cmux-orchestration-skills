#!/usr/bin/env python3
"""Render deterministic prompts for the persistent research lanes.

`session` renders a lane's standing onboarding prompt (sent once at lane launch).
`round` renders the small per-round question prompt for one lane.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator_lib import LANES, read_json, read_text, utc_now


LANE_RULES = {
    "codebase": (
        "You are the codebase researcher. Answer every question exclusively from this "
        "repository: source code, configuration, local docs, and git history. Use read-only "
        "repo tools (Read, Grep, Glob, read-only git commands). Do not use web search or web "
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

    session = subparsers.add_parser("session", help="Render a lane's standing session prompt")
    session.add_argument("--run-dir", required=True)
    session.add_argument("--lane", choices=sorted(LANES), required=True)
    session.add_argument("--out", help="Prompt path. Defaults to run-dir/prompts/session-<lane>.md")

    round_cmd = subparsers.add_parser("round", help="Render a lane's per-round question prompt")
    round_cmd.add_argument("--run-dir", required=True)
    round_cmd.add_argument("--lane", choices=sorted(LANES), required=True)
    round_cmd.add_argument("--round", dest="round_number", type=positive_int, required=True)
    question_source = round_cmd.add_mutually_exclusive_group(required=True)
    question_source.add_argument("--question", help="The round's question text")
    question_source.add_argument("--question-file", help="File containing the round's question text")
    round_cmd.add_argument("--out", help="Prompt path. Defaults to run-dir/prompts/round-<N>-<lane>.md")
    round_cmd.add_argument(
        "--report-path",
        help="Report handoff path. Defaults to run-dir/reports/round-<N>-<lane>.md",
    )

    return parser


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("--round must be >= 1")
    return number


def main() -> int:
    args = build_parser().parse_args()
    run_dir = Path(args.run_dir)
    state = read_json(run_dir / "state.json")
    if args.command == "session":
        out = Path(args.out) if args.out else run_dir / "prompts" / f"session-{args.lane}.md"
        prompt = render_session(args.lane, state, run_dir)
    else:
        if args.round_number > int(state["max_questions"]):
            raise SystemExit(f"round {args.round_number} exceeds max_questions {state['max_questions']}")
        question = read_text(Path(args.question_file)).strip() if args.question_file else args.question.strip()
        if not question:
            raise SystemExit("Question text is empty")
        stem = f"round-{args.round_number}-{args.lane}"
        out = Path(args.out) if args.out else run_dir / "prompts" / f"{stem}.md"
        report_path = Path(args.report_path) if args.report_path else run_dir / "reports" / f"{stem}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = render_round(args.lane, state, run_dir, args.round_number, question, report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(out)
    return 0


def render_session(lane: str, state: dict, run_dir: Path) -> str:
    task = read_text(run_dir / str(state["task_file"])).rstrip()
    return f"""# Research Lane Prompt: {lane} ({LANES[lane]["label"]})

This file is your standing contract for the session, not a document to summarize. Adopt it,
confirm in one line, then wait for round prompts.

Created: {utc_now()}
Run: {state["run_id"]}
Max questions: {state["max_questions"]}

{LANE_RULES[lane]}

## Session Shape

- You are one of four persistent research lanes in an autonomous grilling session. The
  orchestrator grills the task below with one decision-level question per round and sends
  each question to you as a small prompt file.
- Answer every question independently on its own evidence. Do not reuse an earlier round's
  conclusion without re-verifying it; earlier answers are context, not sources.
- You never talk to the user. The orchestrator synthesizes all lane reports; your report is
  raw research input, not a message to a human.
- After finishing a round, wait idle for the next round prompt. Do not invent follow-up work.

## Boundaries

- Read-only research: never create, edit, or delete repository files, and never run
  state-changing commands.
- The only file you may write is the report handoff path named in each round prompt
  (report capture is explicitly delegated to you). Do not write any other orchestration
  lifecycle state.
- If a question cannot be answered from this lane's sources, return `NO ANSWER` and explain
  why under `## Answer` — that is a valid, expected outcome, not a failure.
- If your environment is broken (repo unreadable, tools unavailable), report `BLOCKER`.
- If research shows the task's premise is stale or wrong (the plan contradicts what exists),
  report the smallest accurate correction under `## Plan Drift`.

## Task Under Grilling

```markdown
{task}
```

{contract_block()}"""


def render_round(lane: str, state: dict, run_dir: Path, round_number: int, question: str, report_path: Path) -> str:
    session_prompt = run_dir / "prompts" / f"session-{lane}.md"
    return f"""# Round {round_number} Question — lane {lane}

This file is your round task, not a document to summarize. Answer the question now and write
your report to the handoff path below.

Run: {state["run_id"]}
Created: {utc_now()}

## Question

{question}

## Handoff

- Report handoff path: `{report_path}`
- Standing session contract: `{session_prompt}`

Answer per your standing session contract, then write your final report to the handoff path.
Before writing it, self-validate your draft with

```bash
python3 {parser_path()} <your-draft-file>
```

A well-formed report prints `gate=advance` (or `blocked`/`hitl` if you are genuinely
reporting a blocker or plan drift). Fix the format, never the substance.
"""


def contract_block() -> str:
    return f"""## Research Report Contract

Every section below except `## Notes` is required. Emit exactly one token under `## Result` — not the `|`
menu. An omitted or empty required section is treated as a malformed report and stops the session as HITL;
it never reads as `None`.

```markdown
## Result
ANSWERED

## Answer
Your finding in prose. For NO ANSWER: why this lane cannot answer the question.

## Sources
- relative/repo/path or URL

## Method
- what you searched, read, or ran: outcome

## Blockers
- None

## Plan Drift
- None

## Notes
- Optional: caveats, confidence hints, context. Never load-bearing evidence.
```

Allowed `## Result` values: `ANSWERED`, `NO ANSWER`, `BLOCKER`.

Formatting rules the gate parser enforces:

- In `## Sources`, `## Blockers`, and `## Plan Drift`, an empty section is exactly the line `- None` —
  no prose on or after that line. Explanations belong in `## Answer` or `## Notes`.
- `ANSWERED` requires at least one real source; an ungrounded answer is gated `stop`.
- `NO ANSWER` requires an explanation under `## Answer` and allows `## Sources: - None`.
- `## Method` must list what you actually searched or read, even when the result is `NO ANSWER`.

Before returning, self-validate: write your draft report to a temporary file of your own (not the handoff
path) and run

```bash
python3 {parser_path()} <your-draft-file>
```

A clean report must print `gate=advance`. If you are genuinely reporting a blocker or plan drift,
`blocked`/`hitl` is expected — anything else means your report is malformed. Fix the format, never the
substance.
"""


if __name__ == "__main__":
    raise SystemExit(main())
