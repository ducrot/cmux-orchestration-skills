"""Conservative, in-memory edits of recorded outcomes in a grilling protocol."""
from __future__ import annotations

import json
import re

from artifact_pair import REVIEW_LISTS, render_review, single_line


def decision_outcome(entry: dict) -> str:
    return f"Ausgang ({entry['status']}): {entry['decision']}"


def section(lines: list[str], heading: str, optional: bool = False) -> tuple[int, int] | None:
    """Body line range of the single `## heading` section, or None for an absent optional one."""
    starts = [i for i, line in enumerate(lines) if line.rstrip() == f"## {heading}"]
    if not starts and optional:
        return None
    if len(starts) != 1:
        raise ValueError(f"Markdown: expected exactly one ## {heading} section")
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if re.match(r"^#{1,2} ", lines[i])), len(lines))
    return start, end


def replace_line(lines: list[str], index: int, text: str) -> None:
    old = lines[index]
    lines[index] = text + ('\r\n' if old.endswith('\r\n') else '\n' if old.endswith('\n') else '')


def append_entries(lines: list[str], end: int, entries: list[str], newline: str) -> None:
    if not entries:
        return
    # Insert ahead of separator blanks, leaving every existing non-entry byte intact.
    while end and not lines[end - 1].strip():
        end -= 1
    if end and not lines[end - 1].endswith(('\n', '\r')):
        lines[end - 1] += newline
    lines[end:end] = [entry + newline for entry in entries]


def replace_entries(lines: list[str], heading: str, pattern: str, entries: list[str],
                    newline: str, optional: bool = False) -> None:
    bounds = section(lines, heading, optional)
    if bounds is None:
        return
    start, end = bounds
    positions = [i for i in range(start, end) if re.match(pattern, lines[i])]
    if len(positions) > len(entries):
        raise ValueError(f'Markdown: extra entries in ## {heading}')
    for index, entry in zip(positions, entries):
        replace_line(lines, index, entry)
    append_entries(lines, end, entries[len(positions):], newline)


def transcribe(data: dict, markdown: str) -> str:
    lines = markdown.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in markdown else '\n'
    for review_list in REVIEW_LISTS:
        if review_list.name not in data:
            continue
        texts = data[review_list.texts_name]
        entries = [render_review(text, review, review_list)
                   for text, review in zip(texts, data[review_list.name])]
        replace_entries(lines, review_list.heading, review_list.entry_pattern, entries, newline,
                        optional=not review_list.required and not texts)
    if 'open_facts' in data:
        replace_entries(lines, 'Offene Fakten', r'- ',
                        ['- ' + json.dumps(fact, ensure_ascii=False) for fact in data['open_facts']], newline)

    decisions = data['open_decisions']
    bounds = section(lines, 'Entscheidungen', optional=not decisions)
    if bounds is None:
        return ''.join(lines)
    start, end = bounds
    # Each block starts with a level-three heading that begins with its exact ID; titles may name other IDs.
    blocks = [i for i in range(start, end) if re.match(r'^### ', lines[i])]
    seen = set()
    claimed = set()
    edits = []
    for entry in decisions:
        identity = entry.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError(f'duplicate or invalid decision id: {identity!r}')
        seen.add(identity)
        matches = [i for i in blocks if re.match(rf'^###\s+{re.escape(identity)}(?![\w.])', lines[i])]
        if len(matches) != 1:
            raise ValueError(f'decision {identity}: expected exactly one level-three decision block')
        block_start = matches[0]
        block_end = next((i for i in blocks if i > block_start), end)
        if block_start in claimed:
            raise ValueError(f'decision {identity}: block contains multiple decision ids')
        claimed.add(block_start)
        # Strip list markers and emphasis only for recognition; replace the entire outcome line.
        outcomes = []
        for i in range(block_start + 1, block_end):
            plain = re.sub(r'^\s*(?:[-+*]|\d+[.)])\s+', '', lines[i])
            plain = re.sub(r'[*_`]', '', plain).strip()
            if re.match(r'^Ausgang\s*(?:\([^)]*\))?\s*:', plain):
                outcomes.append(i)
        if len(outcomes) > 1:
            raise ValueError(f'decision {identity}: multiple outcome lines')
        if entry['status'] == 'open':
            if outcomes:
                raise ValueError(f'open decision {identity} already has an outcome line')
            continue
        outcome = decision_outcome(entry)
        if not single_line(outcome):
            raise ValueError(f'decision {identity}: outcome must be a single line')
        edits.append((block_start, block_end, outcomes[0] if outcomes else None, outcome))
    for _, block_end, position, outcome in sorted(edits, reverse=True):
        if position is None:
            append_entries(lines, block_end, [outcome], newline)
        else:
            replace_line(lines, position, outcome)
    return ''.join(lines)
