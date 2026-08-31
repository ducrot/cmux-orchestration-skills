#!/usr/bin/env python3
"""Dependency-free persistence and identity helpers for cmux-planning."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents_config import durable_publish


STAGES = ("spec", "spec-review")
ROLE_LABELS = {"spec": "Spec Author", "spec-review": "Spec Reviewer"}
MINIMUM_WAIT_MINUTES = {"spec": 45, "spec-review": 45}
# One statement of what the Git-visible detector sees, so the snapshot, the tree baseline and
# the run state cannot describe different boundaries.
INTEGRITY_BOUNDARY = {
    "covered": [
        "tracked changes",
        "staged changes",
        "newly listed untracked paths",
        "commits (HEAD movement)",
    ],
    "not_covered": ["ignored files", "content changes to baseline-untracked files"],
}
PROMPT_DELIVERY_TEMPLATE = (
    "Your task assignment is in {prompt_path}. It is not a document to read back or summarize. "
    "Execute it now and write your final report to the handoff path it names."
)


def integrity_boundary() -> dict[str, list[str]]:
    return copy.deepcopy(INTEGRITY_BOUNDARY)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def append_event(
    run_dir: Path, event_type: str, message: str, data: dict[str, Any], *, time: str | None = None
) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": time or utc_now(), "type": event_type, "message": message, "data": data},
    )


def atomic_write(path: Path, payload: bytes) -> None:
    """Publish one complete file in place; readers see old bytes or new bytes, never a prefix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    durable_publish(path, payload, mode=0o644, suffix=".tmp", publish=os.replace)


def checkout_identity(repository: Path) -> dict[str, str]:
    def git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(repository), *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"git {' '.join(args)} could not run: {error}") from error
        if result.returncode != 0:
            raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    head = git("rev-parse", "HEAD").strip()
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    return {
        "repository": str(repository.resolve()),
        "head": head,
        "status_sha256": sha256_bytes(status.encode("utf-8")),
    }


def delivery_text(prompt_path: str) -> str:
    return PROMPT_DELIVERY_TEMPLATE.format(prompt_path=prompt_path)
