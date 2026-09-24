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
        "budget_value": "at most {count} questions · lanes {lanes}",
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
        "commit": "Commit",
        "tracker": "Tracker",
        "tracker_value": "`{path}` · {count} issues, ready now: {ready}",
        "revisions": "Revisions",
        "revisions_value": "spec {spec} · tickets {tickets}",
        "questions": "Questions",
        "questions_value": "{asked} of {budget} · stop: {reason}",
        "assumptions": "Assumptions",
        "decisions": "decisions",
        "decided": "decided",
        "deferred": "deferred",
        "open": "open",
        "artifacts": "Artifacts",
        "none": "none",
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
        "budget_value": "höchstens {count} Fragen · Lanes {lanes}",
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
        "commit": "Commit",
        "tracker": "Tracker",
        "tracker_value": "`{path}` · {count} Issues, sofort startbar: {ready}",
        "revisions": "Revisionen",
        "revisions_value": "Spec {spec} · Tickets {tickets}",
        "questions": "Fragen",
        "questions_value": "{asked} von {budget} · Stop: {reason}",
        "assumptions": "Annahmen",
        "decisions": "Entscheidungen",
        "decided": "entschieden",
        "deferred": "zurückgestellt",
        "open": "offen",
        "artifacts": "Artefakte",
        "none": "keine",
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    budget = labels["budget_value"].format(count=state["max_questions"], lanes=", ".join(state["lanes"]))
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


def issue_chain_recap(state: dict[str, Any], events: list[dict[str, Any]], labels: dict[str, str]) -> list[str]:
    issue = state["issue"]
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
        artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    if isinstance(artifact, dict):
        lines.append(
            f"- {labels['questions']}: "
            + labels["questions_value"].format(
                asked=artifact.get("questionsAsked"),
                budget=artifact.get("maxQuestions", state.get("max_questions")),
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
    commit = last_data(events, "commit.proposed")
    if commit and commit.get("subject"):
        lines.append(f"- {labels['commit']}: {commit['subject']}")
    return "\n".join(lines) + "\n"


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
    pill = update_pill(args, state, outcome)
    event = {
        "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "type": event_type,
        "message": f"{'recap' if recap else 'briefing'} shown to the human",
        "data": {"path": filename, "pill": pill, **({"outcome": outcome} if recap else {})},
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
