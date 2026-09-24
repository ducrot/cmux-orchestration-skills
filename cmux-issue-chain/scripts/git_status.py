"""Fail-closed porcelain v1 -z tokenization shared within issue-chain."""
from __future__ import annotations


def _is_rename_or_copy(token: bytes) -> bool:
    return b"R" in token[:2] or b"C" in token[:2]


def porcelain_entries(raw: bytes) -> list[tuple[str, bytes]]:
    """Return status/path pairs, including rename/copy sources as opaque paths."""
    *body, tail = raw.split(b"\0")
    tokens = iter(body)
    entries = []
    for token in tokens:
        if (len(token) < 4 or token[2:3] != b" "
                or any(char not in b" MADRCUT?!" for char in token[:2])
                or token[:2] == b"  "):
            raise ValueError("git status returned an unparseable porcelain entry")
        code = token[:2].decode("ascii")
        entries.append((code, token[3:]))
        if _is_rename_or_copy(token):
            source = next(tokens, b"")
            if not source:
                raise ValueError("git status rename/copy entry is incomplete")
            entries.append((code, source))
    if tail:
        if _is_rename_or_copy(tail):
            raise ValueError("git status rename/copy entry is incomplete")
        raise ValueError("git status returned an unparseable porcelain entry")
    return entries
