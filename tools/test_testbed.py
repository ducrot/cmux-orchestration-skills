"""Public CLI regressions using a synthetic repository and real fixture validator."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CreateTestbed(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        (self.repo / 'tools').mkdir(parents=True)
        shutil.copy2(ROOT / 'tools/testbed.py', self.repo / 'tools/testbed.py')
        for skill in ('cmux-planning', 'cmux-grilling', 'cmux-issue-chain'):
            (self.repo / skill / 'scripts').mkdir(parents=True)
        shutil.copy2(ROOT / 'cmux-planning/scripts/agents_config.py',
                     self.repo / 'cmux-planning/scripts/agents_config.py')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.org',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.org')
        self.git(self.repo, 'init', '-q')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '-qm', 'source')
        self.bed = self.repo / 'testbeds/demo'
        self.project = self.bed / 'project'
        self.project.mkdir(parents=True)
        (self.project / 'app.php').write_text('application\n')
        (self.project / 'run').write_text('#!/bin/sh\nexit 0\n')
        (self.project / 'run').chmod(0o755)
        (self.project / '.gitignore').write_text('.scratch/\nignored.txt\n')
        (self.project / 'ignored.txt').write_text('keep project files even if ignored\n')
        for name in ('vendor/lib.php', '.scratch/secret', '.git/config', 'data/test.sqlite',
                     'data/test.sqlite-wal', 'data/test.db', '.DS_Store', '._app.php'):
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('excluded')
        (self.bed / 'VERSION').write_text('1.2.3\n')
        for scenario in ('one', 'two'):
            path = self.bed / 'scenarios' / scenario
            path.mkdir(parents=True)
            (path / 'plan.md').write_text(f'Plan {scenario}\n')
        (self.bed / 'scenarios/two/human-input.md').write_bytes(b'Human text\n\nexact tail')
        (self.bed / 'evaluation').mkdir()
        (self.bed / 'evaluation/one.md').write_text('private evaluation')
        subprocess.run([sys.executable, str(self.repo / 'cmux-planning/scripts/agents_config.py'),
                        'init', '--config', str(self.bed / 'agents.json')],
                       cwd=self.repo, env=self.env, check=True, capture_output=True)

    def git(self, cwd, *args):
        return self.git_bytes(cwd, *args).decode().strip()

    def git_bytes(self, cwd, *args):
        return subprocess.check_output(['git', '-C', str(cwd), *args], env=self.env)

    def create(self, target=None, scenario='one', bed='demo', skip=True, env=None):
        args = [sys.executable, str(self.repo / 'tools/testbed.py'), 'create', bed, scenario,
                str(target or self.base / 'target')]
        if skip:
            args.append('--skip-install')
        return subprocess.run(args, cwd=self.base, env=env or self.env, capture_output=True, text=True)

    def test_determinism_contents_and_output(self):
        hashes = []
        skill_state = self.git(self.repo, 'rev-parse', '--short', 'HEAD')
        for number, scenario in enumerate(('one', 'one', 'two')):
            config = self.base / f'gitconfig-{number}'
            template = self.base / f'template-{number}'
            (template / 'hooks').mkdir(parents=True)
            hook = template / 'hooks/pre-commit'
            hook.write_text('#!/bin/sh\nexit 88\n')
            hook.chmod(0o755)
            config.write_text(f'[user]\n name = User{number}\n email = other{number}@example.org\n'
                              '[commit]\n gpgsign = true\n[init]\n defaultBranch = hostile\n'
                              f' templateDir = {template}\n'
                              f'[core]\n hooksPath = {template / "hooks"}\n'
                              ' autocrlf = true\n filemode = false\n')
            env = dict(self.env, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_COUNT='1',
                       GIT_CONFIG_KEY_0='commit.gpgsign', GIT_CONFIG_VALUE_0='true')
            target = self.base / f'target-{number}'
            target.mkdir()
            result = self.create(target, scenario, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            hashes.append((self.git(target, 'rev-parse', 'HEAD^'), self.git(target, 'rev-parse', 'HEAD')))
            self.assertEqual(self.git(target, 'branch', '--show-current'), 'main')
            self.assertFalse((target / '.git/hooks').exists())
            self.assertEqual(self.git(target, 'status', '--porcelain'), '')
            self.assertEqual(set(self.git(target, 'ls-files').splitlines()),
                             {'app.php', 'run', '.gitignore', 'ignored.txt', 'docs/plan.md',
                              '.scratch/orchestrator/agents.json'})
            self.assertEqual((target / '.scratch/orchestrator/agents.json').read_bytes(),
                             (self.bed / 'agents.json').read_bytes())
            self.assertEqual((target / 'docs/plan.md').read_bytes(),
                             (self.bed / f'scenarios/{scenario}/plan.md').read_bytes())
            self.assertTrue((target / 'run').stat().st_mode & 0o111)
            self.assertTrue(self.git(target, 'ls-files', '-s', 'run').startswith('100755'))
            for value in (str(target), 'demo', '1.2.3', scenario, *hashes[-1], skill_state):
                self.assertIn(value, result.stdout)
            if scenario == 'two':
                self.assertTrue(result.stdout.endswith('Human text\n\nexact tail'))
                self.assertIn('orchestrator conversation', result.stdout)
        self.assertEqual(hashes[0], hashes[1])
        self.assertEqual(hashes[0][0], hashes[2][0])
        self.assertNotEqual(hashes[0][1], hashes[2][1])

    def snapshot(self):
        directories, files = set(), {}
        for path in self.base.rglob('*'):
            name = str(path.relative_to(self.base))
            if path.is_dir():
                directories.add(name)
            elif path.is_file():
                files[name] = (path.read_bytes(), path.stat().st_mtime_ns)
        return directories, files

    def test_attributes_preserve_committed_bytes_and_modes(self):
        (self.project / '.gitattributes').write_bytes(b'* text eol=lf ident\n')
        (self.project / 'app.php').write_bytes(b'application\r\n$Id$\r\n')
        (self.project / 'run').write_bytes(b'#!/bin/sh\r\nexit 0\r\n')
        fixture = self.bed / 'agents.json'
        fixture.write_bytes(fixture.read_bytes().replace(b'\n', b'\r\n'))
        plan = self.bed / 'scenarios/one/plan.md'
        plan.write_bytes(b'Plan one\r\n$Id$\r\n')
        target = self.base / 'target'
        result = self.create(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        project = {
            'app.php': self.project / 'app.php',
            'run': self.project / 'run',
            '.gitattributes': self.project / '.gitattributes',
            '.scratch/orchestrator/agents.json': fixture,
        }
        for revision, expected in (('HEAD^', project), ('HEAD', {**project, 'docs/plan.md': plan})):
            for name, source in expected.items():
                with self.subTest(revision=revision, path=name):
                    self.assertEqual(self.git_bytes(target, 'show', f'{revision}:{name}'),
                                     source.read_bytes())
                    mode = '100755' if source.stat().st_mode & 0o111 else '100644'
                    self.assertTrue(self.git(target, 'ls-tree', revision, name).startswith(mode))
        self.assertEqual(self.git(target, 'status', '--porcelain'), '')

    def assert_refused(self, rule, **kwargs):
        before = self.snapshot()
        result = self.create(**kwargs)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(rule, result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.base / 'target').exists())

    def test_refusals_write_nothing(self):
        nonempty = self.base / 'nonempty'
        nonempty.mkdir()
        (nonempty / 'keep').write_text('untouched')
        self.assert_refused('not empty', target=nonempty)
        self.assert_refused('repository', target=self.repo / 'new')
        self.assert_refused('testbed source', target=self.project / 'new')
        alias = self.base / 'alias'
        alias.symlink_to(self.repo, target_is_directory=True)
        self.assert_refused('repository', target=alias / 'new')
        self.assert_refused('unknown testbed', bed='missing')
        self.assert_refused('unknown scenario', scenario='missing')
        self.assert_refused('unknown testbed', bed='../demo')
        self.assert_refused('unknown scenario', scenario='../one')
        (self.bed / 'agents.json').write_text('{}')
        self.assert_refused('invalid fixture')

    def test_dirty_marker_tracks_only_skill_directories(self):
        clean = self.git(self.repo, 'rev-parse', '--short', 'HEAD')
        self.assertIn(f'Skill state: {clean}\n', self.create(self.base / 'clean').stdout)
        for state in ('untracked', 'staged', 'modified'):
            path = self.repo / 'cmux-grilling/change'
            path.write_text(state)
            if state == 'staged':
                self.git(self.repo, 'add', str(path))
            if state == 'modified':
                self.git(self.repo, 'commit', '-qm', 'tracked change')
                clean = self.git(self.repo, 'rev-parse', '--short', 'HEAD')
                path.write_text('modified again')
            result = self.create(self.base / state)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'Skill state: {clean}-dirty\n', result.stdout)

    def test_default_stops_after_commits_with_install_message(self):
        result = self.create(skip=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('installation and registry recording', result.stderr)
        self.assertEqual(self.git(self.base / 'target', 'rev-list', '--count', 'HEAD'), '2')

    def test_preflight_rejects_overwrites_and_symlinks(self):
        (self.project / 'docs').mkdir()
        (self.project / 'docs/plan.md').write_text('existing')
        self.assert_refused('docs/plan.md')
        (self.project / 'docs/plan.md').unlink()
        (self.project / 'link').symlink_to(self.base / 'outside')
        self.assert_refused('symlink')

    def test_preflight_rejects_mixed_case_plan_without_writes(self):
        (self.project / 'Docs').mkdir()
        (self.project / 'Docs/Plan.md').write_text('existing')
        self.assert_refused('docs/plan.md')

    def test_decomposed_file_name_leaves_clean_tree(self):
        (self.project / unicodedata.normalize('NFD', 'übung.txt')).write_text('exercise\n')
        target = self.base / 'target'
        result = self.create(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(target, 'status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
