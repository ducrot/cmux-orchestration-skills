#!/usr/bin/env python3
"""Launch fresh visible planning workers in the run's pinned CMUX workspace."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from worker_readiness import Gate, VERBS, add_commands, begin_start, context

from artifact_manifest import ArtifactIntegrityError, current_attempt, require_current_format, verify_or_gate
from orchestrator_lib import (
    ROLE_LABELS,
    STAGES,
    append_event,
    delivery_text,
    planning_events,
    read_planning_state,
    surface_event_recorded,
    validate_recorded_surface,
)
from stage_snapshot import (
    SnapshotError,
    load_prepared_snapshot,
    snapshot_launch_record,
    snapshot_shell_command,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmux-cmd", help="override cmux executable for tests")
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage_pass = argparse.ArgumentParser(add_help=False)
    stage_pass.add_argument("--run-dir", required=True)
    stage_pass.add_argument("--stage", choices=STAGES, required=True)
    stage_pass.add_argument("--pass", dest="pass_num", type=int, required=True)
    # Every verb but launch addresses an already-launched pane, so --surface lives on this
    # shared parent and run() validates it once for all of them.
    launched_pane = argparse.ArgumentParser(add_help=False, parents=[stage_pass])
    launched_pane.add_argument("--surface", required=True)
    launch = subparsers.add_parser("launch", parents=[stage_pass])
    launch.add_argument("--anchor", required=True)
    launch.add_argument("--direction", choices=("left", "right", "up", "down"), default="right")
    start = subparsers.add_parser("start-agent", parents=[launched_pane])
    start.add_argument("--settle-seconds", type=float, default=0)
    deliver = subparsers.add_parser("deliver", parents=[launched_pane])
    deliver.add_argument("--prompt", required=True)
    deliver.add_argument("--settle-seconds", type=float, default=3)
    subparsers.add_parser("mark-started", parents=[launched_pane])
    subparsers.add_parser("close", parents=[launched_pane])
    add_commands(subparsers, parents=[launched_pane])
    return parser


def cmux_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cmux_cmd) if args.cmux_cmd else ["cmux"]


def pinned_workspace(state: dict) -> str:
    value = state.get("workspace_id")
    if not value:
        raise SnapshotError("run has no pinned workspace; pane control will not use focused-workspace fallback")
    return value


def workspace(run_dir: Path) -> str:
    return pinned_workspace(read_planning_state(run_dir / "state.json"))


def cmux(args: argparse.Namespace, argv: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmux_base(args) + argv, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise SnapshotError(result.stderr.strip() or f"cmux exited {result.returncode}")
    return result


def event(run_dir: Path, kind: str, message: str, data: dict) -> None:
    append_event(run_dir, kind, message, data)


def send(args: argparse.Namespace, surface: str, text: str, kind: str, data: dict) -> dict:
    run_dir = Path(args.run_dir)
    target = ["--workspace", workspace(run_dir), "--surface", surface]
    if kind == "worker.launch_sent":
        data["start_time_ns"] = time.time_ns()
        data = begin_start(args, event, data)
    if kind == "worker.prompt_sent":
        event(run_dir, "worker.delivery_attempted", "task input about to be sent", data)
    cmux(args, ["send", *target, text])
    cmux(args, ["send-key", *target, "enter"])
    event(run_dir, kind, "sent and submitted text to stable planning pane", data)
    if kind != "worker.launch_sent" or args.settle_seconds > 0:
        time.sleep(args.settle_seconds)
        screen = cmux(args, ["read-screen", *target, "--lines", "40"])
        if kind != "worker.launch_sent":
            print(screen.stdout, end="")
    return data


def run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if args.command == "close":
        state_path = run_dir / "state.json"
        require_current_format(read_planning_state(state_path), source=state_path)
    else:
        state = verify_or_gate(run_dir, stage=args.stage)
        attempt = current_attempt(state, args.stage, args.pass_num)
    if args.command == "launch":
        snapshot = load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        pinned = pinned_workspace(state)
        result = cmux(
            args,
            [
                "--json",
                "--id-format",
                "both",
                "new-split",
                args.direction,
                "--workspace",
                pinned,
                "--surface",
                args.anchor,
                "--focus",
                "false",
            ],
        )
        try:
            created = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise SnapshotError("cmux new-split did not return JSON") from error
        surface = created.get("surface_id")
        if not isinstance(surface, str) or not surface:
            raise SnapshotError("cmux new-split returned no stable surface identity")
        label = f"{ROLE_LABELS[args.stage]} {args.pass_num} - {state['run_id']}"
        data = {
            "stage": args.stage,
            "pass": args.pass_num,
            "attempt": attempt["attempt"],
            "attempt_id": attempt["attempt_id"],
            "surface_id": surface,
            "surface_ref": created.get("surface_ref"),
            "pane_id": created.get("pane_id") or created.get("pane_ref"),
            "label": label,
            **snapshot_launch_record(snapshot),
        }
        # Recorded before labeling, so a failing rename never orphans a pane whose identity
        # was never written down.
        event(run_dir, "pane.launched", "launched fresh planning worker", data)
        cmux(args, ["rename-tab", "--workspace", pinned, "--surface", surface, label])
        event(run_dir, "pane.labeled", "labeled fresh planning worker", data)
        print(json.dumps(data, sort_keys=True))
        return 0
    # One choke point for every post-launch verb: a positional ref or any other identity stops
    # here, before the first cmux call, and a later verb cannot forget to check.
    events = planning_events(run_dir)
    # close is the accepted recovery exception: it may reach any pane this stage pass launched,
    # so a pane orphaned by a failed or retried launch stays closable. Work verbs stay latest-only.
    surface = validate_recorded_surface(
        events, args.stage, args.pass_num, args.surface, any_launch=args.command == "close"
    )
    if args.command in VERBS:
        load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        return Gate(args, workspace(run_dir), cmux, event).run()
    if args.command == "start-agent":
        snapshot = load_prepared_snapshot(run_dir, args.stage, args.pass_num, require_baseline=True)
        prompt = Path(snapshot["prompt_path"])
        baseline = state["tree_baseline"]
        if prompt.resolve() != Path(baseline["prompt_path"]).resolve():
            raise SnapshotError("snapshot prompt is not the baseline-verified prompt")
        relative = os.path.relpath(prompt.resolve(), Path(state["repository"]).resolve())
        text = delivery_text(relative)
        launch = send(
            args,
            surface,
            snapshot_shell_command(snapshot, text),
            "worker.launch_sent",
            {"stage": args.stage, "pass": args.pass_num, "surface_id": surface,
             **snapshot_launch_record(snapshot), "prompt_path": str(prompt),
             "prompt_path_relative": relative, "text": text,
             "marker_path": attempt["paths"]["started"]},
        )
        print(json.dumps({key: launch[key] for key in
                          ("launch_id", "surface_id", "prompt_path", "marker_path")} |
                         {"next_step": "await_report.py"}, sort_keys=True))
        return 0
    if args.command == "deliver":
        load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        # The baseline pinned and digest-verified exactly one prompt file. Delivering any other
        # path hands the pane an unaudited work order that every later gate still calls verified.
        verified = read_planning_state(run_dir / "state.json")["tree_baseline"]["prompt_path"]
        if Path(args.prompt).resolve() != Path(verified).resolve():
            raise SnapshotError(f"--prompt is not the baseline-verified prompt: {verified}")
        Gate(args, workspace(run_dir), cmux, event).consume()
        send(
            args,
            surface,
            delivery_text(args.prompt),
            "worker.prompt_sent",
            {"stage": args.stage, "pass": args.pass_num, "surface_id": surface, "prompt": args.prompt},
        )
        return 0
    if args.command == "mark-started":
        snapshot = load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        launch_id, later = context(events, {"stage": args.stage, "pass": args.pass_num}, surface)
        launch = next((e["data"] for e in reversed(events)
                      if e.get("type") == "worker.launch_sent"
                      and e.get("data", {}).get("launch_id") == launch_id), {})
        already_recorded = any(e.get("type") == "worker.started"
                               and e.get("data", {}).get("launch_id") == launch_id
                               and e["data"].get("attempt_id") == attempt["attempt_id"] for e in later)
        delivered = surface_event_recorded(later, "worker.prompt_sent", args.stage, args.pass_num, surface)
        if not delivered and launch.get("prompt_path") != snapshot["prompt_path"]:
            raise SnapshotError("cannot mark-started before the assignment was delivered")
        if not already_recorded:
            event(
                run_dir,
                "worker.started",
                "orchestrator confirmed the deterministic assignment started in the visible pane",
                {
                    "stage": args.stage,
                    "pass": args.pass_num,
                    "surface_id": surface,
                    **snapshot_launch_record(snapshot),
                    "launch_id": launch_id,
                    "evidence": "screen",
                    "marker_path": attempt["paths"]["started"],
                },
            )
        print(
            json.dumps(
                {
                    "already_recorded": already_recorded,
                    "stage": args.stage,
                    "pass": args.pass_num,
                    "surface_id": surface,
                    "started": True,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command != "close":
        raise SnapshotError(f"unhandled command: {args.command}")
    cmux(args, ["close-surface", "--workspace", workspace(run_dir), "--surface", surface])
    event(
        run_dir,
        "pane.closed",
        "closed planning worker pane",
        {"stage": args.stage, "pass": args.pass_num, "surface_id": surface},
    )
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (
        ArtifactIntegrityError,
        SnapshotError,
        OSError,
        KeyError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
