#!/usr/bin/env python3
"""Shared helpers for the cmux-grilling skill."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SLUG_RE = re.compile(r"[^a-z0-9]+")

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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, max_length: int = 48) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "grill"


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
