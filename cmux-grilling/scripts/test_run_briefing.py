#!/usr/bin/env python3
"""Run briefing regression tests. Vendored byte-identical into all three cmux skills."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "run_briefing.py"

FAKE_CMUX = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_CMUX_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("FAKE_CMUX_EXIT", "0")))
'''

ISSUE_STATE = {
    "run_id": "chain-issue-003-2026-09-23-2007",
    "workflow": "issue-chain",
    "workspace_id": "WS-UUID",
    "tracker": ".",
    "issue": {
        "id": "ISSUE-003",
        "title": "Harden triage inputs: fail-closed diff file list and canonical draft blocker IDs",
        "acceptance_total": 4,
        "acceptance_done": 0,
    },
    "blocker_status": {"blockers": [{"id": "ISSUE-001", "status": "done"}]},
    "chain": ["implement", "simplify", "review", "test", "triage"],
    "triage_mode": "autonomous",
}
PLANNING_STATE = {
    "run_id": "plan-briefing-2026-09-24-1000",
    "workflow": "planning",
    "workspace_id": None,
    "tracker_slug": "run-briefing",
    "task": {"path": "task.md", "source": "file:/tmp/task.md"},
    "grilling_import": None,
}
GRILLING_STATE = {
    "run_id": "grill-briefing-2026-09-24-1000",
    "workflow": "grilling",
    "workspace_id": "WS-UUID",
    "slug": "briefing",
    "max_questions": 10,
    "lanes": {"codebase": {}, "codebase2": {}, "docs": {}, "web": {}},
    "output_dir": ".scratch/grilling",
}


class RunBriefing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "cmux.log"
        cmux = self.root / "fake-cmux"
        cmux.write_text(FAKE_CMUX, encoding="utf-8")
        cmux.chmod(0o755)
        self.cmux = str(cmux)

    def tearDown(self):
        self.tmp.cleanup()

    def run_dir(self, state: dict) -> Path:
        run_dir = self.root / state["run_id"]
        run_dir.mkdir()
        (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return run_dir

    def call(self, *args: str, exit_code: int = 0) -> subprocess.CompletedProcess:
        env = {**os.environ, "FAKE_CMUX_LOG": str(self.log), "FAKE_CMUX_EXIT": str(exit_code)}
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=self.root
        )

    def draft(self, run_dir: Path, lang: str = "de") -> dict:
        result = self.call("draft", "--run-dir", str(run_dir), "--lang", lang)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fill(self, run_dir: Path) -> None:
        path = run_dir / "briefing.md"
        text = path.read_text(encoding="utf-8")
        for name in ("goal", "scope", "task", "constraints", "subject", "focus"):
            text = text.replace("{{" + name + "}}", f"filled {name}")
        path.write_text(text, encoding="utf-8")

    def test_issue_chain_skeleton_has_facts_and_placeholders(self):
        run_dir = self.run_dir(ISSUE_STATE)
        drafted = self.draft(run_dir)
        self.assertEqual(drafted["placeholders"], ["goal", "scope"])
        text = (run_dir / "briefing.md").read_text(encoding="utf-8")
        self.assertIn("**Run-Briefing · chain-issue-003-2026-09-23-2007**", text)
        self.assertIn("ISSUE-003 – Harden triage inputs", text)
        self.assertIn("- Akzeptanz: 4 Kriterien, 0 erfüllt", text)
        self.assertIn("- Blockiert durch: ISSUE-001 (done)", text)
        self.assertIn("implement → simplify → review → test → triage (Triage autonom)", text)
        self.assertNotIn("Checks", text)

    def test_hitl_issue_names_empty_chain(self):
        run_dir = self.run_dir({**ISSUE_STATE, "chain": [], "blocker_status": {"blockers": []}})
        self.draft(run_dir, lang="en")
        text = (run_dir / "briefing.md").read_text(encoding="utf-8")
        self.assertIn("- Chain: none (HITL issue", text)
        self.assertNotIn("Blocked by", text)

    def test_planning_and_grilling_skeletons(self):
        planning = self.run_dir(PLANNING_STATE)
        self.assertEqual(self.draft(planning)["placeholders"], ["constraints", "task"])
        text = (planning / "briefing.md").read_text(encoding="utf-8")
        self.assertIn("- Quelle: Task-Datei task.md", text)
        self.assertIn("Tracker `run-briefing`", text)
        grilling = self.run_dir(GRILLING_STATE)
        self.assertEqual(self.draft(grilling)["placeholders"], ["constraints", "focus", "subject"])
        text = (grilling / "briefing.md").read_text(encoding="utf-8")
        self.assertIn("höchstens 10 Fragen · Lanes codebase, codebase2, docs, web", text)
        self.assertIn("`.scratch/grilling`", text)

    def test_grilling_input_source_is_named(self):
        state = {**PLANNING_STATE, "grilling_import": {"source_json": "/x/.scratch/grilling/result.json"}}
        run_dir = self.run_dir(state)
        self.draft(run_dir, lang="en")
        self.assertIn("grilling result result.json", (run_dir / "briefing.md").read_text(encoding="utf-8"))

    def test_draft_never_overwrites_filled_briefing(self):
        run_dir = self.run_dir(ISSUE_STATE)
        self.draft(run_dir)
        self.fill(run_dir)
        self.assertEqual(self.draft(run_dir)["placeholders"], [])
        self.assertIn("filled goal", (run_dir / "briefing.md").read_text(encoding="utf-8"))

    def test_show_refuses_unfilled_placeholders(self):
        run_dir = self.run_dir(ISSUE_STATE)
        self.draft(run_dir)
        result = self.call("show", "--run-dir", str(run_dir), "--cmux-cmd", self.cmux)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("goal, scope", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse((run_dir / "events.jsonl").exists())

    def test_show_prints_logs_and_sets_pill_on_pinned_workspace(self):
        run_dir = self.run_dir(ISSUE_STATE)
        self.draft(run_dir)
        self.fill(run_dir)
        result = self.call("show", "--run-dir", str(run_dir), "--lang", "de", "--cmux-cmd", self.cmux)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (run_dir / "briefing.md").read_text(encoding="utf-8"))
        argv = json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(argv[:2], ["set-status", "cmux-issue-chain-run"])
        self.assertTrue(argv[2].startswith("ISSUE-003 · Harden"))
        self.assertLessEqual(len(argv[2]), 48)
        self.assertTrue(argv[2].endswith("…"))
        self.assertEqual(argv[argv.index("--workspace") + 1], "WS-UUID")
        event = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(event["type"], "run.briefing")
        self.assertEqual(event["data"]["pill"], argv[2])

    def test_show_without_workspace_skips_pill(self):
        run_dir = self.run_dir(PLANNING_STATE)
        self.draft(run_dir)
        self.fill(run_dir)
        result = self.call("show", "--run-dir", str(run_dir), "--cmux-cmd", self.cmux)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())

    def test_pill_failure_does_not_block_the_briefing(self):
        run_dir = self.run_dir(GRILLING_STATE)
        self.draft(run_dir)
        self.fill(run_dir)
        result = self.call("show", "--run-dir", str(run_dir), "--cmux-cmd", self.cmux, exit_code=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status pill not set", result.stderr)
        self.assertIn("filled subject", result.stdout)
        event = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertIsNone(event["data"]["pill"])


if __name__ == "__main__":
    unittest.main()
