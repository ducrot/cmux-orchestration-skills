"""Resumable watcher clocks, vendored for independent skill installations.

The event log is the durable clock: a single armed watcher owns waiting events.
Wall-clock deadlines survive process/host restarts; monotonic clocks handle polling.
"""
from __future__ import annotations

import hashlib
import json
import math
import stat
import time
from pathlib import Path


def wait_key(events: list[dict], scope: dict, targets: list[dict]) -> str:
    generations = []
    for target in targets:
        generation = []
        recovery_pending = False
        for index, event in enumerate(events):
            data = event.get("data", {})
            kind = event.get("type")
            matches = all(data.get(k) == v for k, v in target.items())
            # Session watches emit one exit-9 event naming every pending lane.
            session_timeout = (kind == "worker.waiting" and data.get("session")
                               and target.get("lane") in data.get("not_started", [])
                               and data.get("surface_ids", {}).get(target.get("lane"))
                               == target.get("surface_id"))
            if not matches and not session_timeout:
                continue
            if kind == "worker.launch_sent":
                generation = [(kind, data.get("launch_id"), index)]
                recovery_pending = False
            elif kind == "worker.waiting" and data.get("outcome") == "not_started":
                recovery_pending = True
            elif kind == "worker.prompt_sent":
                generation.append((kind, index))
                recovery_pending = False
            elif recovery_pending and (kind == "worker.dialog_response" or (
                kind == "worker.started" and data.get("evidence") == "screen"
            )):
                generation.append((kind, index))
                recovery_pending = False
        generations.append([target, generation])
    return hashlib.sha256(json.dumps([scope, generations], sort_keys=True).encode()).hexdigest()


def arm(events: list[dict], key: str, minutes: float, start_minutes: float,
        reason: str | None, emit) -> dict:
    """Persist first arm or one reasoned extension; replaying either is idempotent.

    Initial overrides remain useful for smoke tests. Later duration flags alone never
    move a deadline. An extension grants its duration from the first extension arm.
    """
    if not all(math.isfinite(n) and n >= 0 for n in (minutes, start_minutes)):
        raise ValueError("wait durations must be finite and non-negative")
    previous = [e["data"]["watch_clock"] for e in events
                if e.get("type") == "worker.waiting"
                and e.get("data", {}).get("watch_clock", {}).get("key") == key]
    if previous:
        clock, changed = dict(previous[-1]), False
    else:
        now = time.time()
        clock = {
            "key": key, "armed_at": now, "minutes": minutes, "start_minutes": start_minutes,
            "extension": 0, "deadline": now + minutes * 60,
            "start_deadline": now + start_minutes * 60,
        }
        changed = True
    if reason is not None:
        if not reason.strip():
            raise ValueError("deadline extension requires a non-empty reason")
        if clock["extension"]:
            if reason != clock["reason"] or minutes != clock["minutes"]:
                raise ValueError("the one deadline extension is already recorded")
        else:
            clock.update(extension=1, reason=reason, minutes=minutes,
                         deadline=max(clock["deadline"], time.time()) + minutes * 60)
            changed = True
    if changed:
        emit({"watch_clock": clock, "outcome": "armed", "extension": clock["extension"]})
    return clock


def monotonic_deadlines(clock: dict) -> tuple[float, float]:
    offset = time.monotonic() - time.time()
    return clock["deadline"] + offset, clock["start_deadline"] + offset


def fresh_report(path: Path, launch: dict | None) -> bool:
    try:
        info = path.stat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size > 0 and (
        not launch or isinstance(launch.get("start_time_ns"), int)
        and info.st_mtime_ns >= launch["start_time_ns"])
