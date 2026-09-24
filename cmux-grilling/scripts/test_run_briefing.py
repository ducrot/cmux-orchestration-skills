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


class RunDirTestCase(unittest.TestCase):
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


class RunBriefing(RunDirTestCase):
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
        self.assertIn("status pill not updated", result.stderr)
        self.assertIn("filled subject", result.stdout)
        event = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertIsNone(event["data"]["pill"])


def event(event_type: str, time: str = "2026-09-23T21:42:00+00:00", **fields) -> dict:
    return {"type": event_type, "time": time, **fields}


DONE_ISSUE_STATE = {
    **ISSUE_STATE,
    "created_at": "2026-09-23T20:00:00+00:00",
    "current_stage": "done",
    "issue": {**ISSUE_STATE["issue"], "status": "done", "acceptance_done": 4},
}
DONE_ISSUE_EVENTS = [
    event("gate", stage="implement", decision="advance", reason="r"),
    event("gate", stage="test", decision="advance", reason="r"),
    event("recommendations.triaged", data={"id": "R1", "pass": 1, "verdict": "accepted", "consequence": "follow-up", "title": "a"}),
    event("recommendations.triaged", data={"id": "R2", "pass": 1, "verdict": "for-the-human", "consequence": "ledger only", "title": "Pick a name"}),
    event("commit.proposed", data={"subject": "Harden triage inputs", "product_files": []}),
]


class RunRecap(RunDirTestCase):
    def write_events(self, run_dir: Path, events: list) -> None:
        (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def recap(self, run_dir: Path, lang: str = "de") -> str:
        result = self.call("recap-draft", "--run-dir", str(run_dir), "--lang", lang)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["placeholders"], ["outcome"])
        return (run_dir / "recap.md").read_text(encoding="utf-8")

    def fill_recap(self, run_dir: Path) -> None:
        path = run_dir / "recap.md"
        path.write_text(path.read_text(encoding="utf-8").replace("{{outcome}}", "filled outcome"), encoding="utf-8")

    def pill_calls(self) -> list:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_issue_chain_recap_collects_gates_triage_and_commit(self):
        run_dir = self.run_dir(DONE_ISSUE_STATE)
        self.write_events(run_dir, DONE_ISSUE_EVENTS)
        text = self.recap(run_dir)
        self.assertIn("**Run-Recap · chain-issue-003-2026-09-23-2007 · 1 h 42 min**", text)
        self.assertIn("Status: **abgeschlossen**", text)
        self.assertIn("- Tracker-Status: done · 4/4 Kriterien abgehakt", text)
        self.assertIn("- Stages: implement ✓ · test ✓", text)
        self.assertIn("- Triage: 2 Empfehlungen → 1 follow-up, 1 ledger only", text)
        self.assertIn("- Offen für den Menschen: R2 (Triage 1) – Pick a name", text)
        self.assertIn("- Commit: Harden triage inputs", text)

    def test_recap_refuses_an_active_run(self):
        run_dir = self.run_dir({**DONE_ISSUE_STATE, "current_stage": "review"})
        self.write_events(run_dir, DONE_ISSUE_EVENTS[:2])
        result = self.call("recap-draft", "--run-dir", str(run_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still active", result.stderr)
        self.assertFalse((run_dir / "recap.md").exists())

    def test_halted_run_gets_red_pill_with_decision(self):
        run_dir = self.run_dir({**DONE_ISSUE_STATE, "current_stage": "review"})
        self.write_events(run_dir, [event("gate", stage="review", decision="hitl", reason="r")])
        text = self.recap(run_dir, lang="en")
        self.assertIn("Status: **halted at review: hitl**", text)
        self.assertIn("review ✗ hitl", text)
        self.assertNotIn("Triage", text)
        self.assertNotIn("Commit", text)
        self.fill_recap(run_dir)
        result = self.call("recap-show", "--run-dir", str(run_dir), "--cmux-cmd", self.cmux)
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.pill_calls()[-1]
        self.assertTrue(argv[2].startswith("hitl · ISSUE-003"))
        self.assertEqual(argv[argv.index("--color") + 1], "#ff3b30")
        logged = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(logged["type"], "run.recap")
        self.assertEqual(logged["data"]["outcome"]["decision"], "hitl")

    def test_done_run_gets_green_check_pill_or_clears_it(self):
        run_dir = self.run_dir(DONE_ISSUE_STATE)
        self.write_events(run_dir, DONE_ISSUE_EVENTS)
        self.recap(run_dir)
        show = self.call("recap-show", "--run-dir", str(run_dir), "--cmux-cmd", self.cmux)
        self.assertNotEqual(show.returncode, 0)
        self.fill_recap(run_dir)
        show = self.call("recap-show", "--run-dir", str(run_dir), "--cmux-cmd", self.cmux)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("filled outcome", show.stdout)
        argv = self.pill_calls()[-1]
        self.assertTrue(argv[2].startswith("✓ ISSUE-003"))
        self.assertEqual(argv[argv.index("--color") + 1], "#34c759")
        cleared = self.call("recap-show", "--run-dir", str(run_dir), "--clear-status", "--cmux-cmd", self.cmux)
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertEqual(self.pill_calls()[-1], ["clear-status", "cmux-issue-chain-run", "--workspace", "WS-UUID"])

    def test_planning_recap_names_published_tracker(self):
        state = {
            **PLANNING_STATE,
            "created_at": "2026-09-23T08:00:00+00:00",
            "current_stage": "complete",
            "spec_pass": 2,
            "tickets_pass": 1,
            "published_tracker": {
                "path": ".scratch/trackers/run-briefing",
                "ticket_ids": ["ISSUE-001", "ISSUE-002"],
                "ready_frontier": ["ISSUE-001"],
            },
        }
        run_dir = self.run_dir(state)
        self.write_events(run_dir, [event("tracker.published", time="2026-09-23T08:30:00+00:00")])
        text = self.recap(run_dir)
        self.assertIn("· 30 min**", text)
        self.assertIn("- Tracker: `.scratch/trackers/run-briefing` · 2 Issues, sofort startbar: ISSUE-001", text)
        self.assertIn("- Revisionen: Spec 1 · Tickets 0", text)

    def test_grilling_recap_reads_the_artifact(self):
        artifact = self.root / "grilling" / "briefing.json"
        artifact.parent.mkdir()
        artifact.write_text(json.dumps({
            "questionsAsked": 7,
            "maxQuestions": 10,
            "stopReason": "griller-done",
            "assumptions": ["a", "b", "c"],
            "open_decisions": [{"status": "decided"}, {"status": "decided"}, {"status": "deferred"}],
        }), encoding="utf-8")
        state = {
            **GRILLING_STATE,
            "created_at": "2026-09-23T20:00:00+00:00",
            "current_stage": "done",
            "deliverables": {"markdown": str(artifact.with_suffix(".md")), "json": str(artifact)},
        }
        run_dir = self.run_dir(state)
        self.write_events(run_dir, [event("commit.proposed", data={"subject": "Record grilling result"})])
        text = self.recap(run_dir)
        self.assertIn("- Fragen: 7 von 10 · Stop: griller-done", text)
        self.assertIn("- Annahmen: 3 · Entscheidungen: 2 entschieden, 1 zurückgestellt, 0 offen", text)
        self.assertIn("briefing.json`", text)
        self.assertIn("- Commit: Record grilling result", text)


if __name__ == "__main__":
    unittest.main()
