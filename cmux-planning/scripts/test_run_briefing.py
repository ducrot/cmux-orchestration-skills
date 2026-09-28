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
sys.path.insert(0, str(SCRIPT.parent))

import run_briefing  # noqa: E402

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
    "max_rounds": 4,
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

    def test_commit_mode_last_line_all_workflows_and_languages(self):
        for base in (ISSUE_STATE, PLANNING_STATE, GRILLING_STATE, {**ISSUE_STATE, "chain": []}):
            for mode in (None, "propose", "commit"):
                state = dict(base)
                if mode is not None:
                    state["commit_mode"] = mode
                for lang in ("en", "de"):
                    expected = {"en": ("automatic", "proposal"), "de": ("automatisch", "Vorschlag")}[lang][mode != "commit"]
                    text = run_briefing.render_briefing(state, [], lang)
                    self.assertEqual(text.splitlines()[-1], f"- Commit: {expected}")

    def test_next_prompt_preserves_commit_mode(self):
        invocation = "/cmux-issue-chain ISSUE-003 --commit-mode commit"
        prompt, unchanged = run_briefing.next_prompt(
            {**ISSUE_STATE, "invocation": invocation},
            {"id": "ISSUE-004", "path": "ISSUE-004-next.md"},
        )
        self.assertFalse(unchanged)
        self.assertEqual(prompt, "/cmux-issue-chain ISSUE-004 --commit-mode commit")

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
        self.assertIn("höchstens 4 Runden · Lanes codebase, codebase2, docs, web", text)
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
        self.assertIn("- Commit-Vorschlag: Harden triage inputs", text)

    def test_commit_recap_selection_and_legacy(self):
        run_dir = self.run_dir(DONE_ISSUE_STATE)
        for language, label in (("en", "Commit proposal"), ("de", "Commit-Vorschlag")):
            proposal = event("commit.proposed", data={"subject": "Latest proposal"})
            for events in ([proposal], [proposal, event("commit.attempted", data={})]):
                (run_dir / "recap.md").unlink(missing_ok=True)
                self.write_events(run_dir, events)
                self.assertIn(f"- {label}: Latest proposal", self.recap(run_dir, lang=language))
            for kind in ("created", "failed", "skipped"):
                (run_dir / "recap.md").unlink(missing_ok=True)
                self.write_events(run_dir, [event("commit." + kind, data={"subject": "Outcome", "sha": "123456789", "reason": "no-changes"}), proposal])
                text = self.recap(run_dir, lang=language)
                self.assertIn("- Commit", text)
                self.assertNotIn("Latest proposal", text)
                self.assertNotIn(f"- {label}:", text)
            (run_dir / "recap.md").unlink(missing_ok=True)
            self.write_events(run_dir, [])
            self.assertNotIn("- Commit", self.recap(run_dir, lang=language))

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
        self.assertNotIn("- Commit", text)
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
            "roundsRun": 2,
            "maxRounds": 4,
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
        self.assertIn("- Fragen: 7 in 2 von 4 Runden · Stop: griller-done", text)
        self.assertIn("- Annahmen: 3 · Entscheidungen: 2 entschieden, 1 zurückgestellt, 0 offen", text)
        self.assertIn("briefing.json`", text)
        self.assertIn("- Commit-Vorschlag: Record grilling result", text)


def issue_file(issue_id: str, status: str = "todo", blockers: tuple = (), issue_type: str = "AFK", checked: int = 0) -> str:
    blocked = "\n".join(f"- {blocker}" for blocker in blockers) or "- None"
    boxes = "\n".join(["- [x] done"] * checked + ["- [ ] open"] * (2 - checked))
    return (
        f"---\nid: {issue_id}\ntitle: \"Title {issue_id}\"\ntype: {issue_type}\nstatus: {status}\n"
        f"labels:\n  - ready-for-agent\n---\n\n# {issue_id}\n\n## Acceptance Criteria\n\n{boxes}\n\n"
        f"## Blocked by\n\n{blocked}\n"
    )


class NextStep(RunDirTestCase):
    def tracker(self, files: dict) -> Path:
        tracker = self.root / "tracker"
        (tracker / "issues").mkdir(parents=True)
        for issue_id, text in files.items():
            (tracker / "issues" / f"{issue_id}-slug.md").write_text(text, encoding="utf-8")
        return tracker

    def done_run(self, tracker: Path, run_id: str = DONE_ISSUE_STATE["run_id"]) -> Path:
        run_dir = self.run_dir({**DONE_ISSUE_STATE, "tracker": str(tracker), "run_id": run_id})
        (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in DONE_ISSUE_EVENTS), encoding="utf-8")
        return run_dir

    def recap(self, run_dir: Path, lang: str = "de") -> str:
        result = self.call("recap-draft", "--run-dir", str(run_dir), "--lang", lang)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = run_dir / "recap.md"
        path.write_text(path.read_text(encoding="utf-8").replace("{{outcome}}", "filled"), encoding="utf-8")
        return path.read_text(encoding="utf-8")

    def show(self, run_dir: Path) -> subprocess.CompletedProcess:
        return self.call("recap-show", "--run-dir", str(run_dir), "--no-status")

    def test_ranking_prefers_in_progress_then_unlocks_then_lowest_id(self):
        tracker = self.tracker({
            "ISSUE-003": issue_file("ISSUE-003", status="done", checked=2),
            "ISSUE-004": issue_file("ISSUE-004"),
            "ISSUE-005": issue_file("ISSUE-005"),
            "ISSUE-006": issue_file("ISSUE-006", blockers=("ISSUE-005",)),
            "ISSUE-007": issue_file("ISSUE-007", blockers=("ISSUE-006",)),
            "ISSUE-008": issue_file("ISSUE-008", issue_type="HITL"),
        })
        text = self.recap(self.done_run(tracker))
        self.assertIn("- Tracker-Status: done · 2/2 Kriterien abgehakt", text)
        self.assertIn("- Nächster Schritt: ISSUE-005 – Title ISSUE-005 (schaltet 2 Issues frei)", text)
        self.assertIn(f"Prompt für den nächsten Lauf:\n~~~\n/cmux-issue-chain {tracker} ISSUE-005\n~~~", text)
        self.assertIn("  außerdem startbar: ISSUE-004, ISSUE-008 (HITL)", text)
        (tracker / "issues" / "ISSUE-004-slug.md").write_text(issue_file("ISSUE-004", status="in_progress"))
        text = self.recap(self.done_run(tracker, run_id="chain-issue-003-second"))
        self.assertIn("- Nächster Schritt: ISSUE-004 – Title ISSUE-004\n", text)

    def test_only_hitl_ready_is_named_for_the_human(self):
        tracker = self.tracker({
            "ISSUE-003": issue_file("ISSUE-003", status="done"),
            "ISSUE-004": issue_file("ISSUE-004", issue_type="HITL"),
        })
        text = self.recap(self.done_run(tracker))
        self.assertIn("- Nächster Schritt: ISSUE-004 – Title ISSUE-004 (HITL, liegt beim Menschen)", text)
        self.assertNotIn("Start:", text)

    def test_blocked_and_complete_trackers(self):
        tracker = self.tracker({
            "ISSUE-003": issue_file("ISSUE-003", status="in_review"),
            "ISSUE-004": issue_file("ISSUE-004", blockers=("ISSUE-003",)),
        })
        text = self.recap(self.done_run(tracker))
        self.assertIn("- Nächster Schritt: keins startbar – ISSUE-004 wartet auf ISSUE-003", text)
        (tracker / "issues" / "ISSUE-003-slug.md").write_text(issue_file("ISSUE-003", status="done"))
        (tracker / "issues" / "ISSUE-004-slug.md").write_text(issue_file("ISSUE-004", status="done"))
        text = self.recap(self.done_run(tracker, run_id="chain-issue-003-second"))
        self.assertIn("- Nächster Schritt: Tracker vollständig erledigt", text)

    def test_halted_run_has_no_next_issue(self):
        tracker = self.tracker({"ISSUE-004": issue_file("ISSUE-004")})
        run_dir = self.run_dir({**DONE_ISSUE_STATE, "tracker": str(tracker), "current_stage": "review"})
        (run_dir / "events.jsonl").write_text(json.dumps(event("gate", stage="review", decision="hitl", reason="r")) + "\n")
        self.assertNotIn("Nächster Schritt", self.recap(run_dir))

    def test_override_needs_a_startable_issue_and_a_reason(self):
        tracker = self.tracker({
            "ISSUE-004": issue_file("ISSUE-004"),
            "ISSUE-005": issue_file("ISSUE-005"),
            "ISSUE-006": issue_file("ISSUE-006", blockers=("ISSUE-009",)),
        })
        run_dir = self.done_run(tracker)
        path = run_dir / "recap.md"
        default = self.recap(run_dir)
        self.assertIn("ISSUE-004 – Title ISSUE-004", default)
        path.write_text(default.replace("ISSUE-004 – Title ISSUE-004", "ISSUE-006 – Title ISSUE-006"))
        refused = self.show(run_dir)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("ISSUE-006 is not startable", refused.stderr)
        overridden = default.replace("ISSUE-004 – Title ISSUE-004", "ISSUE-005 – Title ISSUE-005")
        path.write_text(overridden)
        refused = self.show(run_dir)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("deviates from the default ISSUE-004", refused.stderr)
        reasoned = overridden.replace(
            "ISSUE-005 – Title ISSUE-005\n", "ISSUE-005 – Title ISSUE-005\n  Begründung: shares files with ISSUE-003\n"
        )
        path.write_text(reasoned)
        refused = self.show(run_dir)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("must name ISSUE-005", refused.stderr)
        path.write_text(reasoned.replace(f"{tracker} ISSUE-004", f"{tracker} ISSUE-005"))
        accepted = self.show(run_dir)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        logged = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(
            logged["data"]["next_step"],
            {"default": "ISSUE-004", "chosen": "ISSUE-005", "override": True, "prompt_edited": False},
        )

    def test_removed_next_step_or_prompt_is_refused(self):
        tracker = self.tracker({"ISSUE-004": issue_file("ISSUE-004")})
        run_dir = self.done_run(tracker)
        path = run_dir / "recap.md"
        default = self.recap(run_dir)
        path.write_text(default.replace("- Nächster Schritt: ISSUE-004 – Title ISSUE-004", "- Nächster Schritt: offen"))
        refused = self.show(run_dir)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("next-step line naming one of ISSUE-004 is missing", refused.stderr)
        path.write_text(default.split("\nPrompt für den nächsten Lauf:")[0] + "\n")
        refused = self.show(run_dir)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("prompt for the next run is missing", refused.stderr)
        self.assertFalse(any(e["type"] == "run.recap" for e in map(json.loads, (run_dir / "events.jsonl").read_text().splitlines())))

    def test_broken_json_is_reported_not_raised(self):
        run_dir = self.run_dir(ISSUE_STATE)
        (run_dir / "events.jsonl").write_text('{"type": "gate"}\n{"type": "ga', encoding="utf-8")
        result = self.call("draft", "--run-dir", str(run_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("events.jsonl:2 is not valid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        artifact = self.root / "broken.json"
        artifact.write_text('{"open_decisions": [],}', encoding="utf-8")
        grilling = {**GRILLING_STATE, "created_at": "2026-09-23T08:00:00+00:00", "current_stage": "done",
                    "deliverables": {"json": str(artifact)}}
        run_dir = self.run_dir(grilling)
        result = self.call("recap-draft", "--run-dir", str(run_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken.json:1 is not valid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((run_dir / "recap.md").exists())

    def invoked_run(self, tracker: Path, invocation: str) -> Path:
        issue = {**DONE_ISSUE_STATE["issue"], "path": str(tracker / "issues" / "ISSUE-003-slug.md")}
        state = {**DONE_ISSUE_STATE, "tracker": str(tracker), "issue": issue, "invocation": invocation}
        run_dir = self.run_dir(state)
        (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in DONE_ISSUE_EVENTS), encoding="utf-8")
        return run_dir

    def test_prompt_reuses_the_initial_invocation_with_the_next_issue(self):
        tracker = self.tracker({
            "ISSUE-003": issue_file("ISSUE-003", status="done"),
            "ISSUE-004": issue_file("ISSUE-004", blockers=("ISSUE-003",)),
        })
        invocation = "/cmux-issue-chain tracker ISSUE-003\nsiehe ISSUE-003-slug.md, bitte Tests zuerst"
        text = self.recap(self.invoked_run(tracker, invocation))
        self.assertIn(
            "~~~\n/cmux-issue-chain tracker ISSUE-004\nsiehe ISSUE-004-slug.md, bitte Tests zuerst\n~~~", text
        )
        self.assertNotIn("unverändert", text)

    def test_prompt_without_the_issue_is_repeated_and_flagged(self):
        tracker = self.tracker({"ISSUE-004": issue_file("ISSUE-004")})
        text = self.recap(self.invoked_run(tracker, "/cmux-issue-chain nimm das nächste ready Issue"))
        self.assertIn("~~~\n/cmux-issue-chain nimm das nächste ready Issue\n~~~", text)
        self.assertIn("steht nicht im ursprünglichen Prompt", text)
        self.assertEqual(self.show(self.root / DONE_ISSUE_STATE["run_id"]).returncode, 0)

    def test_stripping_an_addition_needs_a_reason(self):
        tracker = self.tracker({"ISSUE-004": issue_file("ISSUE-004")})
        run_dir = self.invoked_run(tracker, "/cmux-issue-chain tracker ISSUE-003 achte auf den Porcelain-Parser")
        path = run_dir / "recap.md"
        stripped = self.recap(run_dir).replace(" achte auf den Porcelain-Parser", "")
        path.write_text(stripped)
        refused = self.show(run_dir)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("deviates from the generated one", refused.stderr)
        path.write_text(stripped.replace(
            "ISSUE-004 – Title ISSUE-004\n", "ISSUE-004 – Title ISSUE-004\n  Begründung: parser note was ISSUE-003 only\n"
        ))
        accepted = self.show(run_dir)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        logged = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertTrue(logged["data"]["next_step"]["prompt_edited"])
        self.assertFalse(logged["data"]["next_step"]["override"])

    def test_planning_and_grilling_next_steps(self):
        tracker = self.tracker({"ISSUE-001": issue_file("ISSUE-001"), "ISSUE-002": issue_file("ISSUE-002", blockers=("ISSUE-001",))})
        state = {
            **PLANNING_STATE,
            "created_at": "2026-09-23T08:00:00+00:00",
            "current_stage": "complete",
            "published_tracker": {"path": str(tracker), "ticket_ids": ["ISSUE-001", "ISSUE-002"], "ready_frontier": ["ISSUE-001"]},
        }
        run_dir = self.run_dir(state)
        (run_dir / "events.jsonl").write_text(json.dumps(event("tracker.published")) + "\n")
        text = self.recap(run_dir)
        self.assertIn("- Nächster Schritt: Issue-Chain mit ISSUE-001 – Title ISSUE-001 (schaltet 1 Issue frei)", text)
        self.assertIn(f"~~~\n/cmux-issue-chain {tracker} ISSUE-001\n~~~", text)
        artifact = self.root / "result.json"
        grilling = {**GRILLING_STATE, "created_at": "2026-09-23T08:00:00+00:00", "current_stage": "done",
                    "deliverables": {"json": str(artifact)}}
        run_dir = self.run_dir(grilling)
        (run_dir / "events.jsonl").write_text(json.dumps(event("run.completed")) + "\n")
        artifact.write_text(json.dumps({"open_decisions": [{"status": "open"}, {"status": "decided"}]}))
        text = self.recap(run_dir)
        self.assertIn("- Nächster Schritt: 1 offene Entscheidung im Walkthrough klären", text)
        self.assertNotIn("Prompt", text)
        (run_dir / "recap.md").unlink()
        artifact.write_text(json.dumps({"open_decisions": [{"status": "decided"}]}))
        text = self.recap(run_dir)
        self.assertIn("- Nächster Schritt: Planning mit dem Grilling-Ergebnis", text)
        self.assertIn(f"~~~\n/cmux-planning {artifact}\n~~~", text)

    def test_candidates_match_the_issue_chain_ready_rule(self):
        try:
            from orchestrator_lib import issue_ready, load_issues
        except ImportError:
            self.skipTest("only cmux-issue-chain ships the canonical ready rule")
        tracker = self.tracker({
            "ISSUE-001": issue_file("ISSUE-001", status="done"),
            "ISSUE-002": issue_file("ISSUE-002", blockers=("ISSUE-001",)),
            "ISSUE-003": issue_file("ISSUE-003", status="in_progress", blockers=("ISSUE-002",)),
            "ISSUE-004": issue_file("ISSUE-004", blockers=("ISSUE-099",)),
            "ISSUE-005": issue_file("ISSUE-005", issue_type="HITL"),
        })
        canonical = load_issues(tracker)
        expected = sorted(issue_id for issue_id, issue in canonical.items() if issue_ready(issue, canonical))
        afk = [issue["id"] for issue in run_briefing.ranked_candidates(run_briefing.load_tracker(tracker))
               if issue["type"].upper() != "HITL"]
        self.assertEqual(sorted(afk), expected)




class CommitRecap(unittest.TestCase):
    def test_outcomes_and_hook_suffixes_both_languages(self):
        for lang, skipped, failed, proposal, modified, effects in (
            ('en', 'Commit skipped', 'Commit failed', 'proposal', 'modified by hook: 2 files', 'hook side effects: fx'),
            ('de', 'Commit übersprungen', 'Commit fehlgeschlagen', 'Vorschlag', 'vom Hook geändert: 2 Dateien', 'Hook-Nebeneffekte: fx')):
            labels = run_briefing.LABELS[lang]
            created = {'type':'commit.created', 'data':{'sha':'123456789', 'subject':'Subject', 'hook_modified':['a','b'], 'hook_side_effects':['fx']}}
            events = [created, {'type':'commit.proposed', 'data':{'subject':'Later draft'}}]
            text = run_briefing.render_recap(DONE_ISSUE_STATE, events, lang)
            self.assertIn(f'- Commit: 1234567 Subject; {modified}; {effects}', text)
            self.assertNotIn('Later draft', text)
            text = run_briefing.commit_recap([{'type':'commit.failed', 'data':{'reason':'commit-error', 'subject':'Subject', 'summary':'Hook said NO'}}], labels)
            self.assertEqual(text, [f'- {failed}: Hook said NO, {proposal}: Subject'])
            for reason, english, german in (
                ('all-ignored', 'all run files are ignored by Git', 'alle Run-Dateien sind von Git ignoriert'),
                ('no-changes', 'no run file has changes', 'keine Run-Datei hat Änderungen')):
                data = {'reason':reason}
                text = run_briefing.commit_recap([{'type':'commit.skipped', 'data':data}], labels)
                self.assertEqual(text, [f'- {skipped}: ' + (english if lang=='en' else german)])

    def test_every_failure_label_and_recorded_head(self):
        cases = [
            ('preexisting-changes', 'pre-run changes in a', 'Änderungen vor dem Lauf in a'),
            ('index-not-empty', 'staged changes outside the run in a', 'vorgemerkte Änderungen außerhalb des Laufs in a'),
            ('not-a-leaf', 'not a single file: a', 'keine einzelne Datei: a'),
            ('stage-error', 'staging failed: Failed', 'Vormerken fehlgeschlagen: Failed'),
            ('staged-set-mismatch', 'staged paths differ from the run files: extra: x; missing: y', 'vorgemerkte Pfade weichen von den Run-Dateien ab: extra: x; missing: y'),
            ('hook-added-paths', 'a hook added a', 'ein Hook hat a hinzugefügt'),
            ('unverifiable', 'could not be verified (HEAD abcdef0 may be the run commit, please check)', 'nicht verifizierbar (HEAD abcdef0 könnte der Run-Commit sein, bitte prüfen)'),
            ('no-head', 'the repository has no commit yet', 'das Repository hat noch keinen Commit'),
        ]
        for lang in ('en','de'):
            for reason, english, german in cases:
                with self.subTest(lang=lang, reason=reason):
                    data = dict(reason=reason, paths=['a'], subject='Draft', head='abcdef012345', summary='Failed', extra=['x'], missing=['y'])
                    text = run_briefing.commit_recap([{'type':'commit.failed','data':data}], run_briefing.LABELS[lang])[0]
                    expected = english if lang=='en' else german
                    prefix = '- Commit failed: ' if lang=='en' else '- Commit fehlgeschlagen: '
                    suffix = ', proposal: Draft' if lang=='en' else ', Vorschlag: Draft'
                    self.assertEqual(text, prefix + expected + suffix)
                    if reason=='hook-added-paths':
                        data['reset']=False
                        text = run_briefing.commit_recap([{'type':'commit.failed','data':data}], run_briefing.LABELS[lang])[0]
                        self.assertEqual(text, prefix + expected + (' (commit kept)' if lang=='en' else ' (Commit behalten)') + suffix)

    def test_pending_attempt_uses_proposal_and_absent_commit_is_silent(self):
        for lang in ('en', 'de'):
            labels = run_briefing.LABELS[lang]
            self.assertEqual(run_briefing.commit_recap([], labels), [])
            self.assertEqual(run_briefing.commit_recap([
                {'type':'commit.proposed','data':{'subject':'Draft'}},
                {'type':'commit.attempted','data':{'subject':'Draft'}}], labels),
                ['- ' + labels['commit_proposal'] + ': Draft'])


if __name__ == "__main__":
    unittest.main()
