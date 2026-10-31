import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents_config import ConfigError
from planning_recovery import publication_status
from planning_state import discard_staging
from spec_contract import ContractError
from test_planning_flow import file_contents, remove_path


class DiscardStaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.run = self.repo / '.scratch/orchestrator/runs/test'
        self.stage = self.run / 'publication-stage'
        self.grilling = self.stage / 'grilling'
        self.grilling.mkdir(parents=True)
        self.target = self.repo / '.scratch/2026-10-31-feature'
        self.files = {Path('first.json'): b'{}\n', Path('first.md'): b'# First\n',
                      Path('second.json'): b'{"a": 2}\n', Path('second.md'): b'# Second\n',
                      Path('nested/extra'): b'\x00second\n'}
        for name, data in self.files.items():
            path = self.grilling / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        (self.stage / 'partial-tracker').write_text('discard')
        (self.run / 'state.json').write_text(json.dumps({
            'configuration_created_and_accepted': True,
            'repository': str(self.repo), 'feature_dir': str(self.target), 'tracker_slug': 'feature',
        }))

    def assert_restored(self):
        self.assertFalse(self.stage.exists())
        self.assertEqual(file_contents(self.target / 'grilling'), self.files)

    def test_absent_target_restores_entire_directory(self):
        discard_staging(self.run)
        self.assert_restored()

    def test_empty_target_restores_entire_directory(self):
        self.target.mkdir()
        discard_staging(self.run)
        self.assert_restored()

    def test_rename_failure_preserves_absent_or_empty_target_and_staging(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                if empty:
                    self.target.mkdir()
                with patch('planning_state.os.rename', side_effect=OSError('injected rename failure')):
                    with self.assertRaises(OSError):
                        discard_staging(self.run)
                self.assertEqual(self.target.exists(), empty)
                if empty:
                    self.assertEqual(list(self.target.iterdir()), [])
                self.assertTrue((self.stage / 'partial-tracker').is_file())
                self.assertTrue(self.grilling.is_dir())
        discard_staging(self.run)
        self.assert_restored()

    def test_stop_before_rename_recovers_by_repeat(self):
        with patch('planning_state.os.rename', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                discard_staging(self.run)
        discard_staging(self.run)
        self.assert_restored()

    def test_stop_after_rename_recovers_by_repeat(self):
        with patch('planning_state.shutil.rmtree', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                discard_staging(self.run)
        self.assertFalse(self.grilling.exists())
        self.assertTrue((self.target / 'grilling').is_dir())
        discard_staging(self.run)
        self.assert_restored()

    def test_unapproved_feature_folder_without_staging_is_not_a_moved_publication(self):
        shutil.rmtree(self.stage)
        self.target.mkdir()
        (self.target / '.DS_Store').write_bytes(b'finder')
        errors = []
        state = json.loads((self.run / 'state.json').read_text())
        status = publication_status(self.run, state, errors)
        self.assertEqual((status['phase'], errors), ('not-started', []))

    def test_conflicting_targets_are_untouched_and_retry_succeeds(self):
        for kind in ('duplicate', 'foreign', 'symlink', 'file', 'grilling-symlink'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    self.target.symlink_to(self.stage, target_is_directory=True)
                elif kind == 'file':
                    self.target.write_bytes(b'keep')
                else:
                    self.target.mkdir()
                    entry = self.target / ('foreign' if kind == 'foreign' else 'grilling')
                    if kind == 'duplicate':
                        entry.mkdir()
                    elif kind == 'grilling-symlink':
                        entry.symlink_to(self.grilling, target_is_directory=True)
                    else:
                        entry.write_bytes(b'keep')
                with self.assertRaises((ContractError, ConfigError)):
                    discard_staging(self.run)
                self.assertTrue(self.grilling.is_dir())
                self.assertTrue((self.stage / 'partial-tracker').is_file())
                remove_path(self.target)
        discard_staging(self.run)
        self.assert_restored()

    def test_without_grilling_and_symlinked_staging(self):
        shutil.rmtree(self.grilling)
        discard_staging(self.run)
        self.assertFalse(self.stage.exists())
        self.stage.symlink_to(self.repo, target_is_directory=True)
        discard_staging(self.run)
        self.assertTrue(self.stage.is_symlink())

    def test_invalid_staged_grilling_is_preserved(self):
        shutil.rmtree(self.grilling)
        self.grilling.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(ContractError):
            discard_staging(self.run)
        self.assertTrue(self.grilling.is_symlink())
