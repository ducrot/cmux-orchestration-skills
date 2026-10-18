"""Select the tracker-declared suite shared by prompts and evidence checks."""
from __future__ import annotations

import re


CANONICAL_LABEL = r"Canonical check commands(?:, run as the baseline suite by every worker)?"
TARGETED_LABEL = r"Targeted check commands for implement, simplify, and review"
TARGETED_ROLES = ("implement", "simplify", "review")


def command_group(rules: str, label: str) -> list[str] | None:
    match = re.search(rf"^[-*] {label}:[ \t]*$", rules, re.MULTILINE)
    if not match:
        return None
    commands = []
    for line in rules[match.end():].splitlines():
        if not line.strip():
            continue
        command = re.fullmatch(r"\s+[-*]\s+`(.+)`\s*", line)
        if not command:
            break
        commands.append(command[1])
    return list(dict.fromkeys(commands))


def validated(commands: list[str], kind: str) -> list[str]:
    if not commands or any("<TODO" in command for command in commands):
        raise ValueError(f"tracker {kind} check commands are empty or contain placeholders")
    return commands


def applicable_commands(rules: str, role: str, *, require_canonical: bool = False) -> list[str]:
    if role == "triage":
        return []
    canonical = command_group(rules, CANONICAL_LABEL)
    if require_canonical and canonical is None:
        raise ValueError("tracker ground rules have no canonical check commands")
    if canonical is not None:
        validated(canonical, "canonical")
    targeted = command_group(rules, TARGETED_LABEL) if role in TARGETED_ROLES else None
    if targeted is not None:
        return validated(targeted, "targeted")
    return canonical or []
