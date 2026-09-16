#!/usr/bin/env python3
"""Adopt a `to-tickets` issue directory into the tracker shape this skill orchestrates.

Rewrites issue files in place — filenames are never changed, so the other skills that
address tickets by their `NN-slug.md` path keep working. Idempotent: files that already
carry frontmatter are left untouched.

    python3 scripts/adopt_tracker.py --tracker .scratch/<feature> --dry-run
    python3 scripts/adopt_tracker.py --tracker .scratch/<feature> --check-command "pnpm test"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from orchestrator_lib import (
    FRONTMATTER_RE,
    NON_ISSUE_ALLOWLIST,
    issue_number_from_filename,
    normalize_issue_id,
    parse_frontmatter,
    read_text,
)

# `docs/agents/triage-labels.md` defines a closed vocabulary; only `ready-for-agent`
# means "fully specified, ready for an AFK agent". Everything else stays with the human.
TRIAGE_MAP = {
    "ready-for-agent": ("AFK", "todo"),
    "ready-for-human": ("HITL", "todo"),
    "needs-triage": ("HITL", "todo"),
    "needs-info": ("HITL", "todo"),
    "wontfix": ("HITL", "todo"),
}

REQUIRED_FRONTMATTER = ("id", "title", "type", "status")

STATUS_LINE_RE = re.compile(r"^\s*\**Status:?\**\s*[:\-]?\s*(?P<value>.+?)\s*$", re.IGNORECASE)
BLOCKED_LINE_RE = re.compile(r"^\s*\**Blocked by:?\**\s*[:\-]?\s*(?P<value>.*?)\s*$", re.IGNORECASE)
H1_RE = re.compile(r"^#\s+(?P<title>.+?)\s*$", re.MULTILINE)
TITLE_PREFIX_RE = re.compile(r"^(?:ISSUE-)?\d+\s*[—–\-:.]\s*")
FIRST_CHECKBOX_RE = re.compile(r"^- \[[ xX]\] ", re.MULTILINE)
HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
NUMBER_RE = re.compile(r"(?<![\w-])(?:ISSUE-)?(\d{1,4})(?![\w-])")


@dataclass
class Plan:
    path: Path
    issue_id: str
    title: str
    type: str
    status: str
    triage: str
    blocked_by: list[str]
    text: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tracker", required=True, help="Tracker directory containing issues/")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    parser.add_argument("--check-command", action="append", default=[], help="Canonical check command for the README ground rules (repeatable)")
    parser.add_argument("--branch", help="Working branch to declare in the README ground rules")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tracker = Path(args.tracker)
    issue_dir = tracker / "issues"
    if not issue_dir.is_dir():
        print(f"Missing issue directory: {issue_dir}", file=sys.stderr)
        return 1

    plans: list[Plan] = []
    skipped: list[str] = []
    errors: list[str] = []

    for path in sorted(issue_dir.glob("*.md")):
        if path.name in NON_ISSUE_ALLOWLIST:
            continue
        number = issue_number_from_filename(path.name)
        if number is None:
            errors.append(f"{path.name}: filename matches neither ISSUE-NNN-*.md nor NN-*.md")
            continue
        text = read_text(path)
        if FRONTMATTER_RE.match(text):
            problem = validate_adopted(text)
            (errors if problem else skipped).append(f"{path.name}: {problem}" if problem else path.name)
            continue
        try:
            plans.append(plan_adoption(path, number, text))
        except ValueError as error:
            errors.append(f"{path.name}: {error}")

    if errors:
        print("Adoption aborted, nothing written:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    for name in skipped:
        print(f"skip   {name} (already adopted)")
    for plan in plans:
        blockers = ", ".join(plan.blocked_by) or "None"
        verb = "would adopt" if args.dry_run else "adopt "
        print(f"{verb} {plan.path.name} -> {plan.issue_id} type={plan.type} status={plan.status} (from {plan.triage}) blocked_by={blockers}")

    scaffolds = plan_scaffolds(tracker, args.check_command, args.branch)
    for path, _ in scaffolds:
        print(f"{'would create' if args.dry_run else 'create'} {path.relative_to(tracker)}")

    if args.dry_run:
        return 0

    for plan in plans:
        plan.path.write_text(plan.text, encoding="utf-8")
    for path, content in scaffolds:
        path.write_text(content, encoding="utf-8")

    if not plans and not scaffolds:
        print("Nothing to do — tracker already adopted.")
    if any("<TODO" in content for _, content in scaffolds):
        print("README ground rules contain TODO placeholders — fill in the canonical check commands before starting a chain.")
    readme = tracker / "README.md"
    if readme.exists() and not re.search(r"^##\s+.*ground rules.*$", read_text(readme), re.MULTILINE | re.IGNORECASE):
        print(f"{readme} has no ground-rules section — workers will get no canonical check commands.")
    return 0


def validate_adopted(text: str) -> str | None:
    """An adopted file must carry every key the orchestrator reads; an empty `type` reads as AFK."""
    try:
        frontmatter, _ = parse_frontmatter(text)
    except ValueError as error:
        return str(error)
    missing = [key for key in REQUIRED_FRONTMATTER if not str(frontmatter.get(key, "")).strip()]
    if missing:
        return f"frontmatter is missing {', '.join(missing)}"
    if str(frontmatter["type"]).upper() not in {"AFK", "HITL"}:
        return f"unknown type: {frontmatter['type']}"
    if str(frontmatter["status"]) not in {"todo", "in_progress", "done"}:
        return f"unknown status: {frontmatter['status']}"
    return None


def plan_adoption(path: Path, number: str, text: str) -> Plan:
    issue_id = normalize_issue_id(number)

    body_lines: list[str] = []
    triage_line: str | None = None
    blocked_line: str | None = None
    for line in text.splitlines():
        match = STATUS_LINE_RE.match(line)
        if match and triage_line is None:
            triage_line = match.group("value")
            continue
        match = BLOCKED_LINE_RE.match(line)
        if match and blocked_line is None:
            blocked_line = match.group("value")
            continue
        body_lines.append(line)

    if triage_line is None:
        raise ValueError("no `**Status:**` line found; cannot derive AFK/HITL")
    triage = triage_line.strip().strip("*`").lower()
    if triage not in TRIAGE_MAP:
        raise ValueError(f"unknown triage status {triage!r}; expected one of {', '.join(sorted(TRIAGE_MAP))}")
    issue_type, status = TRIAGE_MAP[triage]

    title_match = H1_RE.search(text)
    title = TITLE_PREFIX_RE.sub("", title_match.group("title").strip()) if title_match else path.stem
    if not title:
        raise ValueError("could not derive a title")

    blocked_by = parse_blockers(blocked_line or "")
    if issue_id in blocked_by:
        raise ValueError("issue lists itself as a blocker")

    body = re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines)).strip()
    body = ensure_criteria_heading(body)
    body = f"{body}\n\n## Blocked by\n\n" + "\n".join(f"- {item}" for item in blocked_by or ["None"]) + "\n"

    frontmatter = "\n".join(
        [
            "---",
            f"id: {issue_id}",
            f'title: "{title.replace(chr(34), chr(39))}"',
            f"type: {issue_type}",
            f"status: {status}",
            "labels:",
            f"  - {triage}",
            "---",
            "",
            "",
        ]
    )
    return Plan(path, issue_id, title, issue_type, status, triage, blocked_by, frontmatter + body)


def parse_blockers(value: str) -> list[str]:
    if not value.strip() or re.search(r"\bNone\b", value, re.IGNORECASE):
        return []
    return sorted({normalize_issue_id(number) for number in NUMBER_RE.findall(value)})


def ensure_criteria_heading(body: str) -> str:
    """Keep the checklist out of the appended `## Blocked by` section's reach."""
    checkbox = FIRST_CHECKBOX_RE.search(body)
    if not checkbox:
        return body
    heading = HEADING_RE.search(body)
    if heading and heading.start() < checkbox.start():
        return body
    return body[: checkbox.start()] + "## Acceptance Criteria\n\n" + body[checkbox.start() :]


def plan_scaffolds(tracker: Path, check_commands: list[str], branch: str | None) -> list[tuple[Path, str]]:
    scaffolds = []
    readme = tracker / "README.md"
    if not readme.exists():
        commands = "\n".join(f"  - `{command}`" for command in check_commands) or "  - `<TODO: canonical test command>`"
        scaffolds.append(
            (
                readme,
                f"# {tracker.name}\n\n"
                "## Ground rules\n\n"
                f"- Working branch: `{branch or '<TODO: working branch>'}`\n"
                "- Canonical check commands, run as the baseline suite by every worker:\n"
                f"{commands}\n",
            )
        )
    decisions = tracker / "decisions.md"
    if not decisions.exists():
        scaffolds.append((decisions, "# Decisions\n\nApproved, rejected, and deferred recommendations, one line each: item, verdict, reason.\n"))
    return scaffolds


if __name__ == "__main__":
    raise SystemExit(main())
