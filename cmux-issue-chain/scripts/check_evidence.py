#!/usr/bin/env python3
"""Verify own and cited wrapper logs against stage launch and capture trees.

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
from await_report import report_path
from parse_report import ADVANCE, EXIT_CODES, STOP, parse_report, pending_payload, split_sections, tests_section
from render_prompt import tracker_ground_rules
from run_check import repository_root
from check_commands import applicable_commands
from evidence_contract import (
    CAPTURE, LAUNCH, EVIDENCE_EXEMPT_STAGES, TEST_EVIDENCE_EVENT, read_events, snapshot_label,
)


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


def cited_paths(report_text: str) -> list[str]:
    checks = tests_section(split_sections(report_text))
    return list(dict.fromkeys(re.findall(r"^[ \t]*[-*][ \t]+cited:[ \t]*`?(.*?)`?[ \t]*$", checks, re.MULTILINE)))


def differences(log: dict, identity: dict) -> list[str]:
    differed = []
    if log["repository"] != identity["repository"]:
        differed.append("repository")
    for key, name in (("head", "HEAD"), ("fingerprint", "fingerprint")):
        if any(log[f"{key}_{when}"] != identity[key] for when in ("before", "after")):
            differed.append(name)
    return differed


def evidence_result(command: str, logs: list[dict], identity: dict, phase: str) -> dict:
    candidates = []
    for log in logs:
        if log["command"] != command:
            continue
        differed = differences(log, identity)
        verdict = "red" if log["exit_code"] else "stale" if differed else "pass"
        candidates.append({"verdict": verdict, "differed": differed,
                           "cited": log["cited"], "log": log})
    # A valid repeat supersedes all earlier attempts.
    chosen = min(candidates, key=lambda item: (item["verdict"] != "pass",
                                              bool(item["differed"])), default=None)
    return {"command": command, "phase": phase,
            **(chosen or {"verdict": "missing", "cited": False})}


def check_evidence(run_dir: Path, stage: str, pass_num: int, repository: Path,
                   report_text: str = "") -> dict:
    state = read_run_state(run_dir)
    tracker = Path(state["deliverables"]["tracker"])
    if not tracker.is_absolute():
        tracker = repository / tracker
    commands = applicable_commands(tracker_ground_rules(tracker), stage, require_canonical=True)
    events = read_events(run_dir)

    def snapshot(prefix):
        label = snapshot_label(prefix, stage, pass_num)
        matches = [event for event in events
                   if event.get("type") == "tree.snapshot" and event.get("message") == label]
        if not matches:
            raise ValueError(f"missing snapshot: {label}")
        event = matches[-1]
        return {"label": label, "time": event["time"], "repository": str(repository),
                "head": event["data"]["head"], "fingerprint": event["data"]["fingerprint"]}

    capture = snapshot(CAPTURE)
    preparation = next((event["data"] for event in reversed(events)
                        if event.get("type") == "stage.prepared"
                        and event.get("data", {}).get("stage") == stage
                        and event.get("data", {}).get("pass") == pass_num), {})
    # stage.prepared records the immutable snapshot's marker. Older preparations have
    # no marker and retain the regular implement contract, regardless of pass number.
    needs_before = stage == "simplify" or (
        stage == "implement" and preparation.get("followup") is True)
    launch = snapshot(LAUNCH) if needs_before or stage == "review" else None
    unchanged_review = stage == "review" and all(
        launch[key] == capture[key] for key in ("head", "fingerprint"))
    citations = cited_paths(report_text)
    citation_refusal = (None if needs_before or unchanged_review
                        else "review changed the tree; own logs required" if stage == "review"
                        else "citations are not allowed for this stage")
    own, cited, invalid = [], [], []
    artifact_root = (run_dir / "artifacts").resolve()
    own_dir = artifact_root / f"{stage}-{pass_num}"

    def load(path, citation=None):
        is_cited = citation is not None
        tag = {"citation": citation} if is_cited else {}
        try:
            resolved = path.resolve()
            # Both own and cited logs must remain inside their artifact boundary.
            relative = resolved.relative_to(artifact_root if is_cited else own_dir)
            if is_cited and len(relative.parts) < 2:
                raise ValueError("citation must be inside a stage artifact directory")
            (cited if is_cited else own).append({**read_log(resolved), "cited": is_cited, **tag})
        except (OSError, ValueError, KeyError) as error:
            invalid.append({"path": str(path), "cited": is_cited, "error": str(error), **tag})

    for path in sorted(own_dir.glob("check-*.log")):
        load(path)
    for citation in citations if not citation_refusal else ():
        path = Path(citation)
        if path.is_absolute() or not citation:
            invalid.append({"path": citation, "citation": citation, "cited": True,
                            "error": "citation must be relative to the run directory"})
        else:
            load(run_dir / path, citation)

    if needs_before:
        # Own logs from the capture tree are after-evidence, not stale before-runs.
        own_before = [log for log in own if not differences(log, launch)]
    results = []
    for command in commands:
        after_logs = own
        if needs_before:
            # A cited command takes its before evidence from citations only; others may use own before-runs.
            cited_command = [log for log in cited if log["command"] == command]
            before = evidence_result(command, cited_command or own_before, launch, "before")
            results.append(before)
            # Even a no-op pass must supply a distinct own after-run.
            if "log" in before:
                after_logs = [log for log in own if log["path"] != before["log"]["path"]]
        elif unchanged_review:
            after_logs = own + cited
        results.append(evidence_result(command, after_logs, capture, "after"))
    # A forbidden or unreadable citation cannot be silently rescued by own logs.
    rejected = ([{"citation": path, "error": citation_refusal}
                 for path in citations] if citation_refusal else [])
    rejected += [item for item in invalid if item["cited"]]
    for citation in rejected:
        for command in commands:
            results.append({"command": command, "phase": "citation", "verdict": "missing",
                            "cited": True, **citation})
    return {"stage": stage, "pass": pass_num, "capture": capture, "launch": launch,
            "results": results,
            "checked_logs": [log for log in own + cited if log["command"] in commands],
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
        report_text = ""
        if args.report:
            if args.report.is_file():
                report_text = args.report.read_text()
                gate = parse_report(report_text)["gate"]
            else:
                gate = pending_payload(args.report)["gate"]
        if args.stage in EVIDENCE_EXEMPT_STAGES:
            print(f"verdict=exempt gate={gate}")
            return EXIT_CODES[gate]
        if not args.report:
            default_report = report_path(args.run_dir, args.stage, args.pass_num)
            report_text = default_report.read_text() if default_report.is_file() else ""
        data = check_evidence(args.run_dir, args.stage, args.pass_num, repository, report_text)
        if data["verdict"] != "pass" and gate == ADVANCE:
            gate = STOP
        data["gate"] = gate
        # Usage counts only this invocation, never the worker commands in checked_logs.
        invocation = [sys.executable, str(Path(__file__).resolve()),
                      *(sys.argv[1:] if argv is None else argv)]
        data["commands"] = [shlex.join(invocation)]
        append_jsonl(args.run_dir / "events.jsonl", {"time": utc_now(),
                     "type": TEST_EVIDENCE_EVENT[0], "message": TEST_EVIDENCE_EVENT[1], "data": data})
        print(f"verdict={data['verdict']} gate={gate}")
        for item in data["results"]:
            detail = ""
            if item["verdict"] == "red":
                detail = f" exit_code={item['log']['exit_code']}"
            elif item["verdict"] == "stale":
                detail = " differed=" + ",".join(item["differed"])
            source = "cited" if item["cited"] else "own"
            citation = f" citation={item['citation']}" if "citation" in item else ""
            print(f"{item['verdict']}: {item['command']}{detail} phase={item['phase']} source={source}{citation}")
        for item in data["invalid_logs"]:
            print(f"invalid log: {item['path']}: {item['error']}")
        return EXIT_CODES[gate]
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"check_evidence: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
