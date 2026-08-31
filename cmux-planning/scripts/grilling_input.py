#!/usr/bin/env python3
"""Validate and normalize the cmux-grilling JSON/Markdown handoff without sibling imports."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from agents_config import ObjectWithDuplicates, duplicate_keys
from orchestrator_lib import checkout_identity, read_json, sha256_bytes, utc_now, write_json
from spec_contract import ContractError, sections


DECISION_STATUSES = {"open", "decided", "deferred"}
DECISION_WHY_OPEN = {"product", "spec-deviation", "tie"}
DECISION_REQUIRED_FIELDS = {
    "id",
    "question",
    "why_open",
    "context",
    "evidence",
    "options",
    "recommendation",
    "rationale",
    "status",
}
TOP_LEVEL_FIELDS = {
    "run_id",
    "task",
    "codebasePath",
    "maxQuestions",
    "questionsAsked",
    "stopReason",
    "qa",
    "assumptions",
    "open_decisions",
    "markdownPath",
    "jsonPath",
}
REQUIRED_MARKDOWN_HEADINGS = {"Aufgabe", "Definierte Annahmen", "Entscheidungen"}


class GrillingInputError(ValueError):
    pass


def _resolve_artifact_path(value: str, cwd: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def _strings(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise GrillingInputError(f"{label} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise GrillingInputError(f"{label} must not be empty")
    return value


def validate_decision(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise GrillingInputError("each open_decisions entry must be an object")
    missing = sorted(DECISION_REQUIRED_FIELDS - set(entry))
    if missing:
        raise GrillingInputError(f"decision {entry.get('id', '?')} is missing: {', '.join(missing)}")
    for field in ("id", "question", "context", "recommendation", "rationale"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            raise GrillingInputError(f"decision {entry.get('id', '?')} has invalid {field}")
    if entry.get("why_open") not in DECISION_WHY_OPEN:
        raise GrillingInputError(f"decision {entry['id']} has invalid why_open")
    if entry.get("status") not in DECISION_STATUSES:
        raise GrillingInputError(f"decision {entry['id']} has invalid status")
    _strings(entry.get("evidence"), f"decision {entry['id']} evidence", allow_empty=False)
    options = entry.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise GrillingInputError(f"decision {entry['id']} needs at least two options")
    for option in options:
        if not isinstance(option, dict) or any(
            not isinstance(option.get(field), str) or not option[field].strip()
            for field in ("label", "implication")
        ):
            raise GrillingInputError(f"decision {entry['id']} has an invalid option")
    if entry["status"] != "open" and (
        not isinstance(entry.get("decision"), str) or not entry["decision"].strip()
    ):
        raise GrillingInputError(f"resolved decision {entry['id']} needs decision text")


def markdown_sections(markdown: str) -> dict[str, str]:
    try:
        parsed = sections(markdown)
    except ContractError as error:
        raise GrillingInputError(f"ambiguous Markdown: {error}") from error
    missing = sorted(REQUIRED_MARKDOWN_HEADINGS - set(parsed))
    if missing:
        raise GrillingInputError("Markdown artifact is missing sections: " + ", ".join(missing))
    return parsed


def premise_corrections(sections: dict[str, str]) -> list[str]:
    body = sections.get("Prämissen-Korrekturen", "")
    if not body:
        return []
    corrections = [
        match.group(1).strip()
        for match in re.finditer(r"^[-*]\s+(.+)$", body, re.MULTILINE)
        if match.group(1).strip()
    ]
    if not corrections:
        raise GrillingInputError("Prämissen-Korrekturen is present but has no unambiguous list entries")
    return corrections


def parse_json_bytes(payload: bytes, source: Path) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=ObjectWithDuplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GrillingInputError(f"malformed grilling JSON {source}: {error}") from error
    if not isinstance(data, dict):
        raise GrillingInputError("grilling JSON root must be an object")

    def duplicate_fields(value: Any, location: str = "root") -> list[str]:
        problems = [f"{location}.{field}" for field in duplicate_keys(value)]
        if isinstance(value, dict):
            for key, child in value.items():
                problems.extend(duplicate_fields(child, f"{location}.{key}"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                problems.extend(duplicate_fields(child, f"{location}[{index}]"))
        return problems

    duplicates = duplicate_fields(data)
    if duplicates:
        raise GrillingInputError("ambiguous duplicate JSON fields: " + ", ".join(duplicates))
    return data


def validate_pair(
    json_path: Path,
    markdown_path: Path | None,
    repository: Path,
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    cwd = (cwd or Path.cwd()).resolve()
    json_path = json_path.expanduser().resolve()
    if not json_path.is_file():
        raise GrillingInputError(f"grilling JSON file is missing: {json_path}")
    json_bytes = json_path.read_bytes()
    data = parse_json_bytes(json_bytes, json_path)
    missing = sorted(TOP_LEVEL_FIELDS - set(data))
    if missing:
        raise GrillingInputError("grilling JSON is missing fields: " + ", ".join(missing))
    for field in ("run_id", "task", "codebasePath", "stopReason", "markdownPath", "jsonPath"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise GrillingInputError(f"grilling JSON field {field} must be a non-empty string")
    for field in ("maxQuestions", "questionsAsked"):
        if isinstance(data.get(field), bool) or not isinstance(data.get(field), int) or data[field] < 0:
            raise GrillingInputError(f"grilling JSON field {field} must be a non-negative integer")
    if data["questionsAsked"] > data["maxQuestions"]:
        raise GrillingInputError("questionsAsked cannot exceed maxQuestions")
    _strings(data.get("assumptions"), "assumptions")
    if not isinstance(data.get("qa"), list):
        raise GrillingInputError("qa must be a list")
    if len(data["qa"]) != data["questionsAsked"]:
        raise GrillingInputError("qa must contain exactly one synthesis entry per question asked")
    decisions = data.get("open_decisions")
    if not isinstance(decisions, list):
        raise GrillingInputError("open_decisions must be a list")
    seen_ids: set[str] = set()
    for decision in decisions:
        validate_decision(decision)
        if decision["id"] in seen_ids:
            raise GrillingInputError(f"ambiguous duplicate decision id: {decision['id']}")
        seen_ids.add(decision["id"])

    named_json = _resolve_artifact_path(data["jsonPath"], cwd)
    if named_json != json_path:
        raise GrillingInputError(f"jsonPath does not identify the supplied JSON: {named_json}")
    named_markdown = _resolve_artifact_path(data["markdownPath"], cwd)
    if markdown_path is not None and markdown_path.expanduser().resolve() != named_markdown:
        raise GrillingInputError("supplied Markdown path does not match JSON markdownPath")
    if not named_markdown.is_file():
        raise GrillingInputError(f"paired grilling Markdown file is missing: {named_markdown}")

    artifact_repo = _resolve_artifact_path(data["codebasePath"], cwd)
    if artifact_repo != repository.resolve():
        raise GrillingInputError(
            f"grilling repository mismatch: artifact={artifact_repo} current={repository.resolve()}"
        )
    markdown_bytes = named_markdown.read_bytes()
    try:
        markdown = markdown_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrillingInputError(f"grilling Markdown is not UTF-8: {error}") from error
    sections = markdown_sections(markdown)
    for assumption in data["assumptions"]:
        if assumption not in sections["Definierte Annahmen"]:
            raise GrillingInputError("Markdown assumptions do not unambiguously match the JSON pair")
    for decision in decisions:
        # Whole-token, because plain containment lets a documented D12 satisfy a missing D1.
        if not re.search(
            rf"(?<![0-9A-Za-z]){re.escape(decision['id'])}(?![0-9A-Za-z])",
            sections["Entscheidungen"],
        ):
            raise GrillingInputError(f"Markdown decisions do not contain {decision['id']}")
    return {
        "data": data,
        "json_path": json_path,
        "markdown_path": named_markdown,
        "json_bytes": json_bytes,
        "markdown_bytes": markdown_bytes,
        "json_sha256": sha256_bytes(json_bytes),
        "markdown_sha256": sha256_bytes(markdown_bytes),
        "premise_corrections": premise_corrections(sections),
    }


def _normalize_triage(source: list[str], outcomes: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(outcomes, list) or len(outcomes) != len(source):
        raise GrillingInputError(f"{label} outcomes must contain exactly {len(source)} entries")
    normalized = []
    for index, (original, outcome) in enumerate(zip(source, outcomes, strict=True), start=1):
        if not isinstance(outcome, dict) or outcome.get("index") != index:
            raise GrillingInputError(f"{label} outcome {index} has a missing or mismatched index")
        status = outcome.get("outcome")
        if status not in {"confirmed", "corrected", "discarded"}:
            raise GrillingInputError(f"{label} outcome {index} has invalid outcome")
        reason = outcome.get("reason", "")
        if status != "confirmed" and (not isinstance(reason, str) or not reason.strip()):
            raise GrillingInputError(f"{label} outcome {index} needs a reason")
        value = original if status == "confirmed" else outcome.get("value", "")
        if status == "corrected" and (not isinstance(value, str) or not value.strip()):
            raise GrillingInputError(f"{label} outcome {index} needs corrected value")
        normalized.append(
            {
                "index": index,
                "source": original,
                "outcome": status,
                "value": None if status == "discarded" else value,
                "reason": reason,
            }
        )
    return normalized


def normalize_revalidation(
    imported: dict[str, Any],
    outcomes: dict[str, Any],
    *,
    task_path: Path,
    repository: Path,
) -> dict[str, Any] | None:
    if outcomes.get("accepted") is False:
        return None
    if outcomes.get("accepted") is not True:
        raise GrillingInputError("revalidation must explicitly set accepted to true or false")
    data = imported["data"]
    assumptions = _normalize_triage(data["assumptions"], outcomes.get("assumptions"), "assumption")
    corrections = _normalize_triage(
        imported["premise_corrections"], outcomes.get("premise_corrections"), "premise correction"
    )
    decision_outcomes = outcomes.get("decisions")
    if not isinstance(decision_outcomes, list) or len(decision_outcomes) != len(data["open_decisions"]):
        raise GrillingInputError("decision outcomes must cover every source decision exactly once")
    source_by_id = {entry["id"]: entry for entry in data["open_decisions"]}
    normalized_decisions = []
    seen: set[str] = set()
    for outcome in decision_outcomes:
        if not isinstance(outcome, dict) or outcome.get("id") not in source_by_id:
            raise GrillingInputError("decision outcome has an unknown id")
        decision_id = outcome["id"]
        if decision_id in seen:
            raise GrillingInputError(f"duplicate decision outcome: {decision_id}")
        seen.add(decision_id)
        status = outcome.get("status")
        if status not in DECISION_STATUSES:
            raise GrillingInputError(f"decision {decision_id} has invalid revalidated status")
        decision_text = outcome.get("decision")
        if status != "open" and (not isinstance(decision_text, str) or not decision_text.strip()):
            raise GrillingInputError(f"decision {decision_id} needs an outcome for {status}")
        normalized_decisions.append(
            {
                "source": copy.deepcopy(source_by_id[decision_id]),
                "id": decision_id,
                "status": status,
                "decision": decision_text if status != "open" else None,
                "reason": outcome.get("reason", ""),
            }
        )
    now = utc_now()
    event_seed = json.dumps(outcomes, sort_keys=True).encode("utf-8") + now.encode("utf-8")
    return {
        "schema_version": 1,
        "revalidated_at": now,
        "revalidation_event_id": "grilling-revalidated-" + sha256_bytes(event_seed)[:16],
        "source": {
            "run_id": data["run_id"],
            "json_path": str(imported["json_path"]),
            "json_sha256": imported["json_sha256"],
            "markdown_path": str(imported["markdown_path"]),
            "markdown_sha256": imported["markdown_sha256"],
        },
        "task": {
            "artifact_text": data["task"],
            "planning_path": str(task_path.resolve()),
            "planning_sha256": sha256_bytes(task_path.read_bytes()),
        },
        "checkout": checkout_identity(repository),
        "premise_corrections": corrections,
        "assumptions": assumptions,
        "decisions": normalized_decisions,
        "evidence": copy.deepcopy(data["qa"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--json", required=True)
    validate.add_argument("--markdown")
    validate.add_argument("--repo", default=".")
    normalize = subparsers.add_parser("normalize")
    normalize.add_argument("--json", required=True)
    normalize.add_argument("--markdown")
    normalize.add_argument("--repo", default=".")
    normalize.add_argument("--task-file", required=True)
    normalize.add_argument("--outcomes", required=True)
    normalize.add_argument("--out", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        imported = validate_pair(
            Path(args.json),
            Path(args.markdown) if args.markdown else None,
            Path(args.repo).resolve(),
            cwd=Path(args.repo).resolve(),
        )
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "json_sha256": imported["json_sha256"],
                        "markdown_sha256": imported["markdown_sha256"],
                        "premise_corrections": imported["premise_corrections"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        outcomes = read_json(Path(args.outcomes))
        if not isinstance(outcomes, dict):
            raise GrillingInputError("revalidation outcomes root must be an object")
        normalized = normalize_revalidation(
            imported, outcomes, task_path=Path(args.task_file), repository=Path(args.repo).resolve()
        )
        if normalized is None:
            print("revalidation=refused")
            return 2
        write_json(Path(args.out), normalized)
        print(Path(args.out))
        return 0
    except (GrillingInputError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
