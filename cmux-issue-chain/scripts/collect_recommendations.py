#!/usr/bin/env python3
"""Collect immutable, numbered recommendations from one issue-chain run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from git_status import porcelain_entries
from orchestrator_lib import append_jsonl, read_run_state, utc_now
from worker_readiness import read_events

ROLES = ("implement", "simplify", "review", "test")
REPORT_RE = re.compile(rf'^({"|".join(ROLES)})-(\d+)\.md$')
ITEM_RE = re.compile(r"^## (R[1-9]\d*)\n", re.MULTILINE)
# Supported triage passes and their `Follow-up pass allowed` header value.
FOLLOWUP_ALLOWED = {1: "yes", 2: "no"}
UNSUPPORTED_PASS_ERROR = "only --pass 1 or 2 is supported"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section_bodies(text: str, name: str) -> list[str]:
    """Keep section content bytes (including continuation indentation) intact."""
    matches = list(re.finditer(r"^## .*(?:\n|$)", text, re.MULTILINE))
    return [text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
            for i, m in enumerate(matches) if m.group().strip() == f"## {name}"]


def entries(body: str) -> list[str]:
    from parse_report import is_noneish
    if is_noneish(body):
        return []
    starts = [m.start() for m in re.finditer(r"^(?:[-*+] |\d+\. )", body, re.MULTILINE)]
    if not starts or body[:starts[0]].strip():
        starts.insert(0, 0)
    return [body[a:b] for a, b in zip(starts, starts[1:] + [len(body)]) if body[a:b].strip()]


def read_items(path: Path) -> dict:
    """Shared collector grammar reader for rendering, gating, and publication."""
    text = path.read_text(encoding="utf-8")
    matches = list(ITEM_RE.finditer(text))
    header = text[:matches[0].start()] if matches else text
    fields = {}
    for key in ("Run", "Issue", "Triage pass", "Follow-up pass allowed", "Scanned reports", "Issue diff files"):
        match = re.search(r"^" + re.escape(key) + r": (.*)$", header, re.MULTILINE)
        if not match:
            raise ValueError(f"{path}: missing {key}")
        fields[key] = match.group(1)
    try:
        pass_num = int(fields["Triage pass"])
        scanned = json.loads(fields["Scanned reports"])
        files = json.loads(fields["Issue diff files"])
    except (ValueError, TypeError) as error:
        raise ValueError(f"{path}: invalid items header") from error
    if fields["Follow-up pass allowed"] != FOLLOWUP_ALLOWED.get(pass_num):
        raise ValueError(f"{path}: triage pass must be 1 (follow-up allowed) or 2 (no follow-up)")
    if not all(isinstance(v, list) and all(isinstance(p, str) for p in v) for v in (scanned, files)):
        raise ValueError(f"{path}: invalid report/file list")
    items = []
    for i, match in enumerate(matches):
        block = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
        metadata = re.match(r"Source: ([^\n]+) \(([^\n]+)\)\nKind: (recommendation|counter-proposal)\n\n", block)
        if not metadata or match.group(1) != f"R{i+1}":
            raise ValueError(f"{path}: malformed item {match.group(1)}")
        items.append({"id": match.group(1), "source": metadata[1], "report": metadata[2],
                      "kind": metadata[3], "text": block[metadata.end():]})
    if not items:
        raise ValueError(f"{path}: no items")
    return {"run": fields["Run"], "issue": fields["Issue"], "pass": pass_num,
            "followup_allowed": FOLLOWUP_ALLOWED[pass_num] == "yes", "scanned_reports": scanned, "diff_files": files, "items": items}


def collected_data(run_dir: Path, pass_num: int) -> dict | None:
    matches = [e["data"] for e in read_events(run_dir)
               if e.get("type") == "triage.collected" and e.get("data", {}).get("pass") == pass_num]
    path = run_dir / f"triage-items-{pass_num}.md"
    if len(matches) > 1:
        raise ValueError("multiple triage.collected events for pass")
    if not matches:
        if path.exists():
            raise ValueError("items file exists without a matching triage.collected event")
        return None
    data = matches[0]
    if data["item_count"] == 0:
        if path.exists() or data.get("items_sha256") is not None or data.get("items_path") is not None:
            raise ValueError("zero-item collection does not match items file")
    elif Path(data.get("items_path") or "").name != path.name or not path.is_file() or sha256(path) != data.get("items_sha256"):
        raise ValueError("items SHA-256 does not match triage.collected event")
    return data


def diff_files() -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                            capture_output=True, check=True)
    return sorted({os.fsdecode(path) for _, path in porcelain_entries(result.stdout)})


def collect(run_dir: Path, pass_num: int) -> dict:
    if pass_num not in FOLLOWUP_ALLOWED:
        raise ValueError(UNSUPPORTED_PASS_ERROR)
    state = read_run_state(run_dir)
    existing = collected_data(run_dir, pass_num)
    if existing is not None:
        return existing
    matched = [(m, p) for p in (run_dir / "reports").glob("*.md") if (m := REPORT_RE.fullmatch(p.name))]
    reports = [p for _, p in sorted(matched, key=lambda mp: (int(mp[0][2]), ROLES.index(mp[0][1])))]
    pending = reports
    if pass_num == 2:
        prior = collected_data(run_dir, 1)
        if not prior or not prior["item_count"]:
            raise ValueError("pass 2 requires nonempty triage-items-1.md")
        # Reports belong to this run; their basenames survive relative/absolute CLI spelling.
        scanned_names = {Path(path).name for path in prior["scanned_reports"]}
        pending = [p for p in reports if p.name not in scanned_names]
    contents = {p.stem: p.read_text(encoding="utf-8") for p in reports}
    items = []
    for path in pending:
        for body in section_bodies(contents[path.stem], "Recommendations"):
            for entry in entries(body):
                kind = "counter-proposal" if "Counter-proposal" in entry else "recommendation"
                attachment = ""
                if kind == "counter-proposal":
                    named = [p for p in reports if re.search(r"(?<![\w-])" + re.escape(p.stem) + r"(?![\w-])", entry)]
                    if not named:
                        attachment = "Earlier decision: not resolved by the collector; see decisions.md and the run's reports\n"
                    for earlier in named:
                        attachment += f"Earlier decision: {earlier.stem}\n"
                        for section in section_bodies(contents[earlier.stem], "Not Applied"):
                            attachment += "## Not Applied\n" + section
                items.append(f"## R{len(items)+1}\nSource: {path.stem} ({path})\nKind: {kind}\n\n" + entry + "\n" + attachment)
    path = run_dir / f"triage-items-{pass_num}.md"
    data = {"pass": pass_num, "item_count": len(items), "scanned_reports": [str(p) for p in pending],
            "items_path": str(path) if items else None, "items_sha256": None}
    if items:
        header = (f'Run: {state["run_id"]}\nIssue: {state["issue"]["id"]}\nTriage pass: {pass_num}\n'
                  f'Follow-up pass allowed: {FOLLOWUP_ALLOWED[pass_num]}\nScanned reports: {json.dumps(data["scanned_reports"])}\n'
                  f"Issue diff files: {json.dumps(diff_files())}\n\n")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(header + "\n".join(items))
        data["items_sha256"] = sha256(path)
    append_jsonl(run_dir / "events.jsonl", {"time": utc_now(), "type": "triage.collected", "data": data})
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--pass", dest="pass_num", type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(Path(args.run_dir), args.pass_num), sort_keys=True))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
