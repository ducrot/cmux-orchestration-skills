#!/usr/bin/env python3
"""Watch fresh round starts and reports; exit 0=ready, 7=pane dead, 8=deadline, 9=not started.

Run in background Bash, or Monitor with re-arm, to wake the orchestrator at exit.
One watcher per round, not per lane: a round synthesizes only when all four lanes
delivered, so a per-lane wake-up would mostly mean "keep waiting". The report files are
ground truth; a pane's state only matters while its report is still missing — a lane
whose pane exits right after writing its report has delivered, not died. No screen-content heuristics: a static-looking pane
(a lane mid-thought, or one already finished) is alive.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
import json
import shlex
import subprocess
import time
from pathlib import Path

from worker_readiness import read_events
from watch_deadlines import arm, monotonic_deadlines, fresh_report
from orchestrator_lib import (
    LANES, append_jsonl, read_run_state, round_marker_path, round_report_path, round_wait_minutes, utc_now,
)

EXIT_REPORTS = 0    # all round reports exist; NOT an advance verdict
EXIT_PANE_DEAD = 7  # a lane surface with a pending report is gone per surface-health
EXIT_DEADLINE = 8   # deadline exceeded with the pending panes alive/unknown
EXIT_NOT_STARTED = 9  # round start window elapsed with lanes unconfirmed
# 1 = crash, 2 = argparse usage; 3-6 = report gates; 7-9 = watchers. Skill-wide unique.


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--round", dest="round_number", type=int)
    parser.add_argument(
        "--lanes",
        default=",".join(LANES),
        help="Comma-separated lanes to await (default: all four)",
    )
    parser.add_argument(
        "--lane-surface",
        action="append",
        default=[],
        metavar="LANE=SURFACE",
        help="Repeatable. Lanes without a surface are watched file-only (no health checks)",
    )
    parser.add_argument(
        "--workspace",
        help="cmux workspace id override (tests). Defaults to the run's pinned workspace_id "
        "from state.json; no env fallback — an unresolvable workspace is a usage error.",
    )
    parser.add_argument(
        "--questions",
        type=int,
        help="Questions in the round; scales the default deadline (15 min + 5 per extra question)",
    )
    parser.add_argument(
        "--deadline-minutes",
        type=float,
        help="Initial wait duration, or additional minutes with --deadline-reason",
    )
    parser.add_argument("--deadline-reason", help="Record the reason for the one deadline extension")
    parser.add_argument("--extend", action="store_true", help="Record the one deadline extension and resume watching")
    parser.add_argument("--reason", help="Required explanation for --extend")
    parser.add_argument("--start-minutes", type=float, default=5)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--health-interval-seconds", type=float, default=60)
    parser.add_argument("--heartbeat-seconds", type=float, default=300)
    parser.add_argument("--health-cmd", help="Override the surface-health command (tests)")
    return parser


def parse_lanes(args: argparse.Namespace) -> list[str]:
    lanes = [name.strip() for name in args.lanes.split(",") if name.strip()]
    if not lanes:
        raise SystemExit("--lanes is empty")
    unknown = [name for name in lanes if name not in LANES]
    if unknown:
        raise SystemExit(f"unknown lanes: {', '.join(unknown)}")
    return lanes


def parse_lane_surfaces(pairs: list[str], lanes: list[str]) -> dict[str, str]:
    surfaces: dict[str, str] = {}
    for pair in pairs:
        lane, separator, surface = pair.partition("=")
        if not separator or not lane.strip() or not surface.strip():
            raise SystemExit(f"--lane-surface expects LANE=SURFACE, got: {pair}")
        lane, surface = lane.strip(), surface.strip()
        if lane not in lanes:
            raise SystemExit(f"--lane-surface for a lane not being awaited: {lane}")
        surfaces[lane] = surface
    return surfaces


def report_path(run_dir: Path, round_number: int, lane: str) -> Path:
    return round_report_path(run_dir, round_number, lane)


def pinned_workspace(run_dir: Path) -> str | None:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        return None
    return read_run_state(run_dir).get("workspace_id") or None


def health_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    if args.health_cmd:
        return shlex.split(args.health_cmd)
    workspace = args.workspace or pinned_workspace(Path(args.run_dir))
    if not workspace:
        # Unscoped surface-health resolves against the focused workspace — the silent
        # wrong-workspace fallback this skill removed. Refuse instead of guessing.
        parser.error(
            "no cmux workspace: the run's state.json has no workspace_id and no "
            "--workspace was given (re-init the run, or pass --workspace explicitly)"
        )
    return ["cmux", "--json", "--id-format", "both", "surface-health", "--workspace", workspace]


def live_surfaces(health_output: str) -> set[str]:
    """Surface refs AND ids from a successful health listing.

    Pinned to real output (captured 2026-07-25): a closed pane's surface simply
    disappears from the listing; there are no dead/exited markers. With
    `--id-format both`, JSON carries `{"surfaces": [{"ref": "surface:465",
    "id": "<UUID>", ...}]}` — the health command must request both, because
    `pane_ctl.py launch` hands out UUIDs and a UUID can never match a ref-only
    listing (the ISSUE-013 pilot's false "all lanes dead" alarm). Plain text is
    one `surface:465  type=terminal in_window=true` line per surface. Membership
    must be exact — a substring check makes `surface:46` match `surface:465`.
    """
    try:
        payload = json.loads(health_output)
    except ValueError:
        return {line.split()[0] for line in health_output.splitlines() if line.strip()}
    entries = payload.get("surfaces", [])
    return {entry.get("ref") for entry in entries} | {
        entry["id"] for entry in entries if entry.get("id")
    }


def check_health(cmd: list[str], surfaces: dict[str, str]) -> tuple[str, list[str], str]:
    """Returns (status, dead_lanes, detail); status is 'dead' | 'alive' | 'unknown'.

    A failing health command is 'unknown' and never ends the wait — a transient CLI
    error must not kill a 15-minute round watch.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        return "unknown", [], str(error)
    if result.returncode != 0:
        return "unknown", [], result.stderr.strip() or f"exit {result.returncode}"
    live = live_surfaces(result.stdout)
    dead = sorted(lane for lane, surface in surfaces.items() if surface not in live)
    if dead:
        detail = ", ".join(f"{lane}={surfaces[lane]}" for lane in dead)
        return "dead", dead, f"surfaces not healthy in listing: {detail}"
    return "alive", [], ""


def waiting_event(run_dir: Path, message: str, data: dict) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": utc_now(), "type": "worker.waiting", "message": message, "data": data},
    )


def join(lanes: list[str]) -> str:
    return ",".join(lanes) if lanes else "none"


def current_launch(events: list[dict], lane: str, surface: str | None, number: int) -> dict | None:
    panes = [e["data"] for e in events if e.get("type") == "pane.launched"
             and e.get("data", {}).get("lane") == lane]
    if panes and (panes[-1].get("round") != number or
                  surface is not None and panes[-1].get("surface_id") != surface):
        return None
    boundary = [e for e in events if e.get("type") in ("worker.starting", "worker.launch_sent")
                and e.get("data", {}).get("lane") == lane]
    if not boundary or boundary[-1]["type"] != "worker.launch_sent":
        return None
    launch = boundary[-1]["data"]
    if launch.get("round") != number or (surface is not None and launch.get("surface_id") != surface):
        return None
    if not isinstance(launch.get("start_time_ns"), int):
        return None
    return launch


def round_clock(events, identity, launches, minutes, start_minutes, reason, emit):
    # A round owns one clock even if a lane is replaced. Only an exit-9 recovery for
    # a named not-started lane creates a new window. Follow-ups never renew it.
    pending = set()
    recoveries = []
    anchor = min((data["start_time_ns"] / 1e9 for data in launches.values() if data), default=None)
    for index, event in enumerate(events):
        data = event.get("data", {})
        if (event.get("type") == "worker.waiting" and data.get("round") == identity["round"]
                and data.get("outcome") == "not_started"):
            pending.update(data.get("not_started", []))
        lane = data.get("lane")
        if lane not in pending:
            continue
        if data.get("surface_id") != identity["surface_ids"].get(lane):
            continue
        kind = event.get("type")
        if kind in ("worker.prompt_sent", "worker.dialog_response", "worker.launch_sent") or (
                kind == "worker.started" and data.get("evidence") == "screen"):
            pending.remove(lane)
            recoveries.append(index)
            anchor = datetime.fromisoformat(event["time"]).timestamp()
    key = hashlib.sha256(json.dumps([identity["round"], identity["lanes"], recoveries], sort_keys=True).encode()).hexdigest()
    def anchored_emit(data):
        clock = data["watch_clock"]
        if not any(e.get("data", {}).get("watch_clock", {}).get("key") == key for e in events) and anchor is not None:
            shift = anchor - clock["armed_at"]
            clock["armed_at"] = anchor
            clock["start_deadline"] += shift
            if not clock["extension"]:
                clock["deadline"] += shift
        emit(data)
    return arm(events, key, minutes, start_minutes, reason, anchored_emit)


def watch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    run_dir = Path(args.run_dir)
    if args.extend and args.deadline_reason is not None:
        raise SystemExit("use either --extend --reason or --deadline-reason")
    if args.extend:
        if not args.reason or not args.reason.strip():
            raise SystemExit("--extend requires a non-blank --reason")
        if args.deadline_minutes is None:
            raise SystemExit("--extend requires --deadline-minutes")
    if args.round_number is None or args.questions is None:
        parser.error("round watches require --round and --questions")
    read_run_state(run_dir)
    if args.round_number < 1:
        parser.error("--round must be >= 1")
    if args.questions < 1:
        raise SystemExit("--questions must be >= 1")
    lanes = parse_lanes(args)
    surfaces = parse_lane_surfaces(args.lane_surface, lanes)
    if any(surface.startswith("surface:") for surface in surfaces.values()):
        parser.error("round watch requires stable surface UUIDs, not positional surface:N refs")
    events = read_events(run_dir)
    extended = any(
        event.get("type") == "worker.waiting"
        and event.get("data", {}).get("round") == args.round_number
        and (event.get("data", {}).get("outcome") == "extension_approved"
             or event.get("data", {}).get("watch_clock", {}).get("extension") == 1)
        for event in events
    )
    if args.extend and extended:
        raise SystemExit("deadline extension already recorded for this round")
    reports = {lane: report_path(run_dir, args.round_number, lane) for lane in lanes}
    deadline_minutes = args.deadline_minutes if args.deadline_minutes is not None else round_wait_minutes(args.questions)
    # File-only mode (no lane surfaces) never shells out, so it needs no workspace.
    cmd = health_command(args, parser) if surfaces else []
    start = time.monotonic()
    identity = {"round": args.round_number, "lanes": sorted(lanes), "surface_ids": surfaces}
    launches = {lane: current_launch(events, lane, surfaces.get(lane), args.round_number) for lane in lanes}
    reason = args.reason if args.extend else args.deadline_reason
    def record_clock(data):
        # A legacy reason can replay its persisted clock, but changing the lane
        # subset or recovering a start must not buy another round extension.
        if reason is not None and extended:
            raise ValueError("deadline extension already recorded for this round")
        waiting_event(run_dir, "round deadline recorded", {
            **identity, "delivered_lanes": [], "missing_lanes": lanes,
            "elapsed_seconds": 0, "deadline_minutes": deadline_minutes, **data})
    clock = round_clock(events, identity, launches, deadline_minutes, args.start_minutes, reason, record_clock)
    if reason is not None and not extended:
        waiting_event(run_dir, "deadline extension approved", {
            "round": args.round_number, "lanes": lanes,
            "outcome": "extension_approved", "extension": 1, "reason": reason,
        })
        extended = True
    deadline, start_deadline = monotonic_deadlines(clock)
    deadline_minutes = clock["minutes"]
    next_health = start
    next_heartbeat = start + args.heartbeat_seconds
    health_status, health_detail, dead_lanes = "unchecked", "", []

    started_lanes = []

    def progress() -> list[str]:
        events = read_events(run_dir)
        started_lanes.clear()
        done = []
        # File-only use with no launch history is retained for offline report capture.
        offline = not surfaces and not any(e.get("type") in ("worker.starting", "worker.launch_sent", "pane.launched") for e in events)
        started_ids = {e.get("data", {}).get("launch_id") for e in events if e.get("type") == "worker.started"}
        for lane in lanes:
            launch = current_launch(events, lane, surfaces.get(lane), args.round_number)
            report = fresh_report(reports[lane], launch) if launch or offline else False
            if report:
                done.append(lane)
            if offline:
                started_lanes.append(lane)
                continue
            if not launch:
                continue
            if launch["launch_id"] in started_ids:
                started_lanes.append(lane)
                continue
            marker = round_marker_path(run_dir, args.round_number, lane)
            try:
                marked = marker.is_file() and marker.stat().st_mtime_ns >= launch["start_time_ns"]
            except FileNotFoundError:
                marked = False
            if marked or report:
                append_jsonl(run_dir / "events.jsonl", {
                    "time": utc_now(), "type": "worker.started", "message": "round start evidence captured",
                    "data": {"lane": lane, "round": args.round_number, "surface_id": launch["surface_id"],
                             "launch_id": launch["launch_id"], "evidence": "marker" if marked else "report",
                             "marker_path": str(marker)},
                })
                started_lanes.append(lane)
        return done

    def base_data(done: list[str]) -> dict:
        pending = [lane for lane in lanes if lane not in done]
        return {
            "round": args.round_number,
            "lanes": lanes,
            "started_lanes": list(started_lanes),
            "not_started": [lane for lane in lanes if lane not in started_lanes],
            "delivered_lanes": done,
            "missing_lanes": pending,
            "surface_ids": surfaces,
            "elapsed_seconds": round(time.monotonic() - start, 1),
            "deadline_minutes": deadline_minutes,
            **({"extension": 1} if extended else {}),
            "health": health_status,
        }

    def finish(outcome: str, code: int, message: str, done: list[str]) -> int:
        data = base_data(done)
        data["outcome"] = outcome
        if dead_lanes:
            data["dead_lanes"] = dead_lanes
        if health_detail:
            data["health_detail"] = health_detail
        waiting_event(run_dir, message, data)
        print(
            f"outcome={outcome} round={args.round_number} "
            f"elapsed_seconds={data['elapsed_seconds']} "
            f"started={join(data['started_lanes'])} not_started={join(data['not_started'])} "
            f"delivered={join(data['delivered_lanes'])} "
            f"missing={join(data['missing_lanes'])} dead={join(dead_lanes)}"
        )
        return code

    while True:
        done = progress()
        pending = [lane for lane in lanes if lane not in done]
        if not pending:
            return finish("reports", EXIT_REPORTS, f"all {len(lanes)} lane reports captured", done)
        now = time.monotonic()
        # Health only for lanes still owing a report: a lane whose pane exits right after
        # writing its report has delivered, and must not read as a dead pane.
        pending_surfaces = {lane: surfaces[lane] for lane in pending if lane in surfaces}
        if pending_surfaces and now >= next_health:
            health_status, dead_lanes, health_detail = check_health(cmd, pending_surfaces)
            next_health = now + args.health_interval_seconds
            if health_status == "dead":
                return finish("pane_dead", EXIT_PANE_DEAD, f"lane pane dead: {health_detail}", done)
        if now >= deadline:
            return finish("deadline", EXIT_DEADLINE, f"deadline of {deadline_minutes} minutes exceeded", done)
        if len(started_lanes) < len(lanes) and now >= start_deadline:
            return finish("not_started", EXIT_NOT_STARTED, "round start window elapsed", done)
        if now >= next_heartbeat:
            waiting_event(run_dir, "lane reports pending; lanes still running", base_data(done))
            next_heartbeat = now + args.heartbeat_seconds
        wake = min(deadline, start_deadline) if len(started_lanes) < len(lanes) else deadline
        time.sleep(min(args.poll_seconds, max(wake - time.monotonic(), 0.01)))


def main() -> int:
    parser = build_parser()
    try:
        return watch(parser.parse_args(), parser)
    except ValueError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
