"""Issue-chain watcher attention and real CLI publishing regressions."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import run_briefing
import test_stage_preparation as fixtures


def prepared(pass_num=1):
    return {"type": "stage.prepared", "data": {"stage": "implement", "pass": pass_num}}


def waiting(outcome, role="implement", pass_num=1):
    return {"type": "worker.waiting", "data": {"role": role, "pass": pass_num, "outcome": outcome}}


class Projection(unittest.TestCase):
    def test_attention_window_and_precedence(self):
        state = {"workflow": "issue-chain", "issue": {"id": "I", "title": "Title"},
                 "current_stage": "implement", "chain": ["implement"],
                 "prepared_stage": {"stage": "implement", "pass": 1}}
        def board(events, **changes):
            return run_briefing.project_board({**state, **changes}, events)
        deadline = waiting("deadline")
        extension = waiting("extension_approved")
        events = [prepared(), deadline]
        self.assertEqual(board(events)[:2], ("hitl", "implement-1: report deadline exceeded, extension decision needed"))
        self.assertEqual(board(events + [extension])[:2], ("running", "Title"))
        self.assertEqual(board(events + [extension, deadline])[1], "implement-1: extended deadline exceeded, relaunch decision needed")
        self.assertEqual(board(events + [waiting("pane_dead")])[1], "implement-1: worker pane dead, relaunch decision needed")
        self.assertEqual(board(events, current_stage="done")[::2], ("done", 1.0))
        for ignored in (waiting("report"), waiting("not_started"), waiting(None)):
            self.assertEqual(board(events + [ignored]), board(events))
        gate = {"type": "gate", "stage": "implement", "decision": "hitl", "reason": "decision"}
        self.assertEqual(board(events + [gate])[:2], ("hitl", "implement: decision"))
        self.assertEqual(board(events + [prepared()])[:2], ("running", "Title"))
        self.assertEqual(board([extension, prepared(), deadline]), board(events))
        self.assertEqual(board([deadline])[0], "running")
        self.assertEqual(board(events, prepared_stage=None)[0], "running")
        self.assertEqual(board(events, prepared_stage={"stage": "review", "pass": 1})[0], "running")
        fresh = [prepared(), extension, prepared(2), waiting("deadline", pass_num=2)]
        second = {"stage": "implement", "pass": 2}
        self.assertIn("report deadline", board(fresh, prepared_stage=second)[1])
        for outcome in ("deadline", "pane_dead", "extension_approved"):
            for stale in (waiting(outcome), waiting(outcome, role="review", pass_num=2)):
                self.assertEqual(board(fresh + [stale], prepared_stage=second), board(fresh, prepared_stage=second))

    def test_documented_extension(self):
        text = (Path(__file__).parents[1] / "SKILL.md").read_text()
        for phrase in ('--extend --reason', '--deadline-minutes', 'exits 7 and 8 publish `hitl`',
                       'recorded extension', 'later `gate`/`prepare`'):
            self.assertIn(phrase, text)
        self.assertNotIn('reason in a `decision.human` or `worker.waiting`', text)


class WatcherCli(unittest.TestCase):
    setUp = fixtures.PreparedStageCli.setUp
    tearDown = fixtures.PreparedStageCli.tearDown
    env = fixtures.PreparedStageCli.env
    initialize_config = fixtures.PreparedStageCli.initialize_config
    run_state = fixtures.PreparedStageCli.run_state
    init = fixtures.PreparedStageCli.init
    init_for = fixtures.PreparedStageCli.init_for
    board_calls = fixtures.PreparedStageCli.board_calls

    def watch(self, outcome, fail=False):
        self.cmux_log.unlink(missing_ok=True)
        extra = ['--deadline-minutes', '0'] if outcome == 'deadline' else [
            '--surface', 'surface:missing', '--health-cmd', f'{sys.executable} -c "print(\'{{\\"surfaces\\": []}}\')"']
        result = self.run_watcher(*extra, FAKE_CMUX_EXIT='7' if fail else '0')
        self.assertEqual(result.returncode, 8 if outcome == 'deadline' else 7, result.stderr)
        self.assertRegex(result.stdout, rf'\Aoutcome={outcome} elapsed_seconds=\d+\.\d report={re.escape(str(self.run_dir))}/reports/implement-1.md\n\Z')
        return result

    def assert_description(self, text):
        calls = self.board_calls()
        self.assertEqual([c[0] for c in calls], ['workspace-action', 'set-progress'])
        self.assertEqual(calls[0][calls[0].index('--description') + 1], 'issue-chain · ' + text)

    def test_cli_sequence(self):
        result = self.init()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.watch('deadline')
        self.assert_description('hitl · implement-1: report deadline exceeded, extension decision needed')
        self.cmux_log.unlink()
        result = self.run_state('event', '--run-dir', str(self.run_dir), '--type', 'worker.waiting',
                                '--message', 'extend', '--data', json.dumps({**waiting('extension_approved')['data'],
                                'surface_id': None, 'extension': 1, 'reason': 'still working'}), '--cmux-cmd', str(self.cmux))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_description('running · Prepared workers')
        self.watch('deadline')
        self.assert_description('hitl · implement-1: extended deadline exceeded, relaunch decision needed')
        self.watch('pane_dead')
        self.assert_description('hitl · implement-1: worker pane dead, relaunch decision needed')
        self.cmux_log.unlink()
        result = self.run_state('gate', '--run-dir', str(self.run_dir), '--stage', 'implement',
                                '--decision', 'hitl', '--reason', 'human choice', '--cmux-cmd', str(self.cmux))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_description('hitl · implement: human choice')

    def test_fail_soft(self):
        self.assertEqual(self.init().returncode, 0)
        state = (self.run_dir / 'state.json').read_bytes()
        for outcome in ('deadline', 'pane_dead'):
            before = (self.run_dir / 'events.jsonl').read_text()
            result = self.watch(outcome, fail=True)
            self.assertEqual((self.run_dir / 'state.json').read_bytes(), state)
            after = (self.run_dir / 'events.jsonl').read_text()
            self.assertTrue(after.startswith(before))
            self.assertEqual(json.loads(after.splitlines()[-1])['data']['outcome'], outcome)
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertIn('sidebar board not updated', result.stderr)
            self.assertEqual([c[0] for c in self.board_calls()], ['workspace-action'])

    def run_watcher(self, *extra, **env):
        return subprocess.run([sys.executable, str(fixtures.SCRIPT_DIR / 'await_report.py'),
                               '--run-dir', str(self.run_dir), '--role', 'implement', '--pass', '1',
                               '--cmux-cmd', str(self.cmux), *extra],
                              capture_output=True, text=True, env=self.env(**env), timeout=10)

    def extend(self, *extra):
        return self.run_watcher('--surface', 'surface:live', '--health-cmd',
                                f'{sys.executable} -c "print(\'surface:live\')"', '--extend', *extra)

    def test_extend_records_and_rearms_then_refuses_duplicate(self):
        self.assertEqual(self.init().returncode, 0)
        self.watch('deadline')
        self.cmux_log.unlink()
        result = self.extend('--reason', 'still working', '--deadline-minutes', '0.001')
        self.assertEqual(result.returncode, 8, result.stderr)
        descriptions = [c[c.index('--description') + 1] for c in self.board_calls() if c[0] == 'workspace-action']
        self.assertEqual(descriptions, ['issue-chain · running · Prepared workers',
            'issue-chain · hitl · implement-1: extended deadline exceeded, relaunch decision needed'])
        events = [json.loads(line) for line in (self.run_dir / 'events.jsonl').read_text().splitlines()]
        extensions = [e['data'] for e in events if e.get('data', {}).get('outcome') == 'extension_approved']
        self.assertEqual(extensions, [dict(role='implement', **{'pass': 1}, surface_id='surface:live',
            outcome='extension_approved', extension=1, reason='still working')])
        self.assertIs(type(extensions[0]['pass']), int)
        self.assertEqual(events[-1]['data']['extension'], 1)
        self.assert_refused('--reason', 'again', '--deadline-minutes', '0')
        # A different surface does not grant a second extension in this preparation.
        self.assert_refused('--surface', 'surface:other', '--reason', 'again', '--deadline-minutes', '0')

    def test_extension_persists_across_rearm(self):
        self.assertEqual(self.init().returncode, 0)
        self.watch('deadline')
        def clocks():
            return [e['data']['watch_clock'] for e in
                    map(json.loads, (self.run_dir / 'events.jsonl').read_text().splitlines())
                    if 'watch_clock' in e.get('data', {})]
        original = clocks()[-1]
        result = self.run_watcher('--extend', '--reason', 'still working', '--deadline-minutes', '.001')
        self.assertEqual(result.returncode, 8, result.stderr)
        current = clocks()[-1]
        self.assertEqual(current['extension'], 1)
        self.assertGreater(current['deadline'], original['deadline'])
        self.assertEqual(current['start_deadline'], original['start_deadline'])
        self.assertEqual(current['reason'], 'still working')
        result = self.run_watcher('--deadline-minutes', '90')
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual(clocks(), [original, current])
        self.assert_refused('--reason', 'again', '--deadline-minutes', '0')

    def assert_refused(self, *extra):
        before = (self.run_dir / 'events.jsonl').read_bytes()
        self.cmux_log.unlink(missing_ok=True)
        result = self.extend(*extra)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        self.assertEqual((self.run_dir / 'events.jsonl').read_bytes(), before)
        self.assertEqual(self.board_calls(), [])

    def test_extend_requires_reason_deadline_and_current_preparation(self):
        self.assertEqual(self.init().returncode, 0)
        for extra in [('--deadline-minutes', '0'), ('--reason', '  ', '--deadline-minutes', '0'),
                      ('--reason', 'working'),
                      ('--reason', 'working', '--deadline-minutes', 'nan'),
                      ('--reason', 'working', '--deadline-minutes', '-1'),
                      ('--reason', 'working', '--deadline-minutes', '0', '--deadline-reason', 'legacy'),
                      ('--pass', '2', '--reason', 'working', '--deadline-minutes', '0')]:
            with self.subTest(extra=extra):
                self.assert_refused(*extra)

    def test_legacy_extension_shares_preparation_budget(self):
        self.assertEqual(self.init().returncode, 0)
        result = self.run_watcher('--deadline-reason', 'legacy', '--deadline-minutes', '0')
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertIn('hitl · implement-1: extended deadline exceeded, relaunch decision needed',
                      self.board_calls()[-2][self.board_calls()[-2].index('--description') + 1])
        self.assert_refused('--reason', 'again', '--deadline-minutes', '0')
        before = (self.run_dir / 'events.jsonl').read_bytes()
        for extra in [(), ('--surface', 'surface:other', '--health-cmd', 'false')]:
            result = self.run_watcher('--deadline-reason', 'another', '--deadline-minutes', '0', *extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((self.run_dir / 'events.jsonl').read_bytes(), before)

    def test_new_preparation_resets_extension(self):
        self.assertEqual(self.init().returncode, 0)
        self.assertEqual(self.extend('--reason', 'working', '--deadline-minutes', '0').returncode, 8)
        with (self.run_dir / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(prepared()) + '\n')
        self.assertEqual(self.extend('--reason', 'new attempt', '--deadline-minutes', '0').returncode, 8)
