#!/usr/bin/env python3
"""Run one shell check from the Git root and write tree-bound evidence.

Usage: python3 run_check.py --artifact-dir <stage-artifacts> --command '<check>'

Version 1 logs have nine key-value lines followed by a literal --- separator.
Command and repository values are JSON strings so even embedded newlines cannot
break the header. Remaining values are numbers or Git hashes. Below the header,
combined stdout/stderr is preserved byte-for-byte. Logs are named by the SHA-256
of the exact command, with -2, -3, ... for repeat runs (exclusive creation).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from run_state import tree_fingerprint


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, check=True,
    )
    return Path(os.fsdecode(result.stdout.removesuffix(b"\n")))


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


def run_check(artifact_dir: Path, command: str) -> int:
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
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--command", required=True)
    args = parser.parse_args(argv)
    try:
        return run_check(args.artifact_dir, args.command)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"run_check: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
