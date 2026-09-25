#!/usr/bin/env python3
"""Create, validate, and inspect deterministic orchestration worker profiles, and preflight,
launch, and probe the harnesses they resolve to."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
DEFAULT_RELATIVE_PATH = Path(".scratch/orchestrator/agents.json")
SCRIPT_PATH = Path(__file__).resolve()
COORDINATED_UPGRADE_WARNING = (
    "Coordinated upgrade required: upgrade all three skills together (cmux-planning, "
    "cmux-grilling, and cmux-issue-chain) before migrating the shared configuration to schema v2. "
    "Older separately installed sibling skills cannot read the migrated file."
)

TOP_LEVEL_FIELDS = {"schema_version", "profiles", "workflows"}
PROFILE_FIELDS = {"harness", "executable", "model", "effort"}
COMPATIBLE_HARNESSES = {
    "issue-chain": {
        "implement": {"claude-code", "codex", "pi"},
        "simplify": {"claude-code", "codex", "pi"},
        "review": {"claude-code", "codex", "pi"},
        "test": {"claude-code", "codex", "pi"},
        "triage": {"claude-code", "codex", "pi"},
    },
    "grilling": {
        "codebase": {"claude-code", "codex", "pi"},
        "codebase2": {"claude-code", "codex", "pi"},
        "docs": {"claude-code", "codex", "pi"},
        # Pi has no web tool, but reaches the web through bash; Codex cannot.
        "web": {"claude-code", "pi"},
    },
    "planning": {
        "spec": {"claude-code", "codex", "pi"},
        "tickets": {"claude-code", "codex", "pi"},
        "reviewer": {"claude-code", "codex", "pi"},
    },
}
# The schema version each workflow became required in, so the version-one view stays derived.
WORKFLOW_SCHEMA_VERSION = {"issue-chain": 1, "grilling": 1, "planning": 2}
LEGACY_COMPATIBLE_HARNESSES = {
    workflow: workers
    for workflow, workers in COMPATIBLE_HARNESSES.items()
    if WORKFLOW_SCHEMA_VERSION.get(workflow, SCHEMA_VERSION) <= LEGACY_SCHEMA_VERSION
}
# Derived so the worker vocabulary cannot drift from the compatibility rules. Ordered, because
# CLI help, error text, and worker iteration all present workers in this order.
WORKFLOW_WORKERS = {
    workflow: tuple(workers) for workflow, workers in COMPATIBLE_HARNESSES.items()
}
OPTIONAL_WORKERS = {"issue-chain": {"triage": "claude-opus-high"}}

# Each workflow calls its workers something else in operator-facing text.
WORKFLOW_NOUN = {"issue-chain": "worker", "grilling": "lane", "planning": "role"}

# Pi resolves a bare model name against its default provider and its auth check rejects one
# outright, so a Pi profile has to name the provider it is entitled to.
PI_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:@-]*/[A-Za-z0-9][A-Za-z0-9._+:/@-]*\Z")

# The registry is the extension seam. Configuration cannot add entries or capabilities.
ADAPTERS = {
    "claude-code": {"supported": True, "efforts": {"low", "medium", "high", "xhigh", "max"}},
    "codex": {"supported": True, "efforts": {"low", "medium", "high", "xhigh", "max", "ultra"}},
    # Pi also knows "off" and "minimal"; they stay out so one effort word means the same
    # thing on every harness.
    "pi": {
        "supported": True,
        "efforts": {"low", "medium", "high", "xhigh", "max"},
        "model_re": PI_MODEL_RE,
    },
    "hermes": {"supported": False, "efforts": set()},
}
SUPPORTED_ADAPTERS = {name for name, adapter in ADAPTERS.items() if adapter["supported"]}

PROFILE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
PROGRAM_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
ABSOLUTE_EXECUTABLE_RE = re.compile(r"/[A-Za-z0-9._+/@:-]+\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:/@-]*\Z")
MODEL_SYNTAX_REASON = {
    "pi": "model must be written as provider/id, for example google/gemini-3.1-pro-preview",
}


def model_syntax_error(harness: object, model: str) -> str | None:
    """The model rule both the config file and a typed override are held to."""
    if not MODEL_RE.fullmatch(model):
        return "model has unusable syntax; use one non-whitespace model identifier"
    rule = ADAPTERS.get(harness, {}).get("model_re") if isinstance(harness, str) else None
    if rule is not None and not rule.fullmatch(model):
        return MODEL_SYNTAX_REASON[harness]
    return None


def valid_executable_syntax(value: str) -> bool:
    """What a pane may be told to run. Config-time and launch-time checks share this rule."""
    return bool(PROGRAM_NAME_RE.fullmatch(value) or ABSOLUTE_EXECUTABLE_RE.fullmatch(value))

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "profiles": {
        "claude-opus-high": {
            "harness": "claude-code",
            "executable": "claude",
            "model": "opus",
            "effort": "high",
        },
        "claude-opus-medium": {
            "harness": "claude-code",
            "executable": "claude",
            "model": "opus",
            "effort": "medium",
        },
        "claude-opus-xhigh": {
            "harness": "claude-code",
            "executable": "claude",
            "model": "opus",
            "effort": "xhigh",
        },
        "claude-sonnet-medium": {
            "harness": "claude-code",
            "executable": "claude",
            "model": "sonnet",
            "effort": "medium",
        },
        "claude-fable-medium": {
            "harness": "claude-code",
            "executable": "claude",
            "model": "fable",
            "effort": "medium",
        },
        "claude-fable-high": {
            "harness": "claude-code",
            "executable": "claude",
            "model": "fable",
            "effort": "high",
        },
        "codex-astra-high": {
            "harness": "codex",
            "executable": "codex",
            "model": "gpt-6-astra",
            "effort": "high",
        },
        "codex-astra-medium": {
            "harness": "codex",
            "executable": "codex",
            "model": "gpt-6-astra",
            "effort": "medium",
        },
        "codex-astra-xhigh": {
            "harness": "codex",
            "executable": "codex",
            "model": "gpt-6-astra",
            "effort": "xhigh",
        },
        "codex-luna-medium": {
            "harness": "codex",
            "executable": "codex",
            "model": "gpt-5.6-luna",
            "effort": "medium",
        },
        "pi-gemini-pro-high": {
            "harness": "pi",
            "executable": "pi",
            "model": "google/gemini-3.1-pro-preview",
            "effort": "high",
        },
        "pi-gemini-pro-medium": {
            "harness": "pi",
            "executable": "pi",
            "model": "google/gemini-3.1-pro-preview",
            "effort": "medium",
        },
        "pi-glm-high": {
            "harness": "pi",
            "executable": "pi",
            "model": "openrouter/z-ai/glm-5.3",
            "effort": "high",
        },
        "pi-glm-medium": {
            "harness": "pi",
            "executable": "pi",
            "model": "openrouter/z-ai/glm-5.3",
            "effort": "medium",
        },
        "pi-grok-high": {
            "harness": "pi",
            "executable": "pi",
            "model": "xai/grok-4.7",
            "effort": "high",
        },
        "pi-grok-medium": {
            "harness": "pi",
            "executable": "pi",
            "model": "xai/grok-4.7",
            "effort": "medium",
        },
    },
    "workflows": {
        "issue-chain": {
            "implement": "codex-astra-xhigh",
            "simplify": "claude-opus-high",
            "review": "claude-opus-high",
            "test": "codex-astra-high",
        },
        "grilling": {
            "codebase": "claude-opus-high",
            "codebase2": "codex-astra-high",
            "docs": "codex-luna-medium",
            "web": "claude-sonnet-medium",
        },
        "planning": {
            "spec": "claude-fable-high",
            "tickets": "claude-fable-high",
            "reviewer": "codex-astra-high",
        },
    },
}


class ConfigError(Exception):
    """Configuration operation could not be completed."""


class ObjectWithDuplicates(dict):
    """JSON object that remembers keys a normal decoder would silently replace."""

    def __init__(self, pairs: Iterable[tuple[str, Any]]):
        super().__init__()
        self.duplicate_keys: list[str] = []
        for key, value in pairs:
            if key in self:
                self.duplicate_keys.append(key)
            self[key] = value


def context_error(
    source: Path,
    message: str,
    *,
    workflow: str = "-",
    worker: str = "-",
    profile: str = "-",
    field: str = "-",
) -> str:
    return (
        f"source={source} workflow={workflow} worker={worker} "
        f"profile={profile} field={field}: {message}"
    )


def git_root(start: Path) -> Path:
    start = start.expanduser().resolve()
    if not start.is_dir():
        raise ConfigError(f"target repository path is not a directory: {start}")
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConfigError(f"could not discover the target repository Git root: {error}") from error
    root = result.stdout.strip()
    if result.returncode != 0 or not root:
        raise ConfigError(
            f"no Git root found from {start}; pass --config with an explicit configuration path"
        )
    return Path(root).resolve()


def config_path(explicit: str | None, repository: str | None) -> Path:
    if explicit is not None:
        if not explicit.strip():
            raise ConfigError("--config must name a configuration file")
        selected = Path(explicit).expanduser()
        if not selected.is_absolute():
            selected = Path.cwd() / selected
        return selected.resolve()
    return git_root(Path(repository) if repository else Path.cwd()) / DEFAULT_RELATIVE_PATH


def durable_publish(
    path: Path,
    payload: bytes,
    *,
    mode: int,
    suffix: str,
    publish: Callable[[Path, Path], None],
) -> None:
    """Write and fsync a sibling temporary file, then publish it into place durably."""
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=suffix,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        handle = os.fdopen(descriptor, "wb")
        # fdopen owns the descriptor from here, including when the write below fails.
        descriptor = -1
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        publish(temporary, path)
        # Best effort once the publish succeeded, so a failure here is never reported as
        # "nothing was written".
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_initialize(path: Path) -> None:
    """Publish a complete default file atomically, without replacing an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def link_only(temporary: Path, destination: Path) -> None:
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise ConfigError(
                f"configuration already exists and was not changed: {destination}"
            ) from error

    durable_publish(
        path,
        (json.dumps(DEFAULT_CONFIG, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        mode=0o644,
        suffix=".tmp",
        publish=link_only,
    )


def duplicate_keys(value: Any) -> list[str]:
    """Keys a normal JSON decoder would have silently replaced; empty for any other value."""
    return value.duplicate_keys if isinstance(value, ObjectWithDuplicates) else []


def add_duplicate_errors(value: Any, errors: list[str], source: Path, *, profile: str = "-") -> None:
    for field in duplicate_keys(value):
        errors.append(
            context_error(source, "duplicate field is ambiguous", profile=profile, field=field)
        )


def require_object(
    value: Any,
    errors: list[str],
    source: Path,
    *,
    workflow: str = "-",
    worker: str = "-",
    profile: str = "-",
    field: str,
) -> bool:
    if isinstance(value, dict):
        return True
    errors.append(
        context_error(
            source,
            "value must be a JSON object",
            workflow=workflow,
            worker=worker,
            profile=profile,
            field=field,
        )
    )
    return False


def validate_profile(name: str, value: Any, source: Path, errors: list[str]) -> None:
    if not PROFILE_NAME_RE.fullmatch(name):
        errors.append(
            context_error(
                source,
                "profile name has invalid syntax",
                profile=name,
                field="profile",
            )
        )
    if not require_object(value, errors, source, profile=name, field="profile"):
        return
    add_duplicate_errors(value, errors, source, profile=name)
    for field in sorted(set(value) - PROFILE_FIELDS):
        errors.append(
            context_error(source, "unknown field", profile=name, field=field)
        )
    for field in sorted(PROFILE_FIELDS - set(value)):
        errors.append(
            context_error(source, "required field is missing", profile=name, field=field)
        )

    for field in sorted(PROFILE_FIELDS & set(value)):
        if not isinstance(value[field], str) or not value[field]:
            expected = (
                "executable must be a single program name or absolute path"
                if field == "executable"
                else f"{field} must be a non-empty string with usable syntax"
            )
            errors.append(context_error(source, expected, profile=name, field=field))

    harness = value.get("harness")
    if isinstance(harness, str) and harness:
        adapter = ADAPTERS.get(harness)
        if adapter is None:
            errors.append(
                context_error(
                    source,
                    f"unknown harness {harness!r}",
                    profile=name,
                    field="harness",
                )
            )
        elif not adapter["supported"]:
            errors.append(
                context_error(
                    source,
                    f"harness adapter {harness!r} is not yet supported",
                    profile=name,
                    field="harness",
                )
            )

    executable = value.get("executable")
    if isinstance(executable, str) and executable:
        if not valid_executable_syntax(executable):
            errors.append(
                context_error(
                    source,
                    "executable must be a single program name or absolute path",
                    profile=name,
                    field="executable",
                )
            )

    model = value.get("model")
    if isinstance(model, str) and model:
        reason = model_syntax_error(harness, model)
        if reason is not None:
            errors.append(context_error(source, reason, profile=name, field="model"))

    effort = value.get("effort")
    if isinstance(harness, str) and harness in SUPPORTED_ADAPTERS and isinstance(effort, str) and effort:
        supported = ADAPTERS[harness]["efforts"]
        if effort not in supported:
            errors.append(
                context_error(
                    source,
                    f"unsupported effort {effort!r} for {harness}; expected one of "
                    + ", ".join(sorted(supported)),
                    profile=name,
                    field="effort",
                )
            )


def validate_workflows(
    workflows: Any,
    profiles: dict[str, Any],
    source: Path,
    errors: list[str],
    *,
    compatibility: dict[str, dict[str, set[str]]] = COMPATIBLE_HARNESSES,
    optional: frozenset[str] = frozenset(),
) -> None:
    if not require_object(workflows, errors, source, field="workflows"):
        return
    for workflow in duplicate_keys(workflows):
        errors.append(
            context_error(
                source,
                "duplicate workflow is ambiguous",
                workflow=workflow,
                field="workflow",
            )
        )

    for workflow in sorted(set(workflows) - set(compatibility)):
        errors.append(
            context_error(
                source,
                "unknown workflow",
                workflow=workflow,
                field="workflow",
            )
        )
    for workflow in sorted(set(compatibility) - set(workflows) - optional):
        errors.append(
            context_error(
                source,
                "required workflow is missing",
                workflow=workflow,
                field="workflow",
            )
        )

    for workflow in sorted(set(workflows) & set(compatibility)):
        assignments = workflows[workflow]
        if not require_object(
            assignments,
            errors,
            source,
            workflow=workflow,
            field="assignments",
        ):
            continue
        for worker in duplicate_keys(assignments):
            profile = assignments.get(worker)
            errors.append(
                context_error(
                    source,
                    "duplicate worker assignment is ambiguous",
                    workflow=workflow,
                    worker=worker,
                    profile=profile if isinstance(profile, str) else "-",
                    field="profile",
                )
            )
        expected_workers = set(compatibility[workflow])
        for worker in sorted(set(assignments) - expected_workers):
            errors.append(
                context_error(
                    source,
                    "unknown worker",
                    workflow=workflow,
                    worker=worker,
                    field="worker",
                )
            )
        for worker in sorted(expected_workers - set(assignments) - set(OPTIONAL_WORKERS.get(workflow, {}))):
            errors.append(
                context_error(
                    source,
                    "required worker assignment is missing",
                    workflow=workflow,
                    worker=worker,
                    field="profile",
                )
            )

        for worker in sorted(set(assignments) & expected_workers):
            profile = assignments[worker]
            if not isinstance(profile, str) or not profile:
                errors.append(
                    context_error(
                        source,
                        "profile reference must be a non-empty string",
                        workflow=workflow,
                        worker=worker,
                        field="profile",
                    )
                )
                continue
            if profile not in profiles:
                errors.append(
                    context_error(
                        source,
                        "referenced profile is not defined",
                        workflow=workflow,
                        worker=worker,
                        profile=profile,
                        field="profile",
                    )
                )
                continue
            profile_value = profiles[profile]
            if not isinstance(profile_value, dict):
                continue
            harness = profile_value.get("harness")
            if harness in SUPPORTED_ADAPTERS and harness not in compatibility[workflow][worker]:
                errors.append(
                    context_error(
                        source,
                        f"harness {harness!r} is not compatible with this worker",
                        workflow=workflow,
                        worker=worker,
                        profile=profile,
                        field="harness",
                    )
                )


def validation_errors(
    data: Any,
    source: Path,
    *,
    expected_schema_version: int = SCHEMA_VERSION,
    compatibility: dict[str, dict[str, set[str]]] = COMPATIBLE_HARNESSES,
    optional: frozenset[str] = frozenset(),
) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return [context_error(source, "configuration root must be a JSON object", field="config")]

    add_duplicate_errors(data, errors, source)
    for field in sorted(set(data) - TOP_LEVEL_FIELDS):
        errors.append(context_error(source, "unknown field", field=field))
    for field in sorted(TOP_LEVEL_FIELDS - set(data)):
        errors.append(context_error(source, "required field is missing", field=field))

    schema_version = data.get("schema_version")
    if "schema_version" in data and (
        isinstance(schema_version, bool) or not isinstance(schema_version, int)
    ):
        errors.append(context_error(source, "schema version must be an integer", field="schema_version"))
    elif isinstance(schema_version, int) and schema_version != expected_schema_version:
        errors.append(
            context_error(
                source,
                f"unsupported schema version {schema_version}; only {expected_schema_version} is supported",
                field="schema_version",
            )
        )

    profiles_value = data.get("profiles")
    profiles: dict[str, Any] = profiles_value if isinstance(profiles_value, dict) else {}
    if "profiles" in data:
        if require_object(profiles_value, errors, source, field="profiles"):
            for profile in duplicate_keys(profiles_value):
                errors.append(
                    context_error(
                        source,
                        "duplicate profile is ambiguous",
                        profile=profile,
                        field="profile",
                    )
                )
            if not profiles_value:
                errors.append(context_error(source, "at least one profile is required", field="profiles"))
            for name, value in sorted(profiles_value.items()):
                validate_profile(name, value, source, errors)

    if "workflows" in data:
        validate_workflows(
            data.get("workflows"),
            profiles,
            source,
            errors,
            compatibility=compatibility,
            optional=optional,
        )
    return errors


def read_config_bytes(source: Path, error: type[ConfigError]) -> bytes:
    try:
        return source.read_bytes()
    except FileNotFoundError as cause:
        raise error(
            context_error(
                source,
                "configuration does not exist; initialize it with agents_config.py init, "
                "review the workflow assignments, then retry",
                field="config",
            )
        ) from cause
    except OSError as cause:
        raise error(
            context_error(source, f"could not read configuration: {cause}", field="config")
        ) from cause


def parse_json(payload: bytes, source: Path, error: type[ConfigError]) -> Any:
    """Decode one configuration buffer while preserving duplicate-key evidence."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as cause:
        raise error(
            context_error(source, f"configuration is not valid UTF-8: {cause}", field="config")
        ) from cause
    try:
        data = json.loads(text, object_pairs_hook=ObjectWithDuplicates)
    except json.JSONDecodeError as cause:
        raise error(
            context_error(
                source,
                f"invalid JSON at line {cause.lineno}, column {cause.colno}: {cause.msg}",
                field="json",
            )
        ) from cause
    return data


def require_valid(data: Any, source: Path, error: type[ConfigError]) -> dict[str, Any]:
    """The one gate every configuration passes, so no config is accepted by a second set of
    rules. Callers that also need a digest hash the same bytes this payload was parsed from."""
    errors = validation_errors(data, source)
    if errors:
        raise error("\n".join(errors))
    return data


def preferred_profile(
    profiles: dict[str, Any], allowed_harnesses: set[str], default: str
) -> str | None:
    """The default when it is compatible, else the first compatible name, else nothing."""
    names = sorted(
        name
        for name, profile in profiles.items()
        if isinstance(profile, dict) and profile.get("harness") in allowed_harnesses
    )
    if default in names:
        return default
    return names[0] if names else None


def migrated_planning_assignments(candidate: dict[str, Any]) -> dict[str, str]:
    profiles = candidate["profiles"]
    defaults = DEFAULT_CONFIG["workflows"]["planning"]
    author = preferred_profile(
        profiles, COMPATIBLE_HARNESSES["planning"]["spec"], defaults["spec"]
    )
    if author is None:
        raise ConfigError("version-one migration found no compatible profile for planning authors")

    reviewer = preferred_profile(
        profiles, COMPATIBLE_HARNESSES["planning"]["reviewer"], defaults["reviewer"]
    )
    if reviewer is None:
        reviewer = defaults["reviewer"]
        suffix = 2
        while reviewer in profiles:
            reviewer = f"{defaults['reviewer']}-{suffix}"
            suffix += 1
        profiles[reviewer] = copy.deepcopy(DEFAULT_CONFIG["profiles"][defaults["reviewer"]])
    return {"spec": author, "tickets": author, "reviewer": reviewer}


def migrate_version_one(data: dict[str, Any], source: Path) -> tuple[dict[str, Any], bytes]:
    """Build and validate the complete v2 candidate before any file replacement."""
    # Workflows introduced after v1 are rebuilt below, so a v1 file that already carries one --
    # the shape a user reaches by editing schema_version back to unblock an older sibling -- must
    # not be rejected as declaring an unknown workflow it can never remove.
    legacy_errors = validation_errors(
        data,
        source,
        expected_schema_version=LEGACY_SCHEMA_VERSION,
        optional=frozenset(set(COMPATIBLE_HARNESSES) - set(LEGACY_COMPATIBLE_HARNESSES)),
    )
    if legacy_errors:
        raise ConfigError("cannot migrate invalid version-one configuration:\n" + "\n".join(legacy_errors))
    candidate = copy.deepcopy(data)
    candidate["schema_version"] = SCHEMA_VERSION
    candidate["workflows"]["planning"] = migrated_planning_assignments(candidate)
    payload = (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode("utf-8")
    # Candidate validation deliberately goes through the same strict parser as every v2 read.
    validated = require_valid(parse_json(payload, source, ConfigError), source, ConfigError)
    return validated, payload


def candidate_digest(payload: bytes) -> str:
    """The digest a human approves in a preview and that an acceptance must still produce."""
    return hashlib.sha256(payload).hexdigest()


def migration_commands(path: Path, digest: str | None = None) -> tuple[str, str]:
    """Exact runnable preview and acceptance commands for one selected configuration.

    The acceptance command carries the previewed candidate's digest, so approval is bound to the
    candidate the human actually saw rather than to whatever the file holds when it is run."""
    base = ["python3", str(SCRIPT_PATH), "migrate"]
    selected = ["--config", str(path)]
    approval = ["--expect-sha256", digest] if digest else []
    return shlex.join([*base, *selected]), shlex.join([*base, "--accept", *approval, *selected])


@dataclass(frozen=True)
class MigrationPreview:
    """One validated migration candidate and all human-facing data derived from it."""

    source: Path
    candidate: dict[str, Any]
    payload: bytes
    accepting: bool = False

    @property
    def digest(self) -> str:
        return candidate_digest(self.payload)

    def render_guidance(self) -> str:
        preview_command, acceptance_command = migration_commands(self.source, self.digest)
        preferred = DEFAULT_CONFIG["workflows"]["planning"]["spec"]
        proposed = self.candidate["workflows"]["planning"]["spec"]
        lines = [
            COORDINATED_UPGRADE_WARNING,
            "Acceptance requested for the schema-v1 migration candidate below."
            if self.accepting
            else "Read-only schema-v1 migration preview; the source file has not been changed.",
            f"Validated schema-v2 candidate SHA-256: {self.digest}",
        ]
        if preferred not in self.candidate["profiles"]:
            profile = self.candidate["profiles"][proposed]
            lines.extend(
                [
                    f"Preferred planning author profile {preferred!r} is unavailable.",
                    "Proposed deterministic compatible fallback "
                    f"(no relative quality inferred): profile={proposed!r}, "
                    f"harness={profile['harness']!r}, model={profile['model']!r}, "
                    f"effort={profile['effort']!r}.",
                ]
            )
        lines.extend(
            [
                "Resolved workflow assignments for the complete candidate:",
                json.dumps(resolved_display(self.candidate, self.source), indent=2, sort_keys=True),
                f"Preview command: {preview_command}",
                f"Acceptance command: {acceptance_command}",
            ]
        )
        return "\n".join(lines)


def migration_preview(
    data: dict[str, Any], source: Path, *, accepting: bool = False
) -> MigrationPreview:
    """Build the one authoritative representation of a validated v2 candidate preview."""
    candidate, payload = migrate_version_one(data, source)
    return MigrationPreview(source=source, candidate=candidate, payload=payload, accepting=accepting)


def migration_target(path: Path) -> tuple[Path, os.stat_result]:
    """Resolve and guard the file that an accepted migration would replace."""
    try:
        target = path.resolve(strict=True)
        identity = target.stat()
    except OSError as cause:
        raise ConfigError(f"cannot resolve migration target {path}: {cause}") from cause
    if not stat.S_ISREG(identity.st_mode):
        raise ConfigError(f"migration target is not a regular file: {target}")
    if stat.S_IMODE(identity.st_mode) & 0o222 == 0:
        raise ConfigError(
            f"migration target has no write bit and was not changed: {target}; "
            "make the intended shared file writable, then preview again"
        )
    if identity.st_nlink != 1:
        raise ConfigError(
            f"migration target has {identity.st_nlink} hard links and was not changed: {target}; "
            "select a single-link configuration file before migrating"
        )
    return target, identity


def identity_key(info: os.stat_result) -> tuple[int, ...]:
    """Fields that must not change between the preview and the replacement."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_nlink,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def atomic_replace(path: Path, payload: bytes, *, expected_original: bytes) -> None:
    """Replace an existing configuration atomically after its candidate is fully validated.

    Resolved first: replacing a symlink would drop the link and leave the shared file it
    points at unmigrated."""
    target, identity = migration_target(path)
    if target.read_bytes() != expected_original:
        raise ConfigError(
            f"migration target changed after preview and was not replaced: {target}; preview again"
        )
    if identity_key(target.stat()) != identity_key(identity):
        raise ConfigError(
            f"migration target identity or metadata changed and was not replaced: {target}; preview again"
        )
    durable_publish(
        target,
        payload,
        mode=stat.S_IMODE(identity.st_mode),
        suffix=".migration.tmp",
        publish=os.replace,
    )


def is_legacy(data: Any) -> bool:
    """Whether a parsed payload declares the previous schema version.

    Shared so preview, refusal, and acceptance cannot disagree about what requires migration.
    `True == 1`, so a bool must not be mistaken for a version-one file."""
    version = data.get("schema_version") if isinstance(data, dict) else None
    return (
        isinstance(version, int)
        and not isinstance(version, bool)
        and version == LEGACY_SCHEMA_VERSION
    )


def load_validated_with_payload(
    path: Path, error: type[ConfigError]
) -> tuple[dict[str, Any], bytes]:
    original = read_config_bytes(path, error)
    data = parse_json(original, path, error)
    if is_legacy(data):
        try:
            preview = migration_preview(data, path)
        except ConfigError as cause:
            raise error(
                context_error(
                    path,
                    f"cannot inspect invalid version-one migration candidate: {cause}",
                    field="migration",
                )
            ) from cause
        raise error(
            f"{preview.render_guidance()}\n"
            "Schema-v1 configuration cannot be used by inspection or orchestration "
            "preparation. Run the preview command, obtain explicit human approval, then run "
            "the acceptance command."
        )
    return require_valid(data, path, error), original


def load_validated(path: Path) -> dict[str, Any]:
    return load_validated_with_payload(path, ConfigError)[0]


def resolved_display(data: dict[str, Any], source: Path) -> dict[str, Any]:
    resolved_workflows: dict[str, dict[str, dict[str, str]]] = {}
    for workflow in data["workflows"]:
        resolved_workflows[workflow] = {
            worker: {**profile, "source": str(source)}
            for worker, profile in resolve_workers(data, source, {}, workflow=workflow).items()
        }
    return {
        "source": str(source),
        "schema_version": data["schema_version"],
        "profiles": data["profiles"],
        "assignments": data["workflows"],
        "resolved_workflows": resolved_workflows,
    }


# --- Harness runtime -------------------------------------------------------------------------
# Turning a validated profile into a preflighted, launchable, or probeable command lives next to
# the ADAPTERS registry above, so a new harness is added here once instead of in every skill.
# Sandbox, approval, and network policy stays with each workflow and arrives as arguments.

DEFAULT_PROBE_TIMEOUT_SECONDS = 120.0
PROBE_SENTINEL = "CMUX_PROFILE_PROBE_OK_V1"
PROBE_SAFETY = "read-only/tool-disabled"
PROBE_PROMPT = (
    f"Reply with exactly {PROBE_SENTINEL} and nothing else. "
    "Do not call tools or modify any files."
)

# Stands in for the profile's model inside an auth-status rule, for harnesses whose auth check
# is scoped rather than global.
MODEL_PLACEHOLDER = "{model}"

PREFLIGHT_RULES = {
    "codex": {
        "help_tokens": ("--model", "--sandbox", "--config", "--ask-for-approval", "login"),
        "auth_help": ("login", "--help"),
        "auth_tokens": ("status",),
        "auth_status": ("login", "status"),
        # Probe options live on the exec subcommand, so they need their own help page.
        "probe_help": ("exec", "--help"),
        "probe_tokens": ("--ephemeral", "--skip-git-repo-check", "--sandbox", "--model", "--config"),
    },
    "claude-code": {
        "help_tokens": ("--model", "--effort", "--permission-mode", "auth"),
        "auth_help": ("auth", "--help"),
        "auth_tokens": ("status",),
        "auth_status": ("auth", "status"),
        "probe_help": ("--help",),
        "probe_tokens": ("--safe-mode", "--print", "--no-session-persistence", "--permission-mode", "--tools"),
    },
    "pi": {
        "help_tokens": ("--model", "--thinking", "--provider", "auth"),
        "auth_help": ("auth", "--help"),
        "auth_tokens": ("check",),
        # Pi has no provider-wide status command: the check is scoped to one provider or model,
        # which is why a Pi profile must spell its model as provider/id.
        "auth_status": ("auth", "check", "--model", MODEL_PLACEHOLDER),
        "probe_help": ("--help",),
        "probe_tokens": ("--print", "--no-session", "--no-tools", "--model", "--thinking"),
    },
}


class HarnessError(ConfigError):
    """A harness could not be preflighted, launched, or probed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _successful_probe(argv: list[str], purpose: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except FileNotFoundError as error:
        raise HarnessError(f"{purpose} failed because the executable disappeared: {argv[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise HarnessError(f"{purpose} timed out for executable {argv[0]}") from error
    except OSError as error:
        raise HarnessError(f"{purpose} failed for executable {argv[0]}: {error}") from error
    if result.returncode != 0:
        raise HarnessError(f"{purpose} failed for executable {argv[0]} (exit {result.returncode})")
    return result


def _executable_file(candidate: Path, label: str, display: object) -> str:
    # The checks follow symlinks; the returned path deliberately does not. Version-manager shims
    # (Volta, mise, asdf) dispatch on the name they were invoked under, so substituting the
    # realpath makes the harness refuse to start. `real_path` keeps it as audit data instead.
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise HarnessError(f"{label} executable is not an executable file: {display}")
    return os.path.normpath(candidate.absolute())


def resolve_executable(requested: str) -> str:
    if "/" in requested:
        return _executable_file(Path(requested), "requested", requested)
    found = shutil.which(requested)
    if not found:
        raise HarnessError(f"requested executable was not found on PATH: {requested}")
    return _executable_file(Path(found), "resolved", Path(found))


def clean_version(result: subprocess.CompletedProcess[str], executable: str) -> str:
    output = result.stdout.strip() or result.stderr.strip()
    if not output:
        raise HarnessError(f"version check produced no version text for executable {executable}")
    first_line = output.splitlines()[0].strip()
    printable = "".join(character for character in first_line if character.isprintable())
    if not printable:
        raise HarnessError(f"version check produced no usable version text for executable {executable}")
    return printable[:256]


def help_has_capability(output: str, token: str) -> bool:
    """Match an option or command word without accepting a longer lookalike token."""
    return re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", output) is not None


_help_pages: dict[tuple[str, ...], str] = {}


def _help_page(argv: list[str], label: str) -> str:
    """One capture per help page per run: preflight and the live probe read the same pages."""
    key = tuple(argv)
    if key not in _help_pages:
        result = _successful_probe(argv, label)
        # Some CLIs print help to stderr, so both streams count as the help page.
        _help_pages[key] = result.stdout + "\n" + result.stderr
    return _help_pages[key]


def _capability_probe(argv: list[str], tokens: tuple[str, ...], *, label: str) -> None:
    """Require each token as a whole option or command word, not a longer lookalike."""
    output = _help_page(argv, label)
    missing = [token for token in tokens if not help_has_capability(output, token)]
    if missing:
        raise HarnessError(
            f"{label} failed for executable {argv[0]}; missing: " + ", ".join(missing)
        )


def preflight_rules(harness: str) -> dict[str, Any]:
    """Refuse an unregistered harness the way the launch and probe adapters do, instead of
    letting a KeyError escape from the middle of a preflight."""
    rules = PREFLIGHT_RULES.get(harness)
    if rules is None:
        raise HarnessError(f"no preflight adapter for harness {harness!r}")
    return rules


def preflight_executable(profile: dict[str, str]) -> dict[str, Any]:
    requested = profile["executable"]
    resolved = resolve_executable(requested)
    rules = preflight_rules(profile["harness"])

    version_result = _successful_probe([resolved, "--version"], "version check")
    version = clean_version(version_result, resolved)
    _capability_probe([resolved, "--help"], rules["help_tokens"], label="root help capability check")
    _capability_probe(
        [resolved, *rules["auth_help"]],
        rules["auth_tokens"],
        label="authentication help capability check",
    )
    auth_status = [
        profile["model"] if part == MODEL_PLACEHOLDER else part for part in rules["auth_status"]
    ]
    auth_result = _successful_probe([resolved, *auth_status], "authentication status check")

    return {
        "requested_executable": requested,
        "resolved_executable": resolved,
        "real_path": os.path.realpath(resolved),
        "detected_version": version,
        "preflight": {
            "status": "passed",
            "executable": {"status": "passed"},
            "version": {"status": "passed", "exit_code": version_result.returncode},
            "capabilities": {
                "status": "passed",
                "root_help": {token: True for token in rules["help_tokens"]},
                "authentication_help": {token: True for token in rules["auth_tokens"]},
            },
            "authentication": {"status": "passed", "exit_code": auth_result.returncode},
        },
        "entitlement": {
            "status": "unverified",
            "reason": "no active provider probe was run",
        },
    }


def adapter_argv(profile: dict[str, Any], *, codex_arguments: list[str]) -> list[str]:
    # The configured executable is the launch identity. Putting the preflighted realpath in argv[0]
    # would version-pin the harness binary, which the spec puts out of scope; the realpath stays in
    # resolved_executable as audit data.
    executable = profile["requested_executable"]
    if profile["harness"] == "claude-code":
        return [
            executable,
            "--model",
            profile["model"],
            "--effort",
            profile["effort"],
            "--permission-mode",
            "auto",
        ]
    if profile["harness"] == "codex":
        return [
            executable,
            *codex_arguments,
            "--model",
            profile["model"],
            "-c",
            f"model_reasoning_effort={profile['effort']}",
        ]
    if profile["harness"] == "pi":
        # Pi ships no sandbox and no approval gate, so there is nothing here to pin: a Pi worker
        # runs its read/bash/edit/write tools unconfined, without Codex's .git carve-out.
        return [
            executable,
            "--model",
            profile["model"],
            "--thinking",
            profile["effort"],
        ]
    raise HarnessError(f"no launch adapter for harness {profile['harness']!r}")


def probe_argv(profile: dict[str, Any]) -> list[str]:
    executable = profile["resolved_executable"]
    if profile["harness"] == "claude-code":
        return [
            executable,
            "--safe-mode",
            "--print",
            "--no-session-persistence",
            "--model",
            profile["model"],
            "--effort",
            profile["effort"],
            "--permission-mode",
            "plan",
            # The prompt goes before the variadic --tools, which would swallow it.
            PROBE_PROMPT,
            "--tools",
            "",
        ]
    if profile["harness"] == "codex":
        return [
            executable,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--model",
            profile["model"],
            "--config",
            f"model_reasoning_effort={profile['effort']}",
            "--config",
            "check_for_update_on_startup=false",
            "--config",
            "tui.whimsy=false",
            "--config",
            'approval_policy="never"',
            "--skip-git-repo-check",
            PROBE_PROMPT,
        ]
    if profile["harness"] == "pi":
        return [
            executable,
            "--no-session",
            "--print",
            "--no-tools",
            "--model",
            profile["model"],
            "--thinking",
            profile["effort"],
            PROBE_PROMPT,
        ]
    raise HarnessError(f"no live probe adapter for harness {profile['harness']!r}")


def probe_key(profile: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Deduplicate repeated assignments without merging independently resolved profiles."""
    return (
        profile["profile"],
        profile["harness"],
        profile["resolved_executable"],
        profile["model"],
        profile["effort"],
    )


def live_profile_probe(
    profile: dict[str, Any],
    *,
    source: Path,
    workflow: str,
    worker: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    argv = probe_argv(profile)
    started_at = utc_now()
    started = time.monotonic()

    def failure(message: str) -> HarnessError:
        return HarnessError(
            context_error(
                source,
                f"live profile probe diagnostic failure: {message}",
                workflow=workflow,
                worker=worker,
                profile=profile["profile"],
                field="entitlement",
            )
        )

    # Check the probe's own options before spending a provider request, so a CLI that cannot be
    # probed reports a missing capability instead of an opaque non-zero exit.
    try:
        rules = preflight_rules(profile["harness"])
        _capability_probe(
            [profile["resolved_executable"], *rules["probe_help"]],
            rules["probe_tokens"],
            label="probe capability check",
        )
    except HarnessError as error:
        raise failure(str(error)) from error

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise failure(f"timed out after {timeout_seconds:g} seconds") from error
    except UnicodeError as error:
        raise failure("produced malformed non-UTF-8 output") from error
    except FileNotFoundError as error:
        raise failure("the preflighted executable disappeared") from error
    except OSError as error:
        raise failure(f"could not start the preflighted executable: {error}") from error

    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    if result.returncode != 0:
        raise failure(f"provider request exited with exit {result.returncode}")
    if result.stdout.strip() != PROBE_SENTINEL:
        raise failure(f"successful request did not return the expected sentinel {PROBE_SENTINEL}")
    return {
        "status": "verified",
        "reason": "live provider and model probe passed",
        "probe": {
            "status": "passed",
            "sentinel": PROBE_SENTINEL,
            "timeout_seconds": timeout_seconds,
            "started_at": started_at,
            "completed_at": utc_now(),
            "duration_ms": duration_ms,
            "exit_code": result.returncode,
            "safety": PROBE_SAFETY,
        },
    }


# --- Worker selection ------------------------------------------------------------------------
# One workflow picks stages, the other picks lanes, but both turn the same CLI overrides into the
# same validated, resolved profiles. Only the noun differs, so `workflow` carries it and the two
# skills ship this layer identically instead of maintaining a copy each.

OVERRIDE_FIELDS = ("profile", "harness", "model", "effort", "executable")
# `profile` selects the base profile; the rest patch fields on top of it.
PROFILE_OVERRIDE_FIELDS = OVERRIDE_FIELDS[1:]

# cmux only silences notifications from panes it considers managed subagents
# (`automation.suppressSubagentNotifications`, on by default), and it infers that from process
# ancestry — a worker started by `cmux new-split` counts as top-level. Without this marker every
# turn end, idle reminder and approval prompt raises a desktop banner while the human is elsewhere.
# Undocumented cmux internal; if it ever stops working the only symptom is that the noise returns.
SUBAGENT_MARKER_ENV = "CMUX_AGENT_MANAGED_SUBAGENT"
SUBAGENT_MARKER_VALUE = "1"


def add_override_options(parser: argparse.ArgumentParser, *, workflow: str) -> None:
    noun = WORKFLOW_NOUN[workflow]
    for field in OVERRIDE_FIELDS:
        parser.add_argument(
            f"--{field}",
            dest=f"{field}_overrides",
            action="append",
            default=[],
            metavar=f"{noun.upper()}={field.upper()}",
            help=f"Override one {workflow} {noun} {field}; repeat for different {noun}s",
        )


def add_probe_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--probe-profiles",
        action="store_true",
        help="Make one read-only live inference request for each unique resolved profile",
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        metavar="SECONDS",
        help=f"Live profile probe timeout (default: {DEFAULT_PROBE_TIMEOUT_SECONDS:g})",
    )


def positive_finite(value: object) -> bool:
    """The probe timeout rule, for CLI input and for persisted snapshot state alike."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def probe_options(args: argparse.Namespace) -> tuple[bool, float]:
    enabled = bool(args.probe_profiles)
    supplied_timeout = args.probe_timeout
    timeout = DEFAULT_PROBE_TIMEOUT_SECONDS if supplied_timeout is None else supplied_timeout
    if not positive_finite(timeout):
        raise HarnessError("--probe-timeout must be a finite number greater than zero")
    if supplied_timeout is not None and not enabled:
        raise HarnessError("--probe-timeout requires --probe-profiles")
    return enabled, timeout


def parse_overrides(args: argparse.Namespace, *, workflow: str) -> dict[str, dict[str, str]]:
    noun = WORKFLOW_NOUN[workflow]
    known = WORKFLOW_WORKERS[workflow]
    overrides: dict[str, dict[str, str]] = {}
    for field in OVERRIDE_FIELDS:
        for raw in getattr(args, f"{field}_overrides", []):
            worker, separator, value = raw.partition("=")
            if not separator or not worker or not value:
                raise HarnessError(
                    f"--{field} must use {noun.upper()}=VALUE with non-empty values"
                )
            if worker not in known:
                raise HarnessError(
                    f"--{field} names unknown {workflow} {noun} {worker!r}; expected "
                    + ", ".join(known)
                )
            worker_overrides = overrides.setdefault(worker, {})
            if field in worker_overrides:
                raise HarnessError(
                    f"duplicate --{field} override for {noun} {worker!r}; argument order is not a tiebreaker"
                )
            worker_overrides[field] = value
    return overrides


def resolve_config_source(explicit: str | None) -> tuple[Path, dict[str, Any], str]:
    source = config_path(explicit, None)
    data, payload = load_validated_with_payload(source, HarnessError)
    return source, data, hashlib.sha256(payload).hexdigest()


def validate_effective_worker(
    worker: str,
    profile_name: str,
    profile: dict[str, Any],
    source: Path,
    *,
    workflow: str,
) -> None:
    def invalid(field: str, message: str) -> HarnessError:
        return HarnessError(
            context_error(
                source,
                message,
                workflow=workflow,
                worker=worker,
                profile=profile_name,
                field=field,
            )
        )

    harness = profile.get("harness")
    executable = profile.get("executable")
    model = profile.get("model")
    effort = profile.get("effort")

    if not PROFILE_NAME_RE.fullmatch(profile_name):
        raise invalid("profile", "profile name has invalid syntax")
    if harness not in SUPPORTED_ADAPTERS:
        raise invalid("harness", f"unknown or unsupported harness {harness!r}")
    if harness not in COMPATIBLE_HARNESSES[workflow][worker]:
        raise invalid("harness", f"harness {harness!r} is not compatible with this worker")
    if not isinstance(executable, str) or not valid_executable_syntax(executable):
        raise invalid("executable", "executable must be a single program name or absolute path")
    if not isinstance(model, str) or not model:
        raise invalid("model", "model has unusable syntax")
    model_reason = model_syntax_error(harness, model)
    if model_reason is not None:
        raise invalid("model", model_reason)
    if not isinstance(effort, str) or effort not in ADAPTERS[harness]["efforts"]:
        raise invalid("effort", f"unsupported effort {effort!r} for {harness}")


def resolve_workers(
    data: dict[str, Any],
    source: Path,
    overrides: dict[str, dict[str, str]],
    *,
    workflow: str,
) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    assignments = data["workflows"][workflow]
    profiles = data["profiles"]
    for worker in WORKFLOW_WORKERS[workflow]:
        worker_overrides = overrides.get(worker, {})
        default = OPTIONAL_WORKERS.get(workflow, {}).get(worker)
        built_in = worker not in assignments and "profile" not in worker_overrides
        profile_name = worker_overrides.get("profile", assignments.get(worker, default))
        available = profiles
        if built_in and profile_name not in profiles:
            available = DEFAULT_CONFIG["profiles"]
        if profile_name not in available:
            raise HarnessError(
                context_error(
                    source,
                    "selected profile is not defined",
                    workflow=workflow,
                    worker=worker,
                    profile=profile_name,
                    field="profile",
                )
            )
        effective = copy.deepcopy(available[profile_name])
        for field in PROFILE_OVERRIDE_FIELDS:
            if field in worker_overrides:
                effective[field] = worker_overrides[field]
        validate_effective_worker(worker, profile_name, effective, source, workflow=workflow)
        resolved[worker] = {"profile": profile_name, **effective}
        if built_in:
            resolved[worker]["assignment_source"] = "built-in default"
    return resolved


def audit_workers(
    resolved: dict[str, dict[str, str]],
    source: Path,
    *,
    workflow: str,
    argv_for: Callable[[str, dict[str, Any]], list[str]],
) -> dict[str, dict[str, Any]]:
    """Preflight each unique assigned harness executable once, fan its audit out over the workers
    sharing it, then stamp every worker's final argv and launch environment. The audit depends
    only on (harness, executable), so repeated assignments cost no extra subprocesses."""
    assigned: dict[tuple[str, str], list[str]] = {}
    for worker in WORKFLOW_WORKERS[workflow]:
        profile = resolved[worker]
        assigned.setdefault((profile["harness"], profile["executable"]), []).append(worker)

    audits: dict[tuple[str, str], dict[str, Any]] = {}
    for key, workers in assigned.items():
        try:
            audits[key] = preflight_executable(resolved[workers[0]])
        except HarnessError as error:
            raise HarnessError(
                context_error(
                    source,
                    str(error),
                    workflow=workflow,
                    worker=",".join(workers),
                    profile=",".join(resolved[worker]["profile"] for worker in workers),
                    field="preflight",
                )
            ) from error

    audited: dict[str, dict[str, Any]] = {}
    for worker in WORKFLOW_WORKERS[workflow]:
        profile = copy.deepcopy(resolved[worker])
        profile.update(copy.deepcopy(audits[(profile["harness"], profile["executable"])]))
        profile["argv"] = argv_for(worker, profile)
        profile["environment"] = {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE}
        audited[worker] = profile
    return audited


def probe_workers(
    audited: dict[str, dict[str, Any]],
    source: Path,
    *,
    workflow: str,
    timeout_seconds: float,
) -> None:
    """One live provider request per unique resolved profile; repeated assignments share it."""
    probes: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for worker in WORKFLOW_WORKERS[workflow]:
        profile = audited[worker]
        key = probe_key(profile)
        if key not in probes:
            probes[key] = live_profile_probe(
                profile,
                source=source,
                workflow=workflow,
                worker=worker,
                timeout_seconds=timeout_seconds,
            )
        profile["entitlement"] = copy.deepcopy(probes[key])


def shell_command(environment: dict[str, str], argv: list[str]) -> str:
    """`K=V ... program args` for a pane. Each assignment is quoted per side: quoting the whole
    `K=V` token would make the shell look for a command by that name once a value needs quoting."""
    assignments = " ".join(
        f"{shlex.quote(key)}={shlex.quote(value)}" for key, value in sorted(environment.items())
    )
    return f"{assignments} {shlex.join(argv)}" if assignments else shlex.join(argv)


def supplied_configuration_inputs(args: argparse.Namespace, *, workflow: str) -> bool:
    """Whether the operator passed any configuration input. Asked next to the flags that define
    them, so a new knob cannot be silently dropped by a caller's re-initialization guard."""
    return bool(
        getattr(args, "config", None)
        or parse_overrides(args, workflow=workflow)
        or args.probe_profiles
        or args.probe_timeout is not None
    )


def snapshot_identity(snapshot: dict[str, Any]) -> str:
    """Canonical self-hash of a snapshot. The writer and the loader must agree byte for byte."""
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_id", None)
    payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def valid_probe_record(probe: object, timeout: float) -> bool:
    """Read back exactly what `live_profile_probe` writes for a passed probe."""
    if not isinstance(probe, dict):
        return False
    duration = probe.get("duration_ms")
    return (
        probe.get("status") == "passed"
        and probe.get("sentinel") == PROBE_SENTINEL
        and probe.get("timeout_seconds") == timeout
        and probe.get("exit_code") == 0
        and probe.get("safety") == PROBE_SAFETY
        and isinstance(probe.get("started_at"), str)
        and isinstance(probe.get("completed_at"), str)
        and isinstance(duration, int)
        and not isinstance(duration, bool)
        and duration >= 0
    )



# --- agents_config CLI -----------------------------------------------------------------------

def add_path_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--config",
        default=default,
        metavar="PATH",
        help="explicit agents.json path; relative paths are resolved from the current directory",
    )
    parser.add_argument(
        "--repo",
        default=default,
        metavar="PATH",
        help="target repository location used for Git-root discovery (default: current directory)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_path_options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("init", "atomically create the complete default configuration"),
        ("validate", "strictly validate an existing configuration"),
        ("show-resolved", "display effective profiles and worker assignments"),
    ):
        subparser = subparsers.add_parser(name, help=help_text)
        add_path_options(subparser, suppress_defaults=True)
    migrate = subparsers.add_parser(
        "migrate",
        help="preview schema-v1 migration; replace the file only with --accept",
    )
    add_path_options(migrate, suppress_defaults=True)
    migrate.add_argument(
        "--accept",
        action="store_true",
        help="explicitly accept and atomically publish the displayed schema-v2 candidate",
    )
    migrate.add_argument(
        "--expect-sha256",
        metavar="DIGEST",
        help="refuse acceptance unless the candidate still matches this previewed digest",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    path = config_path(getattr(args, "config", None), getattr(args, "repo", None))
    if args.command == "init":
        atomic_initialize(path)
        # Validate the persisted bytes through the same public contract used later.
        load_validated(path)
        print(f"initialized: {path}")
        return 0
    if args.command == "migrate":
        approved = args.expect_sha256
        if approved is not None:
            approved = approved.strip().lower()
            # Shape-checked here so a truncated or mistyped digest is reported as a bad argument
            # rather than as "the source changed after its preview", which it did not.
            if not re.fullmatch(r"[0-9a-f]{64}", approved):
                omission_guidance = (
                    "omit --expect-sha256 to accept without digest binding"
                    if args.accept
                    else "omit --expect-sha256 to run a read-only preview"
                )
                raise ConfigError(
                    f"invalid --expect-sha256 digest: {args.expect_sha256!r} is not 64 hexadecimal "
                    "characters; provide the candidate SHA-256 printed by the migration preview, "
                    f"or {omission_guidance}"
                )
        original = read_config_bytes(path, ConfigError)
        parsed = parse_json(original, path, ConfigError)
        if not is_legacy(parsed):
            require_valid(parsed, path, ConfigError)
            print(f"already schema {SCHEMA_VERSION}; no migration needed: {path}")
            return 0
        preview = migration_preview(parsed, path, accepting=args.accept)
        print(preview.render_guidance())
        if not args.accept:
            raise ConfigError(
                "migration preview completed without mutation; explicit acceptance is required"
            )
        if approved is not None and approved != preview.digest:
            raise ConfigError(
                f"approved candidate {approved} is not the candidate this configuration now "
                f"produces ({preview.digest}); the source changed after its preview and was not replaced: "
                f"{path}; preview again"
            )
        atomic_replace(path, preview.payload, expected_original=original)
        print(f"migrated schema {LEGACY_SCHEMA_VERSION} to {SCHEMA_VERSION}: {path}")
        return 0
    data = load_validated(path)
    if args.command == "validate":
        print(f"valid: {path}")
        return 0
    if args.command == "show-resolved":
        print(json.dumps(resolved_display(data, path), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(f"configuration operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
