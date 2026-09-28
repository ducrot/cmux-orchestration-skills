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


class CliCase(unittest.TestCase):
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


class ProposalCli(CliCase):
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


class CommitCli(CliCase):
    def commit(self, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), 'commit', '--run-dir', str(self.run)],
                                cwd=self.root, env=self.env, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def dirty(self, path='f*', content='changed'):
        (self.repo / path).write_text(content)

    def hook(self, name, body):
        path = self.repo / '.git/hooks' / name
        path.write_text('#!/bin/sh\nset -e\n' + body + '\n')
        path.chmod(0o755)

    def wrapper(self, body):
        binary = shutil.which('git')
        directory = self.root / 'bin'
        directory.mkdir(exist_ok=True)
        path = directory / 'git'
        path.write_text('#!' + sys.executable + '\nimport os, sys, subprocess, json\n'
                        + 'real = ' + repr(binary) + '\na = sys.argv[1:]\n'
                        + 'run_dir = ' + repr(str(self.run)) + '\n'
                        + 'repo = ' + repr(str(self.repo)) + '\n'
                        + body + '\nos.execv(real, [real] + a)\n')
        path.chmod(0o755)
        self.env['PATH'] = str(directory) + os.pathsep + os.environ['PATH']

    def last(self):
        return json.loads(self.events().splitlines()[-1])

    def index(self):
        return self.git('diff', '--cached', '--name-only', '-z')

    def test_literal_scope_unchanged_and_ride_along(self):
        self.dirty()
        self.dirty('fx')
        result = self.cli('--ride-along', 'fx', files=['f*', 'd/file'])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.commit()
        self.assertEqual(data['files'], ['f*'])
        self.assertEqual(data['unchanged'], ['d/file'])
        self.assertEqual(data['hook_side_effects'], [])
        self.assertEqual(self.git('show', 'HEAD:fx'), b'original')
        self.assertEqual((self.repo/'fx').read_text(), 'changed')
        self.assertEqual(self.index(), b'')
        self.assertEqual(self.last()['type'], 'commit.created')

    def test_descendant_scope(self):
        self.dirty('d/a')
        self.dirty('d/b')
        self.ok(files=['d/a'])
        data = self.commit()
        self.assertEqual(data['files'], ['d/a'])
        self.assertEqual(self.git('ls-tree', '--name-only', 'HEAD', 'd/b'), b'')
        self.assertEqual((self.repo/'d/b').read_text(), 'changed')
        self.assertEqual(self.index(), b'')

    def test_deletions_and_run_wide_replay(self):
        files = ['f*', 'link', 'tab\tline\nname']
        for path in files:
            (self.repo/path).unlink()
        proposal = self.ok(files=files)
        data = self.commit()
        head = self.git('rev-parse', 'HEAD')
        self.assertEqual(data['files'], sorted(files))
        self.assertEqual(self.git('diff-tree', '--no-commit-id', '--diff-filter=D', '--name-only', '-r', '-z', 'HEAD'),
                         b'f*\0link\0tab\tline\nname\0')
        before = self.events()
        self.assertEqual(self.ok(files=files), proposal)
        self.assertEqual(self.commit(), data)
        self.assertNotEqual(self.cli(files=files, subject='Changed draft').returncode, 0)
        self.assertEqual(self.events(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.index(), b'')

    def test_read_only_fallbacks_and_no_retry(self):
        for reason in ('not-a-leaf', 'preexisting-changes', 'index-not-empty', 'no-head'):
            with self.subTest(reason=reason):
                # Restore a fresh fixture for each independent completed run.
                if reason != 'not-a-leaf':
                    self.setUp()
                self.dirty()
                proposal = self.ok()
                if reason == 'not-a-leaf':
                    (self.repo/'f*').unlink()
                    (self.repo/'f*').mkdir()
                elif reason == 'preexisting-changes':
                    self.state['commit_baseline']['paths'] = ['f*']
                    self.save()
                elif reason == 'index-not-empty':
                    self.dirty('fx')
                    self.git('add', 'fx')
                else:
                    self.git('symbolic-ref', 'HEAD', 'refs/heads/unborn')
                index = (self.repo/'.git/index').read_bytes()
                head = self.git('symbolic-ref', 'HEAD')
                data = self.commit()
                self.assertEqual(data['reason'], reason)
                self.assertIn('head', data)
                self.assertIn('output', data)
                self.assertEqual((self.repo/'.git/index').read_bytes(), index)
                self.assertEqual(self.git('symbolic-ref', 'HEAD'), head)
                before = self.events()
                self.assertEqual(self.ok(), proposal)
                self.commit(success=False)
                self.assertNotEqual(self.cli(subject='Changed draft').returncode, 0)
                self.assertEqual(self.events(), before)

    def test_refusals_do_not_write(self):
        self.ok()
        for field, value in [('commit_mode', 'propose'), ('chain', []), ('current_stage', 'test'), ('commit_baseline', None)]:
            with self.subTest(field=field):
                original = self.state[field]
                self.state[field] = value
                self.save()
                before = {p.name:p.read_bytes() for p in self.run.iterdir()}
                self.commit(success=False)
                self.assertEqual({p.name:p.read_bytes() for p in self.run.iterdir()}, before)
                self.state[field] = original
                self.save()
        with (self.run/'commit.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.events()
            self.commit(success=False)
            self.assertEqual(self.events(), before)
        (self.run/'events.jsonl').unlink()
        self.commit(success=False)
        self.assertEqual(self.events(), b'')
        self.assertEqual(self.index(), b'')

    def test_skips_and_ignore_reclassification(self):
        self.ok()
        data = self.commit()
        self.assertEqual(data, {'reason':'no-changes', 'unchanged':['f*']})
        self.commit(success=False)
        self.setUp()
        self.dirty('new')
        self.ok(files=['new'])
        (self.repo/'.gitignore').write_text('new\n')
        data = self.commit()
        self.assertEqual(data, {'reason':'all-ignored', 'ignored':['new']})
        self.assertEqual(self.index(), b'')
        self.commit(success=False)

    def test_attempt_is_durable_before_commit_and_no_literal_env(self):
        self.dirty()
        self.ok()
        self.env['GIT_LITERAL_PATHSPECS'] = '1'
        self.wrapper('''if "commit" in a:
    events = [json.loads(line) for line in open(run_dir + "/events.jsonl")]
    event = events[-1]
    assert event["type"] == "commit.attempted"
    data = event["data"]
    assert data["tree"] == subprocess.check_output([real, "-C", repo, "write-tree"]).decode().strip()
    assert data["parent"] == subprocess.check_output([real, "-C", repo, "rev-parse", "HEAD"]).decode().strip()
    assert data["paths"] == ["f*"]
    assert data["pre_status"][0]["sha256"]
    assert "GIT_LITERAL_PATHSPECS" not in os.environ
    assert "--literal-pathspecs" not in a
''')
        self.assertEqual(self.commit()['files'], ['f*'])

    def test_staged_set_mismatch_leaves_foreign_index(self):
        self.dirty()
        self.dirty('fx')
        self.ok()
        parent = self.git('rev-parse', 'HEAD')
        self.wrapper('''if "add" in a:
    result = subprocess.run([real] + a)
    subprocess.check_call([real, "-C", repo, "add", "fx"])
    sys.exit(result.returncode)
''')
        data = self.commit()
        self.assertEqual(data['reason'], 'staged-set-mismatch')
        self.assertEqual(data['extra'], ['fx'])
        self.assertEqual(data['missing'], [])
        self.assertEqual(self.index(), b'fx\0')
        self.assertEqual(self.git('rev-parse', 'HEAD'), parent)
        self.assertNotIn(b'commit.attempted', self.events())
        self.assertEqual((self.repo/'f*').read_text(), 'changed')

    def test_stage_error_restores_only_planned_paths(self):
        self.dirty()
        self.dirty('fx')
        self.ok()
        self.wrapper('''if "add" in a:
    subprocess.check_call([real] + a)
    subprocess.check_call([real, "-C", repo, "add", "fx"])
    print("stage failed", file=sys.stderr)
    sys.exit(1)
''')
        data = self.commit()
        self.assertEqual(data['reason'], 'stage-error')
        self.assertIn('stage failed', data['summary'])
        self.assertEqual(self.index(), b'fx\0')
        self.assertNotIn(b'commit.attempted', self.events())

    def test_failed_hook_and_signing_no_retry(self):
        for signing in (False, True):
            with self.subTest(signing=signing):
                if signing:
                    self.setUp()
                    self.git('config', 'commit.gpgsign', 'true')
                    self.git('config', 'gpg.program', 'false')
                else:
                    self.hook('pre-commit', 'echo check-failed >&2\nexit 1')
                self.dirty()
                self.ok()
                parent = self.git('rev-parse', 'HEAD')
                data = self.commit()
                self.assertEqual(data['reason'], 'commit-error')
                self.assertTrue(data['output'])
                self.assertLessEqual(len(data['summary']), 120)
                self.assertEqual(data['hook_side_effects'], [])
                self.assertEqual(self.git('rev-parse', 'HEAD'), parent)
                self.assertEqual(self.index(), b'')
                self.assertEqual((self.repo/'f*').read_text(), 'changed')
                before = self.events()
                self.commit(success=False)
                self.assertEqual(self.events(), before)

    def test_autofixer_and_unstaged_side_effects(self):
        self.dirty()
        self.ok()
        self.hook('pre-commit', "printf fixed > 'f*'\ngit --literal-pathspecs add -- 'f*'\nprintf foreign > fx\nprintf new > new\nprintf unstaged > 'f*'")
        data = self.commit()
        self.assertEqual(data['hook_modified'], ['f*'])
        self.assertEqual(data['hook_side_effects'], ['f*', 'fx', 'new'])
        self.assertEqual(self.git('show', 'HEAD:f*'), b'fixed')
        self.assertEqual((self.repo/'f*').read_text(), 'unstaged')
        self.assertEqual(self.index(), b'')

    def test_hook_mode_change_is_not_a_modified_blob(self):
        self.dirty()
        self.ok()
        self.git('config', 'core.filemode', 'true')
        self.hook('pre-commit', "chmod +x 'f*'\ngit --literal-pathspecs add -- 'f*'")
        data = self.commit()
        self.assertEqual(data['hook_modified'], [])
        self.assertIn(b'100755 blob', self.git('ls-tree', 'HEAD', 'f*'))
        self.assertEqual(self.index(), b'')

    def test_latest_revision_is_committed(self):
        self.dirty()
        self.ok()
        self.dirty('fx')
        revised = self.ok(files=['fx'], subject='Revised subject')
        data = self.commit()
        self.assertEqual(data['subject'], revised['subject'])
        self.assertEqual(data['files'], ['fx'])
        self.assertEqual(self.git('show', 'HEAD:f*'), b'original')
        self.assertEqual(self.index(), b'')

    def test_hook_reverts_one_path_and_rewrites_subject(self):
        self.dirty()
        self.dirty('fx')
        self.ok(files=['f*', 'fx'])
        self.hook('pre-commit', "git show 'HEAD:f*' > 'f*'\ngit --literal-pathspecs add -- 'f*'")
        self.hook('commit-msg', 'printf "Hook subject\\n" > "$1"')
        data = self.commit()
        self.assertEqual(data['files'], ['fx'])
        self.assertEqual(data['hook_reverted'], ['f*'])
        self.assertEqual(data['hook_modified'], ['f*'])
        self.assertEqual(data['subject'], 'Hook subject')

    def test_hook_foreign_undo_preserves_other_staged_entry(self):
        self.dirty()
        self.ok()
        parent = self.git('rev-parse', 'HEAD')
        self.hook('pre-commit', 'printf foreign > fx\ngit add fx')
        self.hook('post-commit', 'printf late > late\ngit add late')
        data = self.commit()
        self.assertEqual(data['reason'], 'hook-added-paths')
        self.assertTrue(data['reset'])
        self.assertEqual(data['paths'], ['fx'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), parent)
        self.assertEqual(self.index(), b'late\0')
        self.assertEqual((self.repo/'fx').read_text(), 'foreign')
        self.assertEqual((self.repo/'f*').read_text(), 'changed')
        self.assertIn(b'run_commit: undo run test commit', self.git('reflog', '-1'))

    def test_remote_tracking_ref_prevents_undo(self):
        self.dirty()
        self.ok()
        parent = self.git('rev-parse', 'HEAD')
        self.hook('pre-commit', 'printf foreign > fx\ngit add fx')
        self.hook('post-commit', 'git update-ref refs/remotes/test/main HEAD')
        data = self.commit()
        self.assertFalse(data['reset'])
        self.assertEqual(data['reason'], 'hook-added-paths')
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), parent)
        self.assertEqual(self.git('show', 'HEAD:fx'), b'foreign')
        self.assertEqual(self.index(), b'')

    def test_cas_failure_leaves_foreign_head_and_index(self):
        self.dirty()
        self.ok()
        self.hook('pre-commit', 'printf foreign > fx\ngit add fx')
        self.wrapper('''if "update-ref" in a:
    tree = subprocess.check_output([real, "-C", repo, "write-tree"]).decode().strip()
    foreign = subprocess.check_output([real, "-C", repo, "commit-tree", tree, "-p", "HEAD", "-m", "Foreign"]).decode().strip()
    subprocess.check_call([real, "-C", repo, "update-ref", "HEAD", foreign])
''')
        data = self.commit()
        self.assertEqual(data['detail'], 'cas-failed')
        self.assertEqual(self.git('log', '-1', '--format=%s').strip(), b'Foreign')
        self.assertEqual(self.index(), b'')
        self.assertEqual(self.git('show', 'HEAD:fx'), b'foreign')

    def test_foreign_commit_and_failure_is_not_undone(self):
        self.dirty()
        self.ok()
        self.wrapper('''if "commit" in a:
    subprocess.check_call([real, "-C", repo, "commit", "-qm", "Foreign"])
    sys.exit(1)
''')
        data = self.commit()
        self.assertEqual(data['detail'], 'head-moved')
        self.assertEqual(self.git('log', '-1', '--format=%s').strip(), b'Foreign')
        self.assertEqual(self.index(), b'')

    def test_post_commit_second_commit_is_not_undone(self):
        self.dirty()
        self.ok()
        self.hook('post-commit', 'rm .git/hooks/post-commit\ngit commit --allow-empty -qm Second')
        data = self.commit()
        self.assertEqual(data['detail'], 'sha-mismatch')
        self.assertEqual(self.git('log', '-1', '--format=%s').strip(), b'Second')
        self.assertEqual(self.index(), b'')

    def test_localized_detached_summary(self):
        self.git('checkout', '--detach', '-q')
        self.dirty()
        self.ok()
        self.env['LANG'] = 'de_DE.UTF-8'
        # Deterministic even on hosts without installed German Git message catalogs.
        self.wrapper('''if "commit" in a:
    result = subprocess.run([real] + a, capture_output=True)
    import re
    output = re.sub(rb"^\\[[^\\]\\n]+ ([0-9a-f]+)\\]", lambda m: "[losgelöster HEAD ".encode() + m.group(1) + b"]", result.stdout, flags=re.M)
    sys.stdout.buffer.write(output)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)
''')
        self.assertEqual(self.commit()['files'], ['f*'])
        self.assertEqual(self.index(), b'')

    def test_summary_missing_and_parent_mismatch(self):
        for detail in ('no-summary-line', 'parent-mismatch'):
            with self.subTest(detail=detail):
                if detail == 'parent-mismatch':
                    self.setUp()
                self.dirty()
                self.ok()
                if detail == 'no-summary-line':
                    body = '''if "commit" in a:
    result = subprocess.run([real] + a, capture_output=True)
    sys.exit(result.returncode)
'''
                else:
                    body = '''if "commit" in a:
    tree = subprocess.check_output([real, "-C", repo, "write-tree"]).decode().strip()
    sha = subprocess.check_output([real, "-C", repo, "commit-tree", tree, "-m", "Foreign root"]).decode().strip()
    subprocess.check_call([real, "-C", repo, "update-ref", "HEAD", sha])
    print("[branch " + sha + "] Foreign root")
    sys.exit(0)
'''
                self.wrapper(body)
                data = self.commit()
                self.assertEqual(data['detail'], detail)
                self.assertEqual(self.index(), b'')
                self.assertEqual(self.git('show', 'HEAD:f*'), b'changed')

    def pending_attempt(self):
        self.dirty()
        proposal = self.ok()
        self.wrapper('''if "commit" in a:
    sys.exit(75)
''')
        # Kill the helper itself at the Git boundary so no outcome can be appended.
        wrapper = self.root/'bin/git'
        wrapper.write_text(wrapper.read_text().replace('sys.exit(75)', 'import signal\n    os.kill(os.getppid(), signal.SIGKILL)\n    sys.exit(75)'))
        self.commit(success=False)
        self.assertEqual(self.last()['type'], 'commit.attempted')
        self.env['PATH'] = os.environ['PATH']
        return proposal, self.last()['data']

    def git_state(self):
        return self.git('rev-parse', 'HEAD'), (self.repo/'.git/index').read_bytes(), (self.repo/'f*').read_bytes()

    def recover_without_git_write(self):
        before = self.git_state()
        data = self.commit()
        self.assertEqual(data['reason'], 'unverifiable')
        events = self.events()
        self.assertIn('no retry', self.commit(success=False).stderr)
        self.assertEqual(self.events(), events)
        self.assertEqual(self.git_state(), before)
        return data, before[0].decode().strip()

    def test_interrupted_recovery_accepts_exact_parent_tree(self):
        proposal, attempt = self.pending_attempt()
        before = self.events()
        self.assertEqual(self.ok(), proposal)
        self.assertNotEqual(self.cli(subject='Changed draft').returncode, 0)
        self.assertEqual(self.events(), before)
        self.git('commit', '-qm', proposal['subject'])
        head = self.git('rev-parse', 'HEAD')
        data = self.commit()
        self.assertTrue(data['recovered'])
        self.assertEqual(data['sha'], head.decode().strip())
        self.assertEqual(data['files'], ['f*'])
        self.assertEqual(data['hook_modified'], [])
        self.assertEqual(data['hook_side_effects'], [])
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.index(), b'')

    def test_recovery_mismatches_never_write_git(self):
        for kind in ('same-subject', 'autofixer', 'different-parent'):
            with self.subTest(kind=kind):
                if kind != 'same-subject':
                    self.setUp()
                proposal, attempt = self.pending_attempt()
                if kind == 'same-subject':
                    self.dirty(content='different tree')
                    self.git('--literal-pathspecs', 'add', 'f*')
                    self.git('commit', '-qm', proposal['subject'])
                elif kind == 'autofixer':
                    self.hook('pre-commit', "printf fixed > 'f*'\ngit --literal-pathspecs add -- 'f*'")
                    self.git('commit', '-qm', proposal['subject'])
                elif kind == 'different-parent':
                    self.git('commit', '-qm', 'First')
                    self.git('commit', '--allow-empty', '-qm', proposal['subject'])
                data, head = self.recover_without_git_write()
                self.assertEqual(data['detail'], 'recovery-mismatch')
                self.assertEqual(data['tree'], attempt['tree'])
                self.assertEqual(data['head'], head)

    def test_interrupted_recovery_still_at_parent_preserves_staged_paths(self):
        proposal, attempt = self.pending_attempt()
        # Preserve unstaged edits too; recovery must not re-stage the planned file.
        self.dirty(content='later unstaged edit')
        self.assertEqual(self.index(), b'f*\0')
        data, head = self.recover_without_git_write()
        self.assertEqual(self.last()['type'], 'commit.failed')
        self.assertEqual(data['detail'], 'recovery-no-commit')
        self.assertEqual(data['head'], head)
        self.assertEqual(data['parent'], head)
        self.assertEqual(attempt['parent'], head)
        self.assertEqual(data['tree'], attempt['tree'])
        self.assertEqual(data['staged'], ['f*'])
        self.assertEqual(data['subject'], proposal['subject'])


if __name__ == '__main__':
    unittest.main()
