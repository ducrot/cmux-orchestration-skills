#!/usr/bin/env python3
"""Create a verified testbed copy: create <testbed> <scenario> <target> [--skip-install].

Sources are resolved beside this module's repository, independent of the current
working directory. Preflight refuses nonempty or internal targets, unknown names,
invalid worker fixtures, symlinks and reserved output paths before writing anything.
Only project files (excluding dependencies, scratch, Git, SQLite, check caches and OS
metadata), the unchanged worker fixture and the chosen docs/plan.md enter the copy. Content
and executable modes are verified before two deterministic, isolated Git commits.
Existing files are never overwritten; failed copies are retained for inspection.
Dependencies are installed without scripts or plugins, then the copy's identity
is appended to the repository's ignored registry. --skip-install is for tests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata
import uuid

REPOSITORY = Path(__file__).resolve().parents[1]
SKILLS = ('cmux-planning', 'cmux-grilling', 'cmux-issue-chain')
FIXTURE = Path('.scratch/orchestrator/agents.json')
PLAN = Path('docs/plan.md')
REGISTRY = REPOSITORY / '.scratch/orchestrator/testbeds/registry.jsonl'
# These redirect or narrow what Composer installs without appearing in the registry.
COMPOSER_OVERRIDES = ('COMPOSER', 'COMPOSER_VENDOR_DIR', 'COMPOSER_BIN_DIR', 'COMPOSER_NO_DEV')


class Refusal(Exception):
    """An input or copy violates the creation rules."""


def inherited_environment() -> dict[str, str]:
    """Discard inherited Git overrides, including injected -c configuration."""
    return {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}


def git_environment() -> dict[str, str]:
    environment = inherited_environment()
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM='1', GIT_ATTR_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
        GIT_AUTHOR_NAME='Testbed', GIT_AUTHOR_EMAIL='testbed@example.invalid',
        GIT_COMMITTER_NAME='Testbed', GIT_COMMITTER_EMAIL='testbed@example.invalid',
        GIT_AUTHOR_DATE='2000-01-01T00:00:00+00:00',
        GIT_COMMITTER_DATE='2000-01-01T00:00:00+00:00',
    )
    return environment


def git_bytes(directory: Path, *arguments: str, input: bytes | None = None) -> bytes:
    result = subprocess.run(
        ['git', '--no-optional-locks', '-c', 'core.hooksPath=' + os.devnull,
         '-c', 'commit.gpgSign=false', '-c', 'core.autocrlf=false',
         '-c', 'core.fileMode=true', '-C', str(directory), *arguments],
        env=git_environment(), capture_output=True, input=input, check=True,
    )
    return result.stdout


def git(directory: Path, *arguments: str) -> str:
    return git_bytes(directory, *arguments).decode('utf-8').strip()


def source_git(*arguments: str) -> str:
    # The user's own configuration (global excludes, core.fileMode) decides what counts as dirty.
    result = subprocess.run(
        ['git', '--no-optional-locks', '-C', str(REPOSITORY), *arguments],
        env=inherited_environment(), capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def named_directory(parent: Path, name: str, label: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
        raise Refusal(f'unknown {label}: {name}')
    path = parent / name
    if path.is_symlink() or not path.is_dir():
        raise Refusal(f'unknown {label}: {name}')
    return path


def regular_file(path: Path) -> tuple[bytes, bool]:
    if path.is_symlink():
        raise Refusal(f'symlink is not allowed in testbed inputs: {path}')
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode):
        raise Refusal(f'expected a regular input file: {path}')
    return path.read_bytes(), bool(mode & 0o111)


def excluded(name: str) -> bool:
    lowered = name.lower()
    return (name in {'.git', 'vendor', '.scratch', '.phpunit.cache', '.phpunit.result.cache',
                     '.phpstan', '.DS_Store', '__MACOSX', 'Thumbs.db', 'Desktop.ini',
                     '.Spotlight-V100', '.Trashes'}
            or name.startswith('._')
            or re.search(r'\.(?:sqlite\d*|db)(?:-(?:wal|shm|journal))?$', lowered) is not None)


def project_manifest(project: Path) -> dict[Path, tuple[bytes, bool]]:
    if project.is_symlink() or not project.is_dir():
        raise Refusal(f'project must be a directory: {project}')
    manifest = {}

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir()):
            if excluded(child.name):
                continue
            if child.is_symlink():
                raise Refusal(f'symlink is not allowed in project: {child}')
            if child.is_dir():
                visit(child)
            else:
                manifest[child.relative_to(project)] = regular_file(child)

    visit(project)
    # These paths are owned by the tool, so never replace a project file with them.
    reserved = {str(path).casefold() for path in (PLAN, *PLAN.parents)}
    for path in manifest:
        folded = str(path).casefold()
        if folded in reserved or folded.startswith(str(PLAN).casefold() + '/'):
            raise Refusal('project conflicts with reserved docs/plan.md')
    return manifest


def verify(target: Path, expected: dict[Path, tuple[bytes, bool]]) -> None:
    actual = {}
    for directory, directories, files in os.walk(target):
        root = Path(directory)
        if root == target and '.git' in directories:
            directories.remove('.git')
        for name in files:
            path = root / name
            actual[path.relative_to(target)] = regular_file(path)
    if actual != expected:
        raise Refusal('copy verification failed: file contents, paths or executable bits differ')


def write_new(target: Path, path: Path, entry: tuple[bytes, bool]) -> None:
    destination = target / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    content, executable = entry
    with destination.open('xb') as stream:
        stream.write(content)
    destination.chmod(0o755 if executable else 0o644)


def verify_git(target: Path, expected: dict[Path, tuple[str, str]], *, committed: bool) -> None:
    arguments = ('ls-tree', '-rz', '--full-tree', 'HEAD') if committed else ('ls-files', '--stage', '-z')
    actual = {}
    for record in git_bytes(target, *arguments).split(b'\0')[:-1]:
        metadata, name = record.split(b'\t', 1)
        fields = metadata.decode('ascii').split()
        actual[Path(os.fsdecode(name))] = (fields[0], fields[2 if committed else 1])
    if actual != expected:
        location = 'commit' if committed else 'index'
        raise Refusal(f'copy verification failed: {location} blobs, paths or executable modes differ')


def stage(target: Path, manifest: dict[Path, tuple[bytes, bool]]) -> dict[Path, tuple[str, str]]:
    # git init enables this on macOS; status then compares precomposed directory
    # names, so decomposed index paths would show the copy as dirty.
    precompose = git(target, 'config', '--bool', '--default', 'false',
                     'core.precomposeUnicode') == 'true'
    staged = {}
    for path, (content, executable) in manifest.items():
        # Hash raw source bytes and populate the index directly: project attributes
        # must never run text, encoding, ident or filter conversions on the copy.
        oid = git_bytes(target, 'hash-object', '-w', '--no-filters', '--stdin',
                        input=content).decode('ascii').strip()
        name = Path(unicodedata.normalize('NFC', str(path))) if precompose else path
        staged[name] = ('100755' if executable else '100644', oid)
    git_bytes(target, 'update-index', '-z', '--index-info', input=b''.join(
        f'{mode} {oid}\t'.encode('ascii') + os.fsencode(path) + b'\0'
        for path, (mode, oid) in staged.items()))
    return staged


def commit(target: Path, expected: dict[Path, tuple[str, str]], message: str) -> str:
    verify_git(target, expected, committed=False)
    git(target, 'commit', '--quiet', '-m', message)
    verify_git(target, expected, committed=True)
    return git(target, 'rev-parse', 'HEAD')


def require_clean(target: Path, step: str) -> None:
    if git(target, 'status', '--porcelain', '--untracked-files=all'):
        raise Refusal(f'{step} verification failed: working tree is not clean')


def create(args: argparse.Namespace) -> int:
    bed = named_directory(REPOSITORY / 'testbeds', args.testbed, 'testbed')
    scenario = named_directory(bed / 'scenarios', args.scenario, 'scenario')
    target = Path(args.target).expanduser().resolve()
    if target.is_relative_to(bed.resolve()):
        raise Refusal('target must be outside the testbed source')
    if target.is_relative_to(REPOSITORY):
        raise Refusal('target must be outside this repository')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise Refusal('target exists and is not empty')

    fixture_path = bed / 'agents.json'
    fixture = regular_file(fixture_path)
    validation = subprocess.run(
        [sys.executable, str(REPOSITORY / 'cmux-planning/scripts/agents_config.py'),
         'validate', '--config', str(fixture_path)],
        cwd=REPOSITORY, env=git_environment(), capture_output=True, text=True,
    )
    if validation.returncode:
        raise Refusal('invalid fixture: ' + (validation.stderr or validation.stdout).strip())
    version = regular_file(bed / 'VERSION')[0].decode('utf-8').strip()
    if not version:
        raise Refusal('VERSION must not be empty')
    plan = regular_file(scenario / 'plan.md')
    human_path = scenario / 'human-input.md'
    human = regular_file(human_path)[0] if human_path.exists() or human_path.is_symlink() else None
    if human is not None:
        human.decode('utf-8')  # Validate before any target write; print the original bytes below.
    project = project_manifest(bed / 'project')
    project[FIXTURE] = fixture
    skill_state = source_git('rev-parse', '--short', 'HEAD')
    if source_git('status', '--porcelain', '--untracked-files=all',
                  '--ignored=no', '--', *SKILLS):
        skill_state += '-dirty'

    target.mkdir(parents=True, exist_ok=True)
    for path, entry in project.items():
        write_new(target, path, entry)
    verify(target, project)
    git(target, 'init', '--quiet', '--initial-branch=main', '--template=')
    # Keep status comparisons consistent with the raw blobs. info/attributes has
    # precedence over project attributes without changing any copied source file.
    write_new(target, Path('.git/info/attributes'),
              (b'* -text -filter -ident -working-tree-encoding\n', False))
    staged = stage(target, project)
    project_commit = commit(target, staged, 'Testbed project')
    write_new(target, PLAN, plan)
    verify(target, {**project, PLAN: plan})
    staged |= stage(target, {PLAN: plan})
    head_commit = commit(target, staged, 'Testbed scenario')
    require_clean(target, 'copy')
    # Installation output belongs to this copy but must not change its seed tree,
    # even when the project's own ignore file does not mention dependencies.
    write_new(target, Path('.git/info/exclude'), (b'/vendor/\n', False))
    if not args.skip_install:
        subprocess.run(
            ['composer', 'install', '--no-interaction', '--no-scripts', '--no-plugins'],
            cwd=target, check=True, env={key: value for key, value in inherited_environment().items()
                                         if key not in COMPOSER_OVERRIDES},
        )
        require_clean(target, 'installation')

    entry = {
        'entry_id': str(uuid.uuid4()),
        'target': str(target),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'testbed': args.testbed,
        'version': version,
        'scenario': args.scenario,
        'skill_state': skill_state,
        'project_commit': project_commit,
        'head_commit': head_commit,
        'fixture_sha256': hashlib.sha256(fixture[0]).hexdigest(),
    }
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry) + '\n')
    print(f'Target: {target}\nTestbed: {args.testbed}\nVersion: {version}\n'
          f'Scenario: {args.scenario}\nSkill state: {skill_state}\n'
          f'Project commit: {project_commit}\nHead commit: {head_commit}\n'
          f'Registry entry: {entry["entry_id"]}')
    if human is not None:
        print('\nState the following in the orchestrator conversation:')
        sys.stdout.flush()
        sys.stdout.buffer.write(human)
        sys.stdout.buffer.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('create', help='create a verified deterministic scenario repository')
    command.add_argument('testbed')
    command.add_argument('scenario')
    command.add_argument('target')
    command.add_argument('--skip-install', action='store_true', help='tests only: skip dependency installation')
    args = parser.parse_args()
    try:
        return create(args)
    except (Refusal, OSError, UnicodeError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else ''
        if isinstance(detail, bytes):
            detail = detail.decode('utf-8', errors='replace')
        print(f'testbed: {(detail or "").strip() or error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
