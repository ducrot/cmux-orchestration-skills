import unittest
from launch_wave import lane_argv


class CodexArguments(unittest.TestCase):
    def test_exact_worker_arguments(self):
        profile = dict(harness="codex", requested_executable="codex",
                       model="test-model", effort="high")
        self.assertEqual(
            lane_argv('codebase2', profile),
            [
                "codex",
                "-s", "workspace-write",
                "--ask-for-approval", "on-request",
                "-c", "approvals_reviewer=auto_review",
                "-c", "check_for_update_on_startup=false",
                "-c", "tui.animations=false",
                "-c", "tui.disable_paste_burst=true",
                "--model", "test-model",
                "-c", "model_reasoning_effort=high",
            ],
        )
