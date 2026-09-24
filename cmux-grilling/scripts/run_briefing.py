#!/usr/bin/env python3
"""Run briefing: a compact what-this-run-does overview for the human, plus a sidebar pill.

Vendored byte-identical into cmux-issue-chain, cmux-planning, and cmux-grilling. `draft`
writes <run-dir>/briefing.md with the facts filled in from state.json and `{{name}}`
placeholders for the parts only the orchestrator can phrase. `show` refuses while a
placeholder remains, prints the briefing, logs `run.briefing`, and sets the status pill.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BRIEFING_FILE = "briefing.md"
PLACEHOLDER_RE = re.compile(r"\{\{([a-z_]+)\}\}")
PILL_KEYS = {"issue-chain": "cmux-issue-chain-run", "planning": "cmux-planning-run", "grilling": "cmux-grilling-run"}
PILL_COLOR = "#8e8e93"
# Above the role pills (priority 80), so the run topic stays first in the sidebar.
PILL_PRIORITY = 90
PILL_MAX_CHARS = 48

LABELS = {
    "en": {
        "heading": "Run briefing",
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
    },
    "de": {
        "heading": "Run-Briefing",
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


BODIES = {"issue-chain": issue_chain_lines, "planning": planning_lines, "grilling": grilling_lines}


def render_skeleton(state: dict[str, Any], lang: str) -> str:
    labels = LABELS[lang]
    lines = [f"**{labels['heading']} · {state['run_id']}**", ""]
    lines += BODIES[state["workflow"]](state, labels)
    return "\n".join(lines) + "\n"


def pill_text(state: dict[str, Any], lang: str) -> str:
    labels = LABELS[lang]
    workflow = state["workflow"]
    if workflow == "issue-chain":
        text = f"{state['issue']['id']} · {state['issue']['title']}"
    elif workflow == "planning":
        text = f"{labels['pill_planning']} · {state['tracker_slug']}"
    else:
        text = f"{labels['pill_grilling']} · {state['slug']}"
    return text if len(text) <= PILL_MAX_CHARS else text[: PILL_MAX_CHARS - 1].rstrip() + "…"


def placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def cmd_draft(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state = read_state(run_dir)
    path = run_dir / BRIEFING_FILE
    # Never overwrite: a filled briefing is the orchestrator's phrasing and survives resumes.
    if not path.exists():
        path.write_text(render_skeleton(state, args.lang), encoding="utf-8")
    print(json.dumps({"path": str(path), "placeholders": placeholders(path.read_text(encoding="utf-8"))}))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state = read_state(run_dir)
    path = run_dir / BRIEFING_FILE
    if not path.is_file():
        raise SystemExit(f"No {BRIEFING_FILE} under {run_dir}; run `run_briefing.py draft` first")
    text = path.read_text(encoding="utf-8")
    missing = placeholders(text)
    if missing:
        raise SystemExit(f"{path} still has unfilled placeholders: {', '.join(missing)}")
    pill = None
    workspace_id = state.get("workspace_id")
    if workspace_id and not args.no_status:
        pill = pill_text(state, args.lang)
        base = shlex.split(args.cmux_cmd) if args.cmux_cmd else ["cmux"]
        argv = base + [
            "set-status", PILL_KEYS[state["workflow"]], pill,
            "--color", PILL_COLOR, "--priority", str(PILL_PRIORITY), "--workspace", workspace_id,
        ]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            failure = (
                (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
                if result.returncode
                else None
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            failure = str(error)
        if failure:
            # The pill is a convenience; a cmux hiccup must not block the run.
            print(f"status pill not set: {failure}", file=sys.stderr)
            pill = None
    event = {
        "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "type": "run.briefing",
        "message": "briefing shown to the human",
        "data": {"path": BRIEFING_FILE, "pill": pill},
    }
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    draft = subparsers.add_parser("draft", help="Write the briefing skeleton from state.json (never overwrites)")
    draft.add_argument("--run-dir", required=True)
    draft.add_argument("--lang", choices=sorted(LABELS), default="en", help="Label language: the human's language")
    show = subparsers.add_parser("show", help="Validate, print, log, and set the sidebar status pill")
    show.add_argument("--run-dir", required=True)
    show.add_argument("--lang", choices=sorted(LABELS), default="en", help="Pill label language")
    show.add_argument("--no-status", action="store_true", help="Skip the sidebar status pill")
    show.add_argument("--cmux-cmd", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return {"draft": cmd_draft, "show": cmd_show}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
