#!/usr/bin/env python3
"""Real-Git CLI regression coverage for the proposal transaction."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from run_commit import capture_baseline, porcelain_entries

SCRIPT = Path(__file__).with_name('run_commit.py')


class ProposalCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        config = self.root / 'gitconfig'
        config.touch()
        environment = patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')
        environment.start()
        self.addCleanup(environment.stop)
        self.env = dict(os.environ)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'f*').write_text('original')
        (self.repo / 'fx').write_text('original')
        (self.repo / 'd').mkdir()
        (self.repo / 'd/file').write_text('original')
        (self.repo / 'tab\tline\nname').write_text('original')
        (self.repo / 'link').symlink_to('d')
        self.git('add', '.')
        self.git('commit', '-qm', 'Initial')
        self.run = self.root / 'run'
        self.run.mkdir()
        self.state = dict(run_id='test', workflow='issue-chain', current_stage='done',
                          working_directory=str(self.repo), commit_mode='commit', chain=['implement'],
                          commit_baseline=capture_baseline(self.repo))
        self.save()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.env,
                              check=True, capture_output=True).stdout

    def save(self):
        (self.run / 'state.json').write_text(json.dumps(self.state))

    def events(self):
        path = self.run / 'events.jsonl'
        return path.read_bytes() if path.exists() else b''

    def cli(self, *extra, files=('f*',), subject='Record proposal'):
        cmd = [sys.executable, str(SCRIPT), 'propose', '--run-dir', str(self.run), '--subject', subject]
        for path in files:
            cmd += ['--file', path]
        return subprocess.run(cmd + list(extra), cwd=self.root, env=self.env, capture_output=True, text=True)

    def ok(self, **kwargs):
        result = self.cli(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_literal_and_classification_and_digest(self):
        (self.repo / 'f*').write_text('changed')
        (self.repo / 'fx').write_text('changed')
        (self.repo / '.gitignore').write_text('d/\nignored\n')
        (self.repo / 'ignored').write_text('ignored')
        self.state['commit_baseline'] = capture_baseline(self.repo)
        self.save()
        files = ['f*', 'd/file', 'ignored']
        data = self.ok(files=files)
        self.assertEqual(data['files'], sorted(files))
        self.assertEqual(data['ignored'], ['ignored'])
        self.assertEqual(data['preexisting'], ['f*'])
        draft = dict(subject='Record proposal', body='', files=sorted(files), ride_along=[], product_files=[], tracker_files=[], unresolved=[])
        self.assertEqual(data['proposal_id'], hashlib.sha256(json.dumps(draft, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        self.assertEqual(self.git('diff', '--cached'), b'')

    def test_conventional_subject_and_mid_body_colon_are_not_trailers(self):
        data = self.ok(subject='feat: record proposal')
        self.assertEqual(data['subject'], 'feat: record proposal')
        refused = self.cli('--body', 'Note: rerun migrations.\n\nSigned-off-by: Person', subject='feat: revise proposal')
        self.assertNotEqual(refused.returncode, 0)
        accepted = self.cli('--body', 'Migration: rerun it.\n\nNo manual steps otherwise.', subject='feat: revise proposal')
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_trailers_before_patch_divider_write_no_events(self):
        for trailer in ('Co-Authored-By: Person <person@example.invalid>', 'Signed-off-by: Person'):
            with self.subTest(trailer=trailer):
                result = self.cli('--body', f'Explanation.\n\n{trailer}\n\n---\nPatch notes.',
                                  subject='Document behavior')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(trailer, result.stderr)
                self.assertEqual(self.events(), b'')

    def test_coauthor_anywhere_write_no_events(self):
        for body in ('Explanation.\n\nCo-Authored-By: Person\n\nClosing prose.',
                     'Explanation.\n  cO-aUtHoReD-bY: Person\nMore prose.'):
            with self.subTest(body=body):
                result = self.cli('--body', body)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('trailer line', result.stderr)
                self.assertEqual(self.events(), b'')
        result = self.cli(subject='  CO-AUTHORED-BY: Person')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('CO-AUTHORED-BY: Person', result.stderr)
        self.assertEqual(self.events(), b'')

    def test_git_trailer_parser_and_repository_configuration(self):
        self.git('config', 'trailer.separators', ':=')
        for trailer in ('See: https://example.invalid', 'Reviewed-by= Person'):
            with self.subTest(trailer=trailer):
                result = self.cli('--body', 'Explanation.\n\n' + trailer)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(trailer.split(':')[0].split('=')[0], result.stderr)
                self.assertEqual(self.events(), b'')

    def test_docs_subject_and_mid_body_key_are_accepted(self):
        self.assertEqual(self.ok(subject='docs: explain behavior')['subject'], 'docs: explain behavior')
        result = self.cli('--body', 'Key: value\n\nOrdinary closing prose.', subject='fix: explain behavior')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.events().splitlines()), 2)

    def test_invalid_paths_messages_and_groups_write_no_events(self):
        for path in ('d', 'missing', '/absolute', '.', '..', 'd/../f*', 'd/', './f*', '.git/config', 'd//file'):
            with self.subTest(path=path):
                result = self.cli(files=[path])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(repr(path), result.stderr)
                self.assertEqual(self.events(), b'')
        for extra, files, subject in [([], ['f*', 'f*'], 'Subject'), ([], ['f*'], 'two\nlines'),
                                     (['--body', 'Co-Authored-By: Person'], ['f*'], 'Subject'),
                                     (['--body', 'Co-Authored-By:Person'], ['f*'], 'Subject'),
                                     (['--body', 'Reviewed-by:'], ['f*'], 'Subject'),
                                     (['--body', 'Signed-off-by: Person'], ['f*'], 'Subject'),
                                     (['--product-file', 'fx'], ['f*'], 'Subject'),
                                     (['--ride-along', 'f*'], ['f*'], 'Subject')]:
            self.assertNotEqual(self.cli(*extra, files=files, subject=subject).returncode, 0)
            self.assertEqual(self.events(), b'')
        os.mkfifo(self.repo / 'fifo')
        self.assertNotEqual(self.cli(files=['fifo']).returncode, 0)

    def test_groups_ride_along_and_existing_symlink(self):
        result = self.cli('--product-file', 'f*', '--tracker-file', 'link', '--ride-along', 'fx', files=['link', 'f*'])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['product_files'], ['f*'])
        self.assertEqual(data['tracker_files'], ['link'])
        self.assertEqual(data['ride_along'], ['fx'])
        self.assertEqual(data['files'], ['f*', 'link'])
        self.assertEqual(data['mode'], 'commit')

    def test_absent_tree_and_gitlink_are_not_leaves(self):
        shutil.rmtree(self.repo / 'd')
        self.assertNotEqual(self.cli(files=['d']).returncode, 0)
        head = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('update-index', '--add', '--cacheinfo', f'160000,{head},sub')
        self.git('commit', '-qm', 'Gitlink')
        self.assertNotEqual(self.cli(files=['sub']).returncode, 0)
        self.assertEqual(self.events(), b'')

    def test_tracked_deletions_are_leaf_files(self):
        files = ['f*', 'link', 'tab\tline\nname']
        for path in files:
            (self.repo / path).unlink()
        self.assertEqual(self.ok(files=files)['files'], sorted(files))

    def test_hitl_incomplete_and_legacy(self):
        self.state['chain'] = []
        self.save()
        self.assertEqual(self.ok()['mode'], 'propose')
        self.state['current_stage'] = 'implement'
        self.save()
        before = self.events()
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.events(), before)
        self.state['current_stage'] = 'done'
        self.state.pop('commit_mode')
        self.state.pop('commit_baseline')
        self.save()
        self.assertEqual(self.ok(subject='Legacy proposal')['preexisting'], [])

    def test_replay_and_revision_before_attempt(self):
        first = self.ok()
        before = self.events()
        self.assertEqual(self.ok(), first)
        self.assertEqual(self.events(), before)
        second = self.ok(subject='Revised proposal')
        self.assertNotEqual(first['proposal_id'], second['proposal_id'])
        self.assertEqual(len(self.events().splitlines()), 2)

    def test_run_wide_guard_replays_without_filesystem_or_head_validation(self):
        first = self.ok()
        original = self.events()
        for outcome in ('attempted', 'failed', 'skipped', 'created'):
            for shape in ('directory', 'absent'):
                path = self.repo / 'f*'
                if path.is_dir():
                    path.rmdir()
                elif path.exists():
                    path.unlink()
                if shape == 'directory':
                    path.mkdir()
                (self.run / 'events.jsonl').write_bytes(original + json.dumps({'type': 'commit.' + outcome, 'data': {}}).encode() + b'\n')
                before = self.events()
                self.assertEqual(self.ok(), first)
                refused = self.cli(subject='Changed proposal')
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn('run test already has a commit outcome or attempt; the proposal cannot change', refused.stderr)
                self.assertEqual(self.events(), before)

    def test_lock_refuses_second_cli(self):
        with (self.run / 'commit.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(self.cli().returncode, 0)
            self.assertEqual(self.events(), b'')

    def test_workflow_scope(self):
        self.state.update(workflow='grilling', deliverables={'markdown': str(self.repo/'f*'), 'json': str(self.repo/'fx')})
        self.save()
        self.assertNotEqual(self.cli().returncode, 0)
        result = self.cli('--unresolved', 'Q1', files=['fx', 'f*'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['unresolved'], ['Q1'])
        self.state.update(workflow='planning', current_stage='complete', repository=str(self.repo), published_tracker={'path': str(self.repo/'d')})
        self.save()
        self.assertNotEqual(self.cli(subject='Planning').returncode, 0)
        self.assertEqual(self.ok(files=['d/file'], subject='Planning')['files'], ['d/file'])

    def test_baseline_covers_rename_staged_unstaged_untracked_and_unborn(self):
        self.git('mv', 'fx', 'renamed')
        (self.repo/'f*').write_text('dirty')
        (self.repo/'untracked').write_text('new')
        baseline = capture_baseline(self.repo)
        self.assertEqual(baseline['paths'], ['f*', 'fx', 'renamed', 'untracked'])
        self.assertEqual(baseline['head'], self.git('rev-parse', 'HEAD').decode().strip())
        unborn = self.root/'unborn'
        unborn.mkdir()
        subprocess.run(['git', 'init', '-q', str(unborn)], check=True, env=self.env)
        self.assertIsNone(capture_baseline(unborn)['head'])

    def test_porcelain_fail_closed_and_copy_source(self):
        self.assertEqual(porcelain_entries(b'C  dst\0src\0'), [('C ', b'dst'), ('C ', b'src')])
        for raw in (b'?? missing-nul', b'R  dest\0', b'ZZ bad\0', b'   bad\0', b'?? \0'):
            with self.assertRaises(ValueError):
                porcelain_entries(raw)


if __name__ == '__main__':
    unittest.main()
