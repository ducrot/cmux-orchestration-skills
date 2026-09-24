#!/usr/bin/env python3
"""Parse a research lane report and evaluate the orchestration gate per question.

A report holds one `## Q<n>` block per round question. The gate checks form, not research
quality: a well-formed `NO ANSWER` advances — an empty finding is a content signal for the
synthesizer, never a gate failure. The report gate is the most severe question gate.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


QUESTION_RE = re.compile(r"^##\s+(?P<id>Q[1-9][0-9]*)\b[^\n]*$", re.MULTILINE)
TOP_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)
SECTION_RE = re.compile(r"^###\s+(?P<name>.+?)\s*$", re.MULTILINE)

ADVANCE = "advance"
STOP = "stop"
HITL = "hitl"
BLOCKED = "blocked"
PENDING = "pending"

# The gate is the max severity of all triggered conditions, never the last one checked.
SEVERITY = {ADVANCE: 0, STOP: 1, HITL: 2, BLOCKED: 3}

# 1 is an unexpected crash, 2 is argparse's usage error. Keep both free.
EXIT_CODES = {ADVANCE: 0, STOP: 3, BLOCKED: 4, HITL: 5, PENDING: 6}

# Absent or empty, these mean "malformed", never "None".
REQUIRED_SECTIONS = ("result", "answer", "sources", "method", "blockers", "plan drift")

RESULT_LABELS = ("ANSWERED", "NO ANSWER", "BLOCKER")

NONEISH = {"", "none", "none.", "n/a", "no", "not run"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument(
        "--questions",
        type=int,
        required=True,
        help="Number of questions the round asked; blocks Q1..QN are expected",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = Path(args.report)
    # A lane that has not finished yet is pending, not failing.
    if args.questions < 1:
        raise SystemExit("--questions must be >= 1")
    if path.is_file():
        payload = parse_report(path.read_text(encoding="utf-8"), args.questions)
    else:
        payload = pending_payload(path)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"gate={payload['gate']} questions={len(payload['questions'])}")
        for question in payload["questions"]:
            print(
                f"  {question['id']} gate={question['gate']} result={question['result']} "
                f"answer={question['has_answer']} sources={question['has_sources']} "
                f"method={question['has_method']} blockers={question['has_blockers']} "
                f"plan_drift={question['has_plan_drift']}"
            )
        for reason in payload["reasons"]:
            print(f"  - {reason}")
    return EXIT_CODES[payload["gate"]]


def pending_payload(path: Path) -> dict:
    return {
        "gate": PENDING,
        "malformed": False,
        "questions": [],
        "reasons": [f"report not written yet: {path}"],
    }


def parse_report(text: str, expected: int) -> dict:
    """Gate every question block; blocks Q1..Q<expected> are demanded, so a gap never passes."""
    if expected < 1:
        raise ValueError("expected must be >= 1")
    blocks, duplicates = split_questions(text)
    ids = [f"Q{number}" for number in range(1, expected + 1)]
    reasons: list[str] = []
    candidates = [ADVANCE]

    questions = []
    for question_id in ids:
        if question_id in blocks:
            questions.append(parse_question(question_id, blocks[question_id]))
        else:
            questions.append(missing_question(question_id))
    unexpected = sorted(set(blocks) - set(ids), key=question_number)

    if duplicates:
        candidates.append(HITL)
        reasons.append(f"malformed report: duplicate question blocks: {', '.join(duplicates)}")
    if unexpected:
        candidates.append(HITL)
        reasons.append(f"malformed report: unexpected question blocks: {', '.join(unexpected)}")
    for question in questions:
        candidates.append(question["gate"])
        reasons.extend(f"{question['id']}: {reason}" for reason in question["reasons"])

    return {
        "gate": max(candidates, key=SEVERITY.__getitem__),
        "malformed": any(question["malformed"] for question in questions) or bool(duplicates or unexpected),
        "questions": questions,
        "reasons": reasons,
    }


def parse_question(question_id: str, block: str) -> dict:
    sections = split_sections(block)
    missing = [name for name in REQUIRED_SECTIONS if not sections.get(name, "").strip()]

    result = classify_result(sections.get("result", ""))
    has_answer = not is_noneish(sections.get("answer", ""))
    has_sources = not is_noneish(sections.get("sources", ""))
    has_method = not is_noneish(sections.get("method", ""))
    has_blockers = result == "BLOCKER" or not is_noneish(sections.get("blockers", ""))
    has_plan_drift = not is_noneish(sections.get("plan drift", ""))

    candidates = [ADVANCE]
    reasons: list[str] = []

    if missing:
        candidates.append(HITL)
        reasons.append(f"malformed report: missing or empty sections: {', '.join(missing)}")
    if result not in RESULT_LABELS:
        candidates.append(STOP)
        reasons.append(f"result is {result}")
    if result in ("ANSWERED", "NO ANSWER") and not has_answer:
        candidates.append(STOP)
        reasons.append(f"{result} without answer text")
    if result == "ANSWERED" and not has_sources:
        candidates.append(STOP)
        reasons.append("ANSWERED without sources")
    if not has_method:
        candidates.append(STOP)
        reasons.append("missing method")
    if has_plan_drift:
        candidates.append(HITL)
        reasons.append("plan drift present")
    if has_blockers:
        candidates.append(BLOCKED)
        reasons.append("blocker present")

    return {
        "id": question_id,
        "result": result,
        "has_answer": has_answer,
        "has_sources": has_sources,
        "has_method": has_method,
        "has_blockers": has_blockers,
        "has_plan_drift": has_plan_drift,
        "missing_sections": missing,
        "malformed": bool(missing),
        "gate": max(candidates, key=SEVERITY.__getitem__),
        "reasons": reasons,
        "sections": sorted(sections),
    }


def missing_question(question_id: str) -> dict:
    return {
        "id": question_id,
        "result": "MISSING",
        "has_answer": False,
        "has_sources": False,
        "has_method": False,
        "has_blockers": False,
        "has_plan_drift": False,
        "missing_sections": list(REQUIRED_SECTIONS),
        "malformed": True,
        "gate": HITL,
        "reasons": [f"malformed report: question block {question_id} is missing"],
        "sections": [],
    }


def question_number(question_id: str) -> int:
    return int(question_id[1:])


def split_questions(text: str) -> tuple[dict[str, str], list[str]]:
    """Question blocks by id, plus the ids that appear more than once."""
    matches = list(QUESTION_RE.finditer(text))
    blocks: dict[str, str] = {}
    duplicates: list[str] = []
    for match in matches:
        # A block ends at the next `##` heading, so a trailing `## Notes` never joins a section.
        following = TOP_HEADING_RE.search(text, match.end())
        end = following.start() if following else len(text)
        question_id = match.group("id")
        if question_id in blocks:
            if question_id not in duplicates:
                duplicates.append(question_id)
            continue
        blocks[question_id] = text[match.end():end]
    return blocks, duplicates


def split_sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("name").strip().lower()] = text[start:end].strip()
    return sections


def classify_result(text: str) -> str:
    """Classify the Result section by its first line, never by substring over the document.

    `## Blockers` contains the substring `BLOCKER`, so scanning wider than the Result
    body invents blockers that no lane reported.
    """
    line = next((raw.strip() for raw in text.splitlines() if raw.strip()), "")
    upper = line.upper()
    if "|" in upper:
        # The unfilled contract template: `ANSWERED | NO ANSWER | BLOCKER`.
        return "UNKNOWN"
    for label in ("NO ANSWER", "ANSWERED", "BLOCKER"):
        if upper.startswith(label):
            return label
    return "UNKNOWN"


def is_noneish(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return all(re.sub(r"^[\s\-*]+", "", line).strip().lower() in NONEISH for line in stripped.splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
