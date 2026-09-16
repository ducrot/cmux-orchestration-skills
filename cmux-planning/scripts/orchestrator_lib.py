#!/usr/bin/env python3
"""Dependency-free persistence and identity helpers for cmux-planning."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents_config import durable_publish


STAGES = ("spec", "spec-review", "tickets", "tickets-review")
ROLE_LABELS = {
    "spec": "Spec Author",
    "spec-review": "Spec Reviewer",
    "tickets": "Tickets Author",
    "tickets-review": "Tickets Reviewer",
}
MINIMUM_WAIT_MINUTES = {
    "spec": 45,
    "spec-review": 45,
    "tickets": 45,
    "tickets-review": 45,
}
# One statement of what the Git-visible detector sees, so the snapshot, the tree baseline and
# the run state cannot describe different boundaries.
INTEGRITY_BOUNDARY = {
    "covered": [
        "tracked changes",
        "staged changes",
        "untracked paths and their content (regular files up to the size cap and symlink target bytes)",
        "commits (HEAD movement)",
    ],
    "not_covered": [
        "ignored files",
        "skipped untracked content (files above the size cap or unsupported types)",
        "contents of unreadable untracked directories that Git omits with a warning",
    ],
}
PROMPT_DELIVERY_TEMPLATE = (
    "Your task assignment is in {prompt_path}. It is not a document to read back or summarize. "
    "Execute it now and write your final report to the handoff path it names."
)
CURRENT_CONFIGURATION_CREATED_KEY = "configuration_created_and_accepted"
LEGACY_CONFIGURATION_CREATED_KEY = "configuration_created_or_migrated_and_accepted"


class PlanningStateCompatibilityError(ValueError):
    """A durable planning state cannot be interpreted without guessing."""


def configuration_created_and_accepted(state: dict[str, Any], *, source: Path) -> bool:
    """Resolve the current or legacy field without changing the persisted representation."""
    current_present = CURRENT_CONFIGURATION_CREATED_KEY in state
    legacy_present = LEGACY_CONFIGURATION_CREATED_KEY in state
    if not current_present and not legacy_present:
        raise PlanningStateCompatibilityError(
            f"planning state {source} has no configuration creation acceptance field; expected "
            f"{CURRENT_CONFIGURATION_CREATED_KEY!r} (current) or "
            f"{LEGACY_CONFIGURATION_CREATED_KEY!r} (legacy)"
        )

    for key in (CURRENT_CONFIGURATION_CREATED_KEY, LEGACY_CONFIGURATION_CREATED_KEY):
        if key in state and not isinstance(state[key], bool):
            raise PlanningStateCompatibilityError(
                f"planning state {source} field {key!r} must be true or false, not "
                f"{type(state[key]).__name__}"
            )

    if current_present and legacy_present:
        current = state[CURRENT_CONFIGURATION_CREATED_KEY]
        legacy = state[LEGACY_CONFIGURATION_CREATED_KEY]
        if current != legacy:
            raise PlanningStateCompatibilityError(
                f"conflicting planning configuration state in {source}: "
                f"{CURRENT_CONFIGURATION_CREATED_KEY!r} is {current!r}, but legacy "
                f"{LEGACY_CONFIGURATION_CREATED_KEY!r} is {legacy!r}; make the values agree "
                "before loading or resuming this run"
            )
        return current
    key = CURRENT_CONFIGURATION_CREATED_KEY if current_present else LEGACY_CONFIGURATION_CREATED_KEY
    return state[key]


def integrity_boundary() -> dict[str, list[str]]:
    return copy.deepcopy(INTEGRITY_BOUNDARY)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_planning_state(path: Path) -> dict[str, Any]:
    """Read durable run state through the explicit current/legacy compatibility contract.

    The returned dict is the persisted representation, so a legacy-only run has no current key.
    Read the value through configuration_created_and_accepted(), never by indexing the dict.
    """
    state = read_json(path)
    # A structurally invalid file is not a compatibility question, so callers that deliberately
    # skip unreadable directories keep skipping it instead of aborting on the whole listing.
    if not isinstance(state, dict):
        raise ValueError(f"planning state root in {path} is not an object")
    configuration_created_and_accepted(state, source=path)
    return state


def write_json(path: Path, data: Any) -> None:
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def append_event(
    run_dir: Path, event_type: str, message: str, data: dict[str, Any], *, time: str | None = None
) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": time or utc_now(), "type": event_type, "message": message, "data": data},
    )


def read_event_stream(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read the durable event stream, collecting per-line problems instead of raising."""
    path = run_dir / "events.jsonl"
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events, ["events.jsonl is missing"]
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # A blank separator line is not corruption, and rejecting it would strand every
        # lifecycle command, close included, on an otherwise readable stream.
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"events.jsonl line {number} is malformed")
            continue
        if not isinstance(entry, dict):
            errors.append(f"events.jsonl line {number} is not an object")
            continue
        events.append(entry)
    return events, errors


def planning_events(run_dir: Path) -> list[dict[str, Any]]:
    """Read the durable event stream strictly for lifecycle-changing commands."""
    events, errors = read_event_stream(run_dir)
    if errors:
        raise ValueError(f"planning event stream in {run_dir} is unusable: {errors[0]}")
    return events


def matching_event(entry: dict[str, Any], stage: str, pass_num: int) -> bool:
    data = entry.get("data")
    return (
        isinstance(data, dict)
        and data.get("stage") == stage
        and data.get("pass") == pass_num
    )


def matching_stage_pass_event(
    entry: dict[str, Any], event_type: str, stage: str, pass_num: int
) -> bool:
    return entry.get("type") == event_type and matching_event(entry, stage, pass_num)


def surface_event_recorded(
    events: list[dict[str, Any]], event_type: str, stage: str, pass_num: int, surface: str
) -> bool:
    """Report whether one stage pass already recorded ``event_type`` under this identity."""
    return any(
        matching_stage_pass_event(entry, event_type, stage, pass_num)
        and entry.get("data", {}).get("surface_id") == surface
        for entry in events
    )


def validate_recorded_surface(
    events: list[dict[str, Any]], stage: str, pass_num: int, supplied_surface: str,
    *, any_launch: bool = False,
) -> str:
    """Reject identities other than a UUID persisted by ``pane.launched`` for this stage pass.

    Work verbs take only the latest launch. ``any_launch`` is the accepted close-only recovery
    exception: a pane orphaned by a later failed or retried launch stays closable, while
    positional refs and unrecorded UUIDs remain invalid for every verb.
    """
    recorded = [
        entry["data"]["surface_id"]
        for entry in events
        if matching_stage_pass_event(entry, "pane.launched", stage, pass_num)
        and isinstance(entry.get("data", {}).get("surface_id"), str)
        and entry["data"]["surface_id"]
    ]
    launched = any(
        matching_stage_pass_event(entry, "pane.launched", stage, pass_num) for entry in events
    )
    if not launched:
        raise ValueError(
            f"no recorded pane launch identity for {stage} pass {pass_num}; run pane_ctl.py launch first"
        )
    if not recorded:
        raise ValueError(
            f"recorded pane launch for {stage} pass {pass_num} has no stable surface_id"
        )
    accepted = recorded if any_launch else recorded[-1:]
    if supplied_surface not in accepted:
        listed = ", ".join(repr(value) for value in accepted)
        raise ValueError(
            f"--surface {supplied_surface!r} does not match recorded stable surface_id "
            f"{listed} for {stage} pass {pass_num}; use --surface {accepted[-1]!r}"
        )
    return supplied_surface


def atomic_write(path: Path, payload: bytes) -> None:
    """Publish one complete file in place; readers see old bytes or new bytes, never a prefix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    durable_publish(path, payload, mode=0o644, suffix=".tmp", publish=os.replace)


def checkout_identity(repository: Path) -> dict[str, str]:
    def git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(repository), *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"git {' '.join(args)} could not run: {error}") from error
        if result.returncode != 0:
            raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    head = git("rev-parse", "HEAD").strip()
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    return {
        "repository": str(repository.resolve()),
        "head": head,
        "status_sha256": sha256_bytes(status.encode("utf-8")),
    }


def delivery_text(prompt_path: str) -> str:
    return PROMPT_DELIVERY_TEMPLATE.format(prompt_path=prompt_path)


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
