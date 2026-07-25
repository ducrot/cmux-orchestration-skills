#!/usr/bin/env python3
"""Shared helpers for the cmux-issue-chain skill."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
CHECKBOX_RE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<text>.*)$", re.MULTILINE)
ISSUE_ID_RE = re.compile(r"\bISSUE-\d+\b")
BARE_NUMBER_RE = re.compile(r"(?<![\w-])(\d{1,4})(?![\w-])")

# Canonical `ISSUE-001-slug.md` plus the `01-slug.md` form that `to-tickets` writes.
ISSUE_FILE_RE = re.compile(r"\A(?:ISSUE-)?(\d{1,4})(?:-|\Z)")

NON_ISSUE_ALLOWLIST = {"README.md", "_index.md", "decisions.md", "spec.md", "map.md"}

# Single source of truth for the wait policy; run_state.py and await_report.py both use it.
MINIMUM_WAIT_MINUTES = {"implement": 45, "simplify": 30, "test": 30, "review": 90}

# Deterministic pane labels per role (SKILL.md, CMUX Control).
ROLE_LABELS = {"implement": "Implementer", "simplify": "Simplifier", "test": "Tester", "review": "Reviewer"}

# Which binary runs which role (SKILL.md, CMUX Control).
ROLE_WORKERS = {"implement": "codex", "simplify": "claude", "test": "codex", "review": "claude"}

# cmux only silences notifications from panes it considers managed subagents
# (`automation.suppressSubagentNotifications`, on by default). It infers that from process
# ancestry, and a worker started by `cmux new-split` counts as a top-level agent — so without
# this marker every turn end, idle reminder and approval prompt raises a desktop banner with
# sound while the human is elsewhere. Undocumented cmux internal; if it ever stops working
# the only symptom is that the noise returns.
SUBAGENT_MARKER_ENV = "CMUX_AGENT_MANAGED_SUBAGENT=1"

# Fixed startup commands per worker binary; policy, not a per-run choice (SKILL.md, CMUX
# Control, explains what each Codex flag buys). Plain binaries, never the teams wrappers.
WORKER_COMMANDS = {
    "claude": "claude",
    "codex": (
        "codex -s workspace-write"
        " -c sandbox_workspace_write.network_access=true"
        " -c 'sandbox_workspace_write.writable_roots=[\"~/.ddev\"]'"
        " --ask-for-approval on-request"
        " -c approvals_reviewer=auto_review"
        " -c check_for_update_on_startup=false"
    ),
}


def launch_command(role: str) -> str:
    """Shell line that starts a role's worker, marked so its pane stays notification-quiet."""
    return f"{SUBAGENT_MARKER_ENV} {WORKER_COMMANDS[ROLE_WORKERS[role]]}"


def normalize_issue_id(number: str | int) -> str:
    return f"ISSUE-{int(number):03d}"


def issue_number_from_filename(name: str) -> str | None:
    """Accepts `ISSUE-001-slug.md`, `ISSUE-001.md`, `01-slug.md` and `01.md`."""
    match = ISSUE_FILE_RE.match(name.removesuffix(".md"))
    return match.group(1) if match else None


class TrackerFormatError(ValueError):
    """Tracker violates the skill's issue-file conventions."""


@dataclass
class Issue:
    path: str
    id: str
    title: str
    type: str
    status: str
    progress: str
    updated: str
    labels: list[str]
    blocked_by: list[str]
    acceptance_total: int
    acceptance_done: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(markdown)
    if not match:
        raise ValueError("Markdown file is missing YAML frontmatter")
    return parse_simple_yaml(match.group(1)), markdown[match.end() :]


def parse_simple_yaml(yaml_text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in yaml_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  - "):
            if current_key is None:
                raise ValueError(f"List item without key: {line}")
            data.setdefault(current_key, []).append(unquote(line[4:].strip()))
            continue
        if ":" not in line:
            raise ValueError(f"Unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        if value == "":
            data[key] = []
        else:
            data[key] = unquote(value)
    return data


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_issue(path: Path) -> Issue:
    markdown = read_text(path)
    frontmatter, body = parse_frontmatter(markdown)
    number = issue_number_from_filename(path.name)
    fallback_id = normalize_issue_id(number) if number else path.stem
    blocked_by = parse_blocked_by(body)
    total = 0
    done = 0
    for match in CHECKBOX_RE.finditer(body):
        total += 1
        if match.group("mark").lower() == "x":
            done += 1
    return Issue(
        path=str(path),
        id=str(frontmatter.get("id") or fallback_id),
        title=str(frontmatter.get("title", "")),
        type=str(frontmatter.get("type", "")),
        status=str(frontmatter.get("status", "")),
        progress=str(frontmatter.get("progress", f"{done}/{total}")),
        updated=str(frontmatter.get("updated", "")),
        labels=[str(label) for label in frontmatter.get("labels", [])],
        blocked_by=blocked_by,
        acceptance_total=total,
        acceptance_done=done,
    )


def parse_blocked_by(body: str) -> list[str]:
    section = section_text(body, "Blocked by")
    if not section:
        return []
    if re.search(r"\bNone\b", section, re.IGNORECASE):
        return []
    ids = set(ISSUE_ID_RE.findall(section))
    if ids:
        # Explicit ids win: bare numbers alongside them are prose ("see PR 42"), not blockers.
        return sorted(ids)
    # `to-tickets` writes bare ticket numbers ("Blocked by: 01, 02").
    return sorted({normalize_issue_id(number) for number in BARE_NUMBER_RE.findall(section)})


def section_text(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE | re.IGNORECASE)
    match = pattern.search(markdown)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", markdown[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(markdown)
    return markdown[start:end].strip()


def load_issues(tracker: Path) -> dict[str, Issue]:
    issue_dir = tracker / "issues"
    if not issue_dir.is_dir():
        raise FileNotFoundError(f"Missing issue directory: {issue_dir}")
    candidates = []
    stray = []
    for path in sorted(issue_dir.glob("*.md")):
        if path.name in NON_ISSUE_ALLOWLIST:
            continue
        (candidates if issue_number_from_filename(path.name) else stray).append(path)
    if stray:
        names = ", ".join(path.name for path in stray)
        raise TrackerFormatError(
            f"{issue_dir}: *.md files that match neither ISSUE-NNN-*.md nor NN-*.md "
            f"would be silently ignored: {names}"
        )
    issues = {}
    unadopted = []
    for path in candidates:
        try:
            issue = parse_issue(path)
        except ValueError as error:
            unadopted.append(f"{path.name} ({error})")
            continue
        issues[issue.id] = issue
    if unadopted:
        raise TrackerFormatError(
            f"{issue_dir}: issue files without usable frontmatter: {', '.join(unadopted)}. "
            f"Run scripts/adopt_tracker.py --tracker {tracker} to adopt them."
        )
    if not issues:
        raise TrackerFormatError(f"{issue_dir}: no issue files found; nothing to orchestrate")
    return issues


def blocker_status(issue: Issue, issues: dict[str, Issue]) -> dict[str, Any]:
    blockers = []
    for blocker_id in issue.blocked_by:
        blocker = issues.get(blocker_id)
        blockers.append(
            {
                "id": blocker_id,
                "known": blocker is not None,
                "status": blocker.status if blocker else "missing",
                "done": bool(blocker and blocker.status == "done"),
            }
        )
    blocked = any(not blocker["done"] for blocker in blockers)
    return {"blocked": blocked, "blockers": blockers}


def issue_ready(issue: Issue, issues: dict[str, Issue]) -> bool:
    if issue.type.upper() == "HITL":
        return False
    if issue.status not in {"todo", "in_progress"}:
        return False
    return not blocker_status(issue, issues)["blocked"]


def read_issue_markdown(tracker: Path, issue_id: str) -> tuple[Issue, str]:
    issues = load_issues(tracker)
    if issue_id not in issues:
        raise KeyError(f"Unknown issue: {issue_id}")
    issue = issues[issue_id]
    return issue, read_text(Path(issue.path))
