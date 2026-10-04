import unittest
from worker_snapshot import stage_argv


class CodexArguments(unittest.TestCase):
    def test_exact_worker_arguments(self):
        profile = dict(harness="codex", requested_executable="codex",
                       model="test-model", effort="high")
        self.assertEqual(
            stage_argv('implement', profile),
            [
                "codex",
                "-s", "workspace-write",
                "-c", "sandbox_workspace_write.network_access=true",
                "-c", "sandbox_workspace_write.writable_roots=[\"~/.ddev\"]",
                "--ask-for-approval", "on-request",
                "-c", "approvals_reviewer=auto_review",
                "-c", "check_for_update_on_startup=false",
                "-c", "tui.animations=false",
                "-c", "tui.disable_paste_burst=true",
                "--model", "test-model",
                "-c", "model_reasoning_effort=high",
            ],
        )
