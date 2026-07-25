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
    "codebase": {"worker": "claude", "web": False, "label": "Researcher Codebase"},
    "codebase2": {"worker": "codex", "web": False, "label": "Researcher Codebase2 (Codex)"},
    "docs": {"worker": "claude", "web": True, "label": "Researcher Docs"},
    "web": {"worker": "claude", "web": True, "label": "Researcher Web"},
}

# Minimum wait per lane and round, uniform across lanes (see SKILL.md, Lane Wait Policy).
LANE_WAIT_MINUTES = 15


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
