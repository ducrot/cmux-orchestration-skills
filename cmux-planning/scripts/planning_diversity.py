#!/usr/bin/env python3
"""Model-diversity identities and operator guidance for planning stages."""

from __future__ import annotations

import copy
import json
import shlex
from pathlib import Path
from typing import Any

from orchestrator_lib import sha256_bytes
from stage_snapshot import STAGE_ROLE, WORKFLOW


REVIEWER = "reviewer"
REVIEWER_ROLE = f"{WORKFLOW}.{REVIEWER}"
# Every stage is decided against the author/reviewer pair that owns its artifact: the author
# stage itself, and the reviewer stage that checks that author's work. Stage names carry the
# pairing, so `tickets-review` resolves against `tickets`.
AUTHOR_ROLE_FOR_STAGE = {stage: stage.split("-", 1)[0] for stage in STAGE_ROLE}
DECISION_STATUSES = {"pending", "refused", "confirmed"}
PENDING_STATUSES = {"pending", "refused"}
STATE_SCRIPT = Path(__file__).resolve().with_name("planning_state.py")


def _worker_identity(role: str, worker: dict[str, Any]) -> dict[str, str]:
    return {
        "role": role,
        "profile": worker["profile"],
        "harness": worker["harness"],
        "model": worker["model"],
    }


def resolution_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Return the author/reviewer resolution for one stage snapshot, including a stable key.

    Both identities come from the resolved profiles rather than the selected worker, so an author
    stage and the reviewer stage that checks it produce the same key: a decision taken at one
    carries to the other, and a configuration edit between them is caught instead of launched.

    Profile names and effort are deliberately excluded from the key. The human decision covers
    exactly the resolved harness-and-model combination named by the issue contract.
    """
    stage = snapshot.get("stage")
    author_role = AUTHOR_ROLE_FOR_STAGE.get(stage)
    if author_role is None:
        return None
    profiles = snapshot["resolved_profiles"]
    author = _worker_identity(f"{WORKFLOW}.{author_role}", profiles[author_role])
    reviewer = _worker_identity(REVIEWER_ROLE, profiles[REVIEWER])
    combination = {
        "author": {"harness": author["harness"], "model": author["model"]},
        "reviewer": {"harness": reviewer["harness"], "model": reviewer["model"]},
    }
    combination_id = sha256_bytes(
        json.dumps(combination, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return {
        "combination_id": combination_id,
        "collision": combination["author"] == combination["reviewer"],
        "author": author,
        "reviewer": reviewer,
        # The role the gated stage would launch, so the guidance names the profile the human can
        # still change rather than one whose work is already done.
        "selected_role": f"{WORKFLOW}.{STAGE_ROLE[stage]}",
    }


def decision_command(run_dir: Path, decision: str) -> str:
    return shlex.join(
        [
            "python3",
            str(STATE_SCRIPT),
            "diversity-confirmation",
            "--run-dir",
            str(run_dir),
            "--decision",
            decision,
            "--reason",
            "<human-reason>",
        ]
    )


def configuration_guidance(
    resolution: dict[str, Any], *, configuration_source: str
) -> dict[str, str]:
    """Where the human assigns a diverse profile, whatever the resolution currently is."""
    assignment_path = f"workflows.{resolution['selected_role']}"
    configuration_path = Path(configuration_source).resolve()
    return {
        "shared_configuration_path": str(configuration_path),
        "assignment_path": assignment_path,
        "guidance": (
            f"To restore model diversity, explicitly assign a diverse profile at "
            f"{configuration_path} under {assignment_path}; the orchestrator "
            "will not substitute a profile automatically."
        ),
    }


def resolution_record(
    snapshot: dict[str, Any], resolution: dict[str, Any], *, configuration_source: str
) -> dict[str, Any]:
    """The decidable identity of one resolved author/reviewer pair, colliding or not."""
    return {
        "status": "pending",
        "stage": snapshot["stage"],
        "pass": snapshot["pass"],
        "combination_id": resolution["combination_id"],
        "collision": resolution["collision"],
        "author": resolution["author"],
        "reviewer": resolution["reviewer"],
        **configuration_guidance(resolution, configuration_source=configuration_source),
        "decisions": [],
    }


def warning_record(
    snapshot: dict[str, Any],
    *,
    run_dir: Path,
    configuration_source: str,
    resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if resolution is None:
        resolution = resolution_from_snapshot(snapshot)
    if resolution is None or not resolution["collision"]:
        raise ValueError("a diversity warning requires a colliding author snapshot")
    author = resolution["author"]
    reviewer = resolution["reviewer"]
    run_dir = run_dir.resolve()
    record = resolution_record(snapshot, resolution, configuration_source=configuration_source)
    record.update(
        {
            "warning": (
                f"Model diversity is missing: {author['role']} resolves to profile "
                f"{author['profile']!r} (harness {author['harness']!r}, model {author['model']!r}), "
                f"and {reviewer['role']} resolves to profile {reviewer['profile']!r} "
                f"(harness {reviewer['harness']!r}, model {reviewer['model']!r}). "
                "Explicit human confirmation with a reason is required before this author stage can "
                "be prepared for launch."
            ),
            "confirmation_command": decision_command(run_dir, "confirm"),
            "refusal_command": decision_command(run_dir, "refuse"),
            "requested_at": snapshot["resolved_at"],
            "effective_overrides": copy.deepcopy(snapshot["effective_overrides"]),
            "live_profile_probe": copy.deepcopy(snapshot["live_profile_probe"]),
        }
    )
    return record


def collision_warning(
    snapshot: dict[str, Any], *, run_dir: Path, configuration_source: str
) -> dict[str, Any] | None:
    """Return a pending warning record when an author snapshot collides with the reviewer."""
    resolution = resolution_from_snapshot(snapshot)
    if resolution is None or not resolution["collision"]:
        return None
    return warning_record(
        snapshot,
        run_dir=run_dir,
        configuration_source=configuration_source,
        resolution=resolution,
    )


def public_warning(record: dict[str, Any]) -> dict[str, Any]:
    """Return warning/decision data without the internal snapshot-replay settings."""
    return {
        key: copy.deepcopy(value)
        for key, value in record.items()
        if key not in {"effective_overrides", "live_profile_probe"}
    }


def pending_confirmation(state: dict[str, Any], stage: str | None = None) -> dict[str, Any] | None:
    record = state.get("diversity_confirmation")
    if not isinstance(record, dict) or record.get("status") not in PENDING_STATUSES:
        return None
    if stage is not None and record.get("stage") != stage:
        return None
    return record
