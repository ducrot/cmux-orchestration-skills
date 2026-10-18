"""Keep the evidence consumers on one contract without relaxing audit parsing."""
import json
from pathlib import Path
import tempfile
import unittest

import check_evidence
import evidence_contract as contract
import run_state
import run_commit
import worker_readiness


class EvidenceContract(unittest.TestCase):
    def test_consumers_share_strict_reader_and_stage_policy(self):
        self.assertIs(run_state.read_events, contract.read_events)
        self.assertIs(check_evidence.read_events, contract.read_events)
        self.assertIs(run_state.EVIDENCE_GATED_STAGES, contract.EVIDENCE_GATED_STAGES)
        self.assertIs(check_evidence.EVIDENCE_EXEMPT_STAGES, contract.EVIDENCE_EXEMPT_STAGES)

    def test_strict_reader_preserves_blank_and_nonobject_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            self.assertEqual(contract.read_events(run_dir), [])
            path = run_dir / "events.jsonl"
            event = {"type": "example"}
            path.write_text(json.dumps(event) + "\n")
            self.assertEqual(contract.read_events(run_dir), [event])
            path.write_text(json.dumps(event) + "\n\n")
            with self.assertRaises(json.JSONDecodeError):
                contract.read_events(run_dir)
            self.assertEqual(worker_readiness.read_events(run_dir), [event])
            self.assertEqual(run_commit.read_events(run_dir), [event])
            path.write_text("[]\n")
            with self.assertRaisesRegex(ValueError, "events.jsonl holds a non-object line"):
                contract.read_events(run_dir)

