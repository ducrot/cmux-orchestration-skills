"""Validation of the review and open-fact extension to a grilling artifact pair."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


REVIEW_LABELS = {
    "unreviewed": "ungeprüft", "confirmed": "bestätigt",
    "corrected": "korrigiert", "discarded": "verworfen",
}


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def timestamp(value: object) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def extension_summary(data: dict) -> str:
    if "assumption_review" not in data:
        return ""
    return f" assumption_review={len(data['assumption_review'])} open_facts={len(data.get('open_facts', []))}"


def validate_review(review: object, index: int) -> list[str]:
    prefix = f"assumption_review entry {index}"
    if not isinstance(review, dict):
        return [f"{prefix}: must be an object"]
    problems = []
    if type(review.get("index")) is not int or review["index"] != index:
        problems.append(f"{prefix}: index must be {index} (one-based, in assumption order)")
    outcome = review.get("outcome")
    if not isinstance(outcome, str) or outcome not in REVIEW_LABELS:
        problems.append(f"{prefix}: unknown outcome")
    problems += [f"{prefix}: {field} must be a string" for field in ("corrected_text", "reason", "reviewed_at")
                 if not isinstance(review.get(field), str)]
    if outcome in ("corrected", "discarded") and not nonempty(review.get("reason")):
        problems.append(f"{prefix}: {outcome} needs a reason")
    if outcome == "corrected" and not nonempty(review.get("corrected_text")):
        problems.append(f"{prefix}: corrected needs corrected_text")
    if outcome == "unreviewed":
        if any(review.get(field) for field in ("corrected_text", "reason", "reviewed_at")):
            problems.append(f"{prefix}: unreviewed fields must be empty")
    elif not timestamp(review.get("reviewed_at")):
        problems.append(f"{prefix}: reviewed_at must be an ISO timestamp with timezone")
    return problems


def validate_fact(fact: dict, prefix: str) -> list[str]:
    problems = [f"{prefix}: {field} must be a non-empty string" for field in ("id", "question", "why_needed")
                if not nonempty(fact.get(field))]
    problems += [f"{prefix}: {field} must be a string" for field in ("answer", "answered_at")
                 if not isinstance(fact.get(field), str)]
    if fact.get("status") == "answered":
        if not nonempty(fact.get("answer")) or not timestamp(fact.get("answered_at")):
            problems.append(f"{prefix}: answered needs answer and ISO answered_at with timezone")
    elif fact.get("status") == "open":
        if fact.get("answer") or fact.get("answered_at"):
            problems.append(f"{prefix}: open answer and answered_at must be empty")
    else:
        problems.append(f"{prefix}: status must be open|answered")
    return problems


def validate_extension(data: dict, artifact_path: Path) -> list[str]:
    """Legacy artifacts skip the extension; new artifacts must provide both lists."""
    if "assumption_review" not in data and "open_facts" not in data:
        return []
    problems = [f"{name}: must be a list" for name in ("assumptions", "assumption_review", "open_facts")
                if not isinstance(data.get(name), list)]
    if problems:
        return problems
    assumptions, reviews, facts = data["assumptions"], data["assumption_review"], data["open_facts"]
    if len(reviews) != len(assumptions):
        problems.append("assumption_review: length must match assumptions (one entry per assumption)")
    for index, text in enumerate(assumptions, 1):
        if not nonempty(text) or "\n" in text or "\r" in text:
            problems.append(f"assumptions entry {index}: must be a non-empty single-line string")
    for index, review in enumerate(reviews, 1):
        problems += validate_review(review, index)
    seen = set()
    for index, fact in enumerate(facts, 1):
        prefix = f"open_facts entry {index}"
        if not isinstance(fact, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        if nonempty(fact.get("id")):
            prefix += f" ({fact['id']})"
            if fact["id"] in seen:
                problems.append(f"{prefix}: duplicate id")
            seen.add(fact["id"])
        problems += validate_fact(fact, prefix)
    if problems:
        return problems
    markdown_path = data.get("markdownPath", str(artifact_path.with_suffix(".md")))
    if not nonempty(markdown_path):
        return ["Markdown: markdownPath must be a non-empty path"]
    try:
        markdown = Path(markdown_path).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [f"Markdown {markdown_path}: {error}"]
    try:
        assumption_lines = section_lines(markdown, "Definierte Annahmen", r"\d+\. ")
        fact_lines = section_lines(markdown, "Offene Fakten", r"- ")
    except ValueError as error:
        return [str(error)]
    if len(assumption_lines) != len(assumptions):
        problems.append("assumption_review Markdown: assumption line count disagrees")
    for index, (line, text, review) in enumerate(zip(assumption_lines, assumptions, reviews), 1):
        prefix = f"{index}. {text} [Prüfung: "
        expected = {"Ergebnis": REVIEW_LABELS[review["outcome"]],
                    "Korrektur": review["corrected_text"], "Grund": review["reason"]}
        if not (line.startswith(prefix) and line.endswith("]") and json_equals(line[len(prefix):-1], expected)):
            problems.append(f"assumption_review entry {index}: Markdown text or review marker disagrees")
    if len(fact_lines) != len(facts):
        problems.append("open_facts Markdown: fact line count disagrees")
    for index, (line, fact) in enumerate(zip(fact_lines, facts), 1):
        if not (line.startswith("- ") and json_equals(line[2:], fact)):
            problems.append(f"open_facts entry {index} ({fact['id']}): Markdown disagrees")
    return problems


def json_equals(text: str, expected: object) -> bool:
    try:
        return json.loads(text) == expected
    except ValueError:
        return False


def section_lines(markdown: str, heading: str, entry: str) -> list[str]:
    matches = list(re.finditer(rf"^## {re.escape(heading)}\s*$", markdown, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f"Markdown: expected exactly one ## {heading} section")
    tail = markdown[matches[0].end():]
    body = re.split(r"^#{1,2} ", tail, maxsplit=1, flags=re.MULTILINE)[0]
    return [line.rstrip() for line in body.splitlines() if re.match(entry, line)]
