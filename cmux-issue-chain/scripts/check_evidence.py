#!/usr/bin/env python3
"""Verify a stage's own wrapper logs against its report-captured tree.

Run from the repository root with --run-dir, --stage, --pass and optionally
--report. Only events.jsonl is appended; checks are never executed here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys

from orchestrator_lib import ROLE_LABELS, append_jsonl, read_run_state, utc_now
from parse_report import ADVANCE, EXIT_CODES, STOP, parse_report, pending_payload
from render_prompt import tracker_ground_rules
from run_check import repository_root


def canonical_commands(tracker: Path) -> list[str]:
    rules = tracker_ground_rules(tracker)
    label = re.search(
        r"^[-*] Canonical check commands(?:, run as the baseline suite by every worker)?:\s*$",
        rules, re.MULTILINE,
    )
    if not label:
        raise ValueError("tracker ground rules have no canonical check commands")
    commands = []
    for line in rules[label.end():].splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s+[-*]\s+`(.+)`\s*", line)
        if not match:
            break
        commands.append(match[1])
    if not commands or any("<TODO" in command for command in commands):
        raise ValueError("tracker canonical check commands are empty or contain placeholders")
    return list(dict.fromkeys(commands))


def read_log(path: Path) -> dict:
    """Read only the bounded v1 header, never runner output or report prose."""
    fields = {}
    with path.open("rb") as stream:
        for _ in range(10):
            line = stream.readline(65537)
            if line == b"---\n":
                break
            if len(line) > 65536 or not line.endswith(b"\n"):
                raise ValueError("incomplete or oversized header")
            key, value = line.decode("utf-8").rstrip("\n").split(": ", 1)
            if key in fields:
                raise ValueError("duplicate header field")
            fields[key] = value
        else:
            raise ValueError("missing header separator")
    if fields.pop("evidence_version", None) != "1":
        raise ValueError("unsupported evidence version")
    for key in ("command", "repository"):
        fields[key] = json.loads(fields[key])
        if not isinstance(fields[key], str) or not fields[key]:
            raise ValueError(f"invalid {key}")
    fields["exit_code"] = int(fields["exit_code"])
    fields["duration_seconds"] = float(fields["duration_seconds"])
    if not 0 <= fields["exit_code"] <= 255:
        raise ValueError("invalid exit code")
    if not math.isfinite(fields["duration_seconds"]) or fields["duration_seconds"] < 0:
        raise ValueError("invalid duration")
    for when in ("before", "after"):
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", fields[f"head_{when}"]):
            raise ValueError("invalid HEAD")
        if not re.fullmatch(r"[0-9a-f]{16}", fields[f"fingerprint_{when}"]):
            raise ValueError("invalid fingerprint")
    return {"path": str(path), **fields}


def check_evidence(run_dir: Path, stage: str, pass_num: int, repository: Path) -> dict:
    state = read_run_state(run_dir)
    tracker = Path(state["deliverables"]["tracker"])
    if not tracker.is_absolute():
        tracker = repository / tracker
    commands = canonical_commands(tracker)
    label = f"report-captured {stage}-{pass_num}"
    events_path = run_dir / "events.jsonl"
    lines = events_path.read_text().splitlines() if events_path.is_file() else []
    captures = []
    for line in lines:
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("events.jsonl holds a non-object line")
        if event.get("type") == "tree.snapshot" and event.get("message") == label:
            captures.append(event)
    if not captures:
        raise ValueError(f"missing snapshot: {label}")
    capture = captures[-1]
    identity = {"repository": str(repository), "head": capture["data"]["head"],
                "fingerprint": capture["data"]["fingerprint"]}
    logs, invalid = [], []
    for path in sorted((run_dir / "artifacts" / f"{stage}-{pass_num}").glob("check-*.log")):
        try:
            logs.append(read_log(path))
        except (OSError, ValueError, KeyError) as error:
            invalid.append({"path": str(path), "error": str(error)})
    results = []
    for command in commands:
        candidates = []
        for log in logs:
            if log["command"] != command:
                continue
            differed = []
            if log["repository"] != identity["repository"]:
                differed.append("repository")
            for key, name in (("head", "HEAD"), ("fingerprint", "fingerprint")):
                if any(log[f"{key}_{when}"] != identity[key] for when in ("before", "after")):
                    differed.append(name)
            verdict = "red" if log["exit_code"] else "stale" if differed else "pass"
            candidates.append({"verdict": verdict, "differed": differed, "log": log})
        # A valid repeat supersedes all earlier attempts, including before-runs.
        chosen = min(candidates, key=lambda item: (item["verdict"] != "pass",
                                                  bool(item["differed"])), default=None)
        results.append({"command": command, **(chosen or {"verdict": "missing"})})
    return {"stage": stage, "pass": pass_num, "capture": {"label": label,
            "time": capture["time"], **identity}, "results": results,
            "checked_logs": [log for log in logs if log["command"] in commands],
            "invalid_logs": invalid,
            "verdict": "pass" if all(item["verdict"] == "pass" for item in results) else "fail"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=tuple(ROLE_LABELS), required=True)
    parser.add_argument("--pass", dest="pass_num", type=int, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.pass_num < 1:
        parser.error("--pass must be positive")
    try:
        repository = repository_root()
        if Path.cwd().resolve() != repository.resolve():
            raise ValueError("invoke check_evidence.py from the repository root")
        gate = ADVANCE
        if args.report:
            report = (parse_report(args.report.read_text()) if args.report.is_file()
                      else pending_payload(args.report))
            gate = report["gate"]
        if args.stage == "triage":
            print(f"verdict=exempt gate={gate}")
            return EXIT_CODES[gate]
        data = check_evidence(args.run_dir, args.stage, args.pass_num, repository)
        if data["verdict"] != "pass" and gate == ADVANCE:
            gate = STOP
        data["gate"] = gate
        # Usage counts only this invocation, never the worker commands in checked_logs.
        invocation = [sys.executable, str(Path(__file__).resolve()),
                      *(sys.argv[1:] if argv is None else argv)]
        data["commands"] = [shlex.join(invocation)]
        append_jsonl(args.run_dir / "events.jsonl", {"time": utc_now(),
                     "type": "orchestrator.verified", "message": "test evidence", "data": data})
        print(f"verdict={data['verdict']} gate={gate}")
        for item in data["results"]:
            detail = ""
            if item["verdict"] == "red":
                detail = f" exit_code={item['log']['exit_code']}"
            elif item["verdict"] == "stale":
                detail = " differed=" + ",".join(item["differed"])
            print(f"{item['verdict']}: {item['command']}{detail}")
        for item in data["invalid_logs"]:
            print(f"invalid log: {item['path']}: {item['error']}")
        return EXIT_CODES[gate]
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"check_evidence: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
