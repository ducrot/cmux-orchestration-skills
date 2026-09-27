#!/usr/bin/env python3
"""Shared helpers for the cmux-grilling skill."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# The four research lanes. Persistent panes for the whole session; the orchestrator
# never substitutes hidden subagents for them.
LANES = {
    "codebase": {"label": "Researcher Codebase"},
    "codebase2": {"label": "Researcher Codebase2"},
    "docs": {"label": "Researcher Docs"},
    "web": {"label": "Researcher Web"},
}

# Minimum wait per lane and round, uniform across lanes (see SKILL.md, Lane Wait Policy).
LANE_WAIT_MINUTES = 15
# Each question beyond the first adds this much to a round's wait.
LANE_WAIT_EXTRA_MINUTES_PER_QUESTION = 5


def round_wait_minutes(questions: int) -> int:
    """Minimum wait for a round asking `questions` questions."""
    return LANE_WAIT_MINUTES + LANE_WAIT_EXTRA_MINUTES_PER_QUESTION * max(questions - 1, 0)

# Task framing is load-bearing, not style: a Claude lane reads "Read <path> and report back"
# as a summarization request — it summarizes the prompt and waits — while Codex reads the same
# line as a work order. The two kinds differ on purpose:
# a session prompt really is adopt-and-wait, a round prompt is work now. Policy, not a per-run
# choice (SKILL.md, CMUX Control).
DELIVERY_TEMPLATES = {
    "session": (
        "Your standing contract for this session is in {prompt_path}. It is not a document to "
        "summarize. Adopt it, confirm in one line, then wait idle for round prompts."
    ),
    "round": (
        "Your round task is in {prompt_path}. It is not a document to read back or summarize. "
        "Answer it now and write your report to the handoff path it names."
    ),
}


def delivery_text(kind: str, prompt_path: str) -> str:
    """Text that hands a lane its rendered session contract or round prompt."""
    return DELIVERY_TEMPLATES[kind].format(prompt_path=prompt_path)


def session_prompt_path(run_dir: Path, lane: str) -> Path:
    return run_dir / "prompts" / f"session-{lane}.md"


def session_marker_path(run_dir: Path, lane: str) -> Path:
    return run_dir / "artifacts" / f"session-{lane}" / "started"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


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


RUN_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def slugify(text: str, max_length: int = 30) -> str:
    """Normalize a task key, retaining whole words within the cap when possible."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_length:
        boundary = slug.rfind("-", 0, max_length + 1)
        slug = slug[:boundary if boundary > 0 else max_length]
    return slug.rstrip("-") or "task"


def run_identifier(workflow: str, key: str, now: str) -> str:
    """Build a readable UTC minute identity using the shared run-id grammar."""
    return RUN_ID_RE.sub("-", f"{workflow}-{key}-{now[:10]}-{now[11:13]}{now[14:16]}").strip("-")


def read_run_state(run_dir: Path) -> dict[str, Any]:
    """Load a current run before any continuation or lifecycle write."""
    state = read_json(run_dir / "state.json")
    # A state without max_rounds predates multi-question rounds and is not resumed.
    if (
        not isinstance(state, dict)
        or state.get("workflow") != "grilling"
        or state.get("layout_version") != 1
        or "max_rounds" not in state
    ):
        raise SystemExit(f"unsupported legacy layout in {run_dir}; inspect read-only and restart the run")
    return state
