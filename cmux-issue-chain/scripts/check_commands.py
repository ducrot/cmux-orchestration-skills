"""Select the tracker-declared suite shared by prompts and evidence checks."""
from __future__ import annotations

import re


CANONICAL_LABEL = r"Canonical check commands(?:, run as the baseline suite by every worker)?"


def command_group(rules: str) -> list[str] | None:
    match = re.search(rf"^[-*] {CANONICAL_LABEL}:[ \t]*$", rules, re.MULTILINE)
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


def applicable_commands(rules: str, role: str, *, require_canonical: bool = False) -> list[str]:
    if role == "triage":
        return []
    canonical = command_group(rules)
    if canonical is None:
        if require_canonical:
            raise ValueError("tracker ground rules have no canonical check commands")
        return []
    if not canonical or any(not command.strip() or "<TODO" in command for command in canonical):
        raise ValueError("tracker canonical check commands are empty or contain placeholders")
    return canonical
