"""Mechanical triage verdict and issue-draft validation; never judges recommendation content."""
from __future__ import annotations

import re
from pathlib import Path

from collect_recommendations import read_items

VERDICTS = ("accepted", "rejected", "deferred", "recorded", "for-the-human")


def read_draft(path: Path) -> dict:
    from parse_report import split_sections, is_noneish
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not re.fullmatch(r"# \S.*", lines[0]) or len(re.findall(r"^# ", text, re.MULTILINE)) != 1:
        raise ValueError(f"{path}: draft needs one initial # title and no frontmatter")
    sections = split_sections(text)
    if not sections.get("what to build") or not re.search(r"^- \[ \] \S", sections.get("acceptance criteria", ""), re.MULTILINE):
        raise ValueError(f"{path}: draft needs What to build and Acceptance Criteria with an unchecked item")
    blocked = sections.get("blocked by", "")
    blockers = []
    if not is_noneish(blocked):
        for line in blocked.splitlines():
            if not line.strip():
                continue
            if not re.fullmatch(r"- ISSUE-\d+", line):
                raise ValueError(f"{path}: Blocked by must name only existing issue IDs")
            blockers.append(line[2:])
    return {"title": lines[0][2:], "body": "\n".join(lines[1:]).strip(), "blockers": blockers}


def parse_verdicts(body: str, items_path: Path) -> dict:
    errors = []
    verdicts = []
    try:
        items = read_items(items_path)
    except (ValueError, OSError) as error:
        return verdict_payload([], [str(error)])
    expected = {item["id"]: item for item in items["items"]}
    matches = list(re.finditer(r"^- (\S+)\s*$", body, re.MULTILINE))
    if not matches or body[:matches[0].start()].strip():
        errors.append("missing or empty Verdicts section, or invalid entry prefix")
    seen = set()
    for i, match in enumerate(matches):
        key = match[1]
        block = body[match.end():matches[i+1].start() if i+1 < len(matches) else len(body)]
        fields = {}
        for field in re.finditer(r"^  - ([A-Za-z -]+):[ \t]*([^\n]*)$", block, re.MULTILINE):
            name = field[1].lower().replace(" ", "_").replace("-", "")
            if name in fields:
                errors.append(f"{key}: duplicate field {field[1]}")
            fields[name] = field[2].strip()
        if key in seen:
            errors.append(f"{key}: duplicate verdict")
        seen.add(key)
        item = expected.get(key)
        if item is None:
            errors.append(f"{key}: unknown ID")
        elif fields.get("source") != item["source"]:
            errors.append(f'{key}: Source differs from {item["source"]}')
        for required in ("title", "reason", "files", "supersedes"):
            if not fields.get(required):
                errors.append(f"{key}: missing {required}")
        verdict = fields.get("verdict")
        eligible = fields.get("followup_eligible")
        if verdict not in VERDICTS:
            errors.append(f"{key}: invalid verdict {verdict!r}")
        if eligible not in ("yes", "no"):
            errors.append(f"{key}: Follow-up eligible must be yes|no")
        if eligible == "yes" and verdict != "accepted":
            errors.append(f"{key}: only accepted can be follow-up eligible")
        raw_files = fields.get("files", "none")
        files = [] if raw_files == "none" else [p.strip().strip("`") for p in raw_files.split(",")]
        if eligible == "yes":
            if not files or any(p not in items["diff_files"] for p in files):
                errors.append(f'{key}: Files {raw_files} must name paths in Issue diff files {items["diff_files"]}')
            if not items["followup_allowed"]:
                errors.append(f"{key}: follow-up is not allowed")
        if verdict == "accepted" and item and item["kind"] == "counter-proposal" and fields.get("supersedes", "none") == "none":
            errors.append(f"{key}: accepted counter-proposal requires Supersedes")
        entry = {"id": key, **fields, "files": files, "followup_eligible": eligible == "yes"}
        if verdict == "accepted" and eligible == "no" and item:
            draft_path = items_path.parent / "artifacts" / f'triage-{items["pass"]}' / f"issue-draft-{key}.md"
            try:
                entry["draft"] = read_draft(draft_path)
                entry["draft_path"] = str(draft_path)
            except (ValueError, OSError) as error:
                errors.append(f"{key}: invalid draft: {error}")
        verdicts.append(entry)
    for key in expected.keys() - seen:
        errors.append(f"{key}: missing verdict")
    return verdict_payload(verdicts, errors)


def verdict_payload(verdicts: list, errors: list) -> dict:
    return {"verdicts": verdicts, "verdict_errors": errors, "verdicts_malformed": bool(errors),
            "followup_items": [v["id"] for v in verdicts if v.get("verdict") == "accepted" and v.get("followup_eligible")],
            "new_issue_items": [v["id"] for v in verdicts if v.get("verdict") == "accepted" and not v.get("followup_eligible")],
            "for_the_human": [v["id"] for v in verdicts if v.get("verdict") == "for-the-human"]}
