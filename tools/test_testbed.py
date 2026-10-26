"""Public CLI regressions using a synthetic repository and real fixture validator."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class ZeiterfassungRelease(unittest.TestCase):
    def test_version_and_shipped_worker_fixture(self):
        bed = ROOT / 'testbeds/zeiterfassung'
        self.assertEqual((bed / 'VERSION').read_bytes(), b'1.0.0\n')
        fixture = bed / 'agents.json'
        with tempfile.TemporaryDirectory() as directory:
            default = Path(directory) / 'agents.json'
            subprocess.run([sys.executable, str(ROOT / 'cmux-planning/scripts/agents_config.py'),
                            'init', '--config', str(default)], check=True, capture_output=True)
            self.assertEqual(fixture.read_bytes(), default.read_bytes())
        for skill in ('cmux-planning', 'cmux-grilling', 'cmux-issue-chain'):
            with self.subTest(skill=skill):
                result = subprocess.run(
                    [sys.executable, str(ROOT / skill / 'scripts/agents_config.py'),
                     'validate', '--config', str(fixture)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


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
                     'data/test.sqlite-wal', 'data/test.db', '.DS_Store', '._app.php',
                     '.phpunit.cache/test-results', '.phpunit.result.cache',
                     '.phpstan/resultCache.php'):
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

    @property
    def registry(self):
        return self.repo / '.scratch/orchestrator/testbeds/registry.jsonl'

    def installer(self, body):
        directory = self.base / 'bin'
        directory.mkdir()
        script = directory / 'composer'
        script.write_text('#!' + sys.executable + '\n' + body)
        script.chmod(0o755)
        return dict(self.env, PATH=str(directory) + os.pathsep + self.env['PATH'])

    def test_released_zeiterfassung_creates_all_four_real_scenarios(self):
        source = ROOT / 'testbeds/zeiterfassung'
        shutil.copytree(source, self.repo / 'testbeds/zeiterfassung',
                        ignore=shutil.ignore_patterns('vendor', '.phpstan', '.phpunit.cache',
                                                     '*.sqlite*', '.DS_Store'))
        for scenario in sorted((source / 'scenarios').iterdir()):
            with self.subTest(scenario=scenario.name):
                target = self.base / scenario.name
                result = self.create(target, scenario=scenario.name, bed='zeiterfassung')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Version: 1.0.0\n', result.stdout)
                self.assertEqual((target / 'docs/plan.md').read_bytes(),
                                 (scenario / 'plan.md').read_bytes())
                fixture = target / '.scratch/orchestrator/agents.json'
                self.assertEqual(fixture.read_bytes(), (source / 'agents.json').read_bytes())
                # The same resolver used by preparation accepts an existing
                # fixture directly, without the first-use initialization branch.
                result = subprocess.run(
                    [sys.executable, str(self.repo / 'cmux-planning/scripts/agents_config.py'),
                     'show-resolved', '--repo', str(target)],
                    cwd=target, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(Path(json.loads(result.stdout)['source']), fixture.resolve())
                self.assertFalse((target / 'evaluation').exists())
                self.assertFalse((target / 'human-input.md').exists())
                self.assertEqual(self.git(target, 'status', '--porcelain'), '')

    def test_e_invoice_scenario_is_complete_and_private_in_copy(self):
        bed = ROOT / 'testbeds/zeiterfassung'
        scenario = bed / 'scenarios/04-e-invoice'
        self.assertEqual(sorted(p.name for p in scenario.iterdir()), ['plan.md'])
        plan = (scenario / 'plan.md').read_bytes()
        text = plan.decode('utf-8')
        for topic in ('invoice model', 'number sequence', 'export', 'fields',
                      'mandatory fields', 'ZUGFeRD', 'XRechnung', 'deadlines', 'Composer'):
            self.assertIn(topic, text)
        for private_word in ('benchmark', 'scenario', 'trap', 'evaluation', 'lane'):
            self.assertNotIn(private_word, text.lower())
        evaluation = (bed / 'evaluation/04-e-invoice.md').read_text()
        for observation in ('code lane', 'docs lane', 'web lane', 'file references',
                            'supported assumptions', 'open decisions', 'same copy',
                            'network access', 'source drift', 'current sources'):
            self.assertIn(observation, evaluation)
        self.assertGreaterEqual(evaluation.count('- [ ]'), 6)
        for field in ('Date', 'Testbed version', 'Scenario', 'Registry entry id',
                      'Recorded skill state', 'Date-attributed skill commit',
                      'Run identifier', 'Observations met', 'Observations missed',
                      'Observations not exercised', 'Baseline sources', 'Evidence and notes'):
            self.assertIn(f'- {field}:\n', evaluation)
        self.assertNotIn('- [x]', evaluation.lower())

        # Exercise the public CLI with the real input, using the synthetic
        # version and configuration until the separate version-cut ticket.
        destination = self.bed / 'scenarios/04-e-invoice'
        destination.mkdir()
        (destination / 'plan.md').write_bytes(plan)
        (self.bed / 'evaluation/04-e-invoice.md').write_text(evaluation)
        result = self.create(scenario='04-e-invoice')
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.base / 'target'
        self.assertEqual((target / 'docs/plan.md').read_bytes(), plan)
        self.assertFalse((target / 'evaluation').exists())
        self.assertFalse((target / 'scenarios').exists())
        self.assertNotIn(evaluation, result.stdout)

    def test_partial_invoice_scenario_is_complete_and_private_in_copy(self):
        bed = ROOT / 'testbeds/zeiterfassung'
        scenario = bed / 'scenarios/01-partial-invoices'
        self.assertEqual(sorted(p.name for p in scenario.iterdir()), ['plan.md'])
        plan = (scenario / 'plan.md').read_bytes()
        text = plan.decode('utf-8').lower()
        for private_word in ('benchmark', 'scenario', 'trap', 'evaluation', 'prefactor', 'ticket'):
            self.assertNotIn(private_word, text)
        evaluation = (bed / 'evaluation/01-partial-invoices.md').read_text()
        self.assertIn('slice_type: prefactor', evaluation)
        for field in ('Date', 'Testbed version', 'Scenario', 'Registry entry id',
                      'Recorded skill state', 'Date-attributed skill commit',
                      'Run identifier', 'Observations met', 'Observations missed'):
            self.assertIn(f'- {field}:\n', evaluation)
        self.assertNotIn('- [x]', evaluation.lower())

        # Exercise the public creation CLI with the real scenario bytes. Version
        # and worker configuration come from the synthetic bed until its version cut.
        (self.bed / 'scenarios/one/plan.md').write_bytes(plan)
        (self.bed / 'evaluation/one.md').write_text(evaluation)
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.base / 'target'
        self.assertEqual((target / 'docs/plan.md').read_bytes(), plan)
        self.assertFalse((target / 'evaluation').exists())
        self.assertFalse((target / 'scenarios').exists())
        self.assertNotIn(b'01-partial-invoices.md', (target / 'app.php').read_bytes())

    def test_vat_scenario_copies_plan_and_prints_private_human_input(self):
        bed = ROOT / 'testbeds/zeiterfassung'
        scenario = bed / 'scenarios/02-vat-rate'
        self.assertEqual(sorted(p.name for p in scenario.iterdir()),
                         ['human-input.md', 'plan.md'])
        plan = (scenario / 'plan.md').read_bytes()
        human = (scenario / 'human-input.md').read_bytes()
        text = plan.decode('utf-8')
        self.assertIn('Invoice::VAT_RATE', text)
        self.assertIn('19%', text)
        self.assertIn('constant in code', text)
        for private_word in ('benchmark', 'scenario', 'trap', 'evaluation', 'contradiction'):
            self.assertNotIn(private_word, text.lower())
        self.assertIn('configurable', human.decode('utf-8'))
        self.assertIn('When:', human.decode('utf-8'))
        evaluation = (bed / 'evaluation/02-vat-rate.md').read_text()
        for field in ('Date', 'Testbed version', 'Scenario', 'Registry entry id',
                      'Recorded skill state', 'Date-attributed skill commit',
                      'Run identifier', 'Observations met', 'Observations missed'):
            self.assertIn(f'- {field}:\n', evaluation)
        self.assertNotIn('- [x]', evaluation.lower())

        # Use the real scenario with the synthetic version/fixture until the
        # testbed version cut; exercise the public CLI without changing the source.
        destination = self.bed / 'scenarios/02-vat-rate'
        destination.mkdir()
        (destination / 'plan.md').write_bytes(plan)
        (destination / 'human-input.md').write_bytes(human)
        (self.bed / 'evaluation/02-vat-rate.md').write_text(evaluation)
        result = self.create(scenario='02-vat-rate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith(human.decode('utf-8')))
        self.assertIn('orchestrator conversation', result.stdout)
        target = self.base / 'target'
        self.assertEqual((target / 'docs/plan.md').read_bytes(), plan)
        self.assertEqual(set(self.git(target, 'ls-files').splitlines()),
                         {'app.php', 'run', '.gitignore', 'ignored.txt', 'docs/plan.md',
                          '.scratch/orchestrator/agents.json'})
        self.assertFalse((target / 'human-input.md').exists())
        self.assertFalse((target / 'evaluation').exists())
        self.assertFalse((target / 'scenarios').exists())

    def test_billed_entries_migration_scenario_is_complete_and_private_in_copy(self):
        bed = ROOT / 'testbeds/zeiterfassung'
        scenario = bed / 'scenarios/03-billed-entries-migration'
        self.assertEqual(sorted(p.name for p in scenario.iterdir()), ['plan.md'])
        plan = (scenario / 'plan.md').read_bytes()
        text = plan.decode('utf-8').lower()
        for required in ('already billed', 'invoice', 'production', 'sqlite',
                         'schema', 'backup', 'run', 'verify', 'restore'):
            self.assertIn(required, text)
        for private_word in ('lock', 'blocker', 'benchmark', 'scenario', 'trap',
                             'evaluation', 'hitl', 'reviewer'):
            self.assertNotIn(private_word, text)
        evaluation = (bed / 'evaluation/03-billed-entries-migration.md').read_text()
        for required in ('specification reviewer', 'gate output',
                         "reviewer's recommendation", 'HITL', 'AFK', 'Blocked by'):
            self.assertIn(required, evaluation)
        for field in ('Date', 'Testbed version', 'Scenario', 'Registry entry id',
                      'Recorded skill state', 'Date-attributed skill commit',
                      'Run identifier', 'Observations met', 'Observations missed',
                      'Observations not exercised', 'Evidence and notes'):
            self.assertIn(f'- {field}:\n', evaluation)
        self.assertNotIn('- [x]', evaluation.lower())

        # Exercise the real scenario through the public CLI with the synthetic
        # version/configuration until the testbed version cut.
        destination = self.bed / 'scenarios/03-billed-entries-migration'
        destination.mkdir()
        (destination / 'plan.md').write_bytes(plan)
        (self.bed / 'evaluation/03-billed-entries-migration.md').write_text(evaluation)
        result = self.create(scenario='03-billed-entries-migration')
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.base / 'target'
        self.assertEqual((target / 'docs/plan.md').read_bytes(), plan)
        self.assertEqual(set(self.git(target, 'ls-files').splitlines()),
                         {'app.php', 'run', '.gitignore', 'ignored.txt', 'docs/plan.md',
                          '.scratch/orchestrator/agents.json'})
        self.assertFalse((target / 'evaluation').exists())
        self.assertFalse((target / 'scenarios').exists())
        self.assertNotIn(evaluation, result.stdout)

    def test_registry_appends_identity_without_rewriting_existing_bytes(self):
        before = datetime.now(timezone.utc)
        entries = []
        for number in range(2):
            previous = self.registry.read_bytes() if self.registry.exists() else b''
            target = self.base / f'copy-{number}'
            result = self.create(target / '..' / target.name)
            self.assertEqual(result.returncode, 0, result.stderr)
            appended = self.registry.read_bytes()
            self.assertTrue(appended.startswith(previous))
            line = appended[len(previous):]
            self.assertEqual(line.count(b'\n'), 1)
            entry = json.loads(line)
            self.assertEqual(set(entry), {'entry_id', 'target', 'created_at', 'testbed',
                             'version', 'scenario', 'skill_state', 'project_commit',
                             'head_commit', 'fixture_sha256'})
            self.assertEqual(str(uuid.UUID(entry['entry_id'])), entry['entry_id'])
            self.assertEqual(entry['target'], str(target.resolve()))
            self.assertEqual((entry['testbed'], entry['version'], entry['scenario']),
                             ('demo', '1.2.3', 'one'))
            self.assertEqual(entry['skill_state'], self.git(self.repo, 'rev-parse', '--short', 'HEAD'))
            for field, revision in (('project_commit', 'HEAD^'), ('head_commit', 'HEAD')):
                self.assertEqual(entry[field], self.git(target, 'rev-parse', revision))
            self.assertEqual(entry['fixture_sha256'],
                             hashlib.sha256((self.bed / 'agents.json').read_bytes()).hexdigest())
            timestamp = datetime.fromisoformat(entry['created_at'])
            self.assertEqual(timestamp.utcoffset().total_seconds(), 0)
            self.assertLessEqual(before, timestamp)
            self.assertLessEqual(timestamp, datetime.now(timezone.utc))
            self.assertTrue(result.stdout.endswith(f"Registry entry: {entry['entry_id']}\n"))
            entries.append(entry)
        self.assertNotEqual(entries[0]['entry_id'], entries[1]['entry_id'])
        for field in ('project_commit', 'head_commit', 'fixture_sha256'):
            self.assertEqual(entries[0][field], entries[1][field])

    def test_registry_preserves_unreadable_history_and_skip_does_not_install(self):
        self.registry.parent.mkdir(parents=True)
        history = b'not valid JSON: \xff\n'
        self.registry.write_bytes(history)
        env = self.installer('raise SystemExit("must not run")\n')
        result = self.create(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.registry.read_bytes().startswith(history))
        self.assertEqual(len(self.registry.read_bytes().splitlines()), 2)

    def test_install_runs_in_committed_copy_before_registry_append(self):
        env = self.installer(
            'import pathlib, subprocess, sys\n'
            'assert sys.argv[1:] == ["install", "--no-interaction", "--no-scripts", "--no-plugins"]\n'
            'assert pathlib.Path("docs/plan.md").is_file()\n'
            'assert subprocess.check_output(["git", "rev-list", "--count", "HEAD"]).strip() == b"2"\n'
            f'assert not pathlib.Path({str(self.registry)!r}).exists()\n'
            'import os\nassert "COMPOSER_VENDOR_DIR" not in os.environ\n'
            'pathlib.Path("vendor").mkdir()\n'
            'pathlib.Path("vendor/autoload.php").write_text("installed")\n')
        env['COMPOSER_VENDOR_DIR'] = str(self.base / 'elsewhere')
        result = self.create(skip=False, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.base / 'target'
        self.assertTrue((target / 'vendor/autoload.php').is_file())
        self.assertEqual(self.git(target, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual(self.git(target, 'check-ignore', 'vendor/autoload.php'), 'vendor/autoload.php')
        self.assertEqual(len(self.registry.read_text().splitlines()), 1)

    def test_failed_install_keeps_committed_target_and_registry_unchanged(self):
        self.registry.parent.mkdir(parents=True)
        self.registry.write_bytes(b'existing history\n')
        env = self.installer('import pathlib, sys\n'
                             'pathlib.Path("partial-install").write_text("inspect me")\n'
                             'print("installer stdout")\n'
                             'print("installer stderr", file=sys.stderr)\n'
                             'raise SystemExit(17)\n')
        result = self.create(skip=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('installer stdout', result.stdout + result.stderr)
        self.assertIn('installer stderr', result.stdout + result.stderr)
        self.assertNotIn('Registry entry:', result.stdout)
        self.assertEqual(self.registry.read_bytes(), b'existing history\n')
        target = self.base / 'target'
        self.assertEqual(self.git(target, 'rev-list', '--count', 'HEAD'), '2')
        self.assertEqual((target / 'partial-install').read_text(), 'inspect me')
        self.assertEqual((target / 'app.php').read_bytes(), (self.project / 'app.php').read_bytes())

    def test_install_that_dirties_seed_is_not_recorded(self):
        env = self.installer('from pathlib import Path\nPath("app.php").write_text("changed")\n')
        result = self.create(skip=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('working tree is not clean', result.stderr)
        self.assertFalse(self.registry.parent.exists())
        self.assertEqual((self.base / 'target/app.php').read_text(), 'changed')

    @unittest.skipUnless(shutil.which('composer'), 'Composer is not installed')
    def test_real_composer_install_with_committed_lock(self):
        (self.project / 'composer.json').write_text(json.dumps({
            'name': 'testbed/minimal', 'require': {},
            'scripts': {'post-install-cmd': '@php -r "touch(\'script-ran\');"'},
        }))
        (self.project / 'composer.lock').write_text(json.dumps({
            'content-hash': '87be2b96663f8f582e027d1b66288bfd',
            'packages': [], 'packages-dev': [], 'aliases': [],
            'minimum-stability': 'stable', 'stability-flags': {},
            'prefer-stable': False, 'prefer-lowest': False,
            'platform': {}, 'platform-dev': {}, 'plugin-api-version': '2.6.0',
        }))
        result = self.create(skip=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.base / 'target'
        self.assertTrue((target / 'vendor/autoload.php').is_file())
        self.assertFalse((target / 'script-ran').exists())
        self.assertEqual(self.git(target, 'show', 'HEAD:composer.lock'),
                         (self.project / 'composer.lock').read_text())
        self.assertEqual(self.git(target, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual(len(self.registry.read_text().splitlines()), 1)

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
        self.registry.parent.mkdir(parents=True)
        self.registry.write_bytes(b'untouched registry history\n')
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
            entry = json.loads(self.registry.read_text().splitlines()[-1])
            self.assertEqual(entry['skill_state'], clean + '-dirty')

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
