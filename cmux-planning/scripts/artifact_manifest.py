#!/usr/bin/env python3
"""Immutable identities and attempt-scoped paths for cmux-planning run artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from orchestrator_lib import (
    append_event,
    read_planning_state,
    sha256_bytes,
    utc_now,
    write_json,
)


MANIFEST_VERSION = 1
RUN_STATE_SCHEMA_VERSION = 3

# One binding between a worker handoff role and its manifest kind, shared by the producers that
# record handoffs and by the verifier that pins each kind to its role-specific location.
HANDOFF_KINDS = {
    "draft": "spec-draft",
    "candidate": "reviewed-candidate",
    "proposal": "tickets-proposal",
    "summary": "tickets-summary",
    "report": "worker-report",
}
ROLE_KEYS = {kind: role for role, kind in HANDOFF_KINDS.items()}


class ArtifactIntegrityError(ValueError):
    """A run artifact no longer has the identity or location the state trusts."""


def attempt_id(stage: str, pass_num: int, attempt: int) -> str:
    if pass_num < 1 or attempt < 1:
        raise ArtifactIntegrityError("artifact pass and attempt must be positive integers")
    return f"{stage}-{pass_num}-attempt-{attempt}"


def attempt_suffix(attempt: int) -> str:
    # Preserve the first-release paths for attempt one. The manifest is the unambiguous binding;
    # every later emission gets a suffix and can never reuse the first attempt's writable files.
    return "" if attempt == 1 else f"-attempt-{attempt}"


def tree_snapshot_path(run_dir: Path, stage: str, pass_num: int, attempt: int, tail: str) -> Path:
    """The one tree-snapshot location shared by its writers, its readers, and the verifier."""
    suffix = attempt_suffix(attempt)
    return run_dir / "tree-snapshots" / f"{stage}-{pass_num}{suffix}-{tail}.json"


def stage_snapshot_prefix(stage: str, pass_num: int, attempt: int) -> str:
    return f"stage-snapshots/{stage}-{pass_num}{attempt_suffix(attempt)}-"


def next_attempt(state: dict[str, Any], stage: str, pass_num: int) -> int:
    """The next unused attempt number for one stage pass; counters are never reused."""
    counters = state.setdefault("artifact_attempt_counters", {})
    return counters.get(f"{stage}-{pass_num}", 0) + 1


def reviewed_candidate_kind(reviewed: dict[str, Any], author_kind: str) -> str:
    """A `pass` verdict leaves the author artifact itself as the reviewed candidate."""
    return author_kind if reviewed.get("verdict") == "pass" else "reviewed-candidate"


def find_attempt_entry(
    state: dict[str, Any], kind: str, identity: str
) -> dict[str, Any] | None:
    """The finalized entry of one kind already recorded for an armed attempt, if any."""
    return next(
        (
            entry
            for entry in state.get("artifact_manifest", {}).values()
            if isinstance(entry, dict)
            and entry.get("kind") == kind
            and entry.get("attempt_id") == identity
        ),
        None,
    )


def stage_paths(run_dir: Path, stage: str, pass_num: int, attempt: int) -> dict[str, str]:
    suffix = attempt_suffix(attempt)
    if stage == "spec":
        relative = {
            "draft": f"artifacts/spec-{pass_num}{suffix}.md",
            "report": f"reports/spec-{pass_num}{suffix}.md",
        }
    elif stage == "spec-review":
        relative = {
            "candidate": f"artifacts/spec-reviewed-{pass_num}{suffix}.md",
            "report": f"reports/spec-review-{pass_num}{suffix}.md",
        }
    elif stage == "tickets":
        relative = {
            "proposal": f"artifacts/tickets-{pass_num}{suffix}.json",
            "summary": f"artifacts/tickets-{pass_num}{suffix}.md",
            "report": f"reports/tickets-{pass_num}{suffix}.md",
        }
    elif stage == "tickets-review":
        relative = {
            "candidate": f"artifacts/tickets-reviewed-{pass_num}{suffix}.json",
            "report": f"reports/tickets-review-{pass_num}{suffix}.md",
        }
    else:
        raise ArtifactIntegrityError(f"unknown planning stage: {stage}")
    relative["started"] = f"artifacts/{stage}-{pass_num}{suffix}/started"
    relative["prompt"] = f"prompts/{stage}-{pass_num}{suffix}.md"
    return {key: str((run_dir / value).resolve()) for key, value in relative.items()}


def _lexical_parts(root: Path, candidate: Path) -> tuple[str, ...]:
    """The unresolved components under the run root, so a symlink component is still visible."""
    try:
        return Path(os.path.normpath(candidate)).relative_to(root).parts
    except ValueError:
        return ()


def _relative_path(run_dir: Path, path: Path | str) -> tuple[Path, str]:
    """Accept a run-relative pointer or an absolute handoff, never a cwd-relative full path."""
    root = run_dir.resolve()
    raw = Path(path)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ArtifactIntegrityError(
            f"artifact path escapes the pinned planning run: {path}"
        ) from error
    if ".." in raw.parts:
        raise ArtifactIntegrityError(f"artifact path contains traversal: {path}")
    # Reject a symlink at any existing component of the path as given. Checking the resolved path
    # would never see one, and a symlink that currently resolves inside the run can later be
    # retargeted, which would make the canonical location mutable.
    for parts in {_lexical_parts(root, candidate), relative.parts}:
        current = root
        for part in parts:
            current = current / part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                break
            if stat.S_ISLNK(mode):
                raise ArtifactIntegrityError(f"artifact path uses a symlink: {current}")
    if not relative.parts:
        raise ArtifactIntegrityError("artifact path cannot be the planning run directory")
    return resolved, relative.as_posix()


def stable_nonempty_bytes(run_dir: Path, path: Path | str) -> tuple[Path, str, bytes]:
    """Read one handoff through two identical observations before trusting its bytes."""
    resolved, relative = _relative_path(run_dir, path)

    def observe() -> tuple[int, int, int, int]:
        """One identity, refused unless the path is still the same regular file."""
        value = resolved.stat()
        if not stat.S_ISREG(value.st_mode):
            raise ArtifactIntegrityError(f"artifact is not a regular file: {relative}")
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)

    try:
        observations = {observe()}
        first = resolved.read_bytes()
        observations.add(observe())
        second = resolved.read_bytes()
        observations.add(observe())
    except FileNotFoundError as error:
        raise ArtifactIntegrityError(f"artifact is missing: {relative}") from error
    except OSError as error:
        raise ArtifactIntegrityError(
            f"artifact could not be read as a regular file: {relative}"
        ) from error
    if not first:
        raise ArtifactIntegrityError(f"artifact is empty: {relative}")
    if len(observations) != 1 or first != second:
        raise ArtifactIntegrityError(f"artifact bytes were not stable while captured: {relative}")
    return resolved, relative, first


def _entry_id(kind: str, stage: str, pass_num: int, attempt: int, relative: str) -> str:
    return f"{kind}:{stage}:{pass_num}:{attempt}:{relative}"


def record_artifact(
    state: dict[str, Any],
    run_dir: Path,
    path: Path | str,
    *,
    kind: str,
    stage: str,
    pass_num: int,
    attempt: int,
    producer: str,
    expected_path: Path | str | None = None,
    source_manifest_id: str | None = None,
) -> dict[str, Any]:
    """Finalize one stable identity without ever re-baselining changed bytes."""
    resolved, relative, payload = stable_nonempty_bytes(run_dir, path)
    expected_resolved, expected_relative = _relative_path(
        run_dir, path if expected_path is None else expected_path
    )
    if resolved != expected_resolved or relative != expected_relative:
        raise ArtifactIntegrityError(
            f"{kind} path substitution: expected {expected_relative}, got {relative}"
        )
    identity = attempt_id(stage, pass_num, attempt)
    entry_id = _entry_id(kind, stage, pass_num, attempt, relative)
    entry = {
        "id": entry_id,
        "path": relative,
        "kind": kind,
        "stage": stage,
        "pass": pass_num,
        "attempt": attempt,
        "attempt_id": identity,
        "byte_size": len(payload),
        "sha256": sha256_bytes(payload),
        "producer": producer,
        "finalized": True,
        "finalized_at": utc_now(),
    }
    if source_manifest_id is not None:
        source = state.get("artifact_manifest", {}).get(source_manifest_id)
        if not isinstance(source, dict):
            raise ArtifactIntegrityError(
                f"approved artifact source is not in the manifest: {source_manifest_id}"
            )
        for field in ("path", "byte_size", "sha256"):
            if entry[field] != source.get(field):
                raise ArtifactIntegrityError(
                    "approved artifact does not match its reviewed manifest identity"
                )
        entry["source_manifest_id"] = source_manifest_id
    manifest = state.setdefault("artifact_manifest", {})
    existing = manifest.get(entry_id)
    if existing is not None:
        comparable = {key: value for key, value in entry.items() if key != "finalized_at"}
        old_comparable = {key: value for key, value in existing.items() if key != "finalized_at"}
        if old_comparable != comparable:
            raise ArtifactIntegrityError(
                f"finalized artifact cannot be rearmed with new bytes or metadata: {relative}"
            )
        return existing
    manifest[entry_id] = entry
    return entry


def verify_entry(
    state: dict[str, Any],
    run_dir: Path,
    manifest_id: str,
    *,
    expected_kind: str | None = None,
    expected_path: Path | str | None = None,
) -> dict[str, Any]:
    entry = state.get("artifact_manifest", {}).get(manifest_id)
    if not isinstance(entry, dict) or not entry.get("finalized"):
        raise ArtifactIntegrityError(
            f"artifact manifest entry is missing or not finalized: {manifest_id}"
        )
    for field in (
        "path",
        "kind",
        "stage",
        "pass",
        "attempt",
        "attempt_id",
        "byte_size",
        "sha256",
        "producer",
    ):
        if field not in entry:
            raise ArtifactIntegrityError(f"artifact manifest entry lacks {field}: {manifest_id}")
    if entry["id"] != _entry_id(
        entry["kind"], entry["stage"], entry["pass"], entry["attempt"], entry["path"]
    ):
        raise ArtifactIntegrityError(f"artifact manifest identity was substituted: {manifest_id}")
    if entry["attempt_id"] != attempt_id(entry["stage"], entry["pass"], entry["attempt"]):
        raise ArtifactIntegrityError(f"artifact attempt identity was substituted: {manifest_id}")
    if not isinstance(entry["producer"], str) or not entry["producer"]:
        raise ArtifactIntegrityError(f"artifact producer is missing: {manifest_id}")
    _verify_role_location(state, run_dir, entry)
    if expected_kind is not None and entry.get("kind") != expected_kind:
        raise ArtifactIntegrityError(
            f"artifact-kind substitution: expected {expected_kind}, got {entry.get('kind')!r}"
        )
    resolved, relative, payload = stable_nonempty_bytes(run_dir, entry.get("path", ""))
    if expected_path is not None:
        expected_resolved, expected_relative = _relative_path(run_dir, expected_path)
        if resolved != expected_resolved or relative != expected_relative:
            raise ArtifactIntegrityError(
                f"artifact path substitution: expected {expected_relative}, got {relative}"
            )
    if relative != entry.get("path"):
        raise ArtifactIntegrityError(f"artifact path is not canonical: {entry.get('path')!r}")
    if len(payload) != entry.get("byte_size"):
        raise ArtifactIntegrityError(f"artifact byte size changed: {relative}")
    if sha256_bytes(payload) != entry.get("sha256"):
        raise ArtifactIntegrityError(f"artifact digest changed: {relative}")
    return entry


def _verify_role_location(state: dict[str, Any], run_dir: Path, entry: dict[str, Any]) -> None:
    kind = entry["kind"]
    stage = entry["stage"]
    pass_num = entry["pass"]
    attempt = entry["attempt"]
    path = entry["path"]
    fixed = {
        "task": "task.md",
        "grilling-source-json": "inputs/grilling-source.json",
        "grilling-source-markdown": "inputs/grilling-source.md",
    }
    expected: str | None = fixed.get(kind)
    if kind == "grilling-revalidation-progress":
        if not path.startswith("inputs/grilling-revalidation-progress") or not path.endswith(
            ".json"
        ):
            raise ArtifactIntegrityError(
                "grilling revalidation artifact has a substituted location"
            )
        return
    if kind == "normalized-grilling-input":
        if not path.startswith("grilling-input") or not path.endswith(".json"):
            raise ArtifactIntegrityError("normalized grilling input has a substituted location")
        return
    if stage in {"spec", "spec-review", "tickets", "tickets-review"}:
        paths = stage_paths(run_dir, stage, pass_num, attempt)
        role_key = "prompt" if kind == "prompt" else ROLE_KEYS.get(kind)
        if role_key is not None:
            if role_key not in paths:
                raise ArtifactIntegrityError(f"{kind} has no role location in stage {stage}")
            _, expected = _relative_path(run_dir, paths[role_key])
        elif kind in {"tree-baseline", "tree-verification"}:
            tail = "before" if kind == "tree-baseline" else "after"
            _, expected = _relative_path(
                run_dir,
                tree_snapshot_path(run_dir, stage, pass_num, attempt, tail).relative_to(run_dir),
            )
        elif kind == "stage-snapshot":
            prefix = stage_snapshot_prefix(stage, pass_num, attempt)
            if not path.startswith(prefix) or not path.endswith(".json"):
                raise ArtifactIntegrityError(
                    "stage snapshot has a substituted role-specific location"
                )
            return
    if kind in {"approved-spec", "approved-tickets"}:
        source_id = entry.get("source_manifest_id")
        source = state.get("artifact_manifest", {}).get(source_id)
        if not isinstance(source, dict) or source.get("path") != path:
            raise ArtifactIntegrityError(f"{kind} is not bound to its reviewed source artifact")
        return
    if expected is None:
        raise ArtifactIntegrityError(f"unknown or substituted artifact kind: {kind!r}")
    if path != expected:
        raise ArtifactIntegrityError(
            f"{kind} path substitution: expected {expected}, got {path}"
        )


def require_current_format(state: dict[str, Any], *, source: Path) -> None:
    if (
        state.get("workflow") != "planning"
        or state.get("layout_version") != 1
        or any(path.parts[-3:] == (".scratch", "orchestrator", "planning-runs")
               for path in source.resolve().parents)
        or state.get("schema_version") != RUN_STATE_SCHEMA_VERSION
        or state.get("artifact_manifest_version") != MANIFEST_VERSION
        or not isinstance(state.get("artifact_manifest"), dict)
        or not isinstance(state.get("artifact_attempt_counters"), dict)
    ):
        raise ArtifactIntegrityError(
            f"planning run {source.parent} uses an unsupported legacy layout or predates artifact-manifest format {MANIFEST_VERSION}; "
            "do not trust or resume it silently. Inspect it read-only, then obtain a human decision "
            "to restart the run or use a separately reviewed migration procedure. "
            "The legacy root .scratch/orchestrator/planning-runs/ cannot be continued; "
            "new runs belong under .scratch/orchestrator/runs/"
        )


def verify_manifest(state: dict[str, Any], run_dir: Path) -> dict[str, list[str]]:
    require_current_format(state, source=run_dir / "state.json")
    for manifest_id in sorted(state["artifact_manifest"]):
        verify_entry(state, run_dir, manifest_id)
    return audit_artifacts(state, run_dir)


def audit_artifacts(state: dict[str, Any], run_dir: Path) -> dict[str, list[str]]:
    known = {
        entry["path"]
        for entry in state.get("artifact_manifest", {}).values()
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    current = state.get("current_attempt")
    declared = set()
    if isinstance(current, dict):
        for value in current.get("paths", {}).values():
            if isinstance(value, str):
                _, relative = _relative_path(run_dir, value)
                declared.add(relative)
    for previous in state.get("attempt_history", []):
        marker = previous.get("paths", {}).get("started")
        if isinstance(marker, str):
            _, relative = _relative_path(run_dir, marker)
            declared.add(relative)
    seen: set[str] = set()
    for path in run_dir.rglob("*"):
        if not (path.is_file() or path.is_symlink()):
            continue
        try:
            _, relative = _relative_path(run_dir, path.relative_to(run_dir))
        except ArtifactIntegrityError:
            relative = str(path.absolute())
        # briefing.md and recap.md are the orchestrator's own human-facing text, never worker handoffs.
        if relative in {"state.json", "events.jsonl", "briefing.md", "recap.md"} or relative.startswith("publication-stage/"):
            continue
        seen.add(relative)
    counters = state.get("artifact_attempt_counters", {})
    attempt_kinds = {
        "stage-snapshot",
        "prompt",
        "tree-baseline",
        "tree-verification",
        "worker-report",
        "spec-draft",
        "reviewed-candidate",
        "tickets-proposal",
        "tickets-summary",
    }
    # Stale means superseded: a later attempt of the same stage pass exists. Comparing against the
    # armed attempt instead would relabel every earlier stage, and the pending approval candidate
    # itself, as stale whenever no attempt is armed.
    stale = sorted(
        entry["path"]
        for entry in state.get("artifact_manifest", {}).values()
        if isinstance(entry, dict)
        and entry.get("kind") in attempt_kinds
        and entry.get("attempt", 0)
        < counters.get(f"{entry.get('stage')}-{entry.get('pass')}", entry.get("attempt", 0))
    )
    return {
        "unexpected": sorted(seen - known - declared),
        "stale": stale,
    }


def gate_violation(
    run_dir: Path, error: ArtifactIntegrityError, *, stage: str | None = None
) -> None:
    """Persist one artifact-integrity HITL decision without adopting changed bytes."""
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    now = utc_now()
    supplied_stage = (
        stage if stage in {"spec", "spec-review", "tickets", "tickets-review"} else None
    )
    current_stage_value = state.get("current_stage")
    current_stage = (
        current_stage_value
        if current_stage_value in {"spec", "spec-review", "tickets", "tickets-review"}
        else None
    )
    gates = state.get("gate_decisions", [])
    last_gate = (
        gates[-1] if isinstance(gates, list) and gates and isinstance(gates[-1], dict) else {}
    )
    source_stage = supplied_stage or current_stage or last_gate.get("stage") or "run"
    gate = {
        "time": now,
        "stage": source_stage,
        "decision": "hitl",
        "reason": "run artifact integrity violation",
        "error": str(error),
    }
    active_attempt = state.get("current_attempt")
    if isinstance(active_attempt, dict) and isinstance(active_attempt.get("attempt"), int):
        gate["attempt"] = active_attempt["attempt"]
        gate["attempt_id"] = active_attempt.get("attempt_id")
    elif isinstance(last_gate.get("attempt"), int):
        gate["attempt"] = last_gate["attempt"]
        gate["attempt_id"] = last_gate.get("attempt_id")
    state.setdefault("gate_decisions", []).append(gate)
    state["artifact_integrity_violation"] = gate
    close_attempt(state, "integrity-violation", "run artifact identity changed")
    state["current_stage"] = "integrity-violation"
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    state["updated_at"] = now
    write_json(state_path, state)
    append_event(
        run_dir,
        "artifact.integrity_violation",
        "run artifact identity violation requires human resolution",
        gate,
        time=now,
    )


def verify_or_gate(run_dir: Path, *, stage: str | None = None) -> dict[str, Any]:
    """Verify all finalized artifacts and persist a HITL gate on the first violation."""
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    # Refuse a pre-manifest run without rewriting it, so the stage, prepared snapshot, and baseline
    # a reviewed migration needs survive the refusal instead of being replaced by a HITL gate.
    require_current_format(state, source=state_path)
    try:
        audit = verify_manifest(state, run_dir)
    except ArtifactIntegrityError as error:
        gate_violation(run_dir, error, stage=stage)
        raise
    state["artifact_audit"] = {**audit, "checked_at": utc_now()}
    write_json(state_path, state)
    return state


def arm_attempt(
    state: dict[str, Any], run_dir: Path, stage: str, pass_num: int, attempt: int
) -> dict[str, Any]:
    identity = attempt_id(stage, pass_num, attempt)
    current = state.get("current_attempt")
    if isinstance(current, dict) and current.get("status") == "armed":
        current["status"] = "closed"
        current["closed_at"] = utc_now()
        current["close_reason"] = "superseded-by-fresh-attempt"
        state.setdefault("attempt_history", []).append(current)
    paths = stage_paths(run_dir, stage, pass_num, attempt)
    record = {
        "stage": stage,
        "pass": pass_num,
        "attempt": attempt,
        "attempt_id": identity,
        "status": "armed",
        "armed_at": utc_now(),
        "paths": paths,
    }
    state["current_attempt"] = record
    return record


def close_attempt(state: dict[str, Any], status: str, reason: str) -> dict[str, Any] | None:
    current = state.get("current_attempt")
    if not isinstance(current, dict):
        return None
    closed = dict(current)
    closed["status"] = status
    closed["closed_at"] = utc_now()
    closed["close_reason"] = reason
    state.setdefault("attempt_history", []).append(closed)
    state["current_attempt"] = None
    return closed


def current_attempt(state: dict[str, Any], stage: str, pass_num: int) -> dict[str, Any]:
    current = state.get("current_attempt")
    if (
        not isinstance(current, dict)
        or current.get("status") != "armed"
        or current.get("stage") != stage
        or current.get("pass") != pass_num
    ):
        raise ArtifactIntegrityError(
            f"no matching prepared stage snapshot is active; no armed artifact attempt for "
            f"{stage} pass {pass_num}"
        )
    return current
