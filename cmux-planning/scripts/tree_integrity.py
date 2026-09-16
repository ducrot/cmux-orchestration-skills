#!/usr/bin/env python3
"""Capture and compare the documented Git-visible planning-worker integrity boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from artifact_manifest import (
    ArtifactIntegrityError,
    current_attempt,
    record_artifact,
    tree_snapshot_path,
    verify_entry,
    verify_or_gate,
)
from orchestrator_lib import (
    STAGES,
    append_event,
    integrity_boundary,
    read_json,
    read_planning_state,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_json,
)
from stage_snapshot import SnapshotError, load_prepared_snapshot


class IntegrityError(ValueError):
    pass


def git(repository: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=text,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise IntegrityError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result.stdout


def git_text(repository: Path, *args: str) -> str:
    """Diff output carries file content, which need not be valid UTF-8; decode it the way
    status paths are so one Latin-1 working file cannot block every planning stage."""
    raw = git(repository, *args, text=False)
    assert isinstance(raw, bytes)
    return raw.decode("utf-8", "surrogateescape")


UNTRACKED_HASH_LIMIT_BYTES = 8 * 1024 * 1024


def untracked_content(repository: Path, raw: bytes) -> tuple[bytes, list[tuple[str, str]], dict[str, dict[str, str]], bytes]:
    """Parse NUL-delimited status and hash bounded untracked content without decoding file bytes.

    Vendored identically across the three independently installed skills.
    Rename/copy source tokens are paths, never independent status entries.
    """
    tokens = raw.split(b"\0")
    entries = []
    states = {}
    hashed = []
    index = 0
    while index < len(tokens) and tokens[index]:
        token = tokens[index]
        if len(token) < 4 or token[2:3] != b" ":
            raise ValueError("git status returned an unparseable porcelain entry")
        code = token[:2].decode("ascii")
        path_bytes = token[3:]
        path = os.fsdecode(path_bytes)
        entries.append((code, path))
        index += 1
        if "R" in code or "C" in code:
            if index >= len(tokens) or not tokens[index]:
                raise ValueError("git status rename/copy entry is incomplete")
            entries.append((code, os.fsdecode(tokens[index])))
            index += 1
        if code != "??":
            continue
        absolute = os.path.join(os.fsencode(repository), path_bytes)
        # Fail closed: an unreadable or vanished path is never silently treated as skipped.
        try:
            info = os.lstat(absolute)
            if stat.S_ISLNK(info.st_mode):
                content = os.readlink(absolute)
            elif stat.S_ISREG(info.st_mode):
                if info.st_size > UNTRACKED_HASH_LIMIT_BYTES:
                    states[path] = {"skipped": "size exceeds 8 MiB limit"}
                    continue
                with open(absolute, "rb") as stream:
                    content = stream.read(UNTRACKED_HASH_LIMIT_BYTES + 1)
                if len(content) > UNTRACKED_HASH_LIMIT_BYTES:
                    states[path] = {"skipped": "size exceeds 8 MiB limit"}
                    continue
            else:
                states[path] = {"skipped": "unsupported file type"}
                continue
        except OSError as error:
            raise ValueError(
                f"cannot hash untracked path {path!r}: {error.strerror or error}; integrity capture is "
                "incomplete, so restore read access or remove the path and retry"
            ) from error
        digest = hashlib.sha256(content).hexdigest()
        states[path] = {"content_sha256": digest}
        hashed.append((path_bytes, digest.encode("ascii")))
    block = b"".join(path + b"\0" + digest + b"\n" for path, digest in sorted(hashed))
    return raw, entries, states, block


def capture_tree(repository: Path) -> dict[str, Any]:
    repository = repository.resolve()
    raw_status = git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=all", text=False)
    assert isinstance(raw_status, bytes)
    try:
        raw_status, entries, untracked, _ = untracked_content(repository, raw_status)
    except ValueError as error:
        raise IntegrityError(str(error)) from error
    # Git reports one path under several codes (a rename source that is also untracked, a
    # staged deletion whose file is back on disk). Keeping only the last would let `??` mask a
    # tracked delta, so every code a path carries is preserved.
    codes_by_path: dict[str, list[str]] = {}
    for code, path in entries:
        codes_by_path.setdefault(path, []).append(code)
    path_states: dict[str, dict[str, str]] = {}
    for path in sorted(codes_by_path):
        codes = sorted(set(codes_by_path[path]))
        status = " ".join(codes)
        if codes == ["??"]:
            path_states[path] = {"status": status, **untracked[path]}
            continue
        # `:(literal)` because a filename containing *, ? or [ is a wildmatch pathspec that
        # would pull unrelated siblings' diffs into this path's state.
        spec = f":(literal){path}"
        working = git_text(repository, "diff", "--no-ext-diff", "--binary", "--", spec)
        staged = git_text(repository, "diff", "--cached", "--no-ext-diff", "--binary", "--", spec)
        path_states[path] = {"status": status, "working_diff": working, "staged_diff": staged}
        if "??" in codes:
            path_states[path].update(untracked[path])
    tracked_diff = git_text(repository, "diff", "--no-ext-diff", "--binary")
    staged_diff = git_text(repository, "diff", "--cached", "--no-ext-diff", "--binary")
    head = git_text(repository, "rev-parse", "HEAD")
    return {
        "captured_at": utc_now(),
        "repository": str(repository),
        "head": head.strip(),
        "status_porcelain_z": raw_status.decode("utf-8", "surrogateescape"),
        "tracked_diff": tracked_diff,
        "staged_diff": staged_diff,
        "path_states": path_states,
        "boundary": integrity_boundary(),
    }


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    # Capture time is audit metadata, not product-tree identity. Excluding it lets a clean retry
    # prove it starts from the exact same tree even when the observations occur seconds apart.
    identity = {key: value for key, value in snapshot.items() if key != "captured_at"}
    return sha256_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def repository_relative(repository: Path, absolute: str) -> str | None:
    """`repository` must already be resolved; callers resolve once outside their loop."""
    try:
        return str(Path(absolute).resolve().relative_to(repository))
    except ValueError:
        return None


def compare_tree(
    before: dict[str, Any], after: dict[str, Any], *, allowed_paths: list[str]
) -> dict[str, Any]:
    repository = Path(before["repository"]).resolve()
    if after.get("repository") != before.get("repository"):
        raise IntegrityError("before and after snapshots name different repositories")
    allowed = {
        relative
        for path in allowed_paths
        if (relative := repository_relative(repository, path)) is not None
    }
    before_states = before.get("path_states", {})
    after_states = after.get("path_states", {})
    changed_paths = sorted(
        path
        for path in set(before_states) | set(after_states)
        if before_states.get(path) != after_states.get(path)
    )
    unauthorized = [path for path in changed_paths if path not in allowed]
    # No planning worker may commit. Without this the status view is clean on both sides and a
    # worker that commits its product edit passes the gate it exists to fail.
    head_moved = before.get("head") != after.get("head")
    # Artifact write permission never authorizes changing the index.
    staged_diff_changed = before.get("staged_diff") != after.get("staged_diff")
    return {
        "ok": not unauthorized and not head_moved and not staged_diff_changed,
        "staged_diff_changed": staged_diff_changed,
        "changed_paths": changed_paths,
        "allowed_changed_paths": [path for path in changed_paths if path in allowed],
        "unauthorized_paths": unauthorized,
        "head_before": before.get("head"),
        "head_after": after.get("head"),
        "head_moved": head_moved,
        "boundary": after["boundary"],
    }


def baseline(run_dir: Path, stage: str, pass_num: int) -> dict[str, Any]:
    verify_or_gate(run_dir, stage=stage)
    snapshot = load_prepared_snapshot(run_dir, stage, pass_num, require_baseline=False)
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    repository = Path(state["repository"])
    captured = capture_tree(repository)
    attempt_record = current_attempt(state, stage, pass_num)
    prompt_path = Path(snapshot["prompt_path"])
    if not prompt_path.is_file():
        raise IntegrityError(
            f"render the deterministic prompt before capturing the launch baseline: {prompt_path}"
        )
    existing = state.get("tree_baseline")
    # Never recapture: a second baseline for the same armed pass would adopt whatever the first
    # worker already changed as the new "before", laundering an unauthorized delta.
    if (
        isinstance(existing, dict)
        and existing.get("stage") == stage
        and existing.get("pass") == pass_num
        and existing.get("attempt_id") == attempt_record["attempt_id"]
        and existing.get("snapshot_id") == snapshot["snapshot_id"]
    ):
        raise IntegrityError(
            f"{stage}-{pass_num} already has a launch baseline; prepare the stage again to rearm it"
        )
    digest = snapshot_digest(captured)
    # The seal outlives `prepare_stage`, which clears `tree_baseline` and mints a fresh
    # snapshot_id. Without it the guard above is bypassed by the rearm it recommends, and the
    # second baseline adopts the first worker's delta as the new "before".
    seals = state.setdefault("tree_baseline_seals", {})
    # All retries of the same logical stage/pass must start from the same product-tree bytes.
    # Attempt-scoped run paths prevent handoff reuse; this cross-attempt seal prevents a retry
    # from laundering the prior worker's product delta into a fresh baseline.
    seal_key = f"{stage}-{pass_num}"
    sealed = seals.get(seal_key)
    if sealed is not None and sealed != digest:
        raise IntegrityError(
            f"{stage}-{pass_num} was already armed against a different working tree; rearming "
            "now would adopt the current delta as its baseline. Resolve the working-tree change "
            "or start a new pass"
        )
    seals[seal_key] = digest
    before_path = tree_snapshot_path(
        run_dir, stage, pass_num, attempt_record["attempt"], "before"
    )
    relative = before_path.relative_to(run_dir)
    if before_path.exists():
        raise IntegrityError(f"unexpected file occupies fresh tree baseline path: {before_path}")
    write_json(before_path, captured)
    before_entry = record_artifact(
        state,
        run_dir,
        relative,
        kind="tree-baseline",
        stage=stage,
        pass_num=pass_num,
        attempt=attempt_record["attempt"],
        producer="tree.baseline",
    )
    prompt_entry = verify_entry(
        state,
        run_dir,
        attempt_record.get("prompt_manifest_id", ""),
        expected_kind="prompt",
        expected_path=prompt_path,
    )
    pointer = {
        "stage": stage,
        "pass": pass_num,
        "attempt": attempt_record["attempt"],
        "attempt_id": attempt_record["attempt_id"],
        "path": str(relative),
        "sha256": digest,
        "manifest_id": before_entry["id"],
        "snapshot_id": snapshot["snapshot_id"],
        "prompt_path": str(prompt_path),
        "prompt_sha256": sha256_file(prompt_path),
        "prompt_manifest_id": prompt_entry["id"],
        "captured_at": captured["captured_at"],
    }
    state["tree_baseline"] = pointer
    state["updated_at"] = captured["captured_at"]
    write_json(state_path, state)
    append_event(
        run_dir,
        "tree.baseline",
        f"captured complete Git-visible baseline for {stage}-{pass_num}",
        pointer,
        time=captured["captured_at"],
    )
    return pointer


def verify(run_dir: Path, stage: str, pass_num: int) -> dict[str, Any]:
    verify_or_gate(run_dir, stage=stage)
    snapshot = load_prepared_snapshot(run_dir, stage, pass_num, require_baseline=True)
    state = read_planning_state(run_dir / "state.json")
    attempt_record = current_attempt(state, stage, pass_num)
    pointer = state["tree_baseline"]
    before_path = run_dir / pointer["path"]
    before = read_json(before_path)
    verify_entry(
        state,
        run_dir,
        pointer.get("manifest_id", ""),
        expected_kind="tree-baseline",
        expected_path=pointer["path"],
    )
    if snapshot_digest(before) != pointer["sha256"]:
        raise IntegrityError("tree baseline is missing or changed")
    after = capture_tree(Path(state["repository"]))
    after_path = tree_snapshot_path(
        run_dir, stage, pass_num, attempt_record["attempt"], "after"
    )
    after_relative = after_path.relative_to(run_dir)
    if after_path.exists():
        raise IntegrityError(
            f"unexpected file occupies fresh tree verification path: {after_path}"
        )
    write_json(after_path, after)
    after_entry = record_artifact(
        state,
        run_dir,
        after_relative,
        kind="tree-verification",
        stage=stage,
        pass_num=pass_num,
        attempt=attempt_record["attempt"],
        producer="tree.verified",
    )
    write_json(run_dir / "state.json", state)
    result = compare_tree(
        before,
        after,
        allowed_paths=list(snapshot["allowed_worker_writes"].values()),
    )
    result["after_path"] = str(after_relative)
    result["after_sha256"] = snapshot_digest(after)
    result["after_manifest_id"] = after_entry["id"]
    append_event(
        run_dir,
        "tree.verified" if result["ok"] else "integrity.violation",
        (
            f"Git-visible integrity verified for {stage}-{pass_num}"
            if result["ok"]
            else f"unauthorized Git-visible delta after {stage}-{pass_num}"
        ),
        result,
        time=after["captured_at"],
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("baseline", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--run-dir", required=True)
        child.add_argument("--stage", choices=STAGES, required=True)
        child.add_argument("--pass", dest="pass_num", type=int, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = (
            baseline(Path(args.run_dir), args.stage, args.pass_num)
            if args.command == "baseline"
            else verify(Path(args.run_dir), args.stage, args.pass_num)
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ok", True) else 2
    except (
        ArtifactIntegrityError,
        IntegrityError,
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
