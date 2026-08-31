#!/usr/bin/env python3
"""Deterministic specification and planning-report contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from orchestrator_lib import sha256_bytes, sha256_file


SPEC_SECTIONS = (
    "Problem Statement",
    "Solution",
    "User Stories",
    "Implementation Decisions",
    "Testing Decisions",
    "Assumptions",
    "Open Decisions",
    "Out of Scope",
    "Further Notes",
)
AUTHOR_REPORT_SECTIONS = (
    "Result",
    "Repository Sources / Methods",
    "Proposed Test Seams",
    "Blockers",
    "Plan Drift",
    "Draft Path",
)
REVIEW_REPORT_SECTIONS = (
    "Verdict",
    "Findings",
    "Methods",
    "Input Identity",
    "Resulting Candidate Identity",
    "Corrections",
    "Blockers",
    "Plan Drift",
)
DIGEST_RE = re.compile(r"\b[0-9a-f]{64}\b")


class ContractError(ValueError):
    pass


def mask_fences(markdown: str) -> str:
    """A same-length copy with fenced blocks blanked, so heading offsets still index the
    original. The rendered prompts hand workers fenced blocks full of `##` contract headings;
    scanning them as real sections turns a quoted contract into a duplicate-section error."""
    lines = markdown.split("\n")
    fence: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                lines[index] = " " * len(line)
            continue
        lines[index] = " " * len(line)
        if stripped.startswith(fence) and not stripped.strip(fence[0]).strip():
            fence = None
    return "\n".join(lines)


def sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", mask_fences(markdown), re.MULTILINE))
    parsed: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        if name in parsed:
            raise ContractError(f"duplicate section: {name}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        parsed[name] = markdown[match.end() : end].strip()
    return parsed


def require_sections(parsed: dict[str, str], required: tuple[str, ...], label: str) -> None:
    missing = [name for name in required if not parsed.get(name, "").strip()]
    if missing:
        raise ContractError(f"{label} has missing or empty sections: {', '.join(missing)}")


def is_none(body: str) -> bool:
    return body.strip() == "- None"


def bullet_count(body: str) -> int:
    return len(re.findall(r"^[-*]\s+\S", body, re.MULTILINE))


def validate_spec(path: Path, *, require_closed_decisions: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"specification is missing: {path}")
    raw = path.read_bytes()
    parsed = sections(raw.decode("utf-8"))
    require_sections(parsed, SPEC_SECTIONS, "specification")
    if bullet_count(parsed["User Stories"]) < 1:
        raise ContractError("User Stories must contain at least one list item")
    testing = parsed["Testing Decisions"]
    for marker in ("Existing seam:", "Prior-art test:", "Verification:"):
        if marker not in testing:
            raise ContractError(f"Testing Decisions must identify {marker.rstrip(':').lower()}")
    if "New seam:" in testing and "Justification:" not in testing:
        raise ContractError("a proposed New seam requires a Justification")
    has_open = not is_none(parsed["Open Decisions"])
    if require_closed_decisions and has_open:
        raise ContractError("reviewed specification still contains an Open Decision")
    return {"sha256": sha256_bytes(raw), "has_open_decisions": has_open, "sections": parsed}


def validate_author_report(report_path: Path, expected_draft: Path) -> dict[str, Any]:
    if not report_path.is_file():
        raise ContractError(f"author report is missing: {report_path}")
    parsed = sections(report_path.read_text(encoding="utf-8"))
    require_sections(parsed, AUTHOR_REPORT_SECTIONS, "author report")
    result = parsed["Result"]
    if result not in {"PASS", "BLOCKED"}:
        raise ContractError("author Result must be exactly PASS or BLOCKED")
    if result == "PASS":
        if not is_none(parsed["Blockers"]) or not is_none(parsed["Plan Drift"]):
            raise ContractError("a passing author report cannot contain blockers or plan drift")
        if is_none(parsed["Repository Sources / Methods"]) or bullet_count(parsed["Repository Sources / Methods"]) < 1:
            raise ContractError("passing author report is ungrounded: no repository source/method")
        if is_none(parsed["Proposed Test Seams"]) or bullet_count(parsed["Proposed Test Seams"]) < 1:
            raise ContractError("passing author report has no proposed test seam")
    elif is_none(parsed["Blockers"]):
        raise ContractError("a BLOCKED author report must state a blocker")
    reported_path = parsed["Draft Path"].strip().strip("`")
    if Path(reported_path).resolve() != expected_draft.resolve():
        raise ContractError(
            f"author report draft path mismatch: expected {expected_draft}, got {reported_path}"
        )
    if result == "BLOCKED":
        # A real blocker stops the author before a complete draft exists, so the draft contract is
        # not enforced here; accept_author routes this to the blocked gate instead of review.
        return {"result": result, "draft": str(expected_draft), "draft_sha256": None}
    spec = validate_spec(expected_draft)
    return {"result": result, "draft": str(expected_draft), "draft_sha256": spec["sha256"]}


def one_digest(body: str, label: str) -> str:
    digests = DIGEST_RE.findall(body)
    if len(digests) != 1:
        raise ContractError(f"{label} must contain exactly one SHA-256 digest")
    return digests[0]


def validate_review_report(
    report_path: Path,
    input_spec: Path,
    reviewed_candidate: Path,
    *,
    expected_input_sha256: str | None = None,
) -> dict[str, Any]:
    if not report_path.is_file():
        raise ContractError(f"review report is missing: {report_path}")
    parsed = sections(report_path.read_text(encoding="utf-8"))
    require_sections(parsed, REVIEW_REPORT_SECTIONS, "review report")
    verdict = parsed["Verdict"]
    if verdict not in {"pass", "pass_with_fixes", "blocked"}:
        raise ContractError("review Verdict must be pass, pass_with_fixes, or blocked")
    input_digest = sha256_file(input_spec)
    # Against the digest the author gate recorded, not just against itself: the draft lives in
    # the run directory, where the Git-visible detector cannot see a reviewer rewriting it.
    if expected_input_sha256 is not None and input_digest != expected_input_sha256:
        raise ContractError("the author draft changed after its own gate; review is not bound to it")
    if one_digest(parsed["Input Identity"], "Input Identity") != input_digest:
        raise ContractError("review Input Identity is not bound to the author draft")
    if bullet_count(parsed["Methods"]) < 1:
        raise ContractError("review report is ungrounded: Methods has no concrete entry")

    if verdict == "blocked":
        if is_none(parsed["Blockers"]):
            raise ContractError("blocked review must state the product/scope decision required")
        if reviewed_candidate.exists():
            raise ContractError("blocked review must not supply an approval candidate")
        return {"verdict": verdict, "input_sha256": input_digest, "gate": "blocked"}

    if not is_none(parsed["Blockers"]) or not is_none(parsed["Plan Drift"]):
        raise ContractError("passing review cannot contain blockers or plan drift")
    if verdict == "pass":
        if not is_none(parsed["Findings"]):
            raise ContractError("pass cannot retain review findings")
        if reviewed_candidate.exists():
            raise ContractError("pass must reference the unchanged draft, not write a candidate")
        candidate = input_spec
        if not is_none(parsed["Corrections"]):
            raise ContractError("pass cannot report corrections")
    else:
        if not reviewed_candidate.is_file():
            raise ContractError("pass_with_fixes requires the complete reviewed candidate")
        if is_none(parsed["Corrections"]):
            raise ContractError("pass_with_fixes requires a structured correction summary")
        candidate = reviewed_candidate
    # `pass` keeps the input spec as its candidate, so its digest is already in hand.
    candidate_digest = input_digest if candidate == input_spec else sha256_file(candidate)
    if one_digest(parsed["Resulting Candidate Identity"], "Resulting Candidate Identity") != candidate_digest:
        raise ContractError("review Resulting Candidate Identity does not match the candidate")
    if verdict == "pass" and candidate_digest != input_digest:
        raise ContractError("pass must preserve the unchanged draft digest")
    validate_spec(candidate, require_closed_decisions=True)
    return {
        "verdict": verdict,
        "input_sha256": input_digest,
        # Resolved, because approval reopens it from whatever cwd the human runs it in.
        "candidate": str(candidate.resolve()),
        "candidate_sha256": candidate_digest,
        "gate": "advance",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    spec = subparsers.add_parser("spec")
    spec.add_argument("path")
    spec.add_argument("--closed", action="store_true")
    author = subparsers.add_parser("author-report")
    author.add_argument("report")
    author.add_argument("--draft", required=True)
    review = subparsers.add_parser("review-report")
    review.add_argument("report")
    review.add_argument("--input", required=True)
    review.add_argument("--candidate", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "spec":
            result = validate_spec(Path(args.path), require_closed_decisions=args.closed)
        elif args.command == "author-report":
            result = validate_author_report(Path(args.report), Path(args.draft))
        else:
            result = validate_review_report(Path(args.report), Path(args.input), Path(args.candidate))
        print(json.dumps(result, sort_keys=True, default=str))
        return 0 if result.get("gate") != "blocked" and result.get("result") != "BLOCKED" else 2
    except (ContractError, OSError, UnicodeError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
