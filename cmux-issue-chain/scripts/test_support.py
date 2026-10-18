#!/usr/bin/env python3
"""Shared fixtures for the script regression tests."""

from __future__ import annotations


def seed_capture(run_dir, stage, pass_num, **fields):
    from orchestrator_lib import append_jsonl

    append_jsonl(run_dir / "events.jsonl", {
        "type": "tree.snapshot", "message": f"report-captured {stage}-{pass_num}",
        "data": {}, **fields,
    })


def seed_evidence(run_dir, stage, pass_num, verdict="pass", **fields):
    from orchestrator_lib import append_jsonl

    append_jsonl(run_dir / "events.jsonl", {
        "type": "orchestrator.verified", "message": "test evidence",
        "data": {"stage": stage, "pass": pass_num, "verdict": verdict}, **fields,
    })


def passing_gate_evidence(run_dir, stage, pass_num=1):
    """Seed capture/check events for tests concerned with later workflow steps."""
    seed_capture(run_dir, stage, pass_num)
    seed_evidence(run_dir, stage, pass_num)


# One stub for the whole cmux CLI contract: a second copy drifts from the real output shape
# without any test noticing.
FAKE_CMUX = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_CMUX_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_CMUX_EXIT"):
    sys.exit(int(os.environ["FAKE_CMUX_EXIT"]))
args = sys.argv[1:]
if "close-surface" in args and os.environ.get("FAKE_CMUX_CONFIRM") and "--force" not in args:
    sys.stderr.write("Error: confirmation_required: live process\\n")
    sys.exit(1)
if "new-split" in args:
    print(json.dumps({
        "pane_id": "PANE-UUID", "pane_ref": "pane:9",
        "surface_id": "SURF-UUID", "surface_ref": "surface:9",
        "type": "terminal", "workspace_id": "WS-UUID", "workspace_ref": "workspace:1",
    }))
elif "read-screen" in args:
    print("PANE SCREEN")
else:
    print("OK")
'''
