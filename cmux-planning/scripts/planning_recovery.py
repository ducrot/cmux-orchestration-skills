#!/usr/bin/env python3
"""Read-only status, discovery, and recovery helpers for cmux-planning."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from worker_readiness import readiness_status

from artifact_manifest import (
    ArtifactIntegrityError,
    current_attempt,
    require_current_format,
    stage_paths,
    tree_snapshot_path,
)
from orchestrator_lib import (
    STAGES,
    PlanningStateCompatibilityError,
    matching_event,
    matching_stage_pass_event,
    read_event_stream,
    read_json,
    read_planning_state,
    sha256_file,
    surface_event_recorded,
)
from planning_diversity import DECISION_STATUSES, pending_confirmation, public_warning
from stage_snapshot import SnapshotError, load_prepared_snapshot
from tracker_contract import ContractError, validate_native_tracker, validate_proposal
from tree_integrity import snapshot_digest


PASS_KEYS = {
    "spec": "spec_pass",
    "spec-review": "spec_review_pass",
    "tickets": "tickets_pass",
    "tickets-review": "tickets_review_pass",
}
MODES = {
    "spec": "author",
    "spec-review": "reviewer",
    "tickets": "author",
    "tickets-review": "reviewer",
}
CLASSIFICATIONS = {
    "input": "input-validation",
    "spec": "spec-authoring",
    "spec-review": "spec-review",
    "tickets": "ticket-authoring",
    "tickets-review": "ticket-review",
    "awaiting-spec-approval": "awaiting-spec-approval",
    "awaiting-ticket-approval": "awaiting-ticket-approval",
    "ready-to-publish": "ready-to-publish",
    "complete": "completed",
}
BLOCKED_STAGES = {
    "spec-blocked",
    "spec-review-blocked",
    "tickets-blocked",
    "tickets-review-blocked",
}
HITL_STAGES = {"integrity-violation"}


def shell_join(argv: list[str | Path]) -> str:
    return shlex.join([str(value) for value in argv])


def script(name: str) -> Path:
    return Path(__file__).resolve().parent / name


def stage_pass(state: dict[str, Any], stage: str) -> int:
    key = PASS_KEYS[stage]
    fallback = "tickets_pass" if stage.startswith("tickets") else "spec_pass"
    value = state.get(key, state.get(fallback))
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"state has no valid pass for {stage}")
    return value


def report_for(state: dict[str, Any], stage: str, pass_num: int) -> Path | None:
    try:
        return Path(current_attempt(state, stage, pass_num)["paths"]["report"])
    except ArtifactIntegrityError:
        # No armed attempt: the pass has no report to gate. Falling back to the first attempt's
        # location would report a closed attempt's preserved file as the ready current handoff.
        return None


def surface_health(cmux_cmd: str, workspace: str | None, surface: str) -> str:
    if not isinstance(workspace, str) or not workspace:
        return "last-known"
    command = shlex.split(cmux_cmd) + [
        "--json",
        "--id-format",
        "both",
        "surface-health",
        "--workspace",
        workspace,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "last-known"
    if result.returncode != 0:
        return "last-known"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "last-known"
    surfaces = payload.get("surfaces") if isinstance(payload, dict) else None
    if not isinstance(surfaces, list) or not all(isinstance(item, dict) for item in surfaces):
        return "last-known"
    return (
        "live"
        if any(surface in (item.get("id"), item.get("ref")) for item in surfaces)
        else "dead"
    )


def pane_status(
    state: dict[str, Any], events: list[dict[str, Any]], stage: str, pass_num: int, cmux_cmd: str
) -> dict[str, Any]:
    pointer = state.get("prepared_stage")
    snapshot_id = pointer.get("snapshot_id") if isinstance(pointer, dict) else None
    launches = [
        event
        for event in events
        if matching_stage_pass_event(event, "pane.launched", stage, pass_num)
    ]
    current = [
        event
        for event in launches
        if isinstance(event.get("data"), dict)
        and event["data"].get("stage_snapshot_id") == snapshot_id
    ]
    launch = current[-1] if current else None
    last_known = launches[-1] if launches else None
    if launch is None:
        payload: dict[str, Any] = {
            "status": "not-launched",
            "surface_id": None,
            "surface_ref": None,
            "pane_id": None,
            "agent_launch_sent": False,
            "assignment_start_confirmed": False,
            "prompt_sent": False,
            "last_event": last_known,
        }
        if last_known is not None:
            payload["previous_attempt"] = last_known.get("data")
        return payload

    data = launch["data"]
    # Only the stable UUID; every pane command rejects a positional ref, so recommending one
    # would hand the operator a command that cannot run.
    surface = data.get("surface_id")
    later = events[events.index(launch) + 1 :]
    relevant = [event for event in later if matching_event(event, stage, pass_num)]
    launches_sent = [e for e in relevant if e.get("type") == "worker.launch_sent"
                     and e.get("data", {}).get("surface_id") == surface]
    agent_launch_sent = bool(launches_sent)
    worker_launch = launches_sent[-1] if launches_sent else None
    launch_data = worker_launch["data"] if worker_launch else {}
    launch_id = launch_data.get("launch_id")
    launch_events = relevant[relevant.index(worker_launch) + 1:] if worker_launch else relevant
    delivery_sent = surface_event_recorded(launch_events, "worker.prompt_sent", stage, pass_num, surface)
    start_prompt = bool(launch_data.get("prompt_path"))
    prompt_sent = delivery_sent or start_prompt
    assignment_start_confirmed = any(
        e.get("type") == "worker.started" and e.get("data", {}).get("surface_id") == surface
        and e["data"].get("launch_id") == launch_id
        and e["data"].get("attempt_id") == data.get("attempt_id") for e in launch_events)
    waits = [e for e in launch_events if e.get("type") == "worker.waiting"
             and e.get("data", {}).get("surface_id") == surface]
    # A timeout or unresolved assessed dialog needs inspection until a response, delivery,
    # or positive start evidence resolves it. Observing/assessing alone does not clear it.
    needs_inspection = False
    for e in launch_events:
        payload = e.get("data", {})
        if payload.get("surface_id") != surface:
            continue
        if ((e.get("type") == "worker.waiting" and payload.get("outcome") == "not_started"
             and payload.get("launch_id") == launch_id)
                or (e.get("type") == "worker.startup_status" and payload.get("state") == "prompt"
                    and payload.get("launch_id") == launch_id)):
            needs_inspection = True
        elif (e.get("type") in {"worker.dialog_response", "worker.started"}
              and payload.get("launch_id") == launch_id) or e.get("type") == "worker.prompt_sent":
            needs_inspection = False
    input_boundaries = [e["type"] for e in relevant
                        if e.get("data", {}).get("surface_id") == surface
                        and e.get("type") in {"worker.starting", "worker.launch_sent",
                                              "worker.delivery_attempted", "worker.prompt_sent"}]
    input_interrupted = bool(input_boundaries) and input_boundaries[-1] in {
        "worker.starting", "worker.delivery_attempted"}
    wait_outcome = waits[-1].get("data", {}).get("outcome") if waits else None
    extension = waits[-1].get("data", {}).get("extension", 0) if waits else 0
    if wait_outcome == "pane_dead":
        health = "dead"
    elif wait_outcome == "deadline":
        health = "watcher-expired" if extension else "deadline"
    else:
        # An event stream without the stable UUID cannot be health-checked; "None" would be
        # probed as a surface name and always come back dead.
        health = (
            surface_health(cmux_cmd, state.get("workspace_id"), surface)
            if isinstance(surface, str) and surface
            else "last-known"
        )
    return {
        "status": health,
        "surface_id": surface,
        "surface_ref": data.get("surface_ref"),
        "pane_id": data.get("pane_id"),
        "startup_state": readiness_status(events, {"stage": stage, "pass": pass_num}, surface),
        "launch_attempted": surface_event_recorded(relevant, "worker.starting", stage, pass_num, surface),
        "delivery_attempted": surface_event_recorded(launch_events, "worker.delivery_attempted", stage, pass_num, surface),
        "agent_launch_sent": agent_launch_sent,
        "start_prompt": start_prompt,
        "needs_start_inspection": needs_inspection,
        "delivery_sent": delivery_sent,
        "input_interrupted": input_interrupted,
        "assignment_start_confirmed": assignment_start_confirmed,
        "prompt_sent": prompt_sent,
        "last_wait_outcome": wait_outcome,
        "extension": extension,
        "last_event": relevant[-1] if relevant else launch,
    }


def pointer_identity(
    run_dir: Path, pointer: Any, label: str, errors: list[str]
) -> dict[str, Any] | None:
    if pointer is None:
        return None
    if not isinstance(pointer, dict):
        errors.append(f"{label} pointer is malformed")
        return {"valid": False}
    result = dict(pointer)
    path_value = pointer.get("path")
    digest = pointer.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str):
        result["valid"] = False
        errors.append(f"{label} identity is incomplete")
        return result
    path = Path(path_value)
    if not path.is_absolute():
        path = run_dir / path
    path = path.resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError:
        result["path"] = str(path)
        result["valid"] = False
        errors.append(f"{label} path escapes the planning run")
        return result
    valid = path.is_file() and sha256_file(path) == digest
    result["path"] = str(path)
    result["valid"] = valid
    if not valid:
        errors.append(f"{label} is missing or changed")
    return result


def approval_status(run_dir: Path, state: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    spec = pointer_identity(run_dir, state.get("approved_spec"), "approved specification", errors)
    tickets = pointer_identity(run_dir, state.get("approved_tickets"), "approved ticket proposal", errors)
    return {
        "spec": {
            "recorded": spec is not None,
            "valid": bool(spec and spec.get("valid")),
            "identity": spec,
        },
        "tickets": {
            "recorded": tickets is not None,
            "valid": bool(tickets and tickets.get("valid")),
            "identity": tickets,
        },
    }


def grilling_import_status(
    run_dir: Path, imported: Any, errors: list[str]
) -> dict[str, Any] | None:
    if imported is None:
        return None
    if not isinstance(imported, dict):
        errors.append("grilling import state is malformed")
        return {"valid": False}
    result = dict(imported)
    valid = True
    for path_key, digest_key, label in (
        ("copied_json", "source_json_sha256", "copied grilling JSON"),
        ("copied_markdown", "source_markdown_sha256", "copied grilling Markdown"),
    ):
        relative = imported.get(path_key)
        digest = imported.get(digest_key)
        if not isinstance(relative, str) or not isinstance(digest, str):
            errors.append(f"{label} identity is incomplete")
            valid = False
            continue
        path = (run_dir / relative).resolve()
        try:
            path.relative_to(run_dir)
        except ValueError:
            errors.append(f"{label} path escapes the planning run")
            valid = False
            continue
        item_valid = path.is_file() and sha256_file(path) == digest
        result[f"{path_key}_valid"] = item_valid
        valid = valid and item_valid
        if not item_valid:
            errors.append(f"{label} is missing or changed")
    result["valid"] = valid
    return result


def publication_proposal(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    approved_spec = state.get("approved_spec")
    if not isinstance(approved_spec, dict):
        raise ContractError("publication has no approved specification identity")
    source = state.get("approved_tickets")
    path_key = "path"
    digest_key = "sha256"
    if not isinstance(source, dict):
        source = state.get("reviewed_tickets")
        path_key = "candidate"
        digest_key = "candidate_sha256"
    if not isinstance(source, dict):
        raise ContractError("publication has no reviewed ticket proposal identity")
    path = Path(source.get(path_key, ""))
    digest = source.get(digest_key)
    if not path.is_file() or not isinstance(digest, str):
        raise ContractError("publication ticket proposal identity is incomplete")
    proposal = validate_proposal(
        path,
        expected_spec=Path(approved_spec["path"]),
        expected_spec_sha256=approved_spec["sha256"],
    )
    if proposal["sha256"] != digest:
        raise ContractError("publication ticket proposal changed after review or approval")
    return approved_spec, proposal


def validate_publication_tracker(
    path: Path,
    state: dict[str, Any],
    *,
    expected_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    approved_spec, proposal = publication_proposal(state)
    validated = validate_native_tracker(
        path,
        expected_spec_sha256=approved_spec["sha256"],
        expected_ticket_ids=proposal["ticket_ids"],
    )
    if expected_artifacts is not None and validated["artifacts"] != expected_artifacts:
        raise ContractError("publication artifact identities changed")
    return validated


def publication_status(run_dir: Path, state: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    staged = state.get("staged_tracker")
    approved = state.get("approved_tickets")
    published = state.get("published_tracker")
    target_value = approved.get("target") if isinstance(approved, dict) else None
    staged_value = staged.get("path") if isinstance(staged, dict) else None
    target = Path(target_value) if isinstance(target_value, str) else None
    canonical_staging = run_dir.resolve() / "publication-stage"
    staged_path = Path(staged_value).resolve() if isinstance(staged_value, str) else canonical_staging
    if isinstance(staged, dict) and staged_path != canonical_staging:
        errors.append("recorded staged tracker path is outside the canonical planning staging directory")
    if (
        not isinstance(staged, dict)
        and canonical_staging.exists()
        and canonical_staging.resolve() != canonical_staging
    ):
        errors.append("unrecorded staging resolves outside the canonical planning staging directory")
    target_exists = bool(target and target.exists())
    staged_exists = staged_path.exists()
    phase = "not-started"
    if published is not None or state.get("current_stage") == "complete":
        phase = "completed"
        if not isinstance(published, dict) or not isinstance(published.get("path"), str):
            phase = "inconsistent"
            errors.append("completed run has no published tracker identity")
        else:
            published_path = Path(published["path"])
            try:
                if target is not None and published_path.resolve() != target.resolve():
                    raise ContractError("published tracker path differs from the approved target")
                validate_publication_tracker(
                    published_path,
                    state,
                    expected_artifacts=published.get("artifacts"),
                )
            except (ContractError, OSError, TypeError, ValueError, KeyError) as error:
                phase = "inconsistent"
                errors.append(f"published tracker is missing or changed: {error}")
    elif target_exists and not staged_exists:
        try:
            validate_publication_tracker(
                target,
                state,
                expected_artifacts=(staged.get("artifacts") if isinstance(staged, dict) else None),
            )
            phase = "published"
        except (ContractError, OSError, TypeError, ValueError, KeyError) as error:
            phase = "inconsistent"
            errors.append(f"moved publication target is missing or changed: {error}")
    elif target_exists and staged_exists:
        phase = "inconsistent"
        errors.append("both staged and target tracker directories exist")
    elif staged_exists:
        try:
            validate_publication_tracker(
                staged_path,
                state,
                expected_artifacts=(staged.get("artifacts") if isinstance(staged, dict) else None),
            )
            if isinstance(staged, dict):
                phase = "validated"
            else:
                phase = "fully-staged"
        except (ContractError, OSError, TypeError, ValueError, KeyError) as error:
            phase = "inconsistent"
            errors.append(f"staged tracker is incomplete or changed: {error}")
    elif staged is not None:
        phase = "staging-missing"
        errors.append("recorded staged tracker is missing")
    return {
        "phase": phase,
        "staged": staged,
        "staged_exists": staged_exists,
        "target": str(target) if target else None,
        "target_exists": target_exists,
        "published": published,
    }


def recovery_context(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    task_pointer = state.get("task")
    task_relative = task_pointer.get("path", "task.md") if isinstance(task_pointer, dict) else "task.md"
    paths = {
        "task": str(run_dir / task_relative),
        "state": str(run_dir / "state.json"),
        "events": str(run_dir / "events.jsonl"),
        "copied_grilling_json": None,
        "copied_grilling_markdown": None,
        "normalized_grilling_input": None,
        "approved_spec": state.get("approved_spec", {}).get("path")
        if isinstance(state.get("approved_spec"), dict)
        else None,
        "latest_spec": state.get("author_spec", {}).get("draft")
        if isinstance(state.get("author_spec"), dict)
        else None,
        "latest_spec_review": state.get("reviewed_spec", {}).get("candidate")
        if isinstance(state.get("reviewed_spec"), dict)
        else None,
        "latest_ticket_proposal": state.get("author_tickets", {}).get("proposal")
        if isinstance(state.get("author_tickets"), dict)
        else None,
        "latest_ticket_review": state.get("reviewed_tickets", {}).get("candidate")
        if isinstance(state.get("reviewed_tickets"), dict)
        else None,
        "stage_snapshots": str(run_dir / "stage-snapshots"),
        "tree_snapshots": str(run_dir / "tree-snapshots"),
        "reports": str(run_dir / "reports"),
        "artifacts": str(run_dir / "artifacts"),
        "spec_approval_diff_command": shell_join(
            ["python3", script("planning_state.py"), "approval-view", "--run-dir", run_dir]
        ),
        "ticket_approval_diff_command": shell_join(
            ["python3", script("planning_state.py"), "ticket-approval-view", "--run-dir", run_dir]
        ),
    }
    imported = state.get("grilling_import")
    if (
        isinstance(imported, dict)
        and isinstance(imported.get("copied_json"), str)
        and isinstance(imported.get("copied_markdown"), str)
    ):
        paths["copied_grilling_json"] = str(run_dir / imported["copied_json"])
        paths["copied_grilling_markdown"] = str(run_dir / imported["copied_markdown"])
    normalized = state.get("normalized_grilling_input")
    if isinstance(normalized, dict) and isinstance(normalized.get("path"), str):
        paths["normalized_grilling_input"] = str(run_dir / normalized["path"])
    files: list[dict[str, Any]] = []
    for directory in ("artifacts", "reports", "stage-snapshots", "tree-snapshots"):
        root = run_dir / directory
        if root.is_dir():
            files.extend(
                {"path": str(path), "sha256": sha256_file(path)}
                for path in sorted(root.iterdir())
                if path.is_file()
            )
    return {
        "commit_mode": state.get("commit_mode", "propose"),
        "paths": paths,
        "history": files,
        "resume_context": state.get("resume_context"),
        "artifact_manifest": state.get("artifact_manifest"),
        "artifact_audit": state.get("artifact_audit"),
        "attempt_history": state.get("attempt_history"),
    }


def recommended_next(
    run_dir: Path,
    state: dict[str, Any],
    classification: str,
    pane: dict[str, Any],
    report: dict[str, Any],
    errors: list[str],
    cmux_cmd: str,
) -> dict[str, str | None]:
    base = ["python3", script("planning_state.py")]
    pane_base = ["python3", script("pane_ctl.py"), "--cmux-cmd", cmux_cmd]
    if errors or classification == "inconsistent" or state.get("current_stage") in HITL_STAGES:
        return {
            "action": "stop for human inspection",
            "command": shell_join(base + ["context", "--run-dir", run_dir]),
        }
    stage = state.get("current_stage")
    if stage == "input":
        return {
            "action": "finish the interrupted validated-input checkpoint",
            "command": shell_join(
                base + ["resume", "--run-dir", run_dir, "--decision", "rejoin"]
            ),
        }
    if stage == "awaiting-grilling-revalidation":
        return {
            "action": "resume the same human revalidation walkthrough",
            "command": shell_join(base + ["show-revalidation", "--run-dir", run_dir]),
        }
    if stage in STAGES:
        pass_num = stage_pass(state, stage)
        pointer = state.get("prepared_stage")
        if not isinstance(pointer, dict):
            pending = pending_confirmation(state, stage)
            if pending is not None:
                if pending.get("status") == "refused":
                    return {
                        "action": (
                            "stop for human inspection: the recorded refusal requires a diverse "
                            "profile in the shared configuration"
                        ),
                        "command": shell_join(base + ["context", "--run-dir", run_dir]),
                    }
                return {
                    "action": (
                        "ask the human to confirm the same-harness-and-model planning "
                        "author/reviewer resolution"
                    ),
                    "command": pending["confirmation_command"],
                }
            return {
                "action": "prepare the current stage",
                "command": shell_join(
                    base
                    + ["prepare", "--run-dir", run_dir, "--stage", stage, "--pass", str(pass_num)]
                ),
            }
        try:
            attempt_record = current_attempt(state, stage, pass_num)
        except ArtifactIntegrityError:
            attempt_record = None
        if attempt_record is None:
            prompt = Path(stage_paths(run_dir, stage, pass_num, 1)["prompt"])
        else:
            prompt = Path(attempt_record["paths"]["prompt"])
        if not prompt.is_file():
            return {
                "action": "render the deterministic worker prompt",
                "command": shell_join(
                    ["python3", script("render_prompt.py"), "--run-dir", run_dir, "--stage", stage, "--pass", str(pass_num)]
                ),
            }
        # An interrupted emission can leave the armed attempt's prompt or baseline path occupied by
        # bytes no manifest entry covers. Both writers then refuse forever, so the only way forward
        # is a fresh attempt; recommending the failing command instead would loop the operator.
        rearm = {
            "action": (
                "prepare the current stage again: the armed attempt has an unfinalized emission "
                "and its paths can never be reused"
            ),
            "command": shell_join(
                base + ["prepare", "--run-dir", run_dir, "--stage", stage, "--pass", str(pass_num)]
            ),
        }
        if attempt_record is not None and not attempt_record.get("prompt_manifest_id"):
            return rearm
        if not isinstance(state.get("tree_baseline"), dict) and attempt_record is not None:
            orphan = tree_snapshot_path(
                run_dir, stage, pass_num, attempt_record["attempt"], "before"
            )
            if orphan.exists():
                return rearm
        if not isinstance(state.get("tree_baseline"), dict):
            return {
                "action": "capture the immutable launch baseline",
                "command": shell_join(
                    ["python3", script("tree_integrity.py"), "baseline", "--run-dir", run_dir, "--stage", stage, "--pass", str(pass_num)]
                ),
            }
        if report.get("ready"):
            gate = "accept-review" if stage.endswith("review") else "accept-author"
            return {
                "action": "validate and gate the pending handoff",
                "command": shell_join(base + [gate, "--run-dir", run_dir]),
            }
        if report.get("uncertain") and pane["status"] not in {"live", "last-known"}:
            return {
                "action": "HITL: inspect the non-empty handoff that was never stably captured",
                "command": shell_join(base + ["context", "--run-dir", run_dir]),
            }
        if pane["status"] == "deadline":
            return {
                "action": "HITL: approve the run's one watcher deadline extension",
                "command": shell_join(
                    base
                    + [
                        "resume",
                        "--run-dir",
                        run_dir,
                        "--cmux-cmd",
                        cmux_cmd,
                        "--decision",
                        "extend",
                        "--reason",
                        "<human-reason>",
                    ]
                ),
            }
        if pane["status"] in {"dead", "watcher-expired"}:
            return {
                "action": "HITL: explicitly approve a fresh recovery pass",
                "command": shell_join(
                    base
                    + [
                        "resume",
                        "--run-dir",
                        run_dir,
                        "--cmux-cmd",
                        cmux_cmd,
                        "--decision",
                        "relaunch",
                        "--reason",
                        "<human-reason>",
                    ]
                ),
            }
        surface = pane.get("surface_id")
        common = ["--run-dir", run_dir, "--stage", stage, "--pass", str(pass_num)]
        if pane["status"] == "not-launched":
            return {
                "action": "launch one fresh visible pane",
                "command": shell_join(
                    [*pane_base, "launch", *common, "--anchor", "<caller-surface>"]
                ),
            }
        interrupted_start = pane.get("launch_attempted") and not pane.get("agent_launch_sent")
        interrupted_delivery = pane.get("delivery_attempted") and not pane.get("delivery_sent")
        if pane.get("input_interrupted") or interrupted_start or interrupted_delivery:
            return {
                "action": "HITL: inspect interrupted input; do not blindly restart or redeliver",
                "command": shell_join([
                    *shlex.split(cmux_cmd), "read-screen", "--workspace", state["workspace_id"],
                    "--surface", str(surface), "--lines", "80",
                ]),
            }
        if not pane.get("agent_launch_sent"):
            return {
                "action": "start the configured worker in the existing pane",
                "command": shell_join(
                    [*pane_base, "start-agent", *common, "--surface", str(surface)]
                ),
            }
        if pane.get("needs_start_inspection"):
            return {
                "action": "observe startup and use the exception procedure; assess and resolve any dialog",
                "command": shell_join([*pane_base, "observe", *common, "--surface", str(surface)]),
            }
        if not pane.get("prompt_sent") and pane.get("startup_state") != "ready":
            return {
                "action": "observe startup and assess the current screen before delivering; resolve any dialog first",
                "command": shell_join([*pane_base, "observe", *common, "--surface", str(surface)]),
            }
        if not pane.get("prompt_sent"):
            return {
                "action": "deliver the same deterministic prompt to the existing not-started assignment",
                "command": shell_join(
                    [
                        *pane_base,
                        "deliver",
                        *common,
                        "--surface",
                        str(surface),
                        "--prompt",
                        prompt,
                    ]
                ),
            }
        if not pane.get("assignment_start_confirmed") and not pane.get("start_prompt"):
            return {
                "action": (
                    "inspect the visible pane; redeliver the same prompt only for a confirmed "
                    "not-started recap, otherwise record that work started"
                ),
                "command": shell_join(
                    [
                        *pane_base,
                        "mark-started",
                        *common,
                        "--surface",
                        str(surface),
                    ]
                ),
            }
        return {
            "action": "rejoin the live worker through the armed watcher",
            "command": shell_join(
                [
                    "python3",
                    script("await_report.py"),
                    *common,
                    "--surface",
                    str(surface),
                    "--cmux-cmd",
                    cmux_cmd,
                    "--extension",
                    str(pane.get("extension", 0)),
                ]
            ),
        }
    if stage == "awaiting-spec-approval":
        return {
            "action": "resume the digest-bound specification approval walkthrough",
            "command": shell_join(base + ["approval-view", "--run-dir", run_dir]),
        }
    if stage == "awaiting-ticket-approval":
        return {
            "action": "resume the digest-bound ticket approval walkthrough",
            "command": shell_join(base + ["ticket-approval-view", "--run-dir", run_dir]),
        }
    if stage in BLOCKED_STAGES:
        return {
            "action": "HITL: record the decision and explicitly prepare a fresh author pass",
            "command": shell_join(
                base
                + [
                    "resume",
                    "--run-dir",
                    run_dir,
                    "--decision",
                    "relaunch",
                    "--reason",
                    "<human-decision>",
                ]
            ),
        }
    if stage == "ready-to-publish":
        return {
            "action": "publish or recover the already approved tracker",
            "command": shell_join(base + ["publish", "--run-dir", run_dir]),
        }
    if stage == "complete":
        return {"action": "run complete; a deliberate new session may be started", "command": None}
    return {
        "action": "stop: state is not a recognized planning stage",
        "command": shell_join(base + ["context", "--run-dir", run_dir]),
    }


def status_payload(run_dir: Path, *, cmux_cmd: str = "cmux") -> dict[str, Any]:
    run_dir = run_dir.resolve()
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise ValueError(f"No state.json under {run_dir}")
    state = read_planning_state(state_path)
    events, errors = read_event_stream(run_dir)
    try:
        require_current_format(state, source=state_path)
    except ArtifactIntegrityError as error:
        errors.append(str(error))
    stage = state.get("current_stage")
    pass_num = None
    if stage in STAGES:
        try:
            pass_num = stage_pass(state, stage)
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))

    task = pointer_identity(run_dir, state.get("task"), "persisted task", errors)
    normalized = pointer_identity(
        run_dir, state.get("normalized_grilling_input"), "normalized grilling input", errors
    )
    revalidation = pointer_identity(
        run_dir, state.get("grilling_revalidation"), "grilling revalidation progress", errors
    )
    grilling_import = grilling_import_status(run_dir, state.get("grilling_import"), errors)
    prepared = state.get("prepared_stage")
    if stage in STAGES and pass_num is not None and isinstance(prepared, dict):
        try:
            baseline = state.get("tree_baseline")
            load_prepared_snapshot(
                run_dir,
                stage,
                pass_num,
                require_baseline=isinstance(baseline, dict),
            )
            if isinstance(baseline, dict):
                before_relative = Path(baseline.get("path", ""))
                if before_relative.is_absolute() or ".." in before_relative.parts:
                    raise SnapshotError("tree baseline path is unsafe")
                before = read_json(run_dir / before_relative)
                if snapshot_digest(before) != baseline.get("sha256"):
                    raise SnapshotError("tree baseline is missing or changed")
            prepared = {**prepared, "valid": True}
        except (SnapshotError, OSError, TypeError, ValueError, KeyError) as error:
            prepared = {**prepared, "valid": False, "error": str(error)}
            errors.append(f"prepared snapshot is unsafe: {error}")
    elif stage in STAGES:
        prepared = None
    elif stage == "input":
        initialization = state.get("initialization")
        if not isinstance(initialization, dict):
            errors.append("validated input checkpoint metadata is missing")
            prepared = None
        elif initialization.get("target_stage") == "spec":
            initial_pointer = initialization.get("prepared_stage")
            if initial_pointer is None and pending_confirmation(state, "spec") is not None:
                prepared = None
            else:
                prepared = pointer_identity(
                    run_dir,
                    initial_pointer,
                    "validated input snapshot",
                    errors,
                )
        elif initialization.get("target_stage") == "awaiting-grilling-revalidation":
            prepared = None
            if initialization.get("prepared_stage") is not None:
                errors.append("grilling input checkpoint prepared a worker before revalidation")
        else:
            prepared = None
            errors.append("validated input checkpoint has an unknown target stage")

    if stage == "integrity-violation":
        gates = state.get("gate_decisions")
        gate = gates[-1] if isinstance(gates, list) and gates and isinstance(gates[-1], dict) else None
        source_stage = gate.get("stage") if gate else None
        if source_stage not in STAGES:
            errors.append("integrity violation has no preserved source stage")
        else:
            try:
                source_pass = stage_pass(state, source_stage)
                attempt = gate.get("attempt", 1)
                before_path = tree_snapshot_path(
                    run_dir, source_stage, source_pass, attempt, "before"
                )
                before = read_json(before_path)
                seals = state.get("tree_baseline_seals")
                expected = (
                    seals.get(f"{source_stage}-{source_pass}")
                    if isinstance(seals, dict)
                    else None
                )
                if not isinstance(expected, str) or snapshot_digest(before) != expected:
                    raise SnapshotError("launch baseline digest changed")
            except (SnapshotError, OSError, TypeError, ValueError, KeyError) as error:
                errors.append(f"integrity violation baseline is unsafe: {error}")

    pane = (
        pane_status(state, events, stage, pass_num, cmux_cmd)
        if stage in STAGES and pass_num is not None
        else {
            "status": "not-applicable",
            "surface_id": None,
            "agent_launch_sent": False,
            "assignment_start_confirmed": False,
            "prompt_sent": False,
            "last_event": None,
        }
    )
    report_path = (
        report_for(state, stage, pass_num)
        if stage in STAGES and pass_num is not None
        else None
    )
    report_exists = bool(report_path and report_path.is_file() and report_path.stat().st_size)
    report_digest = sha256_file(report_path) if report_exists and report_path else None
    captured_reports = [
        event.get("data")
        for event in events
        if matching_stage_pass_event(event, "worker.waiting", stage, pass_num)
        and isinstance(event.get("data"), dict)
        and event["data"].get("outcome") == "report"
        and event["data"].get("report") == str(report_path)
    ] if stage in STAGES and pass_num is not None else []
    captured_digest = captured_reports[-1].get("report_sha256") if captured_reports else None
    report_ready = bool(report_digest and report_digest == captured_digest)
    if isinstance(captured_digest, str) and report_digest != captured_digest:
        errors.append("stably captured report is missing or changed")
    report = {
        "path": str(report_path) if report_path else None,
        "exists": report_exists,
        "sha256": report_digest,
        "captured_sha256": captured_digest,
        "ready": report_ready,
        "uncertain": bool(report_exists and not report_ready),
        "pending": bool(stage in STAGES and not report_ready),
    }
    latest_review = state.get("reviewed_tickets") or state.get("reviewed_spec")
    review_events = [
        event.get("data")
        for event in events
        if event.get("type") == "gate"
        and isinstance(event.get("data"), dict)
        and event["data"].get("stage") in {"spec-review", "tickets-review"}
        and event["data"].get("verdict")
    ]
    if stage == "awaiting-spec-approval" and isinstance(state.get("reviewed_spec"), dict):
        latest_review = state["reviewed_spec"]
    elif stage in {"awaiting-ticket-approval", "ready-to-publish", "complete"} and isinstance(
        state.get("reviewed_tickets"), dict
    ):
        latest_review = state["reviewed_tickets"]
    elif review_events:
        latest_review = review_events[-1]
    if (
        isinstance(latest_review, dict)
        and isinstance(latest_review.get("candidate"), str)
        and isinstance(latest_review.get("candidate_sha256"), str)
    ):
        candidate = Path(latest_review["candidate"]).resolve()
        try:
            candidate.relative_to(run_dir)
        except ValueError:
            errors.append("latest reviewed candidate path escapes the planning run")
        else:
            if not candidate.is_file() or sha256_file(candidate) != latest_review["candidate_sha256"]:
                errors.append("latest reviewed candidate is missing or changed")
    approval = approval_status(run_dir, state, errors)
    publication = publication_status(run_dir, state, errors)
    diversity = state.get("diversity_confirmation")
    diversity_status = None
    if isinstance(diversity, dict):
        diversity_status = public_warning(diversity)
        if diversity.get("status") not in DECISION_STATUSES:
            errors.append("model-diversity confirmation has an unknown status")
    elif diversity is not None:
        errors.append("model-diversity confirmation state is malformed")
    pending_diversity = pending_confirmation(state, stage if isinstance(stage, str) else None)
    if pending_diversity is not None and isinstance(prepared, dict):
        errors.append("pending model-diversity confirmation has a prepared stage snapshot")

    if errors:
        classification = "inconsistent"
    elif stage == "awaiting-grilling-revalidation":
        classification = (
            "grilling-revalidation-interrupted"
            if state.get("grilling_revalidation")
            else "awaiting-grilling-revalidation"
        )
    elif stage in BLOCKED_STAGES:
        classification = "review-blocked" if "review" in stage else "hitl"
    elif stage in HITL_STAGES:
        classification = "hitl"
    elif stage in STAGES and pending_diversity is not None:
        classification = "pending-diversity-confirmation"
    elif stage in STAGES and report["uncertain"] and pane["status"] not in {"live", "last-known"}:
        classification = "hitl"
    elif stage in STAGES and pane["status"] in {"dead", "deadline", "watcher-expired"}:
        classification = "hitl"
    elif stage in STAGES and pane.get("assignment_start_confirmed") and not report_ready:
        classification = "pending-report"
    elif (
        stage == "spec"
        and state.get("spec_pass", 1) > 1
        and state.get("spec_revision_feedback")
    ) or (
        stage == "tickets"
        and state.get("tickets_pass", 1) > 1
        and state.get("ticket_revision_feedback")
    ) or (
        stage in STAGES
        and any(event.get("type", "").endswith("revision_requested") for event in events[-5:])
    ):
        classification = "requested-revision"
    else:
        classification = CLASSIFICATIONS.get(stage, "inconsistent")
        if classification == "inconsistent":
            errors.append(f"unknown current_stage {stage!r}")

    payload = {
        "commit_mode": state.get("commit_mode", "propose"),
        "run_id": state.get("run_id"),
        "run_dir": str(run_dir),
        "repository": state.get("repository"),
        "input": {
            "task": task,
            "grilling_import": grilling_import,
            "normalized_grilling_input": normalized,
            "grilling_revalidation": revalidation,
        },
        "classification": classification,
        "stage": {
            "current": stage,
            "mode": MODES.get(stage),
            "pass": pass_num,
        },
        "prepared_snapshot": prepared,
        "diversity_confirmation": diversity_status,
        "pane": pane,
        "report": report,
        "latest_review": {
            "verdict": latest_review.get("verdict") if isinstance(latest_review, dict) else None,
            "candidate_sha256": latest_review.get("candidate_sha256")
            if isinstance(latest_review, dict)
            else None,
        },
        "approval": approval,
        "publication": publication,
        "staged_artifacts": state.get("staged_tracker", {}).get("artifacts")
        if isinstance(state.get("staged_tracker"), dict)
        else None,
        "published_target": state.get("published_tracker", {}).get("path")
        if isinstance(state.get("published_tracker"), dict)
        else publication.get("target"),
        "consistency_errors": errors,
        "context_recovery": recovery_context(run_dir, state),
    }
    payload["recommended_next"] = recommended_next(
        run_dir, state, classification, pane, report, errors, cmux_cmd
    )
    return payload


def unfinished_runs(runs_root: Path, repository: Path) -> list[dict[str, Any]]:
    if not runs_root.is_dir():
        return []
    repository = repository.resolve()
    found: list[dict[str, Any]] = []
    for state_path in runs_root.glob("*/state.json"):
        try:
            raw = read_json(state_path)
            if not isinstance(raw, dict) or raw.get("workflow") != "planning":
                continue
            state = read_planning_state(state_path)
        # PlanningStateCompatibilityError subclasses ValueError; an unreadable durable run must
        # surface here instead of silently disappearing from the recovery listing.
        except PlanningStateCompatibilityError:
            raise
        except (OSError, ValueError):
            continue
        if not isinstance(state.get("repository"), str):
            continue
        try:
            same = Path(state["repository"]).resolve() == repository
        except (OSError, TypeError):
            same = False
        if same and state.get("current_stage") != "complete":
            run_id = state.get("run_id")
            updated = state.get("updated_at", state.get("created_at", ""))
            found.append(
                {
                    "run_id": run_id if isinstance(run_id, str) else state_path.parent.name,
                    "run_dir": str(state_path.parent.resolve()),
                    "current_stage": state.get("current_stage"),
                    "updated_at": updated if isinstance(updated, str) else "",
                }
            )
    return sorted(found, key=lambda item: (item["updated_at"], item["run_id"]), reverse=True)
