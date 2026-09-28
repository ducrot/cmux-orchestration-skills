#!/usr/bin/env python3
"""Run briefing and recap: compact what-this-run-does/did overviews for the human, plus a sidebar pill.

Vendored byte-identical into cmux-issue-chain, cmux-planning, and cmux-grilling. `draft` and
`recap-draft` write <run-dir>/briefing.md or recap.md with the facts filled in from state.json
and events.jsonl, and `{{name}}` placeholders for the parts only the orchestrator can phrase.
`show` and `recap-show` refuse while a placeholder remains, print the text, log `run.briefing`
or `run.recap`, and set the status pill (running, done, or halted).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BRIEFING_FILE = "briefing.md"
RECAP_FILE = "recap.md"
PLACEHOLDER_RE = re.compile(r"\{\{([a-z_]+)\}\}")
PILL_KEYS = {"issue-chain": "cmux-issue-chain-run", "planning": "cmux-planning-run", "grilling": "cmux-grilling-run"}
PILL_COLORS = {"running": "#8e8e93", "done": "#34c759", "halted": "#ff3b30"}
# Above the role pills (priority 80), so the run topic stays first in the sidebar.
PILL_PRIORITY = 90
PILL_MAX_CHARS = 48
DONE_STAGES = {"issue-chain": "done", "planning": "complete", "grilling": "done"}
HALTING_DECISIONS = {"hitl", "blocked", "stop"}
DECISION_STATUSES = ("decided", "deferred", "open")

# Read-only mirror of cmux-issue-chain's tracker conventions (orchestrator_lib.py); the vendored
# copies in planning and grilling cannot import it.
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
ISSUE_FILE_RE = re.compile(r"\A(?:ISSUE-)?(\d{1,4})(?:-|\Z)")
ISSUE_ID_RE = re.compile(r"\bISSUE-\d+\b")
BARE_NUMBER_RE = re.compile(r"(?<![\w-])(\d{1,4})(?![\w-])")
CHECKBOX_RE = re.compile(r"^- \[(?P<mark>[ xX])\] ", re.MULTILINE)
OPEN_STATUSES = {"todo", "in_progress"}
NEXT_LINE_RE = re.compile(r"^- (?:Next step|Nächster Schritt): .*?\b(ISSUE-\d+)\b", re.MULTILINE)
REASON_LINE_RE = re.compile(r"^  (?:Reason|Begründung): \S", re.MULTILINE)
PROMPT_BLOCK_RE = re.compile(
    r"^(?:Prompt for the next run|Prompt für den nächsten Lauf):\n~~~\n(.*?)\n~~~$", re.MULTILINE | re.DOTALL
)

LABELS = {
    "en": {
        "heading": "Run briefing",
        "recap_heading": "Run recap",
        "goal": "Goal",
        "scope": "Scope",
        "acceptance": "Acceptance",
        "criteria": "{total} criteria, {done} met",
        "blockers": "Blocked by",
        "chain": "Chain",
        "hitl_chain": "none (HITL issue: every acting step belongs to the human)",
        "triage_autonomous": "triage autonomous",
        "triage_human": "triage by the human",
        "branch": "Branch",
        "task": "Task",
        "constraints": "Fixed constraints",
        "source": "Source",
        "source_file": "task file {name}",
        "source_text": "task text",
        "source_summary": "conversation summary",
        "source_grilling": "grilling result {name} (human revalidation pending)",
        "flow": "Flow",
        "planning_flow": "spec author → spec review → approval → tickets author → tickets review → approval → publication",
        "outcome": "Outcome",
        "planning_outcome": "approved specification + tracker `{slug}`",
        "subject": "Subject",
        "focus": "Focus areas",
        "budget": "Budget",
        "budget_value": "at most {count} rounds · lanes {lanes}",
        "grilling_outcome": "assumptions + open decisions as Markdown/JSON under `{path}`",
        "pill_planning": "Planning",
        "pill_grilling": "Grilling",
        "result": "Status",
        "status_done": "done",
        "status_halted": "halted at {stage}: {decision}",
        "tracker_status": "Tracker status",
        "tracker_status_value": "{status} · {done}/{total} criteria checked",
        "stages": "Stages",
        "triage": "Triage",
        "triage_none": "no recommendations",
        "triage_value": "{count} recommendations → {parts}",
        "triage_value_one": "1 recommendation → {parts}",
        "for_human": "Open for the human",
        "triage_pass": "triage {num}",
        "commit_mode_commit": "automatic",
        "commit_mode_propose": "proposal",
        "commit_proposal": "Commit proposal",
        "commit_skipped": "Commit skipped",
        "commit_failed": "Commit failed",
        "commit_failed_proposal": "proposal",
        "hook_modified": "modified by hook: {count} files",
        "hook_side_effects": "hook side effects: {paths}",
        "all-ignored": "all run files are ignored by Git",
        "no-changes": "no run file has changes",
        "preexisting-changes": "pre-run changes in {paths}",
        "index-not-empty": "staged changes outside the run in {paths}",
        "not-a-leaf": "not a single file: {paths}",
        "stage-error": "staging failed: {summary}",
        "commit-error": "{summary}",
        "staged-set-mismatch": "staged paths differ from the run files: {paths}",
        "hook-added-paths": "a hook added {paths}",
        "commit_kept": " (commit kept)",
        "unverifiable": "could not be verified (HEAD {head7} may be the run commit, please check)",
        "no-head": "the repository has no commit yet",
        "commit": "Commit",
        "tracker": "Tracker",
        "tracker_value": "`{path}` · {count} issues, ready now: {ready}",
        "revisions": "Revisions",
        "revisions_value": "spec {spec} · tickets {tickets}",
        "questions": "Questions",
        "questions_value": "{asked} in {rounds} of {budget} rounds · stop: {reason}",
        "assumptions": "Assumptions",
        "decisions": "decisions",
        "decided": "decided",
        "deferred": "deferred",
        "open": "open",
        "artifacts": "Artifacts",
        "none": "none",
        "next": "Next step",
        "also_ready": "also ready",
        "unlocks_one": "unblocks 1 issue",
        "unlocks": "unblocks {count} issues",
        "hitl_next": "HITL, for the human",
        "tracker_complete": "tracker complete, no open issues",
        "none_ready": "none ready – {waits}",
        "waits_for": "{id} waits for {blockers}",
        "chain_with": "issue chain with {issue}",
        "resolve_decisions": "resolve {count} open decisions in the walkthrough",
        "resolve_decision_one": "resolve 1 open decision in the walkthrough",
        "plan_from": "planning with the grilling result `{path}`",
        "prompt": "Prompt for the next run",
        "prompt_unchanged": "the issue does not appear in the initial prompt; it is repeated unchanged",
    },
    "de": {
        "heading": "Run-Briefing",
        "recap_heading": "Run-Recap",
        "goal": "Ziel",
        "scope": "Umfang",
        "acceptance": "Akzeptanz",
        "criteria": "{total} Kriterien, {done} erfüllt",
        "blockers": "Blockiert durch",
        "chain": "Kette",
        "hitl_chain": "keine (HITL-Issue: jeder handelnde Schritt liegt beim Menschen)",
        "triage_autonomous": "Triage autonom",
        "triage_human": "Triage durch den Menschen",
        "branch": "Branch",
        "task": "Aufgabe",
        "constraints": "Feste Vorgaben",
        "source": "Quelle",
        "source_file": "Task-Datei {name}",
        "source_text": "Task-Text",
        "source_summary": "Gesprächszusammenfassung",
        "source_grilling": "Grilling-Ergebnis {name} (Revalidierung durch den Menschen ausstehend)",
        "flow": "Ablauf",
        "planning_flow": "Spec-Autor → Spec-Review → Freigabe → Tickets-Autor → Tickets-Review → Freigabe → Publikation",
        "outcome": "Ergebnis",
        "planning_outcome": "freigegebene Spezifikation + Tracker `{slug}`",
        "subject": "Gegenstand",
        "focus": "Prüfschwerpunkte",
        "budget": "Budget",
        "budget_value": "höchstens {count} Runden · Lanes {lanes}",
        "grilling_outcome": "Annahmen + offene Entscheidungen als Markdown/JSON unter `{path}`",
        "pill_planning": "Planung",
        "pill_grilling": "Grilling",
        "result": "Status",
        "status_done": "abgeschlossen",
        "status_halted": "angehalten bei {stage}: {decision}",
        "tracker_status": "Tracker-Status",
        "tracker_status_value": "{status} · {done}/{total} Kriterien abgehakt",
        "stages": "Stages",
        "triage": "Triage",
        "triage_none": "keine Empfehlungen",
        "triage_value": "{count} Empfehlungen → {parts}",
        "triage_value_one": "1 Empfehlung → {parts}",
        "for_human": "Offen für den Menschen",
        "triage_pass": "Triage {num}",
        "commit_mode_commit": "automatisch",
        "commit_mode_propose": "Vorschlag",
        "commit_proposal": "Commit-Vorschlag",
        "commit_skipped": "Commit übersprungen",
        "commit_failed": "Commit fehlgeschlagen",
        "commit_failed_proposal": "Vorschlag",
        "hook_modified": "vom Hook geändert: {count} Dateien",
        "hook_side_effects": "Hook-Nebeneffekte: {paths}",
        "all-ignored": "alle Run-Dateien sind von Git ignoriert",
        "no-changes": "keine Run-Datei hat Änderungen",
        "preexisting-changes": "Änderungen vor dem Lauf in {paths}",
        "index-not-empty": "vorgemerkte Änderungen außerhalb des Laufs in {paths}",
        "not-a-leaf": "keine einzelne Datei: {paths}",
        "stage-error": "Vormerken fehlgeschlagen: {summary}",
        "commit-error": "{summary}",
        "staged-set-mismatch": "vorgemerkte Pfade weichen von den Run-Dateien ab: {paths}",
        "hook-added-paths": "ein Hook hat {paths} hinzugefügt",
        "commit_kept": " (Commit behalten)",
        "unverifiable": "nicht verifizierbar (HEAD {head7} könnte der Run-Commit sein, bitte prüfen)",
        "no-head": "das Repository hat noch keinen Commit",
        "commit": "Commit",
        "tracker": "Tracker",
        "tracker_value": "`{path}` · {count} Issues, sofort startbar: {ready}",
        "revisions": "Revisionen",
        "revisions_value": "Spec {spec} · Tickets {tickets}",
        "questions": "Fragen",
        "questions_value": "{asked} in {rounds} von {budget} Runden · Stop: {reason}",
        "assumptions": "Annahmen",
        "decisions": "Entscheidungen",
        "decided": "entschieden",
        "deferred": "zurückgestellt",
        "open": "offen",
        "artifacts": "Artefakte",
        "none": "keine",
        "next": "Nächster Schritt",
        "also_ready": "außerdem startbar",
        "unlocks_one": "schaltet 1 Issue frei",
        "unlocks": "schaltet {count} Issues frei",
        "hitl_next": "HITL, liegt beim Menschen",
        "tracker_complete": "Tracker vollständig erledigt",
        "none_ready": "keins startbar – {waits}",
        "waits_for": "{id} wartet auf {blockers}",
        "chain_with": "Issue-Chain mit {issue}",
        "resolve_decisions": "{count} offene Entscheidungen im Walkthrough klären",
        "resolve_decision_one": "1 offene Entscheidung im Walkthrough klären",
        "plan_from": "Planning mit dem Grilling-Ergebnis `{path}`",
        "prompt": "Prompt für den nächsten Lauf",
        "prompt_unchanged": "das Issue steht nicht im ursprünglichen Prompt; er wird unverändert wiederholt",
    },
}


def read_state(run_dir: Path) -> dict[str, Any]:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise SystemExit(f"No state.json under {run_dir}; initialize the run first")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("workflow") not in PILL_KEYS:
        raise SystemExit(f"{state_path} is not a cmux orchestration run state")
    return state


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise SystemExit(f"{path}:{number} is not valid JSON ({error.msg}); repair the event log first") from error
    return events


def read_artifact(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path}:{error.lineno} is not valid JSON ({error.msg}); repair the artifact first") from error


def current_branch(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch else None


def display_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value
    relative = os.path.relpath(path)
    return value if relative.startswith("..") else relative


def issue_chain_lines(state: dict[str, Any], labels: dict[str, str]) -> list[str]:
    issue = state["issue"]
    lines = [
        f"**{issue['id']} – {issue['title']}**",
        f"- {labels['goal']}: {{{{goal}}}}",
        f"- {labels['scope']}: {{{{scope}}}}",
        f"- {labels['acceptance']}: "
        + labels["criteria"].format(total=issue["acceptance_total"], done=issue["acceptance_done"]),
    ]
    blockers = state.get("blocker_status", {}).get("blockers", [])
    if blockers:
        listed = ", ".join(f"{blocker['id']} ({blocker['status']})" for blocker in blockers)
        lines.append(f"- {labels['blockers']}: {listed}")
    chain = state.get("chain") or []
    if chain:
        triage = labels["triage_autonomous"] if state.get("triage_mode") == "autonomous" else labels["triage_human"]
        lines.append(f"- {labels['chain']}: {' → '.join(chain)} ({triage})")
    else:
        lines.append(f"- {labels['chain']}: {labels['hitl_chain']}")
    branch = current_branch(Path(state["tracker"]))
    if branch:
        lines.append(f"- {labels['branch']}: {branch}")
    return lines


def planning_source(state: dict[str, Any], labels: dict[str, str]) -> str:
    grilling = state.get("grilling_import")
    if grilling:
        return labels["source_grilling"].format(name=Path(grilling["source_json"]).name)
    source = state.get("task", {}).get("source", "")
    if source.startswith("file:"):
        return labels["source_file"].format(name=Path(source[len("file:"):]).name)
    if source == "conversation-summary":
        return labels["source_summary"]
    return labels["source_text"]


def planning_lines(state: dict[str, Any], labels: dict[str, str]) -> list[str]:
    return [
        f"- {labels['task']}: {{{{task}}}}",
        f"- {labels['constraints']}: {{{{constraints}}}}",
        f"- {labels['source']}: {planning_source(state, labels)}",
        f"- {labels['flow']}: {labels['planning_flow']}",
        f"- {labels['outcome']}: {labels['planning_outcome'].format(slug=state['tracker_slug'])}",
    ]


def grilling_lines(state: dict[str, Any], labels: dict[str, str]) -> list[str]:
    budget = labels["budget_value"].format(count=state["max_rounds"], lanes=", ".join(state["lanes"]))
    return [
        f"- {labels['subject']}: {{{{subject}}}}",
        f"- {labels['focus']}: {{{{focus}}}}",
        f"- {labels['constraints']}: {{{{constraints}}}}",
        f"- {labels['budget']}: {budget}",
        f"- {labels['outcome']}: {labels['grilling_outcome'].format(path=state['output_dir'])}",
    ]


BRIEFING_BODIES = {"issue-chain": issue_chain_lines, "planning": planning_lines, "grilling": grilling_lines}


def render_briefing(state: dict[str, Any], events: list[dict[str, Any]], lang: str) -> str:
    labels = LABELS[lang]
    lines = [f"**{labels['heading']} · {state['run_id']}**", ""]
    lines += BRIEFING_BODIES[state["workflow"]](state, labels)
    mode = state.get("commit_mode", "propose")
    lines.append(f"- {labels['commit']}: {labels['commit_mode_' + mode]}")
    return "\n".join(lines) + "\n"


def gates(state: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # All three workflows mirror gates into state.json; planning's gate events nest them differently.
    recorded = state.get("gate_decisions")
    if recorded:
        return list(recorded)
    return [event for event in events if event.get("type") == "gate" and "stage" in event]


def run_outcome(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Done, or halted at the last non-advancing gate. An active run has no recap yet."""
    if state.get("current_stage") == DONE_STAGES[state["workflow"]]:
        return {"status": "done"}
    recorded = gates(state, events)
    last = recorded[-1] if recorded else None
    if last and last.get("decision") in HALTING_DECISIONS:
        return {"status": "halted", "stage": last.get("stage"), "decision": last["decision"]}
    raise SystemExit(
        "run is still active: a recap needs a completed run or a last gate of "
        f"{', '.join(sorted(HALTING_DECISIONS))}"
    )


def duration(state: dict[str, Any], events: list[dict[str, Any]]) -> str:
    try:
        start = datetime.fromisoformat(state["created_at"])
        end = datetime.fromisoformat(events[-1]["time"]) if events else datetime.now(timezone.utc)
    except (KeyError, ValueError):
        return ""
    minutes = max(0, int((end - start).total_seconds() // 60))
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def last_data(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    matches = [event.get("data") for event in events if event.get("type") == event_type]
    return matches[-1] if matches and isinstance(matches[-1], dict) else None


def section_text(markdown: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", markdown, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    rest = markdown[match.end():]
    following = re.search(r"^##\s+", rest, re.MULTILINE)
    return (rest[: following.start()] if following else rest).strip()


def blocked_by(body: str) -> list[str]:
    section = section_text(body, "Blocked by")
    if not section or re.search(r"\bNone\b", section, re.IGNORECASE):
        return []
    ids = set(ISSUE_ID_RE.findall(section))
    if ids:
        return sorted(ids)
    return sorted({f"ISSUE-{int(number):03d}" for number in BARE_NUMBER_RE.findall(section)})


def load_tracker(tracker: Path) -> dict[str, dict[str, Any]] | None:
    """Live issue states, or None when the tracker is missing or not adopted."""
    issue_dir = tracker / "issues"
    if not issue_dir.is_dir():
        return None
    issues: dict[str, dict[str, Any]] = {}
    for path in sorted(issue_dir.glob("*.md")):
        number = ISSUE_FILE_RE.match(path.name.removesuffix(".md"))
        if not number:
            continue
        text = path.read_text(encoding="utf-8")
        front = FRONTMATTER_RE.match(text)
        if not front:
            return None
        fields: dict[str, str] = {}
        for line in front.group(1).splitlines():
            if line and not line.startswith(" ") and ":" in line:
                key, value = line.split(":", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                fields[key.strip()] = value
        body = text[front.end():]
        marks = [match.group("mark") for match in CHECKBOX_RE.finditer(body)]
        issue_id = fields.get("id") or f"ISSUE-{int(number.group(1)):03d}"
        issues[issue_id] = {
            "id": issue_id,
            "path": str(path),
            "title": fields.get("title", ""),
            "type": fields.get("type", ""),
            "status": fields.get("status", ""),
            "blocked_by": blocked_by(body),
            "acceptance_done": sum(1 for mark in marks if mark in "xX"),
            "acceptance_total": len(marks),
        }
    return issues or None


def ranked_candidates(issues: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Startable issues: AFK before HITL, in_progress first, most unblocked issues, lowest ID."""
    def unblocked(issue: dict[str, Any]) -> bool:
        return all(issues.get(blocker, {}).get("status") == "done" for blocker in issue["blocked_by"])

    dependents: dict[str, set[str]] = {}
    for issue in issues.values():
        if issue["status"] != "done":
            for blocker in issue["blocked_by"]:
                dependents.setdefault(blocker, set()).add(issue["id"])

    def unlocks(issue_id: str) -> int:
        seen: set[str] = set()
        pending = [issue_id]
        while pending:
            for dependent in dependents.get(pending.pop(), ()):
                if dependent not in seen:
                    seen.add(dependent)
                    pending.append(dependent)
        return len(seen)

    ready = [
        {**issue, "unlocks": unlocks(issue["id"])}
        for issue in issues.values()
        if issue["status"] in OPEN_STATUSES and unblocked(issue)
    ]
    return sorted(
        ready,
        key=lambda issue: (
            issue["type"].upper() == "HITL",
            issue["status"] != "in_progress",
            -issue["unlocks"],
            int(re.sub(r"\D", "", issue["id"]) or 0),
        ),
    )


def next_issue_lines(
    issues: dict[str, dict[str, Any]] | None, labels: dict[str, str], *, wrap: str = "{issue}"
) -> tuple[list[str], dict[str, Any] | None]:
    """Next-step lines plus the recommended issue when it is one the next run can start."""
    if issues is None:
        return [], None
    ranked = ranked_candidates(issues)
    if not ranked:
        waiting = [issue for issue in issues.values() if issue["status"] in OPEN_STATUSES]
        if not waiting:
            return [f"- {labels['next']}: {labels['tracker_complete']}"], None
        waits = "; ".join(
            labels["waits_for"].format(
                id=issue["id"],
                blockers=", ".join(b for b in issue["blocked_by"] if issues.get(b, {}).get("status") != "done"),
            )
            for issue in waiting[:3]
        )
        return [f"- {labels['next']}: {labels['none_ready'].format(waits=waits)}"], None
    first = ranked[0]
    hitl = first["type"].upper() == "HITL"
    text = f"{first['id']} – {first['title']}"
    if hitl:
        text += f" ({labels['hitl_next']})"
    elif first["unlocks"]:
        count = first["unlocks"]
        text += f" ({labels['unlocks_one'] if count == 1 else labels['unlocks'].format(count=count)})"
    lines = [f"- {labels['next']}: {wrap.format(issue=text)}"]
    others = [issue["id"] + (" (HITL)" if issue["type"].upper() == "HITL" else "") for issue in ranked[1:]]
    if others:
        lines.append(f"  {labels['also_ready']}: {', '.join(others)}")
    return lines, None if hitl else first


def substitute_issue(invocation: str, old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """The human's initial prompt with the next issue swapped in; None when it never named the old one."""
    replacements = [(old.get("path", ""), new["path"]), (Path(old.get("path", "")).name, Path(new["path"]).name)]
    text = invocation
    for before, after in replacements:
        if before:
            text = text.replace(before, after)
    text, count = re.subn(rf"\b{re.escape(old['id'])}\b", new["id"], text)
    return text if count or text != invocation else None


def next_prompt(state: dict[str, Any], issue: dict[str, Any] | None) -> tuple[str, bool] | None:
    """Prompt for the next run, and whether it had to repeat the initial prompt unchanged."""
    workflow = state["workflow"]
    if workflow == "grilling":
        json_path = (state.get("deliverables") or {}).get("json")
        return (f"/cmux-planning {display_path(json_path)}", False) if json_path else None
    if issue is None:
        return None
    if workflow == "planning":
        return f"/cmux-issue-chain {display_path(state['published_tracker']['path'])} {issue['id']}", False
    invocation = state.get("invocation")
    if not invocation:
        return f"/cmux-issue-chain {state['tracker']} {issue['id']}", False
    substituted = substitute_issue(invocation, state["issue"], issue)
    return (invocation, True) if substituted is None else (substituted, False)


def recap_tracker(state: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    if state["workflow"] == "issue-chain":
        return load_tracker(Path(state["tracker"]))
    published = state.get("published_tracker")
    if state["workflow"] == "planning" and isinstance(published, dict):
        return load_tracker(Path(published["path"]))
    return None


def issue_chain_recap(state: dict[str, Any], events: list[dict[str, Any]], labels: dict[str, str]) -> list[str]:
    # Live tracker state: the snapshot in state.json predates the status update before `complete`.
    issue = {**state["issue"], **((recap_tracker(state) or {}).get(state["issue"]["id"]) or {})}
    lines = [f"**{issue['id']} – {issue['title']}**", f"- {labels['outcome']}: {{{{outcome}}}}"]
    lines.append(
        f"- {labels['tracker_status']}: "
        + labels["tracker_status_value"].format(
            status=issue["status"], done=issue["acceptance_done"], total=issue["acceptance_total"]
        )
    )
    stages = [
        f"{gate['stage']} ✓" if gate.get("decision") == "advance" else f"{gate['stage']} ✗ {gate.get('decision')}"
        for gate in gates(state, events)
    ]
    if stages:
        lines.append(f"- {labels['stages']}: {' · '.join(stages)}")
    triaged = [event["data"] for event in events if event.get("type") == "recommendations.triaged"]
    if triaged:
        counts: dict[str, int] = {}
        for item in triaged:
            consequence = str(item.get("consequence") or item.get("verdict") or "?")
            counts[consequence] = counts.get(consequence, 0) + 1
        parts = ", ".join(f"{count} {consequence}" for consequence, count in counts.items())
        template = labels["triage_value_one"] if len(triaged) == 1 else labels["triage_value"]
        lines.append(f"- {labels['triage']}: {template.format(count=len(triaged), parts=parts)}")
    elif state.get("chain") and state.get("current_stage") == DONE_STAGES["issue-chain"]:
        # A halted run may never have reached triage; "none" would claim it did.
        lines.append(f"- {labels['triage']}: {labels['triage_none']}")
    open_items = [item for item in triaged if item.get("verdict") == "for-the-human"]
    if open_items:
        listed = "; ".join(
            f"{item.get('id')} ({labels['triage_pass'].format(num=item.get('pass'))}) – {item.get('title')}"
            for item in open_items
        )
        lines.append(f"- {labels['for_human']}: {listed}")
    return lines


def planning_recap(state: dict[str, Any], events: list[dict[str, Any]], labels: dict[str, str]) -> list[str]:
    lines = [f"- {labels['outcome']}: {{{{outcome}}}}"]
    published = state.get("published_tracker")
    if isinstance(published, dict):
        ready = ", ".join(published.get("ready_frontier") or []) or labels["none"]
        lines.append(
            f"- {labels['tracker']}: "
            + labels["tracker_value"].format(
                path=display_path(published["path"]), count=len(published.get("ticket_ids") or []), ready=ready
            )
        )
    spec = max(0, int(state.get("spec_pass") or 1) - 1)
    tickets = max(0, int(state.get("tickets_pass") or 1) - 1)
    lines.append(f"- {labels['revisions']}: {labels['revisions_value'].format(spec=spec, tickets=tickets)}")
    return lines


def grilling_recap(state: dict[str, Any], events: list[dict[str, Any]], labels: dict[str, str]) -> list[str]:
    lines = [f"- {labels['outcome']}: {{{{outcome}}}}"]
    deliverables = state.get("deliverables") or {}
    artifact_path = deliverables.get("json")
    artifact = None
    if artifact_path and Path(artifact_path).is_file():
        artifact = read_artifact(Path(artifact_path))
    if isinstance(artifact, dict):
        lines.append(
            f"- {labels['questions']}: "
            + labels["questions_value"].format(
                asked=artifact.get("questionsAsked"),
                rounds=artifact.get("roundsRun"),
                budget=artifact.get("maxRounds", state.get("max_rounds")),
                reason=artifact.get("stopReason"),
            )
        )
        decisions = [entry for entry in artifact.get("open_decisions") or [] if isinstance(entry, dict)]
        counts = ", ".join(
            f"{sum(1 for entry in decisions if entry.get('status') == status)} {labels[status]}"
            for status in DECISION_STATUSES
        )
        lines.append(
            f"- {labels['assumptions']}: {len(artifact.get('assumptions') or [])} · {labels['decisions']}: {counts}"
        )
    if deliverables:
        paths = ", ".join(f"`{display_path(deliverables[key])}`" for key in ("markdown", "json") if key in deliverables)
        lines.append(f"- {labels['artifacts']}: {paths}")
    return lines


RECAP_BODIES = {"issue-chain": issue_chain_recap, "planning": planning_recap, "grilling": grilling_recap}


def commit_recap(events, labels):
    outcome = next((event for event in reversed(events)
                    if event.get("type") in {"commit.created", "commit.failed", "commit.skipped"}), None)
    data = outcome.get("data", {}) if outcome else last_data(events, "commit.proposed")
    if not data:
        return []
    if outcome is None:
        return [f"- {labels['commit_proposal']}: {data['subject']}"]
    kind = outcome["type"]
    if kind == "commit.created":
        line = f"- {labels['commit']}: {data['sha'][:7]} {data['subject']}"
        if data.get("hook_modified"):
            line += "; " + labels["hook_modified"].format(count=len(data["hook_modified"]))
        if data.get("hook_side_effects"):
            line += "; " + labels["hook_side_effects"].format(paths=", ".join(data["hook_side_effects"]))
        return [line]
    reason = data["reason"]
    paths = ", ".join(data.get("paths", []))
    if reason == "staged-set-mismatch":
        paths = "extra: " + ", ".join(data.get("extra", [])) + "; missing: " + ", ".join(data.get("missing", []))
    error = labels[reason].format(paths=paths, summary=data.get("summary", ""), head7=(data.get("head") or "?")[:7])
    if reason == "hook-added-paths" and data.get("reset") is False:
        error += labels["commit_kept"]
    if kind == "commit.skipped":
        return [f"- {labels['commit_skipped']}: {error}"]
    return [f"- {labels['commit_failed']}: {error}, {labels['commit_failed_proposal']}: {data['subject']}"]


def render_recap(state: dict[str, Any], events: list[dict[str, Any]], lang: str) -> str:
    labels = LABELS[lang]
    outcome = run_outcome(state, events)
    heading = f"**{labels['recap_heading']} · {state['run_id']}"
    elapsed = duration(state, events)
    lines = [heading + (f" · {elapsed}**" if elapsed else "**"), ""]
    if outcome["status"] == "done":
        status = labels["status_done"]
    else:
        status = labels["status_halted"].format(stage=outcome["stage"], decision=outcome["decision"])
    lines.append(f"{labels['result']}: **{status}**")
    lines.append("")
    lines += RECAP_BODIES[state["workflow"]](state, events, labels)
    lines += commit_recap(events, labels)
    # A halted run's next step is resolving the halt; the outcome sentence names it.
    if outcome["status"] == "done":
        lines += next_step_lines(state, labels)
    return "\n".join(lines) + "\n"


def next_step_lines(state: dict[str, Any], labels: dict[str, str]) -> list[str]:
    workflow = state["workflow"]
    if workflow in {"issue-chain", "planning"}:
        wrap = labels["chain_with"] if workflow == "planning" else "{issue}"
        lines, issue = next_issue_lines(recap_tracker(state), labels, wrap=wrap)
        return lines + prompt_block(state, issue, labels) if issue else lines
    json_path = (state.get("deliverables") or {}).get("json")
    if not json_path or not Path(json_path).is_file():
        return []
    artifact = read_artifact(Path(json_path))
    decisions = artifact.get("open_decisions") or [] if isinstance(artifact, dict) else []
    still_open = sum(1 for entry in decisions if isinstance(entry, dict) and entry.get("status") == "open")
    if still_open:
        template = labels["resolve_decision_one"] if still_open == 1 else labels["resolve_decisions"]
        return [f"- {labels['next']}: {template.format(count=still_open)}"]
    return [f"- {labels['next']}: {labels['plan_from'].format(path=display_path(json_path))}"] + prompt_block(
        state, None, labels
    )


def prompt_block(state: dict[str, Any], issue: dict[str, Any] | None, labels: dict[str, str]) -> list[str]:
    generated = next_prompt(state, issue)
    if generated is None:
        return []
    prompt, unchanged = generated
    lines = ["", f"{labels['prompt']}:", "~~~", prompt, "~~~"]
    if unchanged:
        lines.append(f"({labels['prompt_unchanged']})")
    return lines


def checked_next_step(state: dict[str, Any], text: str) -> dict[str, Any] | None:
    """The orchestrator may pick another startable issue, but only with a written reason."""
    if state["workflow"] not in {"issue-chain", "planning"}:
        return None
    issues = recap_tracker(state)
    if issues is None:
        return None
    ranked = [issue["id"] for issue in ranked_candidates(issues)]
    redraft = "if the tracker changed since recap-draft, delete recap.md and draft it again"
    match = NEXT_LINE_RE.search(text)
    if not match:
        if ranked:
            raise SystemExit(f"the next-step line naming one of {', '.join(ranked)} is missing; {redraft}")
        return None
    chosen = match.group(1)
    if chosen not in ranked:
        raise SystemExit(
            f"next step {chosen} is not startable; candidates: {', '.join(ranked) or 'none'}; {redraft}"
        )
    override = chosen != ranked[0]
    reasoned = bool(REASON_LINE_RE.search(text))
    if override and not reasoned:
        raise SystemExit(
            f"next step {chosen} deviates from the default {ranked[0]}; add a reason line under it"
        )
    block = PROMPT_BLOCK_RE.search(text)
    # HITL issues are not started by a run, so they get no prompt.
    expected = None if issues[chosen]["type"].upper() == "HITL" else next_prompt(state, issues[chosen])
    if expected and not block:
        raise SystemExit("the prompt for the next run is missing; restore it or delete recap.md and draft again")
    prompt_edited = False
    if block and expected:
        prompt, unchanged = expected
        if not unchanged and chosen not in block.group(1):
            raise SystemExit(f"the prompt for the next run must name {chosen}")
        prompt_edited = block.group(1) != prompt
        if prompt_edited and not reasoned:
            raise SystemExit("the prompt for the next run deviates from the generated one; add a reason line")
    return {"default": ranked[0], "chosen": chosen, "override": override, "prompt_edited": prompt_edited}


def pill_text(state: dict[str, Any], lang: str, outcome: dict[str, Any] | None = None) -> str:
    labels = LABELS[lang]
    workflow = state["workflow"]
    if workflow == "issue-chain":
        text = f"{state['issue']['id']} · {state['issue']['title']}"
    elif workflow == "planning":
        text = f"{labels['pill_planning']} · {state['tracker_slug']}"
    else:
        text = f"{labels['pill_grilling']} · {state['slug']}"
    if outcome is not None:
        text = f"✓ {text}" if outcome["status"] == "done" else f"{outcome['decision']} · {text}"
    return text if len(text) <= PILL_MAX_CHARS else text[: PILL_MAX_CHARS - 1].rstrip() + "…"


def placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def cmux(args: argparse.Namespace, argv: list[str]) -> str | None:
    """Run one cmux call; return a failure description instead of raising."""
    base = shlex.split(args.cmux_cmd) if args.cmux_cmd else ["cmux"]
    try:
        result = subprocess.run(base + argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    if result.returncode:
        return result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return None


def update_pill(args: argparse.Namespace, state: dict[str, Any], outcome: dict[str, Any] | None) -> str | None:
    """Set (or with --clear-status remove) the run pill. Returns the pill text that was set."""
    workspace_id = state.get("workspace_id")
    if not workspace_id or args.no_status:
        return None
    key = PILL_KEYS[state["workflow"]]
    if getattr(args, "clear_status", False):
        failure = cmux(args, ["clear-status", key, "--workspace", workspace_id])
        pill = None
    else:
        pill = pill_text(state, args.lang, outcome)
        color = PILL_COLORS["running" if outcome is None else outcome["status"]]
        failure = cmux(
            args,
            ["set-status", key, pill, "--color", color, "--priority", str(PILL_PRIORITY), "--workspace", workspace_id],
        )
    if failure:
        # The pill is a convenience; a cmux hiccup must not block the run.
        print(f"status pill not updated: {failure}", file=sys.stderr)
        return None
    return pill


def draft(args: argparse.Namespace, filename: str, render: Any) -> int:
    run_dir = Path(args.run_dir)
    state = read_state(run_dir)
    path = run_dir / filename
    # Never overwrite: a filled text is the orchestrator's phrasing and survives resumes.
    if not path.exists():
        path.write_text(render(state, read_events(run_dir), args.lang), encoding="utf-8")
    print(json.dumps({"path": str(path), "placeholders": placeholders(path.read_text(encoding="utf-8"))}))
    return 0


def show(args: argparse.Namespace, filename: str, event_type: str, recap: bool) -> int:
    run_dir = Path(args.run_dir)
    state = read_state(run_dir)
    path = run_dir / filename
    if not path.is_file():
        command = "recap-draft" if recap else "draft"
        raise SystemExit(f"No {filename} under {run_dir}; run `run_briefing.py {command}` first")
    text = path.read_text(encoding="utf-8")
    missing = placeholders(text)
    if missing:
        raise SystemExit(f"{path} still has unfilled placeholders: {', '.join(missing)}")
    outcome = run_outcome(state, read_events(run_dir)) if recap else None
    next_step = checked_next_step(state, text) if outcome and outcome["status"] == "done" else None
    pill = update_pill(args, state, outcome)
    event = {
        "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "type": event_type,
        "message": f"{'recap' if recap else 'briefing'} shown to the human",
        "data": {"path": filename, "pill": pill, **({"outcome": outcome, "next_step": next_step} if recap else {})},
    }
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("draft", "Write the briefing skeleton from state.json (never overwrites)"),
        ("recap-draft", "Write the recap skeleton of a completed or halted run (never overwrites)"),
    ):
        command = subparsers.add_parser(name, help=text)
        command.add_argument("--run-dir", required=True)
        command.add_argument("--lang", choices=sorted(LABELS), default="en", help="Label language: the human's language")
    for name, text in (
        ("show", "Validate, print, log, and set the running pill"),
        ("recap-show", "Validate, print, log, and set the done/halted pill"),
    ):
        command = subparsers.add_parser(name, help=text)
        command.add_argument("--run-dir", required=True)
        command.add_argument("--lang", choices=sorted(LABELS), default="en", help="Pill label language")
        command.add_argument("--no-status", action="store_true", help="Leave the sidebar status pill untouched")
        command.add_argument("--cmux-cmd", help=argparse.SUPPRESS)
        if name == "recap-show":
            command.add_argument("--clear-status", action="store_true", help="Remove the run pill instead of marking it")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "draft":
        return draft(args, BRIEFING_FILE, render_briefing)
    if args.command == "recap-draft":
        return draft(args, RECAP_FILE, render_recap)
    if args.command == "show":
        return show(args, BRIEFING_FILE, "run.briefing", recap=False)
    return show(args, RECAP_FILE, "run.recap", recap=True)


if __name__ == "__main__":
    raise SystemExit(main())
