#!/usr/bin/env python3
"""Regression tests for orchestrator_usage.py: workflow detection and call classification."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import orchestrator_usage as ou

CHAIN = ou.WORKFLOWS["issue-chain"]
PLANNING = ou.WORKFLOWS["planning"]
GRILLING = ou.WORKFLOWS["grilling"]


def evidence_for(workflow, *commands):
    evidence = ou.new_evidence()
    for command in commands:
        ou.scan_command(command, evidence, workflow)
    return evidence


class WorkflowDetection(unittest.TestCase):
    def test_skill_directory_identifies_the_workflow(self):
        command = "python3 ~/.claude/skills/cmux-planning/scripts/pane_ctl.py observe"
        self.assertTrue(ou.is_orchestrator(evidence_for(PLANNING, command)))
        self.assertFalse(ou.is_orchestrator(evidence_for(CHAIN, command)))
        self.assertFalse(ou.is_orchestrator(evidence_for(GRILLING, command)))

    def test_workflow_only_script_identifies_the_workflow_behind_a_variable(self):
        self.assertTrue(ou.is_orchestrator(evidence_for(GRILLING, 'python3 "$S/launch_wave.py" --round 1')))
        self.assertTrue(ou.is_orchestrator(evidence_for(PLANNING, "python3 $S/tree_integrity.py baseline")))
        self.assertTrue(ou.is_orchestrator(evidence_for(CHAIN, "python3 $S/issue_state.py set")))
        # A sibling's only-script is never evidence for another workflow.
        self.assertFalse(evidence_for(CHAIN, "python3 $S/launch_wave.py")["soft"])
        self.assertFalse(evidence_for(GRILLING, "python3 $S/tree_integrity.py")["soft"])

    def test_composite_scripts_count_as_orchestrator_executions(self):
        for script in ("stage.py capture", "wave.py round", "baseline_delta.py --run-dir r"):
            with self.subTest(script=script):
                self.assertTrue(evidence_for(PLANNING, f"python3 $S/{script}")["soft"])

    def test_shared_script_behind_a_variable_needs_the_skill_directory(self):
        command = "python3 $S/run_state.py event"
        self.assertFalse(ou.is_orchestrator(evidence_for(PLANNING, command)))
        self.assertTrue(ou.is_orchestrator(evidence_for(
            PLANNING, "S=~/.claude/skills/cmux-planning/scripts", command)))

    def test_mixed_session_counts_where_it_touched_a_run_of_the_workflow(self):
        commands = ("S=/x/cmux-planning/scripts; T=/x/cmux-grilling/scripts",
                    "python3 $S/run_state.py event --run-dir .scratch/orchestrator/runs/plan-demo-1")
        self.assertTrue(ou.is_orchestrator(evidence_for(PLANNING, *commands)))
        self.assertFalse(ou.is_orchestrator(evidence_for(GRILLING, *commands)))

    def test_run_prefix_attributes_runs(self):
        self.assertTrue(PLANNING.owns_run("plan-demo-2026-09-22-1702"))
        self.assertTrue(GRILLING.owns_run("grill-demo"))
        self.assertTrue(CHAIN.owns_run("chain-issue-001"))
        for run in ("plan-demo", "grill-demo"):
            self.assertFalse(CHAIN.owns_run(run))
        self.assertFalse(PLANNING.owns_run("grill-demo"))
        self.assertFalse(GRILLING.owns_run("chain-issue-001"))

    def test_quoted_invocation_is_discussion_not_execution(self):
        command = "grep -n 'python3 cmux-grilling/scripts/launch_wave.py' README.md"
        self.assertFalse(ou.is_orchestrator(evidence_for(GRILLING, command)))


class Classification(unittest.TestCase):
    def test_report_capture_is_not_a_screen_read_after_wait(self):
        for command in (
            'python3 $S/run_state.py snapshot --label "report-captured review-1"',
            'python3 $S/run_state.py event --message "review report captured"',
            'python3 $S/run_state.py event --message "confirmed via read-screen"',
            'python3 $S/run_state.py event --message "launch and capture snapshots agree"',
            'python3 $S/run_state.py event --message "checked read-screen output"',
            "python3 $S/run_state.py snapshot --label 'checked capture-pane output'",
            'python3 $S/run_state.py event --message="checked read-screen output"',
            'python3 $S/run_state.py snapshot --label=read-screen',
        ):
            with self.subTest(command=command):
                self.assertEqual(ou.classify_bash(command, "wait"), "bookkeeping")

    def test_executable_quoted_screen_reads_still_count(self):
        for command in (
            'screen="$(cmux read-screen --surface s)"',
            'bash -c "cmux read-screen --surface s"',
            "bash -c 'cmux capture-pane --surface s'",
            'python3 run_state.py event --message "checked read-screen output"; '
            'bash -c "cmux read-screen --surface s"',
        ):
            for previous, expected in ((None, "pane-lifecycle"), ("wait", "wait"),
                                       ("reply-after-wait", "wait")):
                with self.subTest(command=command, previous=previous):
                    self.assertEqual(ou.classify_bash(command, previous), expected)

    def test_actual_screen_commands_still_count_after_wait(self):
        for command in (
            'cmux read-screen --surface s',
            'cmux capture-pane --surface s',
            'cmux capture --surface s',
            'python3 $S/pane_ctl.py cmux --run-dir r -- read-screen --surface s',
            'cmux read-screen --surface "$S";echo',
            'out=$(cmux read-screen --surface s)',
        ):
            with self.subTest(command=command):
                self.assertEqual(ou.classify_bash(command, "wait"), "wait")
                self.assertEqual(ou.classify_bash(command), "pane-lifecycle")

    def test_stage_capture_after_monitor_is_bookkeeping(self):
        previous = ou.classify_tool("Monitor", None)
        self.assertEqual(previous, "wait")
        self.assertEqual(ou.classify_bash("python3 $S/stage.py capture --run-dir r", previous),
                         "bookkeeping")
        # The plain screen read after a wait stays a wait.
        self.assertEqual(ou.classify_bash("cmux read-screen --surface s", previous), "wait")

    def test_composite_verbs_are_classified_by_verb(self):
        expected = {"open": "pane-lifecycle", "round": "pane-lifecycle",
                    "deliver": "pane-lifecycle", "started": "pane-lifecycle",
                    "mark-started": "pane-lifecycle", "capture": "bookkeeping",
                    "gate": "bookkeeping"}
        for verb, category in expected.items():
            for script in ("stage.py", "wave.py"):
                with self.subTest(script=script, verb=verb):
                    self.assertEqual(ou.classify_bash(f"python3 $S/{script} {verb} --run-dir r",
                                                      "wait"), category)

    def test_baseline_delta_is_bookkeeping(self):
        self.assertEqual(ou.classify_bash("python3 $S/baseline_delta.py --run-dir r"), "bookkeeping")

    def test_existing_rules_are_unchanged(self):
        self.assertEqual(ou.classify_bash("python3 $S/pane_ctl.py deliver"), "pane-lifecycle")
        self.assertEqual(ou.classify_bash("cmux read-screen --surface s"), "pane-lifecycle")
        self.assertEqual(ou.classify_bash("python3 $S/await_report.py --run-dir r"), "wait")


def write_transcript(path: Path, commands: list[str], first_user: str = "run the grilling"):
    lines = [{"type": "user", "cwd": "/repo", "message": {"content": first_user}}]
    for index, command in enumerate(commands):
        lines.append({
            "type": "assistant", "requestId": f"req-{index}", "cwd": "/repo",
            "timestamp": f"2026-09-13T10:0{index}:00Z",
            "message": {"usage": {"input_tokens": 10, "output_tokens": 5,
                                  "cache_read_input_tokens": 1000},
                        "content": [{"type": "tool_use", "name": "Bash",
                                     "input": {"command": command}}]},
        })
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


class ClaudeSessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"

    def test_watcher_then_report_capture_does_not_inflate_wait_count(self):
        write_transcript(self.path, [
            "python3 cmux-issue-chain/scripts/run_state.py init --run-dir .scratch/orchestrator/runs/chain-demo",
            "python3 $S/await_report.py --run-dir .scratch/orchestrator/runs/chain-demo",
            'python3 $S/run_state.py snapshot --label "report-captured review-1"',
            'python3 $S/run_state.py event --message "launch and capture snapshots agree"',
        ])
        session = ou.parse_claude(self.path, CHAIN)
        self.assertEqual(session["purpose_calls"]["wait"], 1)
        self.assertEqual(session["purpose_calls"]["bookkeeping"], 3)

    def test_watcher_then_quoted_screen_reads_count_as_waits(self):
        write_transcript(self.path, [
            "python3 cmux-issue-chain/scripts/run_state.py init --run-dir .scratch/orchestrator/runs/chain-demo",
            "python3 $S/await_report.py --run-dir .scratch/orchestrator/runs/chain-demo",
            'screen="$(cmux read-screen --surface s)"',
            'bash -c "cmux read-screen --surface s"',
            "bash -c 'cmux capture-pane --surface s'",
            'python3 $S/run_state.py event --message "checked read-screen output"',
        ])
        session = ou.parse_claude(self.path, CHAIN)
        self.assertEqual(session["purpose_calls"]["wait"], 4)
        self.assertEqual(session["purpose_calls"]["bookkeeping"], 2)

    def test_grilling_session_is_selected_only_for_grilling(self):
        write_transcript(self.path, [
            "python3 cmux-grilling/scripts/run_state.py init --run-dir .scratch/orchestrator/runs/grill-demo",
        ])
        session = ou.parse_claude(self.path, GRILLING)
        self.assertIsNotNone(session)
        self.assertEqual(session["run_ids"], ["grill-demo"])
        self.assertIsNone(ou.parse_claude(self.path, CHAIN))
        self.assertIsNone(ou.parse_claude(self.path, PLANNING))

    def test_worker_session_is_never_an_orchestrator(self):
        write_transcript(
            self.path, ["python3 cmux-grilling/scripts/run_state.py status"],
            first_user="Your round task is in .scratch/orchestrator/runs/grill-demo/prompts/round-1-web.md.")
        self.assertIsNone(ou.parse_claude(self.path, GRILLING))


class GrillingFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        run_dir = self.root / ".scratch" / "orchestrator" / "runs" / "grill-demo"
        (run_dir / "reports").mkdir(parents=True)
        for name in ("round-1-web", "round-1-docs", "round-2-web", "round-2-docs", "notes"):
            (run_dir / "reports" / f"{name}.md").write_text("x", encoding="utf-8")
        events = [
            {"type": "run.init", "time": "2026-09-13T10:00:00+00:00"},
            {"type": "grill.question", "time": "2026-09-13T10:02:30+00:00"},
            {"type": "grill.question", "time": "2026-09-13T10:05:00+00:00"},
        ]
        (run_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events), encoding="utf-8")
        self.run_dir = run_dir

    def call(self, minute, total):
        call = ou.Call(f"2026-09-13T10:0{minute}:00+00:00", total, 0, 0, 0, None)
        call.category = "other-bash"
        call.run_id = "grill-demo"
        return call


class GrillingRounds(GrillingFixture):
    def test_rounds_are_the_stage_unit(self):
        state = ou.read_run_state(self.run_dir, GRILLING)
        self.assertEqual(state["stages_completed"], 2)
        self.assertEqual(state["first_question"], "2026-09-13T10:02:30+00:00")
        # Without the workflow every report file stays its own stage, as before.
        self.assertEqual(ou.read_run_state(self.run_dir)["stages_completed"], 5)

    def test_session_start_is_reported_apart_from_the_rounds(self):
        calls = [self.call(0, 100), self.call(1, 100), self.call(2, 100),
                 self.call(3, 400), self.call(4, 400), self.call(5, 400), self.call(6, 400)]
        session = ou.build_session("claude", "s1", "p", str(self.root), calls)
        [row] = ou.aggregate_runs([session], GRILLING)
        self.assertEqual(row["session_start_calls"], 3)
        self.assertEqual(row["session_start_tokens"], 300)
        self.assertEqual(row["calls_per_stage"], 2.0)
        self.assertEqual(row["tokens_per_stage"], 800)

    def test_other_workflows_keep_their_columns(self):
        calls = [self.call(0, 100)]
        session = ou.build_session("claude", "s1", "p", str(self.root), calls)
        self.assertEqual(ou.aggregate_runs([session], PLANNING), [])
        chain_rows = ou.aggregate_runs([session])
        self.assertTrue(chain_rows)
        self.assertNotIn("session_start_calls", chain_rows[0])


class RunAttribution(GrillingFixture):
    def events(self, run="grill-demo", **kwargs):
        directory = self.root / ".scratch/orchestrator/runs" / run
        directory.mkdir(parents=True, exist_ok=True)
        events = [{"type": "run.init", "time": "2026-09-13T10:01:00Z"},
                  {"type": "grill.question", "time": "2026-09-13T10:02:00Z"},
                  {"type": "grill.question", "time": "2026-09-13T10:02:10Z"},
                  {"type": "grill.question", "time": "2026-09-13T10:02:20Z"},
                  {"type": "run.completed", "time": "2026-09-13T10:04:00Z"}]
        events[0].update(kwargs)
        (directory / "events.jsonl").write_text("\n".join(map(json.dumps, events)))
        return directory

    def parsed(self, owners, sid="owner"):
        return ou.parsed_session("claude", sid, "p", str(self.root),
                                 [self.call(i, 100) for i in range(7)], [], owners)

    def test_modes_and_missing_directory(self):
        for flags, expected in (([], ""), ([False], "old-start"), ([True, True], "new-start"),
                                ([False, True], "mixed")):
            self.events()
            with (self.run_dir / "events.jsonl").open("a") as fh:
                for flag in flags:
                    fh.write("\n" + json.dumps({"type": "worker.launch_sent",
                                                "data": {"prompt_path": "p"} if flag else {}}))
            self.assertEqual(ou.read_run_state(self.run_dir)["start_mode"], expected)
        session = ou.build_session("claude", "s", "p", "/does-not-exist", [self.call(1, 10)])
        self.assertEqual(ou.aggregate_runs([session], GRILLING)[0]["start_mode"], "")

    def test_mentions_do_not_own_and_windows_exclude_unrelated_work(self):
        self.events()
        sessions = ou.owned_session_windows([self.parsed(["grill-demo"]), self.parsed([], "analysis")], GRILLING)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["calls"], 4)
        [row] = ou.aggregate_runs(sessions, GRILLING)
        self.assertEqual(row["questions"], 3)
        self.assertEqual(row["calls_per_question"], 1)
        self.assertEqual(row["tokens_per_question"], 100)
        self.assertEqual(row["sessions"], "owner")

    def test_event_owner_and_recap_fallback(self):
        self.events(data={"orchestrator_session_id": "owner"})
        path = self.run_dir / "events.jsonl"
        path.write_text(path.read_text().replace("run.completed", "run.recap"))
        self.assertEqual(ou.owned_session_windows([self.parsed([])], GRILLING)[0]["calls"], 4)

    def test_multiple_runs_and_open_window(self):
        self.events()
        second = self.events("plan-second")
        path = second / "events.jsonl"
        path.write_text(path.read_text().replace("10:01", "10:05").replace("10:04", "10:06"))
        session = self.parsed(["grill-demo", "plan-second"])
        self.assertEqual(ou.owned_session_windows([session], GRILLING)[0]["calls"], 4)
        self.assertEqual(ou.owned_session_windows([session], PLANNING)[0]["calls"], 2)
        path = self.run_dir / "events.jsonl"
        path.write_text("\n".join(l for l in path.read_text().splitlines() if "run.completed" not in l))
        self.assertEqual(ou.owned_session_windows([session], GRILLING)[0]["calls"], 4)

    def test_init_pair_generated_id_and_discussion(self):
        path = self.root / "owner.jsonl"
        write_transcript(path, ["python3 cmux-grilling/scripts/run_state.py init --slug demo"])
        events = [json.loads(l) for l in path.read_text().splitlines()]
        events[1]["message"]["content"][0]["id"] = "init"
        events += [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "init", "content": ".scratch/orchestrator/runs/grill-demo"}]}}]
        path.write_text("\n".join(map(json.dumps, events)))
        self.assertEqual(ou.parse_claude(path, GRILLING)["owned_runs"], ["grill-demo"])
        self.assertFalse(ou.executed_init("grep 'python3 cmux-grilling/scripts/run_state.py init' log"))
        self.assertEqual(ou.owned_session_windows([self.parsed([])], GRILLING), [])

    def test_planning_init_pair(self):
        path = self.root / "planner.jsonl"
        write_transcript(path, ["python3 cmux-planning/scripts/planning_state.py init --task-file t.md --repo ."])
        events = [json.loads(l) for l in path.read_text().splitlines()]
        events[1]["message"]["content"][0]["id"] = "init"
        events += [{"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "init", "content": ".scratch/orchestrator/runs/plan-demo"}]}}]
        path.write_text("\n".join(map(json.dumps, events)))
        self.assertEqual(ou.parse_claude(path, PLANNING)["owned_runs"], ["plan-demo"])
        self.assertFalse(ou.executed_init("python3 cmux-planning/scripts/planning_state.py status"))

    def worker(self, harness, workflow, prompt_name):
        run = {"grilling": "grill-demo", "planning": "plan-demo", "issue-chain": "chain-demo"}[workflow.name]
        prompt = f"Your standing contract is in .scratch/orchestrator/runs/{run}/prompts/{prompt_name}.md."
        path = self.root / f"{harness}.jsonl"
        if harness == "claude":
            write_transcript(path, ["echo working"] * 4, prompt)
            lines = [json.loads(l) for l in path.read_text().splitlines()]
            for ev in lines:
                ev["cwd"] = str(self.root)
        else:
            lines = [{"type": "session_meta", "payload": {"id": "codex-lane", "cwd": str(self.root)}},
                     {"type": "response_item", "payload": {"type": "message", "role": "user",
                      "content": [{"type": "input_text", "text": "# AGENTS.md instructions\n# nested heading\nRules"},
                                  {"type": "input_text", "text": "<environment_context>env</environment_context>"}]}},
                     {"type": "response_item", "payload": {"type": "message", "role": "user", "content": prompt}}]
            lines.append({"type": "response_item", "payload": {
                "type": "function_call", "name": "exec_command",
                "arguments": json.dumps({"cmd": f"python3 {workflow.subdir}/scripts/run_state.py status"})}})
            for i in range(4):
                lines.append({"type": "event_msg", "timestamp": f"2026-09-13T10:0{i}:00Z",
                              "payload": {"type": "token_count", "info": {"total_token_usage":
                                          {"input_tokens": 100 * (i + 1), "total_tokens": 100 * (i + 1)}}}})
        path.write_text("\n".join(map(json.dumps, lines)))
        parser = ou.parse_claude if harness == "claude" else ou.parse_codex
        self.assertIsNone(parser(path, workflow))
        session = parser(path, workflow, include_workers=True)
        self.assertEqual(session["worker_runs"], [run])
        self.assertEqual(ou.owned_session_windows([session], workflow), [])
        return session

    def test_workers_all_workflows_and_harnesses(self):
        for workflow in (CHAIN, PLANNING, GRILLING):
            for harness in ("claude", "codex"):
                for prompt in ("session-docs", "round-1-docs", "implement-1"):
                    with self.subTest(workflow=workflow.name, harness=harness, prompt=prompt):
                        self.worker(harness, workflow, prompt)

    def test_worker_totals_and_round_question_denominators(self):
        self.events()
        workers = [self.worker(h, GRILLING, "session-docs") for h in ("claude", "codex")]
        rows = ou.aggregate_runs(ou.owned_session_windows([self.parsed(["grill-demo"])], GRILLING), GRILLING)
        ou.add_worker_usage(rows, workers, GRILLING)
        row = rows[0]
        self.assertEqual(row["harnesses"], "claude")
        self.assertEqual(row["worker_sessions"], 2)
        self.assertEqual(row["worker_tokens_claude"], 4060)
        self.assertEqual(row["worker_tokens_codex"], 400)
        self.assertEqual(row["worker_tokens"], 4460)
        self.assertEqual(row["worker_tokens_per_round"], 1115)
        self.assertEqual(row["worker_tokens_per_question"], 743)
        self.assertEqual(row["worker_tokens_per_round_codex"], 100)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ou.print_start_summary([], rows, GRILLING)
        self.assertIn("start_mode", output.getvalue())

    def test_worker_run_ids_only_come_from_assignment_prompt_paths(self):
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness):
                self.worker(harness, GRILLING, "session-docs")
                path = self.root / f"{harness}.jsonl"
                text = path.read_text().replace(
                    "session-docs.md.",
                    "session-docs.md. Read .scratch/orchestrator/runs/grill-reference/reports/round-1.md "
                    "and .scratch/orchestrator/runs/plan-reference/events.jsonl for context.")
                path.write_text(text)
                parser = ou.parse_claude if harness == "claude" else ou.parse_codex
                session = parser(path, GRILLING, include_workers=True)
                self.assertEqual(session["worker_runs"], ["grill-demo"])

    def test_codex_worker_prompt_shares_message_with_agents_and_environment(self):
        self.worker("codex", GRILLING, "session-docs")
        path = self.root / "codex.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        prompt = events.pop(2)["payload"]["content"]
        events[1]["payload"]["content"].append({"type": "input_text", "text": prompt})
        path.write_text("\n".join(map(json.dumps, events)))
        self.assertIsNone(ou.parse_codex(path, GRILLING))
        session = ou.parse_codex(path, GRILLING, include_workers=True)
        self.assertEqual(session["worker_runs"], ["grill-demo"])
        self.assertEqual(ou.owned_session_windows([session], GRILLING), [])

    def test_missing_state_window_keeps_calls_until_next_run_mention(self):
        calls = [self.call(i, 10 * (i + 1)) for i in range(7)]
        for call, run in zip(calls, (None, "grill-missing", None, None,
                                     "grill-other", None, None)):
            call.run_id = run
        session = ou.parsed_session("claude", "owner", "p", str(self.root), calls,
                                    [], ["grill-missing", "grill-other"])
        windows = ou.owned_session_windows([session], GRILLING)
        self.assertEqual(len(windows), 2)
        by_run = {s["run_ids"][0]: s for s in windows}
        self.assertEqual(by_run["grill-missing"]["calls"], 3)
        self.assertEqual(by_run["grill-missing"]["tokens_total"], 90)
        self.assertEqual(by_run["grill-other"]["calls"], 3)
        self.assertEqual(by_run["grill-other"]["tokens_total"], 180)

    def test_run_project_without_run_root_uses_cwd_project_name(self):
        with patch.object(ou, "project_root", return_value=None):
            self.assertEqual(ou.run_project("/projects/example-app"), "-projects-example-app")

    def test_start_summary_matches_both_session_id_and_run_id(self):
        self.events()
        sessions = ou.owned_session_windows([self.parsed(["grill-demo"], "owner123-long")], GRILLING)
        rows = ou.aggregate_runs(sessions, GRILLING)
        rows[0]["start_mode"] = "new-start"
        # A different cwd/project must not break the row's explicit owner link.
        owner = dict(sessions[0], cwd="/unrelated/cwd", project="different-project")
        wrong_session = dict(owner, session_id="outsider-long", avg_context_per_call=900)
        wrong_run = dict(owner, run_ids=["grill-other"], avg_context_per_call=700)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ou.print_start_summary([owner, wrong_session, wrong_run], rows, GRILLING)
        line = next(line for line in output.getvalue().splitlines() if line.startswith("new-start "))
        fields = line.split()
        self.assertEqual(fields[1:3], ["1", "1"])
        self.assertEqual(float(fields[5]), 100)

    def test_codex_init_output_owns_generated_run(self):
        path = self.root / "codex-owner.jsonl"
        events = [
            {"type": "session_meta", "payload": {"id": "owner", "cwd": str(self.root)}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "start grilling"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "init",
             "arguments": json.dumps({"cmd": "python3 cmux-grilling/scripts/run_state.py init --slug demo"})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "init",
             "output": ".scratch/orchestrator/runs/grill-demo"}},
            {"type": "event_msg", "timestamp": "2026-09-13T10:02:00Z",
             "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "total_tokens": 100}}}},
        ]
        path.write_text("\n".join(map(json.dumps, events)))
        self.events()
        session = ou.parse_codex(path, GRILLING)
        self.assertEqual(session["owned_runs"], ["grill-demo"])
        self.assertEqual(ou.owned_session_windows([session], GRILLING)[0]["tokens_total"], 100)

    def test_start_summary_has_separate_modes_and_worker_medians(self):
        self.events()
        sessions = ou.owned_session_windows([self.parsed(["grill-demo"])], GRILLING)
        rows = ou.aggregate_runs(sessions, GRILLING)
        ou.add_worker_usage(rows, [], GRILLING)
        rows = [dict(rows[0], start_mode=mode) for mode in ("old-start", "new-start", "mixed")]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ou.print_summary(sessions, rows, GRILLING)
        text = output.getvalue()
        for mode in ("old-start", "new-start", "mixed"):
            self.assertIn(mode + " 1 1", text)
        for label in ("medians per skill commit", "ctx/call", "pane-calls/session",
                      "calls/question", "worker_tokens_per_question_codex"):
            self.assertIn(label, text)

    def test_cli_filters_both_tables_and_preserves_excluded_csv(self):
        self.events()
        with (self.run_dir / "events.jsonl").open("a") as fh:
            fh.write("\n" + json.dumps({"type": "worker.launch_sent", "data": {"prompt_path": "p"}}))
        with patch.object(ou, "scan", return_value=[self.parsed(["grill-demo"])]), \
             patch.object(ou, "CLAUDE_PROJECTS", self.root), \
             patch.object(ou, "CODEX_SESSIONS", self.root / "absent"), \
             patch.object(ou, "assign_skill_version"), contextlib.redirect_stdout(io.StringIO()) as output:
            result = ou.main(["--workflow", "grilling", "--since", "2026-09-13", "--project", self.root.name,
                              "--exclude-project", "unmatched", "--exclude-project", str(self.root), "--no-cache", "--out", str(self.root / "out")])
            for args in (["--since", "2027-01-01"], ["--project", "does-not-match"]):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(ou.main(["--workflow", "grilling", "--no-cache", *args]), 1)
        self.assertEqual(result, 0)
        self.assertNotIn("[claude]", output.getvalue())
        self.assertIn("new-start", (self.root / "out/orchestrator-usage-runs.csv").read_text())


UNITTEST_LOG = """test_a (x.T) ... ok
----------------------------------------------------------------------
Ran 384 tests in 120.000s

OK
"""
PHPUNIT_LOG = """PHPUnit 11.5.0 by Sebastian Bergmann and contributors.

.....                                                               5 / 5 (100%)

Time: 01:30.500, Memory: 22.00 MB

OK (52 tests, 103 assertions)
"""
PHPUNIT_FAILED_LOG = """Time: 00:00.007, Memory: 4.00 MB

FAILURES!
Tests: 1315, Assertions: 3651, Errors: 177, Skipped: 9.
"""
VITEST_LOG = """ Test Files  12 passed (12)
      Tests  122 passed (122)
   Start at  07:40:01
   Duration  4.81s (transform 13%)
"""


class WallTime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_dir = self.root / ".scratch/orchestrator/runs/chain-issue-001-demo"
        self.run_dir.mkdir(parents=True)

    def write_events(self, *events):
        (self.run_dir / "events.jsonl").write_text(
            "\n".join(json.dumps({"type": t, "time": f"2026-10-17T{clock}+00:00", **extra})
                      for clock, t, extra in events), encoding="utf-8")

    def write_log(self, stage, name, text):
        directory = self.run_dir / "artifacts" / stage
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(text, encoding="utf-8")

    def snapshot(self, clock, label):
        return (clock, "tree.snapshot", {"message": label})

    def test_stage_durations_and_orchestrator_gap(self):
        self.write_events(
            ("10:00:00", "run.init", {}),
            self.snapshot("10:01:00", "launched implement-1"),
            self.snapshot("10:07:00", "report-captured implement-1"),
            self.snapshot("10:07:30", "launched simplify-1"),
            self.snapshot("10:20:00", "report-captured simplify-1"),
            ("10:27:00", "orchestrator.verified", {"data": {"commands": [
                "python3 -m unittest discover -s a", "python3 -m unittest discover -s b",
                "git diff"], "pass": "1", "stage": "simplify"}}),
            ("10:27:00", "gate", {"decision": "advance"}),
            self.snapshot("10:27:06", "launched review-1"),
            self.snapshot("10:40:00", "report-captured review-1"),
            ("10:40:30", "run.completed", {}),
        )
        stages = {s["stage"]: s for s in ou.read_run_timing(self.run_dir)["stages"]}
        self.assertEqual(list(stages), ["implement-1", "simplify-1", "review-1"])
        self.assertEqual(stages["implement-1"]["worker_minutes"], 6.0)
        self.assertEqual(stages["implement-1"]["orchestrator_gap_minutes"], 0.5)
        self.assertEqual(stages["simplify-1"]["worker_minutes"], 12.5)
        self.assertEqual(stages["simplify-1"]["orchestrator_gap_minutes"], 7.1)
        self.assertEqual(stages["simplify-1"]["suite_runs_orchestrator"], 2)
        self.assertEqual(stages["review-1"]["gap_minutes"], 0.5)
        columns = ou.run_timing_columns(list(stages.values()), CHAIN)
        self.assertEqual(columns["wall_worker_minutes"], 31.4)
        self.assertEqual(columns["wall_simplify_minutes"], 12.5)
        self.assertEqual(columns["wall_test_minutes"], "")
        self.assertEqual(columns["suite_runs_orchestrator"], 2)

    def test_human_wait_is_split_from_the_orchestrator_gap(self):
        self.write_events(
            self.snapshot("10:00:00", "launched test-1"),
            self.snapshot("10:10:00", "report-captured test-1"),
            ("10:12:00", "gate", {"decision": "hitl"}),
            ("10:30:00", "decision.human", {}),
            ("10:42:00", "hitl.resolved", {}),
            self.snapshot("10:43:00", "launched implement-2"),
            self.snapshot("10:50:00", "report-captured implement-2"),
        )
        [test, implement] = ou.read_run_timing(self.run_dir)["stages"]
        self.assertEqual(test["gap_minutes"], 33.0)
        self.assertEqual(test["human_wait_minutes"], 30.0)
        self.assertEqual(test["orchestrator_gap_minutes"], 3.0)
        self.assertEqual(implement["role"], "implement")

    def test_pane_and_waiter_events_time_stages_without_snapshots(self):
        self.write_events(
            ("10:00:00", "pane.launched", {"data": {"stage": "spec", "pass": "1"}}),
            ("10:09:00", "worker.waiting", {"data": {"stage": "spec", "pass": "1",
                                                     "outcome": "report"}}),
        )
        [spec] = ou.read_run_timing(self.run_dir)["stages"]
        self.assertEqual((spec["stage"], spec["worker_minutes"]), ("spec-1", 9.0))

    def test_suite_logs_count_unittest_phpunit_and_vitest_runs(self):
        self.assertEqual(ou.test_runs_in_log(UNITTEST_LOG), [120.0])
        self.assertEqual(ou.test_runs_in_log(PHPUNIT_LOG), [90.5])
        self.assertEqual(ou.test_runs_in_log(PHPUNIT_FAILED_LOG), [0.007])
        self.assertEqual(ou.test_runs_in_log(VITEST_LOG), [4.81])
        self.assertEqual(ou.test_runs_in_log("== 3 passed, 1 failed in 2.50s =="), [2.5])
        self.assertEqual(ou.test_runs_in_log("Build at: x - Time: 21746ms\nPASS smoke"), [])
        self.assertEqual(ou.test_commands({"commands": ["ddev composer test -- x",
                                                        "ddev make check-all", "phpstan"]}), 2)
        self.assertIsNone(ou.test_commands({"verdict": "clean"}))

    def test_missing_or_unparsed_logs_are_unknown(self):
        self.write_events(
            self.snapshot("10:00:00", "launched implement-1"),
            self.snapshot("10:05:00", "report-captured implement-1"),
            ("10:06:00", "orchestrator.verified", {"data": {"verdict": "clean"}}),
            self.snapshot("10:06:00", "launched simplify-1"),
            self.snapshot("10:10:00", "report-captured simplify-1"),
            self.snapshot("10:11:00", "launched test-1"),
            self.snapshot("10:20:00", "report-captured test-1"),
        )
        self.write_log("implement-1", "phpunit.log", PHPUNIT_LOG)
        self.write_log("implement-1-attempt-2", "cmux-suite.log", UNITTEST_LOG)
        self.write_log("simplify-1", "build.log", "Build at: x - Time: 21746ms\n")
        stages = {s["stage"]: s for s in ou.read_run_timing(self.run_dir)["stages"]}
        self.assertEqual(stages["implement-1"]["suite_runs_worker"], 2)
        self.assertEqual(stages["implement-1"]["suite_minutes_worker"], 3.5)
        self.assertEqual(stages["implement-1"]["suite_runs_orchestrator"], ou.UNKNOWN)
        self.assertEqual(stages["simplify-1"]["suite_runs_worker"], ou.UNKNOWN)
        self.assertEqual(stages["test-1"]["suite_minutes_worker"], ou.UNKNOWN)
        columns = ou.run_timing_columns(list(stages.values()), CHAIN)
        self.assertEqual(columns["suite_runs_worker"], 2)
        self.assertEqual(columns["suite_unknown_stages"], 2)
        self.assertEqual(columns["suite_runs_orchestrator"], 0)
        self.assertEqual(ou.run_timing_columns([], CHAIN)["wall_worker_minutes"], "")

    def test_runs_csv_keeps_columns_and_stages_csv_lists_stages(self):
        self.write_events(
            ("10:00:00", "run.init", {}),
            self.snapshot("10:01:00", "launched implement-1"),
            self.snapshot("10:07:00", "report-captured implement-1"),
        )
        call = ou.Call("2026-10-17T10:02:00+00:00", 100, 0, 0, 0, None)
        call.category, call.run_id = "other-bash", "chain-issue-001-demo"
        session = ou.build_session("claude", "s1", "p", str(self.root), [call])
        rows = ou.aggregate_runs([session])
        self.assertEqual(rows[0]["wall_implement_minutes"], 6.0)
        out = self.root / "out"
        out.mkdir()
        header = (ou.write_runs_csv(rows, out).read_text().splitlines()[0]).split(",")
        self.assertNotIn("stage_timings", header)
        self.assertIn("calls_per_stage", header)
        self.assertIn("wall_worker_minutes", header)
        stages = ou.write_stages_csv(rows, out).read_text().splitlines()
        self.assertEqual(len(stages), 2)
        self.assertIn("implement-1", stages[1])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ou.print_wall_time(rows, CHAIN)
        self.assertIn("orch-gap", output.getvalue())


if __name__ == "__main__":
    unittest.main()
