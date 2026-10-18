"""Shared event identity, snapshot labels, and audit policy for test evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re

from worker_snapshot import ISSUE_WORKERS


TEST_EVIDENCE_EVENT = ("orchestrator.verified", "test evidence")
EVIDENCE_EXEMPT_STAGES = frozenset({"triage"})
EVIDENCE_GATED_STAGES = tuple(stage for stage in ISSUE_WORKERS
                              if stage not in EVIDENCE_EXEMPT_STAGES)
LAUNCH = "launched"
CAPTURE = "report-captured"


def snapshot_label(kind: str, stage: str, pass_num: int | str) -> str:
    return f"{kind} {stage}-{pass_num}"


def snapshot_label_pattern(stage: str) -> re.Pattern:
    """Match either snapshot kind, preserving kind/pass capture groups."""
    return re.compile(snapshot_label(f"({re.escape(LAUNCH)}|{re.escape(CAPTURE)})", re.escape(stage),
                                     r"([1-9][0-9]*)"))


def read_events(run_dir: Path) -> list[dict]:
    """Read audit objects strictly: blank and non-object lines are errors."""
    path = run_dir / "events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    if any(not isinstance(event, dict) for event in events):
        raise ValueError("events.jsonl holds a non-object line")
    return events
