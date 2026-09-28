#!/usr/bin/env python3
"""Record validated commit proposals without changing Git's index or HEAD."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import subprocess

from orchestrator_lib import append_jsonl, read_json, utc_now

DONE_STAGES = {"issue-chain": "done", "planning": "complete", "grilling": "done"}
WORKFLOW_KEYS = {"issue-chain": ("product_files", "tracker_files"), "grilling": ("unresolved",), "planning": ()}
OUTCOMES = {"commit.attempted", "commit.failed", "commit.skipped", "commit.created"}


def git(root, *args, input=None, allowed=(0,), literal=True):
    result = subprocess.run(["git", *(["--literal-pathspecs"] if literal else []), "-C", str(root), *args],
                            input=input, capture_output=True)
    if result.returncode not in allowed:
        raise ValueError(os.fsdecode(result.stderr).strip())
    return result.stdout


def repository_root(directory):
    return Path(os.fsdecode(git(directory, "rev-parse", "--show-toplevel")).removesuffix("\n"))


def porcelain_entries(raw: bytes) -> list[tuple[str, bytes]]:
    """Fail closed on malformed porcelain, retaining rename/copy source paths."""
    *body, tail = raw.split(b"\0")
    tokens = iter(body)
    entries = []
    for token in tokens:
        if (len(token) < 4 or token[2:3] != b" "
                or any(char not in b" MADRCUT?!" for char in token[:2])
                or token[:2] == b"  "):
            raise ValueError("git status returned an unparseable porcelain entry")
        code = token[:2].decode("ascii")
        entries.append((code, token[3:]))
        if b"R" in token[:2] or b"C" in token[:2]:
            source = next(tokens, b"")
            if not source:
                raise ValueError("git status rename/copy entry is incomplete")
            entries.append((code, source))
    if tail:
        raise ValueError("git status returned an incomplete porcelain entry")
    return entries


def capture_baseline(directory):
    root = repository_root(directory)
    head = git(root, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)).strip()
    entries = porcelain_entries(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
    return {"head": head.decode() or None, "captured_at": utc_now(),
            "paths": sorted({os.fsdecode(path) for _, path in entries})}


def normalized_paths(values, flag):
    for path in values:
        if (not path or "\0" in path or posixpath.isabs(path) or path == "."
                or path != posixpath.normpath(path) or ".." in path.split("/")
                or ".git" in path.split("/")):
            raise ValueError(f"{flag}: invalid literal path {path!r}")
        if values.count(path) > 1:
            raise ValueError(f"{flag}: duplicated path {path!r}")
    return sorted(values)


def validate_leaf(root, path):
    try:
        mode = os.lstat(root / path).st_mode
    except FileNotFoundError:
        raw = git(root, "ls-tree", "-z", "HEAD", "--", path, allowed=(0, 128))
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, kind, _ = metadata.split(b" ")
            if name == os.fsencode(path) and kind == b"blob" and mode in (b"100644", b"100755", b"120000"):
                return
    else:
        if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            return
    raise ValueError(f"--file: not a literal leaf file: {path!r}")


def propose(args, run_dir):
    state = read_json(run_dir / "state.json")
    workflow = state["workflow"]
    if workflow not in DONE_STAGES or state.get("current_stage") != DONE_STAGES[workflow]:
        raise ValueError(f"run {state['run_id']} is not complete")
    if not args.subject.strip() or len(args.subject.splitlines()) != 1 or "\r" in args.subject or "\n" in args.subject:
        raise ValueError(f"--subject must be one line: {args.subject!r}")
    draft = {"subject": args.subject, "body": args.body}
    for key in ("files", "ride_along", "product_files", "tracker_files"):
        draft[key] = normalized_paths(getattr(args, key), key)
    draft["unresolved"] = sorted(args.unresolved)
    for key in ("product_files", "tracker_files"):
        if not set(draft[key]) <= set(draft["files"]):
            raise ValueError(f"{key} must be a subset of --file: {draft[key]!r}")
    if set(draft["ride_along"]) & set(draft["files"]):
        raise ValueError(f"--ride-along must be excluded from --file: {draft['ride_along']!r}")
    for key in ("product_files", "tracker_files", "unresolved"):
        if draft[key] and key not in WORKFLOW_KEYS[workflow]:
            raise ValueError(f"{key} is not accepted for workflow {workflow}")
    proposal_id = hashlib.sha256(json.dumps(draft, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    events_path = run_dir / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()] if events_path.exists() else []
    latest = next((e["data"] for e in reversed(events) if e.get("type") == "commit.proposed"), None)
    if latest and latest.get("proposal_id") == proposal_id:
        return latest
    if any(e.get("type") in OUTCOMES for e in events):
        raise ValueError(f"run {state['run_id']} already has a commit outcome or attempt; the proposal cannot change")
    root = repository_root(state["repository"] if workflow == "planning" else state.get("working_directory", os.getcwd()))
    message = args.subject + "\n\n" + args.body
    for line in message.splitlines():
        if re.match(r"^\s*co-authored-by:", line, re.IGNORECASE):
            raise ValueError(f"message: trailer line is not allowed: {line!r}")
    trailers = git(root, "interpret-trailers", "--parse", input=message.encode()).strip()
    if trailers:
        raise ValueError(f"message: trailer lines are not allowed: {os.fsdecode(trailers)!r}")
    files = draft["files"]
    if workflow == "grilling":
        deliverables = [Path(state["deliverables"][key]) for key in ("markdown", "json")]
        expected = sorted(os.path.relpath(path.parent.resolve() / path.name, root) for path in deliverables)
        if files != expected:
            raise ValueError(f"--file must equal recorded grilling deliverables: {files!r}; expected {expected!r}")
    if workflow == "planning":
        published = state.get("published_tracker") or {}
        target = Path(published.get("path", ""))
        target = (target if target.is_absolute() else root / target).resolve()
        if not published.get("path") or any(not (root / path).is_relative_to(target) or root / path == target for path in files):
            raise ValueError(f"--file must lie under published_tracker.path: {files!r}")
    for path in files:
        validate_leaf(root, path)
    ignored = git(root, "check-ignore", "-z", "--stdin", input=b"".join(os.fsencode(p) + b"\0" for p in files),
                  allowed=(0, 1), literal=False)
    mode = "propose" if workflow == "issue-chain" and state.get("chain") == [] else state.get("commit_mode", "propose")
    data = {key: draft[key] for key in ("subject", "body", "files", "ride_along", *WORKFLOW_KEYS[workflow])}
    data.update(proposal_id=proposal_id, mode=mode,
                ignored=sorted(os.fsdecode(p) for p in ignored.split(b"\0") if p),
                preexisting=sorted(set(files) & set(state.get("commit_baseline", {}).get("paths", []))))
    append_jsonl(events_path, {"time": utc_now(), "type": "commit.proposed", "message": args.subject, "data": data})
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    proposal = sub.add_parser("propose")
    proposal.add_argument("--run-dir", required=True)
    proposal.add_argument("--subject", required=True)
    proposal.add_argument("--body", default="")
    for flag, dest in (("file", "files"), ("ride-along", "ride_along"), ("product-file", "product_files"), ("tracker-file", "tracker_files"), ("unresolved", "unresolved")):
        proposal.add_argument("--" + flag, dest=dest, action="append", default=[], required=flag == "file")
    args = parser.parse_args()
    try:
        run_dir = Path(args.run_dir)
        with (run_dir / "commit.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(f"commit.lock is held for {run_dir}") from None
            print(json.dumps(propose(args, run_dir), sort_keys=True))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
