#!/usr/bin/env python3
"""Inspect local Markdown issue state and blocker readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator_lib import TrackerFormatError, blocker_status, issue_ready, load_issues, read_issue_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "ready", "show"])
    parser.add_argument("--tracker", required=True, help="Tracker directory, e.g. .scratch/<tracker>")
    parser.add_argument("--issue", help="Issue id for show")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tracker = Path(args.tracker)
    try:
        issues = load_issues(tracker)
    except TrackerFormatError as error:
        print(f"Tracker preflight failed: {error}", file=sys.stderr)
        return 1

    if args.command == "list":
        rows = []
        for issue in issues.values():
            gate = blocker_status(issue, issues)
            rows.append({**issue.to_dict(), **gate, "ready": issue_ready(issue, issues)})
        emit(rows, args.json)
        return 0

    if args.command == "ready":
        rows = []
        for issue in issues.values():
            if issue_ready(issue, issues):
                rows.append({**issue.to_dict(), **blocker_status(issue, issues), "ready": True})
        emit(rows, args.json)
        return 0

    if args.command == "show":
        if not args.issue:
            raise SystemExit("--issue is required for show")
        issue, markdown = read_issue_markdown(tracker, args.issue)
        payload = {
            **issue.to_dict(),
            **blocker_status(issue, issues),
            "ready": issue_ready(issue, issues),
            "markdown": markdown,
        }
        emit(payload, args.json)
        return 0

    raise AssertionError(args.command)


def emit(payload, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if isinstance(payload, list):
        for row in payload:
            blockers = ", ".join(item["id"] for item in row.get("blockers", [])) or "None"
            print(
                f"{row['id']}\t{row['status']}\t{row['progress']}\t"
                f"{row['type']}\tready={row.get('ready', False)}\tblocked_by={blockers}\t{row['title']}"
            )
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
