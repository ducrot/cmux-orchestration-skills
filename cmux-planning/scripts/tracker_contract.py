#!/usr/bin/env python3
"""Deterministic ticket-proposal and native Markdown tracker contracts.

This module is deliberately standalone from ``cmux-issue-chain``.  The planning skill can be
installed by itself, while repository integration tests may still feed the rendered tracker to
the sibling skill as an independent compatibility check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from orchestrator_lib import atomic_write, sha256_bytes, sha256_file
from spec_contract import (
    REVIEW_REPORT_SECTIONS,
    ContractError,
    bullet_count,
    is_none,
    one_digest,
    require_sections,
    sections,
)


PROPOSAL_SCHEMA_VERSION = 1
ISSUE_ID_RE = re.compile(r"\AISSUE-(\d{3})\Z")
SLUG_BODY = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SLUG_RE = re.compile(rf"\A{SLUG_BODY}\Z")
TOKEN_SIZING_RE = re.compile(r"\btokens?\b", re.IGNORECASE)
AUTHOR_REPORT_SECTIONS = (
    "Result",
    "Repository Sources / Methods",
    "Source Spec Identity",
    "Ticket Count",
    "Ready Frontier",
    "Blockers",
    "Plan Drift",
    "Proposal Paths",
)
WIDE_PHASES = {"expand", "migrate", "contract", "integration"}
REQUIRED_TRACKER_FILES = {"README.md", "spec.md", "map.md", "decisions.md"}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be non-empty text")
    return value.strip()


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise ContractError(f"{label} must be {qualifier} of strings")
    result = []
    for index, item in enumerate(value, 1):
        result.append(_text(item, f"{label}[{index}]"))
    if len(result) != len(set(result)):
        raise ContractError(f"{label} contains duplicates")
    return result


def _safe_slug(value: Any, label: str = "tracker.slug") -> str:
    slug = _text(value, label)
    if not SLUG_RE.fullmatch(slug):
        raise ContractError(f"{label} must be lowercase kebab-case without path separators")
    return slug


def _load_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise ContractError(f"{label} is missing: {path}")
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"{label} is not valid UTF-8 JSON: {error}") from error
    return raw, _object(parsed, label)


def _cycle(ticket_ids: list[str], blockers: dict[str, list[str]]) -> list[str] | None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(issue_id: str) -> list[str] | None:
        if issue_id in visiting:
            start = visiting.index(issue_id)
            return visiting[start:] + [issue_id]
        if issue_id in visited:
            return None
        visiting.append(issue_id)
        for prerequisite in blockers[issue_id]:
            found = visit(prerequisite)
            if found:
                return found
        visiting.pop()
        visited.add(issue_id)
        return None

    for issue_id in ticket_ids:
        found = visit(issue_id)
        if found:
            return found
    return None


def _validate_dependency_graph(
    ids: list[str],
    blockers: dict[str, list[str]],
    *,
    issue_label: str = "",
    cycle_label: str = "",
    reject_self_blocker: bool = False,
) -> None:
    known = set(ids)
    for issue_id, prerequisites in blockers.items():
        if reject_self_blocker and issue_id in prerequisites:
            raise ContractError(f"{issue_id} lists itself as a blocker")
        unknown = sorted(set(prerequisites) - known)
        if unknown:
            raise ContractError(
                f"{issue_label}{issue_id} has unknown blocker(s): {', '.join(unknown)}"
            )
    cycle = _cycle(ids, blockers)
    if cycle:
        raise ContractError(f"{cycle_label}dependency cycle: " + " -> ".join(cycle))


def validate_proposal(
    path: Path,
    *,
    expected_spec: Path | None = None,
    expected_spec_sha256: str | None = None,
    expected_tracker_slug: str | None = None,
) -> dict[str, Any]:
    raw, data = _load_json(path, "ticket proposal")
    if set(data) != {"schema_version", "source_spec", "tracker", "tickets"}:
        raise ContractError(
            "ticket proposal keys must be exactly schema_version, source_spec, tracker, and tickets"
        )
    if data["schema_version"] != PROPOSAL_SCHEMA_VERSION:
        raise ContractError(f"unsupported ticket proposal schema: {data['schema_version']!r}")

    source = _object(data["source_spec"], "source_spec")
    if set(source) != {"path", "sha256"}:
        raise ContractError("source_spec keys must be exactly path and sha256")
    source_path = Path(_text(source["path"], "source_spec.path")).resolve()
    source_digest = _text(source["sha256"], "source_spec.sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ContractError("source_spec.sha256 must be a lowercase SHA-256 digest")
    if expected_spec is not None and source_path != expected_spec.resolve():
        raise ContractError("ticket proposal is not bound to the approved specification path")
    if expected_spec_sha256 is not None and source_digest != expected_spec_sha256:
        raise ContractError("ticket proposal is not bound to the approved specification digest")
    if expected_spec is not None and sha256_file(expected_spec) != source_digest:
        raise ContractError("approved specification changed after approval")

    tracker = _object(data["tracker"], "tracker")
    if set(tracker) != {"slug", "title", "working_branch", "canonical_check_commands"}:
        raise ContractError(
            "tracker keys must be exactly slug, title, working_branch, and canonical_check_commands"
        )
    slug = _safe_slug(tracker["slug"])
    if expected_tracker_slug is not None and slug != expected_tracker_slug:
        raise ContractError(f"tracker.slug must equal frozen tracker slug {expected_tracker_slug!r}")
    title = _text(tracker["title"], "tracker.title")
    branch = _text(tracker["working_branch"], "tracker.working_branch")
    if any(character in branch for character in "\r\n`"):
        raise ContractError("tracker.working_branch contains unsafe formatting")
    commands = _string_list(tracker["canonical_check_commands"], "canonical_check_commands")
    if any("\n" in command or "\r" in command or "`" in command for command in commands):
        raise ContractError("canonical check commands must each fit safely on one Markdown line")

    tickets_value = data["tickets"]
    if not isinstance(tickets_value, list) or not tickets_value:
        raise ContractError("tickets must be a non-empty list")
    tickets: list[dict[str, Any]] = []
    ids: list[str] = []
    blockers: dict[str, list[str]] = {}
    wide: dict[str, list[str]] = {phase: [] for phase in WIDE_PHASES}
    forbidden_sizing_text: list[str] = []
    required_ticket_keys = {
        "id",
        "title",
        "delivered_behavior",
        "acceptance_criteria",
        "blocked_by",
        "merge_split_rationale",
        "slice_type",
        "technical_layers",
        "wide_refactor",
    }
    for index, value in enumerate(tickets_value, 1):
        ticket = _object(value, f"tickets[{index}]")
        if set(ticket) != required_ticket_keys:
            raise ContractError(
                f"tickets[{index}] keys must be exactly {', '.join(sorted(required_ticket_keys))}"
            )
        issue_id = _text(ticket["id"], f"tickets[{index}].id")
        if not ISSUE_ID_RE.fullmatch(issue_id):
            raise ContractError(f"tickets[{index}].id must use ISSUE-NNN")
        if issue_id in ids:
            raise ContractError(f"duplicate issue id: {issue_id}")
        ids.append(issue_id)
        ticket_title = _text(ticket["title"], f"{issue_id}.title")
        delivered = _text(ticket["delivered_behavior"], f"{issue_id}.delivered_behavior")
        criteria = _string_list(ticket["acceptance_criteria"], f"{issue_id}.acceptance_criteria")
        ticket_blockers = _string_list(ticket["blocked_by"], f"{issue_id}.blocked_by", allow_empty=True)
        rationale = _text(ticket["merge_split_rationale"], f"{issue_id}.merge_split_rationale")
        layers = _string_list(ticket["technical_layers"], f"{issue_id}.technical_layers")
        slice_type = _text(ticket["slice_type"], f"{issue_id}.slice_type")
        if slice_type not in {"vertical", "wide-refactor"}:
            raise ContractError(f"{issue_id}.slice_type must be vertical or wide-refactor")
        wide_refactor = ticket["wide_refactor"]
        if slice_type == "vertical":
            if wide_refactor is not None:
                raise ContractError(f"{issue_id} is vertical and must set wide_refactor to null")
        else:
            details = _object(wide_refactor, f"{issue_id}.wide_refactor")
            if set(details) != {"phase", "sequence", "integration_reason"}:
                raise ContractError(
                    f"{issue_id}.wide_refactor keys must be phase, sequence, and integration_reason"
                )
            phase = _text(details["phase"], f"{issue_id}.wide_refactor.phase")
            if phase not in WIDE_PHASES:
                raise ContractError(f"{issue_id} has an unknown wide-refactor phase")
            if details["sequence"] != "expand-migrate-contract":
                raise ContractError(f"{issue_id} must use the expand-migrate-contract sequence")
            integration_reason = details["integration_reason"]
            if phase == "integration":
                _text(integration_reason, f"{issue_id}.wide_refactor.integration_reason")
            elif integration_reason is not None:
                raise ContractError(
                    f"{issue_id} may set integration_reason only for an integration exception"
                )
            wide[phase].append(issue_id)
        blockers[issue_id] = ticket_blockers
        forbidden_sizing_text.extend([ticket_title, delivered, *criteria, rationale, *layers])
        tickets.append(
            {
                **ticket,
                # Every normalized value goes back, or the renderer would see the raw text the
                # validator never judged.
                "id": issue_id,
                "slice_type": slice_type,
                "title": ticket_title,
                "delivered_behavior": delivered,
                "acceptance_criteria": criteria,
                "blocked_by": ticket_blockers,
                "merge_split_rationale": rationale,
                "technical_layers": layers,
            }
        )

    _validate_dependency_graph(ids, blockers, reject_self_blocker=True)
    if any(TOKEN_SIZING_RE.search(text) for text in forbidden_sizing_text):
        raise ContractError("ticket sizing must stay qualitative; proposal text may not mention tokens")

    if any(wide.values()):
        for phase in ("expand", "migrate", "contract"):
            if not wide[phase]:
                raise ContractError(
                    "a wide refactor must include explicit expand, bounded migrate, and contract tickets"
                )
        expands = set(wide["expand"])
        migrates = set(wide["migrate"])
        for issue_id in wide["migrate"]:
            if not expands.intersection(blockers[issue_id]):
                raise ContractError(f"wide migrate ticket {issue_id} must be blocked by an expand ticket")
        for issue_id in wide["contract"]:
            if not migrates.issubset(set(blockers[issue_id])):
                raise ContractError(
                    f"wide contract ticket {issue_id} must wait for every bounded migrate ticket"
                )
        contracts = set(wide["contract"])
        for issue_id in wide["integration"]:
            if not contracts.intersection(blockers[issue_id]):
                raise ContractError(
                    f"wide integration ticket {issue_id} must be blocked by a contract ticket"
                )

    frontier = [issue_id for issue_id in ids if not blockers[issue_id]]
    return {
        "path": str(path.resolve()),
        "sha256": sha256_bytes(raw),
        "source_spec_path": str(source_path),
        "source_spec_sha256": source_digest,
        "tracker": {
            "slug": slug,
            "title": title,
            "working_branch": branch,
            "canonical_check_commands": commands,
        },
        "tickets": tickets,
        "ticket_ids": ids,
        "ticket_count": len(ids),
        "ready_frontier": frontier,
        "wide_refactor": {phase: values for phase, values in wide.items() if values},
    }


def render_summary(proposal: dict[str, Any]) -> str:
    lines = [
        f"# {proposal['tracker']['title']} — Proposed Tracker",
        "",
        f"Source specification: `{proposal['source_spec_sha256']}`",
        "",
        f"Ready frontier: {', '.join(proposal['ready_frontier'])}",
        "",
        "## Tickets",
        "",
    ]
    for number, ticket in enumerate(proposal["tickets"], 1):
        blockers = ", ".join(ticket["blocked_by"]) or "None"
        lines.extend(
            [
                f"### {number}. {ticket['id']} — {ticket['title']}",
                "",
                f"Delivered behavior: {ticket['delivered_behavior']}",
                "",
                "Acceptance criteria:",
                "",
                *[f"- {criterion}" for criterion in ticket["acceptance_criteria"]],
                "",
                f"Blocked by: {blockers}",
                "",
                f"Merge/split rationale: {ticket['merge_split_rationale']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def validate_summary(path: Path, proposal: dict[str, Any]) -> str:
    if not path.is_file():
        raise ContractError(f"human-readable ticket summary is missing: {path}")
    expected = render_summary(proposal)
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        raise ContractError(
            "human-readable ticket summary does not exactly represent the machine-readable proposal"
        )
    return sha256_bytes(actual.encode("utf-8"))


def _reported_paths(body: str) -> set[Path]:
    return {Path(value).resolve() for value in re.findall(r"`([^`]+)`", body)}


def validate_ticket_author_report(
    report_path: Path,
    proposal_path: Path,
    summary_path: Path,
    *,
    expected_spec: Path,
    expected_spec_sha256: str,
    expected_tracker_slug: str | None = None,
) -> dict[str, Any]:
    if not report_path.is_file():
        raise ContractError(f"tickets author report is missing: {report_path}")
    parsed = sections(report_path.read_text(encoding="utf-8"))
    require_sections(parsed, AUTHOR_REPORT_SECTIONS, "tickets author report")
    result = parsed["Result"]
    if result not in {"PASS", "BLOCKED"}:
        raise ContractError("tickets author Result must be exactly PASS or BLOCKED")
    if one_digest(parsed["Source Spec Identity"], "Source Spec Identity") != expected_spec_sha256:
        raise ContractError("tickets author report is not bound to the approved specification")
    expected_paths = {proposal_path.resolve(), summary_path.resolve()}
    if _reported_paths(parsed["Proposal Paths"]) != expected_paths:
        raise ContractError("tickets author report must name exactly both proposal handoff paths")
    if result == "BLOCKED":
        if is_none(parsed["Blockers"]):
            raise ContractError("a BLOCKED tickets report must state a blocker")
        return {"result": result, "gate": "blocked"}
    if not is_none(parsed["Blockers"]) or not is_none(parsed["Plan Drift"]):
        raise ContractError("a passing tickets author report cannot contain blockers or plan drift")
    if bullet_count(parsed["Repository Sources / Methods"]) < 1:
        raise ContractError("passing tickets report is ungrounded: no repository source/method")
    proposal = validate_proposal(
        proposal_path,
        expected_spec=expected_spec,
        expected_spec_sha256=expected_spec_sha256,
        expected_tracker_slug=expected_tracker_slug,
    )
    summary_sha256 = validate_summary(summary_path, proposal)
    counts = re.findall(r"\b\d+\b", parsed["Ticket Count"])
    if len(counts) != 1 or int(counts[0]) != proposal["ticket_count"]:
        raise ContractError("tickets report Ticket Count does not match the proposal")
    reported_frontier = re.findall(r"\bISSUE-\d{3}\b", parsed["Ready Frontier"])
    if reported_frontier != proposal["ready_frontier"]:
        raise ContractError("tickets report Ready Frontier does not match the proposal")
    return {
        "result": result,
        "gate": "advance",
        "proposal": proposal["path"],
        "proposal_sha256": proposal["sha256"],
        "summary": str(summary_path.resolve()),
        "summary_sha256": summary_sha256,
        "ticket_count": proposal["ticket_count"],
        "ready_frontier": proposal["ready_frontier"],
        "source_spec_sha256": proposal["source_spec_sha256"],
    }


def validate_ticket_review_report(
    report_path: Path,
    input_proposal: Path,
    reviewed_candidate: Path,
    *,
    expected_input_sha256: str,
    expected_spec: Path,
    expected_spec_sha256: str,
    expected_tracker_slug: str | None = None,
) -> dict[str, Any]:
    if not report_path.is_file():
        raise ContractError(f"tickets review report is missing: {report_path}")
    parsed = sections(report_path.read_text(encoding="utf-8"))
    require_sections(parsed, REVIEW_REPORT_SECTIONS, "tickets review report")
    verdict = parsed["Verdict"]
    if verdict not in {"pass", "pass_with_fixes", "blocked"}:
        raise ContractError("tickets review Verdict must be pass, pass_with_fixes, or blocked")
    input_digest = sha256_file(input_proposal)
    if input_digest != expected_input_sha256:
        raise ContractError("tickets proposal changed after its author gate")
    if one_digest(parsed["Input Identity"], "Input Identity") != input_digest:
        raise ContractError("tickets review Input Identity is not bound to the author proposal")
    if bullet_count(parsed["Methods"]) < 1:
        raise ContractError("tickets review is ungrounded: Methods has no concrete entry")
    if verdict == "blocked":
        if is_none(parsed["Blockers"]):
            raise ContractError("blocked tickets review must state the substantive decision required")
        if reviewed_candidate.exists():
            raise ContractError("blocked tickets review must not supply an approval candidate")
        return {"verdict": verdict, "input_sha256": input_digest, "gate": "blocked"}
    if not is_none(parsed["Blockers"]) or not is_none(parsed["Plan Drift"]):
        raise ContractError("passing tickets review cannot contain blockers or plan drift")
    if verdict == "pass":
        if not is_none(parsed["Findings"]) or not is_none(parsed["Corrections"]):
            raise ContractError("pass cannot retain findings or corrections")
        if reviewed_candidate.exists():
            raise ContractError("pass must reference the unchanged proposal, not write a candidate")
        candidate = input_proposal
    else:
        if not reviewed_candidate.is_file():
            raise ContractError("pass_with_fixes requires the complete reviewed proposal candidate")
        if is_none(parsed["Corrections"]):
            raise ContractError("pass_with_fixes requires a structured correction summary")
        candidate = reviewed_candidate
    candidate_proposal = validate_proposal(
        candidate,
        expected_spec=expected_spec,
        expected_spec_sha256=expected_spec_sha256,
        expected_tracker_slug=expected_tracker_slug,
    )
    candidate_digest = candidate_proposal["sha256"]
    if one_digest(parsed["Resulting Candidate Identity"], "Resulting Candidate Identity") != candidate_digest:
        raise ContractError("tickets review Resulting Candidate Identity does not match the candidate")
    if verdict == "pass" and candidate_digest != input_digest:
        raise ContractError("pass must preserve the unchanged ticket proposal digest")
    return {
        "verdict": verdict,
        "input_sha256": input_digest,
        "candidate": str(candidate.resolve()),
        "candidate_sha256": candidate_digest,
        "ticket_count": candidate_proposal["ticket_count"],
        "ready_frontier": candidate_proposal["ready_frontier"],
        "gate": "advance",
    }


def issue_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:72].rstrip("-") or "work"


def render_issue(ticket: dict[str, Any]) -> str:
    title = ticket["title"].replace('"', "'")
    blockers = "\n".join(f"- {item}" for item in ticket["blocked_by"]) or "- None"
    criteria = "\n".join(f"- [ ] {item}" for item in ticket["acceptance_criteria"])
    wide = ""
    if ticket["slice_type"] == "wide-refactor":
        details = ticket["wide_refactor"]
        wide = (
            "\n\n## Wide Refactor Sequence\n\n"
            f"- Sequence: `{details['sequence']}`\n"
            f"- Phase: `{details['phase']}`"
        )
        if details["integration_reason"]:
            wide += f"\n- Integration exception: {details['integration_reason']}"
    return f'''---
id: {ticket["id"]}
title: "{title}"
type: AFK
status: todo
labels:
  - ready-for-agent
---

# {ticket["id"]} — {ticket["title"]}

## What to build

{ticket["delivered_behavior"]}

## Acceptance Criteria

{criteria}

## Merge / Split Rationale

{ticket["merge_split_rationale"]}{wide}

## Blocked by

{blockers}
'''


def render_readme(proposal: dict[str, Any]) -> str:
    tracker = proposal["tracker"]
    commands = "\n".join(f"  - `{command}`" for command in tracker["canonical_check_commands"])
    return f'''# {tracker["title"]}

## Ground rules

- Working branch: `{tracker["working_branch"]}`
- Canonical check commands, run as the baseline suite by every worker:
{commands}
'''


def render_decisions(proposal: dict[str, Any]) -> str:
    lines = [
        "# Decisions",
        "",
        "Approved ticket merge and split choices:",
        "",
    ]
    for ticket in proposal["tickets"]:
        lines.append(f"- {ticket['id']}: {ticket['merge_split_rationale']}")
    return "\n".join(lines) + "\n"


def stage_native_tracker(
    destination: Path,
    proposal: dict[str, Any],
    *,
    approved_spec: Path,
) -> dict[str, Any]:
    if destination.exists():
        raise ContractError(f"staged tracker path already exists: {destination}")
    destination.mkdir(parents=True)
    issues = destination / "issues"
    issues.mkdir()
    atomic_write(destination / "README.md", render_readme(proposal).encode("utf-8"))
    atomic_write(destination / "spec.md", approved_spec.read_bytes())
    atomic_write(destination / "map.md", render_summary(proposal).encode("utf-8"))
    atomic_write(destination / "decisions.md", render_decisions(proposal).encode("utf-8"))
    for ticket in proposal["tickets"]:
        number = ISSUE_ID_RE.fullmatch(ticket["id"]).group(1)  # validated above
        filename = f"ISSUE-{number}-{issue_slug(ticket['title'])}.md"
        atomic_write(issues / filename, render_issue(ticket).encode("utf-8"))
    return validate_native_tracker(
        destination,
        expected_spec_sha256=proposal["source_spec_sha256"],
        expected_ticket_ids=proposal["ticket_ids"],
    )


def _frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    match = re.match(r"\A---\n(.*?)\n---\n", markdown, re.DOTALL)
    if not match:
        raise ContractError("native issue is missing YAML frontmatter")
    data: dict[str, Any] = {}
    current: str | None = None
    for raw in match.group(1).splitlines():
        if raw.startswith("  - "):
            if current is None:
                raise ContractError("native issue has a frontmatter list item without a key")
            data.setdefault(current, []).append(raw[4:].strip().strip("\"'"))
            continue
        if ":" not in raw:
            raise ContractError(f"native issue has unsupported frontmatter: {raw}")
        key, value = raw.split(":", 1)
        current = key.strip()
        value = value.strip()
        data[current] = [] if not value else value.strip("\"'")
    return data, markdown[match.end() :]


def validate_native_tracker(
    tracker: Path,
    *,
    expected_spec_sha256: str | None = None,
    expected_ticket_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not tracker.is_dir():
        raise ContractError(f"native tracker directory is missing: {tracker}")
    missing = sorted(name for name in REQUIRED_TRACKER_FILES if not (tracker / name).is_file())
    if missing:
        raise ContractError("native tracker is partial; missing: " + ", ".join(missing))
    issue_dir = tracker / "issues"
    if not issue_dir.is_dir():
        raise ContractError("native tracker is partial; missing issues directory")
    # Read each required file once: the same bytes back both the content checks and the digests.
    required_raw = {name: (tracker / name).read_bytes() for name in sorted(REQUIRED_TRACKER_FILES)}
    readme = required_raw["README.md"].decode("utf-8")
    if not re.search(r"^##\s+Ground rules\s*$", readme, re.MULTILINE):
        raise ContractError("native tracker README has no canonical Ground rules section")
    if "Working branch: `" not in readme or "Canonical check commands" not in readme:
        raise ContractError("native tracker README has incomplete ground rules")
    if not re.search(r"^\s+- `[^`]+`\s*$", readme, re.MULTILINE):
        raise ContractError("native tracker README has no runnable canonical check command")
    spec_digest = sha256_bytes(required_raw["spec.md"])
    if expected_spec_sha256 is not None and spec_digest != expected_spec_sha256:
        raise ContractError("native tracker spec.md does not match the approved specification")
    if not required_raw["map.md"].decode("utf-8").strip():
        raise ContractError("native tracker map.md is empty")
    if not required_raw["decisions.md"].decode("utf-8").startswith("# Decisions\n"):
        raise ContractError("native tracker decisions.md is malformed")

    candidates = sorted(issue_dir.glob("*.md"))
    if not candidates:
        raise ContractError("native tracker has no issue files")
    ids: list[str] = []
    blockers: dict[str, list[str]] = {}
    artifacts: dict[str, str] = {}
    for path in candidates:
        match = re.fullmatch(rf"ISSUE-(\d{{3}})-({SLUG_BODY})\.md", path.name)
        if not match:
            raise ContractError(f"malformed native issue filename: {path.name}")
        issue_raw = path.read_bytes()
        markdown = issue_raw.decode("utf-8")
        frontmatter, body = _frontmatter(markdown)
        required = {"id", "title", "type", "status", "labels"}
        if set(frontmatter) != required:
            raise ContractError(f"{path.name} frontmatter keys must be exactly {', '.join(sorted(required))}")
        issue_id = _text(frontmatter["id"], f"{path.name} id")
        if issue_id != f"ISSUE-{match.group(1)}" or not ISSUE_ID_RE.fullmatch(issue_id):
            raise ContractError(f"{path.name} id does not match its filename")
        if issue_id in ids:
            raise ContractError(f"duplicate native issue id: {issue_id}")
        if frontmatter["type"] != "AFK" or frontmatter["status"] != "todo":
            raise ContractError(f"{path.name} must be fully specified AFK todo work")
        if frontmatter["labels"] != ["ready-for-agent"]:
            raise ContractError(f"{path.name} must carry only the ready-for-agent label")
        parsed = sections(body)
        for heading in ("What to build", "Acceptance Criteria", "Merge / Split Rationale", "Blocked by"):
            if not parsed.get(heading, "").strip():
                raise ContractError(f"{path.name} is missing native heading {heading}")
        criteria = re.findall(r"^- \[ \] \S.*$", parsed["Acceptance Criteria"], re.MULTILINE)
        if not criteria:
            raise ContractError(f"{path.name} has no stable acceptance criteria")
        blocked = [] if is_none(parsed["Blocked by"]) else re.findall(r"\bISSUE-\d{3}\b", parsed["Blocked by"])
        ids.append(issue_id)
        blockers[issue_id] = blocked
        artifacts[str(path.relative_to(tracker))] = sha256_bytes(issue_raw)
    _validate_dependency_graph(
        ids, blockers, issue_label="native issue ", cycle_label="native tracker "
    )
    # `ids` follows filename order, the proposal follows authoring order; only the set of issues
    # has to agree, or a proposal whose ids are not in ascending order would fail staging.
    if expected_ticket_ids is not None and sorted(ids) != sorted(expected_ticket_ids):
        raise ContractError("native tracker is a partial or mismatched issue set")
    for name, raw in required_raw.items():
        artifacts[name] = sha256_bytes(raw)
    return {
        "tracker": str(tracker.resolve()),
        "spec_sha256": spec_digest,
        "ticket_ids": ids,
        "ready_frontier": [issue_id for issue_id in ids if not blockers[issue_id]],
        "artifacts": artifacts,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    proposal = subparsers.add_parser("proposal")
    proposal.add_argument("path")
    proposal.add_argument("--spec", required=True)
    proposal.add_argument("--spec-sha256", required=True)
    proposal.add_argument("--tracker-slug")
    summary = subparsers.add_parser("summary")
    summary.add_argument("path")
    summary.add_argument("--proposal", required=True)
    render = subparsers.add_parser("render-summary")
    render.add_argument("--proposal", required=True)
    render.add_argument("--out", required=True)
    author = subparsers.add_parser("author-report")
    author.add_argument("report")
    author.add_argument("--proposal", required=True)
    author.add_argument("--summary", required=True)
    author.add_argument("--spec", required=True)
    author.add_argument("--spec-sha256", required=True)
    author.add_argument("--tracker-slug")
    review = subparsers.add_parser("review-report")
    review.add_argument("report")
    review.add_argument("--input", required=True)
    review.add_argument("--candidate", required=True)
    review.add_argument("--input-sha256", required=True)
    review.add_argument("--spec", required=True)
    review.add_argument("--spec-sha256", required=True)
    review.add_argument("--tracker-slug")
    native = subparsers.add_parser("native-tracker")
    native.add_argument("path")
    native.add_argument("--spec-sha256")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "proposal":
            result = validate_proposal(
                Path(args.path),
                expected_spec=Path(args.spec),
                expected_spec_sha256=args.spec_sha256,
                expected_tracker_slug=args.tracker_slug,
            )
        elif args.command == "summary":
            proposal = validate_proposal(Path(args.proposal))
            result = {"sha256": validate_summary(Path(args.path), proposal)}
        elif args.command == "render-summary":
            proposal = validate_proposal(Path(args.proposal))
            output = Path(args.out)
            atomic_write(output, render_summary(proposal).encode("utf-8"))
            result = {"path": str(output.resolve()), "sha256": sha256_file(output)}
        elif args.command == "author-report":
            result = validate_ticket_author_report(
                Path(args.report),
                Path(args.proposal),
                Path(args.summary),
                expected_spec=Path(args.spec),
                expected_spec_sha256=args.spec_sha256,
                expected_tracker_slug=args.tracker_slug,
            )
        elif args.command == "review-report":
            result = validate_ticket_review_report(
                Path(args.report),
                Path(args.input),
                Path(args.candidate),
                expected_input_sha256=args.input_sha256,
                expected_spec=Path(args.spec),
                expected_spec_sha256=args.spec_sha256,
                expected_tracker_slug=args.tracker_slug,
            )
        else:
            result = validate_native_tracker(
                Path(args.path), expected_spec_sha256=args.spec_sha256
            )
        print(json.dumps(result, sort_keys=True, default=str))
        return 2 if result.get("gate") == "blocked" else 0
    except (ContractError, OSError, UnicodeError, KeyError, TypeError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
