#!/usr/bin/env python3
"""Parse a worker report and evaluate the orchestration gate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)

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
REQUIRED_SECTIONS = ("result", "blockers", "plan drift")

NONEISH = {"", "none", "none.", "n/a", "no", "not run"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = Path(args.report)
    # A worker that has not finished yet is pending, not failing.
    payload = pending_payload(path) if not path.is_file() else parse_report(path.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"gate={payload['gate']} result={payload['result']} "
            f"tests={payload['has_tests']} findings={payload['has_findings']} "
            f"blockers={payload['has_blockers']} plan_drift={payload['has_plan_drift']}"
        )
        for reason in payload["reasons"]:
            print(f"  - {reason}")
    return EXIT_CODES[payload["gate"]]


def pending_payload(path: Path) -> dict:
    return {
        "result": "PENDING",
        "has_tests": False,
        "has_findings": False,
        "has_blockers": False,
        "has_plan_drift": False,
        "missing_sections": list(REQUIRED_SECTIONS),
        "malformed": False,
        "gate": PENDING,
        "reasons": [f"report not written yet: {path}"],
        "sections": [],
    }


def parse_report(text: str) -> dict:
    sections = split_sections(text)
    missing = [name for name in REQUIRED_SECTIONS if not sections.get(name, "").strip()]

    result_text = sections.get("result", "")
    tests_text = sections.get("tests / checks", "") or sections.get("tests", "") or sections.get("checks", "")
    findings_text = sections.get("findings", "")
    blockers_text = sections.get("blockers", "")
    drift_text = sections.get("plan drift", "")

    result = classify_result(result_text)
    has_tests = has_substantive_list(tests_text)
    has_findings = not is_noneish(findings_text)
    has_blockers = result == "BLOCKER" or not is_noneish(blockers_text)
    has_plan_drift = "PLAN DRIFT" in result_text.upper() or not is_noneish(drift_text)

    candidates = [ADVANCE]
    reasons: list[str] = []

    if missing:
        candidates.append(HITL)
        reasons.append(f"malformed report: missing or empty sections: {', '.join(missing)}")
    if result != "NO FINDINGS":
        candidates.append(STOP)
        reasons.append(f"result is {result}")
    if not has_tests:
        candidates.append(STOP)
        reasons.append("missing tests/checks")
    if has_findings:
        candidates.append(STOP)
        reasons.append("findings present")
    if has_plan_drift:
        candidates.append(HITL)
        reasons.append("plan drift present")
    if has_blockers:
        candidates.append(BLOCKED)
        reasons.append("blocker present")

    return {
        "result": result,
        "has_tests": has_tests,
        "has_findings": has_findings,
        "has_blockers": has_blockers,
        "has_plan_drift": has_plan_drift,
        "missing_sections": missing,
        "malformed": bool(missing),
        "gate": max(candidates, key=SEVERITY.__getitem__),
        "reasons": reasons,
        "sections": sorted(sections),
    }


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
    body invents blockers that no worker reported.
    """
    line = next((raw.strip() for raw in text.splitlines() if raw.strip()), "")
    upper = line.upper()
    if "|" in upper:
        # The unfilled contract template: `NO FINDINGS | FINDINGS | BLOCKER`.
        return "UNKNOWN"
    for label in ("NO FINDINGS", "BLOCKER", "FINDINGS"):
        if upper.startswith(label):
            return label
    return "UNKNOWN"


def has_substantive_list(text: str) -> bool:
    if is_noneish(text):
        return False
    return bool(re.search(r"(^|\n)\s*[-*]\s+`?[^`\n]+`?:\s*\S+", text))


def is_noneish(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return all(re.sub(r"^[\s\-*]+", "", line).strip().lower() in NONEISH for line in stripped.splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
