#!/usr/bin/env python3
"""Record commit proposals and execute one verified commit per completed run."""
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


def git_result(root, *args, input=None, literal=True):
    # Do not pass the helper's literal-pathspec setting into repository hooks.
    env = dict(os.environ)
    if not literal:
        env.pop("GIT_LITERAL_PATHSPECS", None)
    return subprocess.run(["git", *(["--literal-pathspecs"] if literal else []), "-C", str(root), *args],
                          input=input, capture_output=True, env=env)


def git(root, *args, input=None, allowed=(0,), literal=True):
    result = git_result(root, *args, input=input, literal=literal)
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


def run_root(state):
    return repository_root(state["repository"] if state["workflow"] == "planning"
                           else state.get("working_directory", os.getcwd()))


def effective_mode(state):
    if state["workflow"] == "issue-chain" and state.get("chain") == []:
        return "propose"
    return state.get("commit_mode", "propose")


def head_sha(root):
    return git(root, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)).decode().strip() or None


def paths_from(raw):
    return sorted({os.fsdecode(path) for path in raw.split(b"\0") if path})


def ignored_paths(root, files):
    return paths_from(git(root, "check-ignore", "-z", "--stdin", input=b"".join(os.fsencode(p) + b"\0" for p in files),
                          allowed=(0, 1), literal=False))


def status_paths(root, *paths):
    entries = porcelain_entries(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths))
    return {os.fsdecode(path) for _, path in entries}


def read_events(run_dir):
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def last_data(events, kind):
    return next((e["data"] for e in reversed(events) if e.get("type") == kind), None)


def capture_baseline(directory):
    root = repository_root(directory)
    return {"head": head_sha(root), "captured_at": utc_now(), "paths": sorted(status_paths(root))}


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
    events = read_events(run_dir)
    latest = last_data(events, "commit.proposed")
    if latest and latest.get("proposal_id") == proposal_id:
        return latest
    if any(e.get("type") in OUTCOMES for e in events):
        raise ValueError(f"run {state['run_id']} already has a commit outcome or attempt; the proposal cannot change")
    root = run_root(state)
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
    data = {key: draft[key] for key in ("subject", "body", "files", "ride_along", *WORKFLOW_KEYS[workflow])}
    data.update(proposal_id=proposal_id, mode=effective_mode(state), ignored=ignored_paths(root, files),
                preexisting=sorted(set(files) & set(state.get("commit_baseline", {}).get("paths", []))))
    append_jsonl(run_dir / "events.jsonl", {"time": utc_now(), "type": "commit.proposed", "message": args.subject, "data": data})
    return data


def staged_paths(root):
    return git(root, "diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD")


def status_snapshot(root):
    entries = porcelain_entries(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
    snapshot = []
    for code, raw in entries:
        path = root / os.fsdecode(raw)
        try:
            mode = path.lstat().st_mode
            content = os.fsencode(os.readlink(path)) if stat.S_ISLNK(mode) else path.read_bytes() if stat.S_ISREG(mode) else None
        except OSError:
            content = None
        snapshot.append({"path": os.fsdecode(raw), "status": code,
                         "sha256": hashlib.sha256(content).hexdigest() if content is not None else None})
    return snapshot


def side_effects(before, after, committed=()):
    def by_path(entries):
        result = {}
        for entry in entries:
            result.setdefault(entry["path"], []).append((entry["status"], entry["sha256"]))
        return result
    old, new = by_path(before), by_path(after)
    return sorted(path for path in old.keys() | new.keys()
                  if old.get(path) != new.get(path)
                  and not (path in committed and path in old and path not in new))


def tree_blobs(root, tree, paths):
    entries = git(root, "ls-tree", "-r", "-z", tree, "--", *paths)
    return {os.fsdecode(name): metadata.split()[2]
            for entry in entries.split(b"\0") if entry
            for metadata, name in [entry.split(b"\t", 1)]}


def changed_paths(root, parent, head):
    return paths_from(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--no-renames", parent, head))


def parents_of(root, head):
    return git(root, "rev-list", "--parents", "-n", "1", head).decode().split()[1:] if head else []


def commit_subject(root, head):
    return os.fsdecode(git(root, "log", "-1", "--format=%s", head)).rstrip("\n")


def summary(output):
    return next((line.strip()[:120] for line in output.splitlines() if line.strip()), "Git command failed")


def command_output(result):
    return os.fsdecode(result.stdout + result.stderr)


def commit_context(run_dir):
    state = read_json(run_dir / "state.json")
    workflow = state["workflow"]
    events = read_events(run_dir)
    proposal = last_data(events, "commit.proposed")
    if effective_mode(state) != "commit":
        raise ValueError("this run only permits a commit proposal")
    if workflow not in DONE_STAGES or state.get("current_stage") != DONE_STAGES[workflow]:
        raise ValueError("run is not complete")
    if proposal is None or not state.get("commit_baseline"):
        raise ValueError("commit requires a proposal and commit_baseline")
    return state, events, proposal


def commit(args, run_dir):
    state, events, proposal = commit_context(run_dir)
    created = last_data(events, "commit.created")
    if created is not None:
        return created
    if any(e.get("type") in {"commit.failed", "commit.skipped"} for e in events):
        raise ValueError("run already has a commit outcome; no retry")
    root = run_root(state)

    def record(kind, **data):
        append_jsonl(run_dir / "events.jsonl", {"time": utc_now(), "type": "commit." + kind,
                                              "message": proposal["subject"], "data": data})
        return data

    def failed(reason, output="", **data):
        return record("failed", reason=reason, subject=proposal["subject"],
                      head=data.pop("head") if "head" in data else head_sha(root), output=output, **data)

    attempt = last_data(events, "commit.attempted")
    if attempt is not None:
        head = head_sha(root)
        parent, tree = attempt["parent"], attempt["tree"]
        if (head != parent and parents_of(root, head) == [parent]
                and git(root, "rev-parse", head + "^{tree}").decode().strip() == tree):
            files = changed_paths(root, parent, head)
            return record("created", sha=head, subject=commit_subject(root, head), files=files, recovered=True,
                          hook_modified=[], hook_side_effects=side_effects(attempt["pre_status"], status_snapshot(root), files))
        detail = "recovery-no-commit" if head == parent else "recovery-mismatch"
        return failed("unverifiable", detail=detail, head=head, parent=parent, tree=tree,
                      staged=paths_from(staged_paths(root)) if head else [])

    files = proposal["files"]
    ignored = ignored_paths(root, files)
    candidates = sorted(set(files) - set(ignored))
    if not candidates:
        return record("skipped", reason="all-ignored", ignored=ignored)
    parent = head_sha(root)
    if not parent:
        return failed("no-head", head=None)
    invalid, errors = [], []
    for path in candidates:
        try:
            validate_leaf(root, path)
        except (ValueError, OSError) as error:
            invalid.append(path)
            errors.append(str(error))
    if invalid:
        return failed("not-a-leaf", head=parent, paths=invalid, output="\n".join(errors))
    preexisting = sorted(set(candidates) & set(state["commit_baseline"]["paths"]))
    if preexisting:
        return failed("preexisting-changes", head=parent, paths=preexisting)
    staged = staged_paths(root)
    if staged:
        return failed("index-not-empty", head=parent, paths=paths_from(staged), output=os.fsdecode(staged))
    planned = sorted(set(candidates) & status_paths(root, *candidates))
    unchanged = sorted(set(candidates) - set(planned))
    if not planned:
        return record("skipped", reason="no-changes", unchanged=unchanged)
    before = status_snapshot(root)
    added = git_result(root, "add", "--", *planned)
    staged = staged_paths(root)
    now_staged = set(paths_from(staged))
    if added.returncode or now_staged != set(planned):
        git(root, "reset", "-q", "--", *planned)
        if added.returncode:
            output = command_output(added)
            return failed("stage-error", output=output, summary=summary(output))
        return failed("staged-set-mismatch", extra=sorted(now_staged - set(planned)),
                      missing=sorted(set(planned) - now_staged), output=os.fsdecode(staged))
    tree = git(root, "write-tree").decode().strip()
    record("attempted", proposal_id=proposal["proposal_id"], parent=parent, tree=tree,
           paths=planned, unchanged=unchanged, subject=proposal["subject"], pre_status=before)
    message_args = ["-m", proposal["subject"]]
    if proposal["body"]:
        message_args += ["-m", proposal["body"]]
    result = git_result(root, "commit", *message_args, literal=False)
    output, head = command_output(result), head_sha(root)
    if result.returncode and head == parent:
        git(root, "reset", "-q", "--", *planned)
        return failed("commit-error", output=output, summary=summary(output),
                      hook_side_effects=side_effects(before, status_snapshot(root)))
    matches = re.findall(r"^\[([^\]\n]+)\] .*$", os.fsdecode(result.stdout), re.MULTILINE)
    detail = None
    if result.returncode:
        detail = "head-moved"
    elif len(matches) != 1 or len(matches[0].split()) < 2:
        detail = "no-summary-line"
    else:
        printed = matches[0].split()[-1]
        resolved = git(root, "rev-parse", "--verify", "--quiet", printed + "^{commit}", allowed=(0, 1, 128)).decode().strip()
        if resolved != head:
            detail = "sha-mismatch"
        elif parents_of(root, head) != [parent]:
            detail = "parent-mismatch"
    if detail:
        return failed("unverifiable", detail=detail, head=head, parent=parent, output=output,
                      hook_side_effects=side_effects(before, status_snapshot(root)))
    actual = changed_paths(root, parent, head)
    effects = side_effects(before, status_snapshot(root), actual)
    foreign = sorted(set(actual) - set(planned))
    if foreign:
        reset = not git(root, "for-each-ref", "--contains", head, "refs/remotes").strip()
        if reset:
            undo = git_result(root, "update-ref", "-m", f"run_commit: undo run {state['run_id']} commit", "HEAD", parent, head)
            if undo.returncode:
                return failed("unverifiable", detail="cas-failed", parent=parent, sha=head,
                              output=output + command_output(undo))
            git(root, "reset", "-q", "--", *actual)
        return failed("hook-added-paths", paths=foreign, sha=head, reset=reset, output=output,
                      summary=summary(output), hook_side_effects=effects)
    expected_blobs = tree_blobs(root, tree, planned)
    committed_blobs = tree_blobs(root, head + "^{tree}", planned)
    modified = [path for path in planned if expected_blobs.get(path) != committed_blobs.get(path)]
    return record("created", sha=head, subject=commit_subject(root, head), files=actual, hook_modified=modified,
                  hook_side_effects=effects, hook_reverted=sorted(set(planned) - set(actual)), unchanged=unchanged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    proposal = sub.add_parser("propose")
    proposal.add_argument("--run-dir", required=True)
    proposal.add_argument("--subject", required=True)
    proposal.add_argument("--body", default="")
    for flag, dest in (("file", "files"), ("ride-along", "ride_along"), ("product-file", "product_files"), ("tracker-file", "tracker_files"), ("unresolved", "unresolved")):
        proposal.add_argument("--" + flag, dest=dest, action="append", default=[], required=flag == "file")
    execution = sub.add_parser("commit")
    execution.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    try:
        run_dir = Path(args.run_dir)
        if args.command == "commit":
            commit_context(run_dir)  # Refusals must not even create the lock file.
        with (run_dir / "commit.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(f"commit.lock is held for {run_dir}") from None
            print(json.dumps((propose if args.command == "propose" else commit)(args, run_dir), sort_keys=True))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
