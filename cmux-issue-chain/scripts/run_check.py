#!/usr/bin/env python3
"""Run one shell check from the Git root and write tree-bound evidence.

Usage: python3 run_check.py --artifact-dir <stage-artifacts> --command '<check>'

Version 1 logs have nine key-value lines followed by a literal --- separator.
Command and repository values are JSON strings so even embedded newlines cannot
break the header. Remaining values are numbers or Git hashes. Below the header,
combined stdout/stderr is preserved byte-for-byte. Logs are named by the SHA-256
of the exact command, with -2, -3, ... for repeat runs (exclusive creation).
After writing the log, its absolute path is reported on the wrapper's stderr.

Canonical suites belong to the final test: inside a run's implement, simplify, or review
artifact directory, a command equal to a tracker-declared canonical command is refused with
exit code 64 and no log, unless --full-suite-reason names why this diff needs it. The reason
is kept beside the log as <log>.reason, which evidence checks do not read as a log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from check_commands import applicable_commands
from orchestrator_lib import read_run_state
from render_prompt import tracker_ground_rules
from run_state import tree_fingerprint

GUARDED_STAGE = re.compile(r"(?:implement|simplify|review)-\d+")
REFUSED_EXIT = 64


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, check=True,
    )
    return Path(os.fsdecode(result.stdout.removesuffix(b"\n")))


def guarded_commands(artifact_dir: Path, repository: Path) -> list[str]:
    resolved = artifact_dir.resolve()
    if not GUARDED_STAGE.fullmatch(resolved.name) or resolved.parent.name != "artifacts":
        return []
    # The guard only saves time, and the evidence check reports bad declarations at the gate,
    # so an unreadable run or tracker must not stop a worker's checks.
    try:
        tracker = Path(read_run_state(resolved.parents[1])["deliverables"]["tracker"])
        return applicable_commands(tracker_ground_rules(repository / tracker), "implement")
    # read_run_state exits on a legacy or foreign state instead of raising.
    except (OSError, ValueError, KeyError, TypeError, SystemExit):
        return []


def reserve_log(artifact_dir: Path, command: str):
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stem = "check-" + hashlib.sha256(command.encode("utf-8")).hexdigest()
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f"-{attempt}"
        try:
            return (artifact_dir / f"{stem}{suffix}.log").open("xb")
        except FileExistsError:
            attempt += 1


def run_check(artifact_dir: Path, command: str, reason: str = "") -> int:
    repository = repository_root()
    before = tree_fingerprint(repository)
    # Reserve the name before starting so repeated runs never clobber evidence.
    # Spool output outside the repository until the exit status/header are known.
    with reserve_log(artifact_dir, command) as log, tempfile.TemporaryFile() as output:
        # A headerless log would read as evidence, so drop the reservation on any failure.
        try:
            started = time.monotonic()
            process = subprocess.Popen(
                command, shell=True, cwd=repository, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert process.stdout is not None
            with process.stdout:
                while chunk := process.stdout.read1(65536):
                    output.write(chunk)
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
            returncode = process.wait()
            # Shell-compatible status if the shell itself was terminated by a signal.
            exit_code = returncode if returncode >= 0 else 128 - returncode
            duration = time.monotonic() - started
            after = tree_fingerprint(repository)
            fields = {
                "evidence_version": "1",
                "command": json.dumps(command, ensure_ascii=True),
                "exit_code": str(exit_code),
                "duration_seconds": f"{duration:.6f}",
                "repository": json.dumps(str(repository), ensure_ascii=True),
                "head_before": before["head"],
                "fingerprint_before": before["fingerprint"],
                "head_after": after["head"],
                "fingerprint_after": after["fingerprint"],
            }
            log.write(("".join(f"{key}: {value}\n" for key, value in fields.items()) + "---\n").encode("utf-8"))
            output.seek(0)
            shutil.copyfileobj(output, log)
        except BaseException:
            os.unlink(log.name)
            raise
    if reason:
        Path(f"{log.name}.reason").write_text(reason + "\n", encoding="utf-8")
    # Unbuffered fd 2: a closed or broken stderr must neither reach stdout (sys.stderr is
    # None then) nor turn the command's exit code into a shutdown flush failure.
    try:
        os.write(2, os.fsencode(f"run_check: log written to {Path(log.name).resolve()}\n"))
    except OSError:
        pass
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--command", required=True)
    parser.add_argument("--full-suite-reason", default="",
                        help="why this diff needs a canonical suite before the final test")
    args = parser.parse_args(argv)
    try:
        if (not args.full_suite_reason.strip()
                and args.command in guarded_commands(args.artifact_dir, repository_root())):
            print("run_check: refused: canonical suites belong to the final test; select smaller "
                  "tests, or pass --full-suite-reason '<why this diff needs it>' and repeat the "
                  "reason in your selection bullet", file=sys.stderr)
            return REFUSED_EXIT
        return run_check(args.artifact_dir, args.command, args.full_suite_reason.strip())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"run_check: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
