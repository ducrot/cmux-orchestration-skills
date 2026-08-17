#!/usr/bin/env python3
"""Shared fixtures for the script regression tests."""

from __future__ import annotations


# One stub for the whole cmux CLI contract: a second copy drifts from the real output shape
# without any test noticing.
FAKE_CMUX = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_CMUX_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
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
