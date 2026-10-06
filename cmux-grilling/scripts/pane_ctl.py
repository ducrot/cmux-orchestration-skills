#!/usr/bin/env python3
"""Deterministic cmux control, scoped to the run's pinned workspace.

Every cmux call this skill makes goes through here so the workspace scope always
comes from the run's state.json (pinned at `run_state.py init`), never from the
focused workspace or an environment fallback. Verbs:

  workspace  print the pinned workspace id
  cmux       generic passthrough that injects --workspace into any cmux command
  launch      launch-wave check + new-split + deterministic label + pane lifecycle events
  start-agent send the prepared launch-wave command with round prompt + worker.launch_sent
  observe/assess/respond  screen-bound readiness and individually assessed dialog keys
  deliver     consume readiness + send + send-key enter + screen + worker.prompt_sent
              (--prompt hands over a rendered prompt with the skill's own wording;
               --text is for follow-ups)
  close       close-surface + pane.closed event

The round watcher confirms normal starts from markers. The readiness gate enforces
observation and assessment for exception-path input and follow-ups.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from worker_readiness import Gate, ReadinessError, add_commands, begin_start, read_events

from launch_wave import (
    LaunchWaveError,
    lane_launch_record,
    lane_shell_command,
    git_root,
    load_launchable_lane,
)
from orchestrator_lib import (
    DELIVERY_TEMPLATES,
    LANES,
    append_jsonl,
    delivery_text,
    read_run_state,
    round_marker_path,
    round_prompt_path,
    utc_now,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmux-cmd", help="Override the cmux executable (tests)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    workspace = subparsers.add_parser("workspace", help="Print the run's pinned workspace id")
    workspace.add_argument("--run-dir", required=True)

    passthrough = subparsers.add_parser(
        "cmux",
        help="Run any cmux command with --workspace injected from the pinned workspace",
    )
    passthrough.add_argument("--run-dir", required=True)
    passthrough.add_argument("args", nargs=argparse.REMAINDER, help="cmux command and arguments (after --)")

    launch = subparsers.add_parser("launch", help="Split a new lane pane, label it, record events")
    launch.add_argument("--run-dir", required=True)
    launch.add_argument("--lane", required=True, choices=sorted(LANES))
    launch.add_argument("--anchor", required=True, help="Surface id to split from (previous lane pane)")
    launch.add_argument("--direction", default="right", choices=["left", "right", "up", "down"])

    start = subparsers.add_parser(
        "start-agent",
        help="Start the lane's agent in its pane with the skill's fixed launch command",
    )
    start.add_argument("--run-dir", required=True)
    start.add_argument("--surface", required=True)
    start.add_argument("--lane", required=True, choices=sorted(LANES))
    start.add_argument("--settle-seconds", type=float, default=0.0, help="Optional diagnostic wait before read-screen")
    start.add_argument("--read-lines", type=int, default=40)

    deliver = subparsers.add_parser("deliver", help="Send text to a pane, submit with Enter, echo the screen")
    deliver.add_argument("--run-dir", required=True)
    deliver.add_argument("--surface", required=True)
    payload = deliver.add_mutually_exclusive_group(required=True)
    payload.add_argument("--prompt", help="Prompt path to hand over; the skill supplies the wording")
    payload.add_argument("--text", help="Follow-up text (re-emission requests, clarifications)")
    deliver.add_argument(
        "--kind",
        choices=sorted(DELIVERY_TEMPLATES),
        default="round",
        help="Which prompt --prompt hands over: a round task for exit-9 recovery",
    )
    deliver.add_argument("--lane", choices=sorted(LANES), required=True)
    deliver.add_argument("--settle-seconds", type=float, default=3.0, help="Wait before read-screen")
    deliver.add_argument("--read-lines", type=int, default=40)

    close = subparsers.add_parser("close", help="Close a lane pane and record pane.closed")
    close.add_argument("--run-dir", required=True)
    close.add_argument("--surface", required=True)
    close.add_argument("--lane", required=True, choices=sorted(LANES))

    for command in (launch, start, close, deliver):
        command.add_argument("--round", dest="round_number", type=int, required=command is start)
    for name in ("open-round", "start-round"):
        command = subparsers.add_parser(name)
        command.add_argument("--run-dir", required=True)
        command.add_argument("--round", dest="round_number", type=int, required=True)
        if name == "open-round":
            command.add_argument("--anchor", help="Orchestrator surface UUID, required for round 1")
        else:
            command.set_defaults(settle_seconds=0, read_lines=40)
    add_commands(subparsers, selector="lane")
    return parser


def pinned_workspace(run_dir: Path) -> str:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise SystemExit(f"No state.json under {run_dir} — run run_state.py init first")
    workspace_id = read_run_state(run_dir).get("workspace_id")
    if not workspace_id:
        raise SystemExit(
            f"{state_path} has no pinned workspace_id — re-init the run from a cmux pane "
            "(or with --workspace-id); pane control refuses to fall back to the focused workspace"
        )
    return workspace_id


def cmux_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cmux_cmd) if args.cmux_cmd else ["cmux"]


def run_cmux(args: argparse.Namespace, argv: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    result = subprocess.run(cmux_base(args) + argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise SystemExit(
            f"cmux {' '.join(argv)} failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def record_event(run_dir: Path, event_type: str, message: str, data: dict) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": utc_now(), "type": event_type, "message": message, "data": data},
    )


def lane_label(lane: str, slug: str) -> str:
    return f"{LANES[lane]['label']} - grill-{slug}"


def cmd_workspace(args: argparse.Namespace) -> int:
    print(pinned_workspace(Path(args.run_dir)))
    return 0


def cmd_cmux(args: argparse.Namespace) -> int:
    passthrough = list(args.args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    if not passthrough:
        raise SystemExit("No cmux command given (use: pane_ctl.py cmux --run-dir <dir> -- <command> ...)")
    if "--workspace" in passthrough:
        raise SystemExit("Do not pass --workspace here; the pinned workspace is injected automatically")
    workspace_id = pinned_workspace(Path(args.run_dir))
    # Global flags (--json, --id-format ...) precede the command word; --workspace is a
    # command option and must come after it.
    command_index = next((i for i, token in enumerate(passthrough) if not token.startswith("-")), None)
    if command_index is None:
        raise SystemExit(f"No cmux command word found in: {' '.join(passthrough)}")
    argv = (
        passthrough[: command_index + 1]
        + ["--workspace", workspace_id]
        + passthrough[command_index + 1 :]
    )
    result = subprocess.run(cmux_base(args) + argv)
    return result.returncode


def require_surface_id(surface: str) -> None:
    if not surface or surface.startswith("surface:"):
        raise SystemExit("pane control requires stable surface UUIDs, not positional surface:N refs")


def cmd_launch(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    # Validate the entire immutable cohort before even resolving cmux. One missing, failed,
    # mismatched, or tampered lane blocks every pane, so no partial layout can be created.
    load_launchable_lane(run_dir, args.lane)
    require_surface_id(args.anchor)
    workspace_id = pinned_workspace(run_dir)
    state = read_run_state(run_dir)
    slug = state.get("slug", "unknown")
    split = run_cmux(
        args,
        [
            "--json",
            "--id-format",
            "both",
            "new-split",
            args.direction,
            "--workspace",
            workspace_id,
            "--surface",
            args.anchor,
            "--focus",
            "false",
        ],
    )
    try:
        created = json.loads(split.stdout)
    except ValueError:
        raise SystemExit(f"new-split returned no parseable JSON: {split.stdout.strip()}")
    surface_id = created.get("surface_id")
    if not surface_id or surface_id.startswith("surface:"):
        raise SystemExit(f"new-split output carries no surface id: {split.stdout.strip()}")
    label = lane_label(args.lane, slug)
    if args.round_number is not None:
        label += f" - round-{args.round_number}"
    launch_data = {
        "lane": args.lane,
        "round": args.round_number,
        "surface_id": surface_id,
        "surface_ref": created.get("surface_ref"),
        "pane_id": created.get("pane_id") or created.get("pane_ref"),
        "direction": args.direction,
        "anchor": args.anchor,
    }
    record_event(run_dir, "pane.launched", f"launched {label}", launch_data)
    run_cmux(args, ["rename-tab", "--workspace", workspace_id, "--surface", surface_id, label])
    record_event(run_dir, "pane.labeled", f"labeled {label}", {**launch_data, "label": label})
    print(json.dumps({"surface_id": surface_id, "surface_ref": created.get("surface_ref"), "label": label}))
    return 0


def send_submit_echo(
    args: argparse.Namespace,
    workspace_id: str,
    text: str,
    event_type: str,
    message: str,
    data: dict,
    echo: str | None = "stdout",
) -> None:
    run_dir = Path(args.run_dir)
    target = ["--workspace", workspace_id, "--surface", args.surface]
    if event_type == "worker.prompt_sent":
        record_event(run_dir, "worker.delivery_attempted", "task input about to be sent", data)
    run_cmux(args, ["send", *target, text])
    # A trailing \n does not submit in the Codex/Claude TUIs; Enter must be its own key event.
    run_cmux(args, ["send-key", *target, "enter"])
    record_event(run_dir, event_type, message, data)
    if echo:
        time.sleep(args.settle_seconds)
        screen = run_cmux(args, ["read-screen", *target, "--lines", str(args.read_lines)])
        print(screen.stdout, end="", file=sys.stderr if echo == "stderr" else sys.stdout)


def cmd_start_agent(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    snapshot, lane_entry = load_launchable_lane(run_dir, args.lane)
    require_surface_id(args.surface)
    validate_round(run_dir, args.round_number)
    prompt = round_prompt_path(run_dir, args.round_number, args.lane)
    if not prompt.is_file():
        raise SystemExit(f"Missing round prompt: {prompt}")
    relative = os.path.relpath(prompt, git_root(Path.cwd()))
    marker = round_marker_path(run_dir, args.round_number, args.lane)
    text = delivery_text("round", relative)
    command = lane_shell_command(lane_entry, text)
    workspace_id = pinned_workspace(run_dir)
    data = begin_start(args, record_event, {
        "lane": args.lane,
        "surface_id": args.surface,
        "round": args.round_number,
        "command": command,
        **lane_launch_record(snapshot, lane_entry),
        "prompt_path": str(prompt),
        "prompt_path_relative": relative,
        "text": text,
        "marker_path": str(marker),
        "start_time_ns": time.time_ns(),
    })
    send_submit_echo(
        args,
        workspace_id,
        command,
        "worker.launch_sent",
        "round attached; arm the round watcher",
        data,
        echo="stderr" if args.settle_seconds > 0 else None,
    )
    print(json.dumps({key: data[key] for key in
                      ("launch_id", "surface_id", "prompt_path", "marker_path")} |
                     {"next": f"arm await_reports.py --round {args.round_number} --questions <n>"}))
    return 0


def cmd_readiness(args: argparse.Namespace) -> int:
    return Gate(args, pinned_workspace(Path(args.run_dir)), run_cmux, record_event).run()


def cmd_deliver(args: argparse.Namespace) -> int:
    workspace_id = pinned_workspace(Path(args.run_dir))
    Gate(args, workspace_id, run_cmux, record_event).consume()
    text = delivery_text(args.kind, args.prompt) if args.prompt else args.text
    send_submit_echo(
        args,
        workspace_id,
        text,
        "worker.prompt_sent",
        "text sent and submitted; started-confirmation is the orchestrator's call",
        {
            "lane": args.lane,
            "surface_id": args.surface,
            "prompt_path": args.prompt,
            "kind": args.kind if args.prompt else None,
            "round": args.round_number,
            "text": text,
        },
    )
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    require_surface_id(args.surface)
    run_dir = Path(args.run_dir)
    workspace_id = pinned_workspace(run_dir)
    run_cmux(args, ["close-surface", "--workspace", workspace_id, "--surface", args.surface])
    record_event(
        run_dir,
        "pane.closed",
        f"closed {args.lane} lane pane",
        {"lane": args.lane, "round": args.round_number, "surface_id": args.surface},
    )
    return 0


def validate_round(run_dir: Path, number: int) -> None:
    if number < 1 or number > read_run_state(run_dir)["max_rounds"]:
        raise SystemExit("round is outside the run's budget")


def round_surfaces(events: list[dict], number: int) -> dict[str, str]:
    surfaces = {}
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "pane.launched" and data.get("round") == number:
            surfaces[data["lane"]] = data["surface_id"]
    return surfaces


def require_snapshot(events: list[dict], label: str, number: int) -> None:
    snapshots = [(i, e) for i, e in enumerate(events) if e.get("type") == "tree.snapshot"]
    if not snapshots or snapshots[-1][1].get("message") != label:
        raise SystemExit(f"newest tree.snapshot must be {label}")
    last_pane = max((i for i, e in enumerate(events) if e.get("type", "").startswith("pane.")
                     and e.get("data", {}).get("round") == number), default=-1)
    if snapshots[-1][0] <= last_pane:
        raise SystemExit(f"tree.snapshot {label} must be newer than the round's last pane event")


def cmd_open_round(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    validate_round(run_dir, args.round_number)
    load_launchable_lane(run_dir, "codebase")
    events = read_events(run_dir)
    if round_surfaces(events, args.round_number):
        raise SystemExit("round already has panes; use single-lane recovery verbs")
    previous = round_surfaces(events, args.round_number - 1)
    if args.round_number > 1:
        if set(previous) != set(LANES):
            raise SystemExit("previous round does not have all four lane surfaces")
        require_snapshot(events, f"reports-captured round-{args.round_number - 1}", args.round_number - 1)
        for lane in LANES:
            gates = [e for e in events if e.get("type") == "gate"
                     and e.get("stage") == f"round-{args.round_number - 1}-{lane}"]
            if not gates:
                raise SystemExit(f"previous round gate not recorded: {lane}")
    elif not args.anchor or args.anchor.startswith("surface:"):
        raise SystemExit("round 1 needs --anchor with the orchestrator's stable surface UUID")
    launched, closed = {}, []
    before = len(events)
    try:
        for lane in LANES:
            anchor = previous[lane] if previous else (next(reversed(launched.values())) if launched else args.anchor)
            direction = "down" if previous or launched else "right"
            lane_args = argparse.Namespace(**{**vars(args), "lane": lane, "anchor": anchor, "direction": direction})
            with contextlib.redirect_stdout(io.StringIO()) as output:
                cmd_launch(lane_args)
            launched[lane] = json.loads(output.getvalue())["surface_id"]
        for lane, surface in previous.items():
            cmd_close(argparse.Namespace(**{
                **vars(args), "lane": lane, "surface": surface, "round_number": args.round_number - 1}))
            closed.append(surface)
    except (SystemExit, OSError, subprocess.SubprocessError, LaunchWaveError) as error:
        new_events = read_events(run_dir)[before:]
        created = [e["data"]["surface_id"] for e in new_events if e.get("type") == "pane.launched"]
        orphaned = created if len(launched) < len(LANES) else [
            surface for surface in previous.values() if surface not in closed]
        raise SystemExit(f"open-round failed: {error}; " + json.dumps({
            "launched": created, "closed": closed, "orphaned": orphaned})) from error
    print(json.dumps(launched))
    return 0


def cmd_start_round(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    validate_round(run_dir, args.round_number)
    load_launchable_lane(run_dir, "codebase")
    events = read_events(run_dir)
    require_snapshot(events, f"launched round-{args.round_number}", args.round_number)
    surfaces = round_surfaces(events, args.round_number)
    if set(surfaces) != set(LANES):
        raise SystemExit("open all four round panes before start-round")
    if any(e.get("type") in ("worker.starting", "worker.launch_sent") and
           e.get("data", {}).get("round") == args.round_number for e in events):
        raise SystemExit("round start already attempted; use single-lane recovery verbs")
    started = {}
    try:
        for lane, surface in surfaces.items():
            with contextlib.redirect_stdout(io.StringIO()) as output:
                cmd_start_agent(argparse.Namespace(**{**vars(args), "lane": lane, "surface": surface}))
            started[lane] = json.loads(output.getvalue())
    except (SystemExit, OSError, subprocess.SubprocessError, LaunchWaveError, ReadinessError) as error:
        raise SystemExit(f"start-round failed: {error}; " + json.dumps({
            "started": list(started), "unstarted": [lane for lane in LANES if lane not in started]})) from error
    print(json.dumps(started))
    return 0


COMMANDS = {
    "open-round": cmd_open_round,
    "start-round": cmd_start_round,
    "observe": cmd_readiness,
    "assess": cmd_readiness,
    "respond": cmd_readiness,
    "workspace": cmd_workspace,
    "cmux": cmd_cmux,
    "launch": cmd_launch,
    "start-agent": cmd_start_agent,
    "deliver": cmd_deliver,
    "close": cmd_close,
}


def main() -> int:
    args = build_parser().parse_args()
    try:
        return COMMANDS[args.command](args)
    except (LaunchWaveError, ReadinessError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
